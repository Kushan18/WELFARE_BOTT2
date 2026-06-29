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
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

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

chroma_client = PersistentClient(path="./chroma_storage")

welfare_graph = build_graph(groq_client, sync_users_collection, sync_schemes_collection)

# Scraper + scheduler (moved to top so they're defined before any endpoint uses them)
from scraper.manager import run_scraper
from apscheduler.schedulers.background import BackgroundScheduler

scheduler = BackgroundScheduler()
scheduler.add_job(run_scraper, "interval", days=3, id="scraper_job")
scheduler.start()

# FastAPI app instance
app = FastAPI(title="WelfareBot Backend")

@app.get("/")
async def root():
    return {"message": "WelfareBot Backend is running"}

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serve React front‑end build
app.mount("/", StaticFiles(directory="frontend/dist", html=True), name="frontend")

# Fallback for any unknown route (SPA)
@app.get("/{full_path:path}", include_in_schema=False)
async def spa_catchall(full_path: str):
    return FileResponse("frontend/dist/index.html")


# Request/Response models
class ChatRequest(BaseModel):
    session_id: str
    message: str


class ChatResponse(BaseModel):
    reply: str
    show_form_choice: Optional[bool] = None
    clear_session: Optional[bool] = None
    chips: Optional[List[str]] = None


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


# Helper function to generate chips dynamically
def generate_chips(onboarding_step: str, user_doc: dict, intent: str = None, schemes: list = None) -> List[str]:
    """Generate suggestion chips based on conversation state."""
    chips = []
    
    # Always add Start Over
    chips.append("Start Over")
    
    if onboarding_step == "name":
        chips.extend(["English", "हिंदी", "తెలుగు", "தமிழ்", "ಕನ್ನಡ"])
    elif onboarding_step == "language_preference":
        chips.extend(["Fill Form", "Chat Instead"])
    elif onboarding_step == "form_chat_choice":
        chips.extend(["Fill Form", "Chat Instead"])
    elif onboarding_step == "state":
        chips.extend(["Andhra Pradesh", "Telangana", "Delhi", "Maharashtra", "Tamil Nadu", "Karnataka"])
    elif onboarding_step == "occupation":
        chips.extend(["Student", "Farmer", "Daily Wage", "Business", "Government", "Other"])
    elif onboarding_step == "caste_category":
        chips.extend(["General", "OBC", "SC", "ST"])
    elif onboarding_step == "gender":
        chips.extend(["Male", "Female", "Other"])
    elif onboarding_step == "age":
        chips.extend(["18-25", "26-35", "36-50", "50+"])
    elif onboarding_step == "income_bracket":
        chips.extend(["Below 1 Lakh", "1-2.5 Lakh", "2.5-5 Lakh", "5-10 Lakh", "Above 10 Lakh"])
    elif onboarding_step == "confirmation":
        chips.extend(["Yes Continue", "Edit Details"])
    elif intent == "scheme_query" and schemes:
        # Add scheme names as chips
        for scheme in schemes[:5]:
            chips.append(scheme.get("name", "Unknown Scheme"))
        chips.append("Ask Something Else")
    elif intent == "faq":
        # Enhanced quick reply chips for FAQ/general queries
        quick_replies = [
            "Find My Schemes",
            "Check Eligibility",
            "Documents Needed",
            "Application Deadlines",
            "Contact Support"
        ]
        chips.extend(quick_replies)
        chips.append("Ask Something Else")
    elif onboarding_step is None and intent == "faq":
        # General conversation quick replies
        general_replies = [
            "Tell me about PM Kisan",
            "Farmer schemes in Telangana",
            "Student scholarships",
            "Pension schemes",
            "Health insurance schemes"
        ]
        chips.extend(general_replies)
    
    return chips

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

        schemes = match_schemes(profile_dict, sync_schemes_collection)
        # Convert ObjectId to string for JSON serialization
        schemes_list = []
        for scheme in schemes[:5]:
            scheme_dict = dict(scheme)
            if "_id" in scheme_dict:
                scheme_dict["_id"] = str(scheme_dict["_id"])
            schemes_list.append(scheme_dict)
        return {"status": "success", "schemes": schemes_list}
    except Exception as e:
        return {"error": str(e)}


@app.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest):
    try:
        session_id = request.session_id
        message = request.message.strip()

        if not message:
            return ChatResponse(reply="Please say something.")

        # Use LangGraph for all routing (smart routing + onboarding + FAQ + schemes)
        user_doc = sync_users_collection.find_one({"session_id": session_id}) or {}
        onboarding_step = user_doc.get("onboarding_step", "name")

        state = {
            "session_id": session_id,
            "message": message,
            "onboarding_step": onboarding_step,
            "intent": None,
            "reply": None,
            "show_form_choice": None,
            "clear_session": None,
            "user_profile": user_doc,
        }

        result = welfare_graph.invoke(state)

        reply = result.get("reply", "Sorry, couldn't process that.")
        show_form_choice = result.get("show_form_choice", False)
        clear_session = result.get("clear_session", False)
        
        # Generate chips based on result state
        result_onboarding_step = result.get("onboarding_step", onboarding_step)
        result_intent = result.get("intent")
        chips = generate_chips(result_onboarding_step, user_doc, result_intent)

        await conversations_collection.insert_one({
            "session_id": session_id,
            "user_message": message,
            "bot_reply": reply,
            "intent": result.get("intent"),
            "timestamp": datetime.utcnow(),
        })
        
        # Save to conversation history
        from agent.conversation_history import save_conversation
        try:
            # Get current messages from frontend or build from DB
            existing_history = sync_users_collection.find_one({"session_id": session_id}) or {}
            messages = existing_history.get("messages", [])
            messages.append({"role": "user", "text": message, "timestamp": datetime.utcnow().isoformat()})
            messages.append({"role": "bot", "text": reply, "timestamp": datetime.utcnow().isoformat()})
            save_conversation(session_id, messages, user_doc)
        except Exception as e:
            logger.error(f"Failed to save conversation history: {e}")

        return ChatResponse(
            reply=reply,
            show_form_choice=show_form_choice,
            clear_session=clear_session,
            chips=chips,
        )
    except Exception as e:
        logging.error(f"Chat endpoint error: {e}")
        return ChatResponse(reply=f"Error: {str(e)}")


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

# Start Phase 7 scraper scheduler (runs every 2 days)
try:
    from scraper.main_scheduler import start_scheduler
    start_scheduler()
    print("[SCRAPER] 2-day scheduler started successfully")
except Exception as e:
    print(f"[SCRAPER] Scheduler startup failed: {e}")

# -------------------- API ENDPOINTS --------------------

# Existing staging endpoint
@app.get("/staging")
async def get_staging():
    client = motor.motor_asyncio.AsyncIOMotorClient(os.getenv("MONGODB_URI"))
    db = client.get_default_database()
    cursor = db.staging.find({"status": "pending"}).sort("scraped_at", -1).limit(100)
    return await cursor.to_list(length=100)


# Approval workflow endpoints
@app.get("/admin/staging")
async def get_staging_schemes():
    """Get all schemes in staging awaiting review."""
    from agent.approval_workflow import ApprovalWorkflow
    workflow = ApprovalWorkflow(os.getenv("MONGODB_URI"))
    schemes = workflow.get_staging_schemes()
    # Convert ObjectId to string for JSON serialization
    for scheme in schemes:
        if "_id" in scheme:
            scheme["_id"] = str(scheme["_id"])
    return {"schemes": schemes}

@app.get("/admin/pending")
async def get_pending_schemes():
    """Get all schemes in pending_approval."""
    from agent.approval_workflow import ApprovalWorkflow
    workflow = ApprovalWorkflow(os.getenv("MONGODB_URI"))
    schemes = workflow.get_pending_schemes()
    # Convert ObjectId to string for JSON serialization
    for scheme in schemes:
        if "_id" in scheme:
            scheme["_id"] = str(scheme["_id"])
    return {"schemes": schemes}

@app.post("/admin/approve/{scheme_id}")
async def approve_scheme(scheme_id: str):
    """Approve a scheme from staging to pending_approval."""
    from agent.approval_workflow import ApprovalWorkflow
    workflow = ApprovalWorkflow(os.getenv("MONGODB_URI"))
    success = workflow.approve_scheme(scheme_id)
    if success:
        return {"status": "success", "message": "Scheme moved to pending approval"}
    return {"status": "error", "message": "Failed to approve scheme"}

@app.post("/admin/reject-staging/{scheme_id}")
async def reject_staging_scheme(scheme_id: str, reason: str = ""):
    """Reject a scheme from staging."""
    from agent.approval_workflow import ApprovalWorkflow
    workflow = ApprovalWorkflow(os.getenv("MONGODB_URI"))
    success = workflow.reject_scheme(scheme_id, reason)
    if success:
        return {"status": "success", "message": "Scheme rejected"}
    return {"status": "error", "message": "Failed to reject scheme"}

@app.post("/admin/publish/{scheme_id}")
async def publish_scheme(scheme_id: str):
    """Publish a scheme from pending_approval to live."""
    from agent.approval_workflow import ApprovalWorkflow
    workflow = ApprovalWorkflow(os.getenv("MONGODB_URI"))
    success = workflow.publish_scheme(scheme_id)
    if success:
        return {"status": "success", "message": "Scheme published to live"}
    return {"status": "error", "message": "Failed to publish scheme"}

@app.post("/admin/reject-pending/{scheme_id}")
async def reject_pending_scheme(scheme_id: str, reason: str = ""):
    """Reject a scheme from pending_approval."""
    from agent.approval_workflow import ApprovalWorkflow
    workflow = ApprovalWorkflow(os.getenv("MONGODB_URI"))
    success = workflow.reject_pending_scheme(scheme_id, reason)
    if success:
        return {"status": "success", "message": "Scheme rejected"}
    return {"status": "error", "message": "Failed to reject scheme"}

@app.get("/admin/stats")
async def get_approval_stats():
    """Get approval workflow statistics."""
    from agent.approval_workflow import ApprovalWorkflow
    workflow = ApprovalWorkflow(os.getenv("MONGODB_URI"))
    stats = workflow.get_approval_stats()
    return stats

# Conversation History Endpoints
@app.get("/history/{session_id}")
async def get_history(session_id: str):
    """Get conversation history for a session."""
    from agent.conversation_history import get_conversation_history
    history = get_conversation_history(session_id)
    if history:
        history['_id'] = str(history['_id'])
        history['created_at'] = history['created_at'].isoformat()
        history['updated_at'] = history['updated_at'].isoformat()
    return {"history": history}

@app.get("/history")
async def get_all_history(limit: int = 50):
    """Get all conversation histories."""
    from agent.conversation_history import get_all_conversations
    histories = get_all_conversations(limit)
    for h in histories:
        h['_id'] = str(h['_id'])
        h['created_at'] = h['created_at'].isoformat()
        h['updated_at'] = h['updated_at'].isoformat()
    return {"histories": histories}

@app.get("/history/search")
async def search_history(query: str, limit: int = 20):
    """Search conversation histories."""
    from agent.conversation_history import search_conversations
    histories = search_conversations(query, limit)
    for h in histories:
        h['_id'] = str(h['_id'])
        h['created_at'] = h['created_at'].isoformat()
        h['updated_at'] = h['updated_at'].isoformat()
    return {"histories": histories}

@app.delete("/history/{session_id}")
async def delete_history(session_id: str):
    """Delete a conversation history."""
    from agent.conversation_history import delete_conversation
    success = delete_conversation(session_id)
    return {"status": "success" if success else "error"}

@app.get("/history/stats")
async def get_history_stats():
    """Get conversation history statistics."""
    from agent.conversation_history import get_conversation_stats
    stats = get_conversation_stats()
    return stats

# Email Reminder Endpoints
@app.post("/email/test")
async def send_test_email(request: dict):
    """Send a test email to verify email configuration."""
    from agent.email_scheduler import send_test_email
    to_email = request.get("email")
    if not to_email:
        raise HTTPException(status_code=400, detail="Email address required")
    success = send_test_email(to_email)
    return {"status": "success" if success else "error"}

@app.post("/email/subscribe")
async def subscribe_email_reminders(request: dict):
    """Subscribe user to email reminders."""
    session_id = request.get("session_id")
    email = request.get("email")
    subscribe = request.get("subscribe", True)
    
    if not session_id or not email:
        raise HTTPException(status_code=400, detail="session_id and email required")
    
    result = sync_users_collection.update_one(
        {"session_id": session_id},
        {"$set": {"email": email, "email_reminders": subscribe}}
    )
    
    return {"status": "success", "modified": result.modified_count > 0}

@app.get("/email/schedule")
async def schedule_email_reminders():
    """Manually trigger scheduling of email reminders."""
    from agent.email_scheduler import schedule_deadline_reminders
    schedule_deadline_reminders()
    return {"status": "success", "message": "Email reminders scheduled"}


# RAG endpoint – simple semantic search over stored schemes
@app.post("/rag")
async def rag_query(query: dict):
    """Accepts JSON {"question": "..."} and returns top matching scheme texts."""
    question = query.get("question", "")
    if not question:
        raise HTTPException(status_code=400, detail="Question required")

    try:
        # Use Groq to get embedding (placeholder: use text as is)
        # For now, perform a naive text match against stored documents
        docs = collection.get(ids=collection.get().ids)
        # Very naive: return first 3 documents
        return {"matches": docs['documents'][:3]}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# Endpoint to manually trigger scraper
@app.post("/scraper/run")
async def trigger_scraper():
    loop = asyncio.get_event_loop()
    loop.run_in_executor(None, run_scraper)
    return {"status": "scraper started", "message": "Check /staging in 1-2 minutes"}