"""LangGraph node handlers and shared helpers for the WelfareBot chat phase.

The onboarding / profile-collection / confirmation state machine lives in
``agent/conversation.py``. This module only contains the handlers used once the
user has reached the free-chat phase, plus helpers shared across the app:

* intent detection and routing nodes (``detect_intent``, ``handle_faq``,
  ``handle_scheme_query``, ``handle_scheme_detail``)
* dynamic suggestion-chip builders
* the ChromaDB -> live fetch -> Groq knowledge retrieval cascade

Shared resources (Groq client and Mongo collections) are injected by
``agent.graph.build_graph`` as module-level globals.
"""
import re
import logging
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)

# Injected by build_graph(); typed loosely because they come from main.py.
groq_client = None
users_collection = None
schemes_collection = None

# ---------- Constants ----------
REQUIRED_FIELDS = [
    "name",
    "language_preference",
    "state",
    "occupation",
    "caste_category",
    "gender",
    "age",
    "income_bracket",
]

PROFILE_FIELDS = ["state", "occupation", "caste_category", "gender", "age", "income_bracket"]

SCHEME_KEYWORDS = [
    "scheme", "schemes", "eligible", "eligibility", "scholarship", "benefit",
    "welfare", "apply", "subsidy", "yojana", "assistance", "pension", "loan",
]

FIND_SCHEMES_TRIGGERS = ["find my schemes", "find schemes", "see other schemes", "show schemes"]

LANGUAGE_CHIPS = ["English", "Hindi", "Telugu", "Tamil", "Kannada"]
START_OVER = "Start Over"


# ---------- Chip builders (dynamic suggestion chips) ----------
def chips_general_chat() -> List[str]:
    return ["Find My Schemes", "Ask Something Else", START_OVER]


def chips_for_scheme_list(scheme_names: List[str]) -> List[str]:
    return list(scheme_names) + [START_OVER]


def chips_for_scheme_detail() -> List[str]:
    return ["Apply Now", "Required Documents", "See Other Schemes", START_OVER]


# ---------- Helpers ----------
def extract_first_name(text: str) -> str:
    """Extract a first name from a natural-language introduction."""
    patterns = [
        r"my\s+name\s+is\s+([A-Za-z]+)",
        r"i\s+am\s+([A-Za-z]+)",
        r"i['\u2019]?m\s+([A-Za-z]+)",
        r"call\s+me\s+([A-Za-z]+)",
        r"this\s+is\s+([A-Za-z]+)",
    ]
    for pat in patterns:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            return m.group(1).capitalize()
    words = re.findall(r"[A-Za-z]+", text.strip())
    return words[0].capitalize() if words else "Friend"


def safe_groq_chat(messages: List[Dict[str, str]], temperature: float = 0.7) -> str:
    """Call Groq chat completion with retries; returns "" on failure."""
    if groq_client is None:
        logger.error("safe_groq_chat: groq_client not initialised")
        return ""
    for attempt in range(1, 3):
        try:
            resp = groq_client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=messages,
                temperature=temperature,
                timeout=20,
            )
            return resp.choices[0].message.content.strip()
        except Exception as e:  # noqa: BLE001 - we want any failure to degrade gracefully
            logger.error(f"Groq chat error (attempt {attempt}): {e}")
    return ""


def _all_scheme_names() -> List[str]:
    if schemes_collection is None:
        return []
    try:
        return [s.get("name", "") for s in schemes_collection.find({}, {"name": 1, "_id": 0})]
    except Exception as e:  # noqa: BLE001
        logger.error(f"_all_scheme_names error: {e}")
        return []


def _match_scheme_name(message: str, candidates: List[str]) -> Optional[str]:
    msg = message.strip().lower()
    if not msg:
        return None
    for name in candidates:
        if name and (msg == name.lower() or name.lower() in msg or msg in name.lower()):
            return name
    return None


def _format_scheme_list(schemes: List[Dict[str, Any]]) -> str:
    lines = ["Here are schemes that match your profile. Tap one to see details:\n"]
    for s in schemes:
        desc = (s.get("description") or "").strip()
        one_line = desc.split(". ")[0]
        if len(one_line) > 120:
            one_line = one_line[:117] + "..."
        lines.append(f"\u2022 {s.get('name')} \u2014 {one_line}")
    return "\n".join(lines)


def _format_scheme_detail(scheme: Dict[str, Any]) -> str:
    name = scheme.get("name", "This scheme")
    overview = (scheme.get("description") or "").strip() or "Not available."
    rules = scheme.get("eligibility_rules", {}) or {}
    elig_parts = []
    if rules.get("state") and rules.get("state") != "all":
        elig_parts.append(f"State: {rules.get('state')}")
    if rules.get("caste_category"):
        elig_parts.append(f"Category: {rules.get('caste_category')}")
    if rules.get("occupation"):
        elig_parts.append(f"Occupation: {rules.get('occupation')}")
    if rules.get("gender"):
        elig_parts.append(f"Gender: {rules.get('gender')}")
    if rules.get("max_income"):
        elig_parts.append(f"Max annual income: Rs.{rules.get('max_income'):,}")
    if rules.get("min_age") or rules.get("max_age"):
        elig_parts.append(f"Age: {rules.get('min_age', 'any')}-{rules.get('max_age', 'any')}")
    eligibility = "; ".join(elig_parts) if elig_parts else "Open to all eligible applicants."

    docs = scheme.get("required_documents") or []
    documents = ", ".join(docs) if docs else "Aadhaar card and basic KYC documents."
    benefits = scheme.get("benefits") or overview
    apply_link = scheme.get("apply_link") or "Check the official government portal."
    how_to_apply = (
        scheme.get("how_to_apply")
        or f"Visit {apply_link}, register/login, fill the application form and upload the required documents."
    )
    deadline = scheme.get("deadline")

    parts = [
        f"**{name}**",
        f"\n**Overview**\n{overview}",
        f"\n**Eligibility**\n{eligibility}",
        f"\n**Benefits**\n{benefits}",
        f"\n**Required Documents**\n{documents}",
        f"\n**How to Apply**\n{how_to_apply}",
        f"\n**Official Link**\n{apply_link}",
    ]
    if deadline:
        parts.append(f"\n**Deadline**\n{deadline}")
    return "\n".join(parts)


def _retrieve_scheme_knowledge(scheme_name: str, user_state: Optional[str]) -> str:
    """ChromaDB -> live fetch -> Groq knowledge cascade for unknown schemes."""
    # 1. ChromaDB cache
    try:
        from rag.cached_retriever import cached_retrieve
        cached = cached_retrieve(scheme_name, n=3)
        if cached:
            context = "\n".join(cached)
            structured = safe_groq_chat([
                {"role": "system", "content": "Summarise the welfare scheme into Overview, Eligibility, Benefits, Required Documents, How to Apply, and Official Link. Be concise and factual."},
                {"role": "user", "content": f"Scheme: {scheme_name}\n\nContext:\n{context}"},
            ], temperature=0.3)
            if structured:
                return structured
    except Exception as e:  # noqa: BLE001
        logger.error(f"cached retrieval failed: {e}")

    # 2. Live fetch
    try:
        from rag.smart_retriever import smart_retrieve
        results, source = smart_retrieve(scheme_name, user_state)
        if results and source != "none":
            context = "\n".join(results)
            structured = safe_groq_chat([
                {"role": "system", "content": "Summarise the welfare scheme into Overview, Eligibility, Benefits, Required Documents, How to Apply, and Official Link. Be concise and factual."},
                {"role": "user", "content": f"Scheme: {scheme_name}\n\nContext:\n{context}"},
            ], temperature=0.3)
            if structured:
                return structured
    except Exception as e:  # noqa: BLE001
        logger.error(f"live retrieval failed: {e}")

    # 3. Groq knowledge fallback (with disclaimer)
    knowledge = safe_groq_chat([
        {"role": "system", "content": "You are a welfare scheme expert for Indian government schemes. Provide Overview, Eligibility, Benefits, Required Documents, How to Apply, and Official Link if known. Be concise."},
        {"role": "user", "content": f"Tell me about the scheme: {scheme_name}"},
    ], temperature=0.5)
    if knowledge:
        return (
            knowledge
            + "\n\n_Note: this information comes from the assistant's general knowledge and may be outdated. "
            "Please verify details on the official government website._"
        )
    return (
        f"I couldn't find detailed information about '{scheme_name}' right now. "
        "Please check the official myscheme.gov.in portal."
    )


# ---------- LangGraph nodes ----------
def detect_intent(state: Dict[str, Any]) -> Dict[str, Any]:
    """Classify the message into scheme_detail / scheme_query / faq."""
    message = (state.get("message") or "").strip()
    lower = message.lower()
    user_doc = state.get("user_profile", {}) or {}

    # Chip-driven sub-actions tied to a previously selected scheme.
    if lower in ("apply now", "required documents") and user_doc.get("selected_scheme"):
        state["intent"] = "scheme_detail"
        state["selected_scheme"] = user_doc.get("selected_scheme")
        return state

    if any(t in lower for t in ["see other schemes", "find my schemes", "find schemes", "show schemes"]):
        state["intent"] = "scheme_query"
        return state

    # Direct selection of a scheme by name (from last shown list, else any scheme).
    candidates = state.get("last_schemes") or []
    matched = _match_scheme_name(message, candidates) or _match_scheme_name(message, _all_scheme_names())
    if matched:
        state["intent"] = "scheme_detail"
        state["selected_scheme"] = matched
        return state

    if any(kw in lower for kw in SCHEME_KEYWORDS):
        state["intent"] = "scheme_query"
        return state

    state["intent"] = "faq"
    return state


def handle_faq(state: Dict[str, Any]) -> Dict[str, Any]:
    """Answer general questions with Groq (works even with no scheme match)."""
    user_doc = state.get("user_profile", {}) or {}
    system_prompt = (
        "You are WelfareBot, a friendly assistant that helps Indian citizens with "
        "government welfare schemes and general questions. Answer helpfully and concisely. "
        "If the user asks something outside welfare, still answer using your general knowledge."
    )
    reply = safe_groq_chat(
        [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": state.get("message", "")},
        ],
        temperature=0.7,
    )
    state["reply"] = reply or "I'm here to help! Ask me anything, or tap 'Find My Schemes'."
    state["chips"] = chips_general_chat()
    return state


def handle_scheme_query(state: Dict[str, Any]) -> Dict[str, Any]:
    """Match schemes from the profile and present a tappable list."""
    session_id = state["session_id"]
    user_doc = (users_collection.find_one({"session_id": session_id}) if users_collection else None) or {}
    try:
        from agent.eligibility import match_schemes
        schemes = match_schemes(user_doc, schemes_collection)[:8]
        if schemes:
            names = [s.get("name") for s in schemes]
            if users_collection is not None:
                users_collection.update_one(
                    {"session_id": session_id},
                    {"$set": {"last_schemes": names, "selected_scheme": None}},
                )
            state["reply"] = _format_scheme_list(schemes)
            state["chips"] = chips_for_scheme_list(names)
            state["last_schemes"] = names
        else:
            # No DB match -> Groq general guidance (with disclaimer).
            guidance = safe_groq_chat([
                {"role": "system", "content": "You are WelfareBot. The user has no exact scheme matches in our database. Suggest, from general knowledge, a few Indian government welfare schemes they might explore based on their profile, and advise verifying on official portals."},
                {"role": "user", "content": f"User profile: {{'state': {user_doc.get('state')!r}, 'occupation': {user_doc.get('occupation')!r}, 'category': {user_doc.get('caste_category')!r}, 'gender': {user_doc.get('gender')!r}, 'age': {user_doc.get('age')!r}}}"},
            ], temperature=0.6)
            state["reply"] = (
                (guidance or "No exact matches found in our database right now.")
                + "\n\n_Note: these suggestions come from general knowledge and may be outdated. "
                "Please verify on myscheme.gov.in._"
            )
            state["chips"] = ["Ask Something Else", START_OVER]
    except Exception as e:  # noqa: BLE001
        logger.error(f"Scheme query error: {e}")
        state["reply"] = "I'm having trouble fetching schemes right now. Please try again later."
        state["chips"] = chips_general_chat()
    return state


def handle_scheme_detail(state: Dict[str, Any]) -> Dict[str, Any]:
    """Show a scheme's detail, or answer Apply Now / Required Documents."""
    session_id = state["session_id"]
    message = (state.get("message") or "").strip().lower()
    user_doc = (users_collection.find_one({"session_id": session_id}) if users_collection else None) or {}
    scheme_name = state.get("selected_scheme") or user_doc.get("selected_scheme")

    if not scheme_name:
        state["intent"] = "scheme_query"
        return handle_scheme_query(state)

    scheme = schemes_collection.find_one({"name": scheme_name}, {"_id": 0}) if schemes_collection else None

    # Persist current selection for follow-up chip actions.
    if users_collection is not None:
        users_collection.update_one({"session_id": session_id}, {"$set": {"selected_scheme": scheme_name}})

    if message == "apply now":
        link = (scheme or {}).get("apply_link") or "the official government portal"
        state["reply"] = f"To apply for **{scheme_name}**, visit: {link}"
        state["chips"] = chips_for_scheme_detail()
        return state

    if message == "required documents":
        docs = (scheme or {}).get("required_documents") or []
        doc_text = "\n".join(f"\u2022 {d}" for d in docs) if docs else "Aadhaar card and standard KYC documents."
        state["reply"] = f"**Required documents for {scheme_name}:**\n{doc_text}"
        state["chips"] = chips_for_scheme_detail()
        return state

    if scheme:
        state["reply"] = _format_scheme_detail(scheme)
    else:
        # Unknown scheme -> retrieval cascade (ChromaDB -> live -> Groq).
        state["reply"] = _retrieve_scheme_knowledge(scheme_name, user_doc.get("state"))
    state["chips"] = chips_for_scheme_detail()
    return state
