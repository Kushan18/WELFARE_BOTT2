import logging
import re
import os
from pymongo import MongoClient
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

def _clean_name(name: str) -> str:
    return re.sub(r"\s+", " ", name.strip()).lower()

def compute_quality_score(scheme: dict) -> int:
    score = 0
    if scheme.get("description") and len(scheme["description"].strip()) >= 40:
        score += 30
    if scheme.get("eligibility") and scheme["eligibility"].strip():
        score += 25
    if scheme.get("apply_link") and scheme["apply_link"].strip():
        score += 25
    if scheme.get("deadline") and scheme["deadline"].strip():
        score += 20
    return score

def upsert_scheme(staging, scheme):
    if not scheme.get("apply_link"):
        return False
    scheme_to_set = {k: v for k, v in scheme.items() if k != "_id" and k != "status"}
    from datetime import datetime
    result = staging.update_one(
        {"apply_link": scheme["apply_link"]},
        {
            "$set": scheme_to_set,
            # New schemes start as pending_approval and are only promoted to the
            # live `schemes` collection after manual review.
            "$setOnInsert": {"status": "pending_approval", "scraped_at": datetime.utcnow()},
        },
        upsert=True,
    )
    return result.upserted_id is not None

def run_scraper():
    from scraper import ts_official, ts_vikaspedia, ap_official, ap_vikaspedia, data_gov, pmindia, vikaspedia_central
    client = MongoClient(os.getenv("MONGODB_URI"))
    db = client["welfarebot"]
    staging = db["staging"]
    added = 0
    skipped = 0
    sources = [
        ("ts_official", ts_official.scrape),
        ("ts_vikaspedia", ts_vikaspedia.scrape),
        ("ap_official", ap_official.scrape),
        ("ap_vikaspedia", ap_vikaspedia.scrape),
        ("data_gov", data_gov.scrape),
        ("pmindia", pmindia.scrape),
        ("vikaspedia_central", vikaspedia_central.scrape),
    ]
    # Collect all schemes
    all_schemes = []
    for name, fn in sources:
        try:
            schemes = fn()
            logger.info(f"{name}: got {len(schemes)} schemes")
            all_schemes.extend(schemes)
        except Exception as e:
            logger.error(f"{name} failed: {e}")

    # Fix 1: Add source field to all schemes missing it
    for scheme in all_schemes:
        if not scheme.get('source') or scheme['source'] == '':
            scheme['source'] = scheme.get('state', 'unknown').lower().replace(' ', '') + '.gov.in'

    # Deduplicate by normalized name
    seen = set()
    deduped = []
    for s in all_schemes:
        norm = _clean_name(s.get("name", ""))
        if norm in seen:
            continue
        seen.add(norm)
        deduped.append(s)
    logger.info(f"Deduplication: reduced from {len(all_schemes)} to {len(deduped)} schemes")
    # Quality filter & score
    qualified = []
    for s in deduped:
        if len(s.get("name", "").strip()) < 8:
            continue
        if len(s.get("description", "").strip()) < 40:
            continue
        s["quality_score"] = compute_quality_score(s)
        qualified.append(s)
    logger.info(f"Quality filter: {len(qualified)} schemes passed")
    qualified.sort(key=lambda x: x["quality_score"], reverse=True)
    # Upsert
    for s in qualified:
        try:
            if upsert_scheme(staging, s):
                added += 1
            else:
                skipped += 1
        except Exception as e:
            logger.error(f"upsert failed: {e}")
    logger.info(f"Scraper done: {added} new, {skipped} already existed")
    # Preview top 10
    top10 = qualified[:10]
    if top10:
        logger.info("Top 10 schemes by quality_score:")
        for scheme in top10:
            logger.info(f"- {scheme.get('name')} ({scheme.get('state')}) score={scheme.get('quality_score')}")
    client.close()