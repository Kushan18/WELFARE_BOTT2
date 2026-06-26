import sys
import os
import logging
import traceback
import asyncio
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()
logging.getLogger("pymongo").setLevel(logging.WARNING)

# Ensure module path works when running via uvicorn
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

# FastAPI application
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import Optional, List, Dict

# Groq client
from groq import Groq

GROQ_API_KEY = os.getenv("GROQ_API_KEY")
if not GROQ_API_KEY:
    raise RuntimeError("GROQ_API_KEY environment variable not set")
groq_client = Groq(api_key=GROQ_API_KEY)

# MongoDB connections
from pymongo import MongoClient
import motor.motor_asyncio

MONGODB_URI = os.getenv("MONGODB_URI")
if not MONGODB_URI:
    raise RuntimeError("MONGODB_URI environment variable not set")

# Synchronous client for quick reads/writes
sync_mongo_client = MongoClient(MONGODB_URI)

# Asynchronous client for async endpoints
async_mongo_client = motor.motor_asyncio.AsyncIOMotorClient(MONGODB_URI)

# Collections
sync_users_collection = sync_mongo_client["welfarebot"]["users"]
sync_schemes_collection = sync_mongo_client["welfarebot"]["schemes"]
conversations_collection = async_mongo_client["welfarebot"]["conversations"]

# Build LangGraph
from agent.graph import build_graph
from chromadb import PersistentClient

# Unified ChromaDB location (the embedder and cached_retriever also use this path).
chroma_client = PersistentClient(path="./chroma_db")

welfare_graph = build_graph(groq_client, sync_users_collection, sync_schemes_collection)

# Scraper + scheduler (moved to top so they're defined before any endpoint uses them)
from scraper.manager import run_scraper
from apscheduler.schedulers.background import BackgroundScheduler

scheduler = BackgroundScheduler()
scheduler.add_job(run_scraper, "interval", days=3, id="scraper_job")
scheduler.start()

# FastAPI app instance
app = FastAPI(title="WelfareBot Backend")

# allow_origins=["*"] is incompatible with allow_credentials=True per the CORS
# spec, so credentials are disabled while we accept any origin.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Request/Response models
class ChatRequest(BaseModel):
    session_id: str
    message: str


class ChatResponse(BaseModel):
    reply: str
    chips: List[str] = Field(default_factory=list)
    show_form_choice: Optional[bool] = None
    open_form: Optional[bool] = None
    clear_session: Optional[bool] = None
    intent: Optional[str] = None


class SubmitProfileRequest(BaseModel):
    session_id: str
    name: str
    language_preference: str
    state: str
    occupation: str
    caste_category: str
    gender: str
    age: str
    income_bracket: str
    aadhaar: Optional[str] = ""


# Endpoints
@app.get("/health")
async def health():
    return {"status": "running", "db": "connected"}


@app.get("/schemes")
async def get_schemes():
    schemes = list(sync_schemes_collection.find({}, {"_id": 0}))
    return {"schemes": schemes}


@app.get("/session")
async def get_session(session_id: str):
    user = sync_users_collection.find_one({"session_id": session_id})
    return {"session_id": session_id, "profile": user or {}}


@app.post("/submit-profile")
async def submit_profile(request: SubmitProfileRequest):
    try:
        profile_dict = request.dict()
        sync_users_collection.update_one(
            {"session_id": request.session_id},
            {"$set": profile_dict},
            upsert=True,
        )

        from agent.eligibility import match_schemes

        schemes = match_schemes(profile_dict, sync_schemes_collection)[:8]
        # Mark onboarding complete and remember the matched list so chat-based
        # scheme selection works after the form path.
        sync_users_collection.update_one(
            {"session_id": request.session_id},
            {"$set": {
                "onboarding_step": "ready",
                "last_schemes": [s.get("name") for s in schemes],
                "selected_scheme": None,
            }},
        )
        clean = [{k: v for k, v in s.items() if k != "_id"} for s in schemes]
        return {"status": "success", "schemes": clean}
    except Exception as e:
        return {"error": str(e)}


@app.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest):
    try:
        session_id = request.session_id
        message = request.message.strip()

        if not message:
            return ChatResponse(reply="Please say something.", chips=["Start Over"])

        from agent.conversation import handle_turn

        result = handle_turn(
            session_id, message, sync_users_collection, sync_schemes_collection, welfare_graph
        )

        await conversations_collection.insert_one({
            "session_id": session_id,
            "user_message": message,
            "bot_reply": result.get("reply"),
            "intent": result.get("intent"),
            "timestamp": datetime.utcnow(),
        })

        return ChatResponse(
            reply=result.get("reply", ""),
            chips=result.get("chips", []),
            show_form_choice=result.get("show_form_choice", False),
            open_form=result.get("open_form", False),
            clear_session=result.get("clear_session", False),
            intent=result.get("intent"),
        )
    except Exception as e:
        logging.error(f"Chat endpoint error: {e}")
        return ChatResponse(reply=f"Error: {str(e)}", chips=["Start Over"])


# Startup diagnostics
print("\n" + "=" * 50)
print("WELFAREBOT BACKEND READY (Groq-only)")
print("=" * 50)
print(f"[OK] Groq client: {groq_client}")
print(f"[OK] MongoDB connected: {sync_mongo_client}")
print(f"[OK] Users collection: {sync_users_collection}")
print(f"[OK] Schemes collection: {sync_schemes_collection}")
print(f"[OK] LangGraph: {welfare_graph}")

# Initialize Chromadb collection for RAG (reuses chroma_client created above)
collection = chroma_client.get_or_create_collection(name="welfare_schemes")
print("=" * 50 + "\n")

# -------------------- API ENDPOINTS --------------------

# -------------------- Approval workflow --------------------
# Scraped schemes land in `staging` with status "pending_approval" and are only
# promoted to the live `schemes` collection after manual review here.
class ApprovalRequest(BaseModel):
    apply_link: str


def _staging_to_live(doc: dict) -> dict:
    """Map a raw staging document to the live scheme schema the matcher reads."""
    rules = {}
    state = (doc.get("state") or "all").strip().lower()
    rules["state"] = state if state else "all"
    return {
        "name": doc.get("name"),
        "description": doc.get("description", ""),
        "eligibility_rules": rules,
        "required_documents": doc.get("required_documents", []),
        "apply_link": doc.get("apply_link", ""),
        "deadline": doc.get("deadline", ""),
        "category": doc.get("category", "general"),
        "source": doc.get("source", ""),
    }


@app.get("/staging")
async def get_staging():
    """List schemes awaiting approval."""
    cursor = (
        async_mongo_client["welfarebot"]["staging"]
        .find({"status": "pending_approval"}, {"_id": 0})
        .sort("scraped_at", -1)
        .limit(100)
    )
    return {"pending": await cursor.to_list(length=100)}


@app.post("/staging/approve")
async def approve_scheme(request: ApprovalRequest):
    """Promote one pending scheme from staging to the live schemes collection."""
    staging = sync_mongo_client["welfarebot"]["staging"]
    doc = staging.find_one({"apply_link": request.apply_link})
    if not doc:
        raise HTTPException(status_code=404, detail="Scheme not found in staging")
    live = _staging_to_live(doc)
    sync_schemes_collection.update_one({"name": live["name"]}, {"$set": live}, upsert=True)
    staging.update_one({"apply_link": request.apply_link}, {"$set": {"status": "approved"}})
    return {"status": "approved", "scheme": live["name"]}


@app.post("/staging/reject")
async def reject_scheme(request: ApprovalRequest):
    staging = sync_mongo_client["welfarebot"]["staging"]
    result = staging.update_one(
        {"apply_link": request.apply_link}, {"$set": {"status": "rejected"}}
    )
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Scheme not found in staging")
    return {"status": "rejected"}


# RAG endpoint - semantic search over stored schemes (ChromaDB)
@app.post("/rag")
async def rag_query(query: dict):
    """Accepts JSON {"question": "..."} and returns top matching scheme texts."""
    question = query.get("question", "")
    if not question:
        raise HTTPException(status_code=400, detail="Question required")

    try:
        from rag.cached_retriever import cached_retrieve
        matches = cached_retrieve(question, n=3)
        return {"matches": matches}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# Endpoint to manually trigger scraper
@app.post("/scraper/run")
async def trigger_scraper():
    loop = asyncio.get_event_loop()
    loop.run_in_executor(None, run_scraper)
    return {"status": "scraper started", "message": "Check /staging in 1-2 minutes"}