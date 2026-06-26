"""Conversation orchestrator for WelfareBot.

Drives the deterministic part of the flow (greeting -> name -> language ->
form/chat choice -> profile collection -> confirmation summary) and delegates
the free-chat phase to the LangGraph workflow in ``agent/graph.py``.

The per-session step is stored on the user document as ``onboarding_step``.
"""
import logging
from typing import Any, Dict, List, Optional

from agent.nodes import (
    extract_first_name,
    chips_general_chat,
    LANGUAGE_CHIPS,
    PROFILE_FIELDS,
    START_OVER,
    SCHEME_KEYWORDS,
)

logger = logging.getLogger(__name__)

PROFILE_QUESTIONS = {
    "state": "Which state do you live in?",
    "occupation": "What is your occupation? (e.g. student, farmer, daily wage worker, business, government employee, other)",
    "caste_category": "What is your caste category?",
    "gender": "What is your gender?",
    "age": "What is your age?",
    "income_bracket": "What is your annual family income? (a number, or e.g. 'below 1 lakh')",
}

PROFILE_CHIPS = {
    "caste_category": ["General", "OBC", "SC", "ST", "EWS", START_OVER],
    "gender": ["Male", "Female", "Other", START_OVER],
    "income_bracket": [
        "Below Rs.1 Lakh", "Rs.1-2.5 Lakh", "Rs.2.5-5 Lakh", "Rs.5-10 Lakh", "Above Rs.10 Lakh", START_OVER,
    ],
}

EDIT_FIELD_CHIPS = ["Name", "Language", "State", "Occupation", "Category", "Gender", "Age", "Income", START_OVER]

LANGUAGE_LABELS = {
    "english": "English", "en": "English",
    "hindi": "Hindi", "हिंदी": "Hindi", "hi": "Hindi",
    "telugu": "Telugu", "తెలుగు": "Telugu", "te": "Telugu",
    "tamil": "Tamil", "தமிழ்": "Tamil", "ta": "Tamil",
    "kannada": "Kannada", "ಕನ್ನಡ": "Kannada", "kn": "Kannada",
}

# Maps the words used on edit chips to the canonical profile field.
EDIT_FIELD_MAP = {
    "name": "name",
    "language": "language_preference",
    "state": "state",
    "occupation": "occupation",
    "category": "caste_category",
    "caste": "caste_category",
    "gender": "gender",
    "age": "age",
    "income": "income_bracket",
}

RESET_WORDS = {"start over", "start_over", "restart", "reset"}
YES_WORDS = ["yes", "continue", "correct", "confirm"]


def _normalize_language(text: str) -> str:
    t = (text or "").strip().lower()
    return LANGUAGE_LABELS.get(t, (text or "").strip().title() or "English")


def _profile_complete(user_doc: Dict[str, Any]) -> bool:
    return all(user_doc.get(f) for f in PROFILE_FIELDS)


def _first_missing_field(user_doc: Dict[str, Any]) -> Optional[str]:
    for f in PROFILE_FIELDS:
        if not user_doc.get(f):
            return f
    return None


def _ask_field(field: str) -> Dict[str, Any]:
    return {
        "reply": PROFILE_QUESTIONS[field],
        "chips": PROFILE_CHIPS.get(field, [START_OVER]),
        "onboarding_step": f"collect_{field}",
    }


def _summary(user_doc: Dict[str, Any]) -> str:
    lines = [
        "Please confirm your details:",
        "",
        f"Name: {user_doc.get('name', '-')}",
        f"Language: {user_doc.get('language_preference', '-')}",
        f"State: {user_doc.get('state', '-')}",
        f"Occupation: {user_doc.get('occupation', '-')}",
        f"Category: {user_doc.get('caste_category', '-')}",
        f"Gender: {user_doc.get('gender', '-')}",
        f"Age: {user_doc.get('age', '-')}",
        f"Income: {user_doc.get('income_bracket', '-')}",
        "",
        "Is this correct?",
    ]
    return "\n".join(lines)


def _confirm_response(user_doc: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "reply": _summary(user_doc),
        "chips": ["Yes Continue", "Edit Details", START_OVER],
        "onboarding_step": "confirm",
    }


def _wants_schemes(lower: str) -> bool:
    if any(t in lower for t in ["find my schemes", "find schemes", "show schemes", "see other schemes"]):
        return True
    return any(kw in lower for kw in SCHEME_KEYWORDS)


def handle_turn(session_id, message, users_collection, schemes_collection, welfare_graph) -> Dict[str, Any]:
    """Process one chat turn and return a response dict."""
    message = (message or "").strip()
    lower = message.lower()
    user_doc = users_collection.find_one({"session_id": session_id}) or {}
    step = user_doc.get("onboarding_step") or "name"

    def save(fields: Dict[str, Any]):
        users_collection.update_one({"session_id": session_id}, {"$set": fields}, upsert=True)

    # --- Global: Start Over ---
    if lower in RESET_WORDS:
        users_collection.delete_one({"session_id": session_id})
        return {"reply": "", "chips": [], "clear_session": True, "intent": "reset"}

    # --- Step: name ---
    if step == "name" or not user_doc.get("name"):
        name = extract_first_name(message)
        save({"name": name, "onboarding_step": "language"})
        return {
            "reply": f"Hello {name}, nice to meet you! Which language would you prefer?",
            "chips": LANGUAGE_CHIPS + [START_OVER],
            "intent": "onboarding",
        }

    # --- Step: language ---
    if step == "language":
        lang = _normalize_language(message)
        save({"language_preference": lang, "onboarding_step": "mode"})
        return {
            "reply": "Great! Would you like to fill a form or just chat?",
            "chips": ["Fill Form", "Chat Instead", START_OVER],
            "show_form_choice": True,
            "intent": "onboarding",
        }

    # --- Step: form-or-chat choice ---
    if step == "mode":
        if "form" in lower:
            save({"onboarding_step": "chat"})
            return {
                "reply": "Sure! I'll open the profile form for you.",
                "chips": [START_OVER],
                "open_form": True,
                "intent": "onboarding",
            }
        if "chat" in lower:
            save({"onboarding_step": "chat"})
            return {
                "reply": "Perfect! Ask me anything, or tap 'Find My Schemes' to discover schemes you may be eligible for.",
                "chips": chips_general_chat(),
                "intent": "onboarding",
            }
        return {
            "reply": "Would you like to fill a form or just chat?",
            "chips": ["Fill Form", "Chat Instead", START_OVER],
            "show_form_choice": True,
            "intent": "onboarding",
        }

    # --- Profile collection ---
    if step.startswith("collect_"):
        field = step[len("collect_"):]
        value = extract_first_name(message) if field == "name" else message
        save({field: value})
        user_doc[field] = value
        nxt = _first_missing_field(user_doc)
        if nxt:
            r = _ask_field(nxt)
            save({"onboarding_step": r["onboarding_step"]})
            return {"reply": r["reply"], "chips": r["chips"], "intent": "onboarding"}
        save({"onboarding_step": "confirm"})
        return {**_confirm_response(user_doc), "intent": "onboarding"}

    # --- Confirmation summary ---
    if step == "confirm":
        if "edit" in lower:
            save({"onboarding_step": "edit_select"})
            return {
                "reply": "Which detail would you like to edit?",
                "chips": EDIT_FIELD_CHIPS,
                "intent": "onboarding",
            }
        if any(w in lower for w in YES_WORDS):
            save({"onboarding_step": "ready"})
            return _run_graph(session_id, "find my schemes", users_collection, welfare_graph)
        return {**_confirm_response(user_doc), "intent": "onboarding"}

    # --- Edit: choose field ---
    if step == "edit_select":
        field = None
        for key, canonical in EDIT_FIELD_MAP.items():
            if key in lower:
                field = canonical
                break
        if not field:
            return {
                "reply": "Please pick a detail to edit.",
                "chips": EDIT_FIELD_CHIPS,
                "intent": "onboarding",
            }
        save({"onboarding_step": f"edit_{field}"})
        question = (
            "What is your name?" if field == "name"
            else "Which language would you prefer?" if field == "language_preference"
            else PROFILE_QUESTIONS.get(field, "Enter the new value:")
        )
        chips = (
            LANGUAGE_CHIPS + [START_OVER] if field == "language_preference"
            else PROFILE_CHIPS.get(field, [START_OVER])
        )
        return {"reply": question, "chips": chips, "intent": "onboarding"}

    # --- Edit: capture new value ---
    if step.startswith("edit_"):
        field = step[len("edit_"):]
        if field == "name":
            value = extract_first_name(message)
        elif field == "language_preference":
            value = _normalize_language(message)
        else:
            value = message
        save({field: value, "onboarding_step": "confirm"})
        user_doc[field] = value
        return {**_confirm_response(user_doc), "intent": "onboarding"}

    # --- Free chat phase (chat / ready) ---
    if step in ("chat", "ready") and _wants_schemes(lower) and not _profile_complete(user_doc):
        nxt = _first_missing_field(user_doc)
        r = _ask_field(nxt)
        save({"onboarding_step": r["onboarding_step"]})
        return {
            "reply": "Let's quickly set up your profile to find the best schemes.\n\n" + r["reply"],
            "chips": r["chips"],
            "intent": "onboarding",
        }

    return _run_graph(session_id, message, users_collection, welfare_graph)


def _run_graph(session_id, message, users_collection, welfare_graph) -> Dict[str, Any]:
    user_doc = users_collection.find_one({"session_id": session_id}) or {}
    state = {
        "session_id": session_id,
        "message": message,
        "user_profile": user_doc,
        "last_schemes": user_doc.get("last_schemes") or [],
        "intent": None,
        "reply": None,
        "chips": None,
    }
    result = welfare_graph.invoke(state)
    return {
        "reply": result.get("reply") or "Sorry, I couldn't process that.",
        "chips": result.get("chips") or chips_general_chat(),
        "intent": result.get("intent"),
    }
