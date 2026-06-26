from typing import List, Dict, Any, Optional
from pymongo.collection import Collection

# Map the income-bracket labels used by the frontend / chat flow to a
# representative upper rupee value so we can compare against a scheme's
# ``max_income`` cap.
INCOME_LABEL_MAP = {
    "below rs.1 lakh": 100000,
    "below 1 lakh": 100000,
    "rs.1-2.5 lakh": 250000,
    "1-2.5 lakh": 250000,
    "rs.2.5-5 lakh": 500000,
    "2.5-5 lakh": 500000,
    "rs.5-10 lakh": 1000000,
    "5-10 lakh": 1000000,
    "above rs.10 lakh": 2000000,
    "above 10 lakh": 2000000,
}


def parse_income(value: Any) -> Optional[int]:
    """Best-effort conversion of an income value (label or number) to rupees.

    Returns ``None`` when the value cannot be interpreted so callers can treat
    income as "unknown" rather than crashing.
    """
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return int(value)
    text = str(value).strip().lower()
    if not text:
        return None
    if text in INCOME_LABEL_MAP:
        return INCOME_LABEL_MAP[text]
    # Plain number, possibly with separators/currency symbols/decimals.
    num_str = "".join(ch for ch in text if ch.isdigit() or ch == ".")
    if num_str:
        try:
            num = float(num_str)
        except ValueError:
            return None
        if "lakh" in text:
            num *= 100000
        elif "crore" in text:
            num *= 10000000
        return int(num)
    return None


def _to_int(value: Any) -> Optional[int]:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def _norm(value: Any) -> str:
    return str(value or "").strip().lower()


def match_schemes(user_profile: Dict[str, Any], schemes_collection: Collection) -> List[Dict[str, Any]]:
    """Return schemes whose eligibility rules are satisfied by the user profile.

    Rules are applied inclusively: a missing rule on a scheme means "no
    constraint", so schemes are never excluded merely for omitting a field.
    """
    user_state = _norm(user_profile.get("state"))
    user_caste = _norm(user_profile.get("caste_category"))
    user_occupation = _norm(user_profile.get("occupation"))
    user_gender = _norm(user_profile.get("gender"))
    user_income = parse_income(user_profile.get("income_bracket"))
    user_age = _to_int(user_profile.get("age"))

    matches: List[Dict[str, Any]] = []
    for scheme in schemes_collection.find({}):
        rules = scheme.get("eligibility_rules", {}) or {}

        rule_state = _norm(rules.get("state", "all"))
        if rule_state not in ("", "all") and user_state and rule_state != user_state:
            continue

        rule_caste = _norm(rules.get("caste_category"))
        if rule_caste and rule_caste != "all" and user_caste and rule_caste != user_caste:
            continue

        rule_occ = _norm(rules.get("occupation"))
        if rule_occ and rule_occ not in ("all", "any") and user_occupation:
            if rule_occ != user_occupation and rule_occ not in user_occupation and user_occupation not in rule_occ:
                continue

        rule_gender = _norm(rules.get("gender"))
        if rule_gender and rule_gender != "all" and user_gender and rule_gender != user_gender:
            continue

        max_income = rules.get("max_income")
        if max_income is not None and user_income is not None and user_income > int(max_income):
            continue

        min_age = rules.get("min_age")
        max_age = rules.get("max_age")
        if user_age is not None:
            if min_age is not None and user_age < int(min_age):
                continue
            if max_age is not None and user_age > int(max_age):
                continue

        matches.append(scheme)

    return matches
