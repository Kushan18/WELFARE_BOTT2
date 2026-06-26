from langgraph.graph import StateGraph, END
from agent.state import ConversationState
from agent.nodes import (
    detect_intent,
    handle_faq,
    handle_scheme_query,
    handle_scheme_detail,
)


def build_graph(groq_client, users_collection, schemes_collection):
    """Create the LangGraph workflow used during the free-chat phase.

    Routing:
    * ``detect_intent`` classifies the message.
    * ``handle_faq`` answers general questions with Groq.
    * ``handle_scheme_query`` matches and lists eligible schemes.
    * ``handle_scheme_detail`` shows a single scheme's details (with the
      ChromaDB -> live -> Groq cascade for unknown schemes).
    """
    # Expose shared resources to the node module.
    import agent.nodes as nodes
    nodes.groq_client = groq_client
    nodes.users_collection = users_collection
    nodes.schemes_collection = schemes_collection

    workflow = StateGraph(ConversationState)
    workflow.add_node("detect_intent", detect_intent)
    workflow.add_node("handle_faq", handle_faq)
    workflow.add_node("handle_scheme_query", handle_scheme_query)
    workflow.add_node("handle_scheme_detail", handle_scheme_detail)

    workflow.add_conditional_edges(
        "detect_intent",
        lambda state: state.get("intent", "faq"),
        {
            "scheme_query": "handle_scheme_query",
            "scheme_detail": "handle_scheme_detail",
            "faq": "handle_faq",
        },
    )

    workflow.add_edge("handle_faq", END)
    workflow.add_edge("handle_scheme_query", END)
    workflow.add_edge("handle_scheme_detail", END)

    workflow.set_entry_point("detect_intent")
    return workflow.compile()
