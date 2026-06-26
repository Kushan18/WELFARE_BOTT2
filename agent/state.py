from typing import Optional, List
from typing_extensions import TypedDict


class ConversationState(TypedDict, total=False):
    session_id: str
    message: str
    user_profile: Optional[dict]
    intent: Optional[str]
    reply: Optional[str]
    chips: Optional[List[str]]
    selected_scheme: Optional[str]
    last_schemes: Optional[List[str]]
    onboarding_step: Optional[str]
    awaiting_name: Optional[bool]
    show_form: Optional[bool]
    show_form_choice: Optional[bool]
    open_form: Optional[bool]
    clear_session: Optional[bool]
    awaiting_confirmation: Optional[bool]
    suggestions: Optional[List[str]]
