import logging
from rag.live_retriever import live_retrieve
from rag.cached_retriever import cached_retrieve
from rag.sources import STATE_SOURCE_MAP, ALL_SOURCES

logger = logging.getLogger(__name__)


def detect_state(query, user_state=None):
    if user_state:
        return user_state.lower()
    q = (query or "").lower()
    if "telangana" in q:
        return "telangana"
    if "andhra" in q or "ap" in q:
        return "andhra pradesh"
    if "central" in q or "pm " in q:
        return "central"
    return None


def smart_retrieve(query, user_state=None):
    """Retrieve scheme information with a layered strategy.

    1. Try cached retrieval (ChromaDB). Return ("cached") if anything is found.
    2. Otherwise attempt a live fetch from the state's official sources.
    3. If nothing is found, return ([], "none") so the caller can fall back to
       the LLM's own knowledge.
    """
    state = detect_state(query, user_state)
    logger.info(f"smart_retrieve: state={state}")

    cached = cached_retrieve(query, n=3)
    if cached:
        logger.info(f"smart_retrieve: ChromaDB returned {len(cached)} results")
        return cached, "cached"

    logger.warning("smart_retrieve: ChromaDB empty, attempting live fetch")
    urls = STATE_SOURCE_MAP.get(state, ALL_SOURCES)
    # live_retrieve expects (scheme_name, apply_link); try each source URL.
    for url in urls:
        live = live_retrieve(query, url)
        if live:
            return live, "live"

    return [], "none"
