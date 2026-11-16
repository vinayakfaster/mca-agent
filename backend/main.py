"""FastAPI wrapper around the REAL run_agent() in step4_agent_loop.py.
Run from the project root:  uvicorn backend.main:app --port 8000
step4_agent_loop.py is NOT modified."""

from typing import Optional
import os, re, secrets, threading, logging, shutil, tempfile
from datetime import datetime

import requests
from dotenv import load_dotenv
from fastapi import Depends, FastAPI, Header, HTTPException, Query, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from fastapi.staticfiles import StaticFiles

# Study Companion Imports
from study_companion.study_tools import load_pdf, search_documents, generate_flashcards, create_quiz
# Data Analysis Imports
from study_companion.data_tools import load_data, clean_data, run_sql_query, generate_charts, statistical_analysis
# Code Documentation Imports
from study_companion.code_tools import scan_codebase, analyze_functions, generate_readme, write_docstrings

load_dotenv()
log = logging.getLogger("backend")

OLLAMA = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434").rstrip("/")
MODEL = os.getenv("OLLAMA_MODEL", "qwen3:8b")
API_KEY = os.getenv("API_KEY", "")
ORIGINS = [o.strip() for o in os.getenv("ALLOWED_ORIGINS", "http://localhost:5173").split(",") if o.strip()]
if not API_KEY:
    raise RuntimeError("API_KEY is not set. Copy .env.example to .env and set it.")
if "*" in ORIGINS:
    raise RuntimeError("ALLOWED_ORIGINS must not contain '*'.")

import step4_agent_loop as agent
from conversation_store import save_conversation, load_conversation, list_conversations

agent.url = f"{OLLAMA}/api/chat"

app = FastAPI(title="MCA Agent API")
app.add_middleware(CORSMiddleware, allow_origins=ORIGINS, allow_methods=["GET", "POST"],
                   allow_headers=["Content-Type", "X-API-Key", "ngrok-skip-browser-warning"])

# Mount charts directory for Data Analysis
os.makedirs("generated_charts", exist_ok=True)
app.mount("/charts", StaticFiles(directory="generated_charts"), name="charts")

UID_RE = re.compile(r"^[A-Za-z0-9_.@-]{1,64}$")
CID_RE = re.compile(r"^chat_[A-Za-z0-9_]{1,40}$")
LOCK = threading.Lock()
CITIES: dict = {}


def auth(x_api_key: str = Header(default="")):
    if not secrets.compare_digest(x_api_key.encode(), API_KEY.encode()):
        raise HTTPException(401, "Invalid or missing access key.")


def check_ids(uid, cid=None):
    if not UID_RE.match(uid):
        raise HTTPException(400, "Invalid user id.")
    if cid is not None and not CID_RE.match(cid):
        raise HTTPException(400, "Invalid conversation id.")


class ChatIn(BaseModel):
    user_id: str
    conversation_id: Optional[str] = None
    message: str = Field(min_length=1, max_length=4000)

class PathRequest(BaseModel):
    path: str


@app.get("/api/health")
def health():
    try:
        tags = requests.get(f"{OLLAMA}/api/tags", timeout=3).json().get("models", [])
        names = [m.get("name", "") for m in tags]
        return {"status": "ok", "ollama": True, "model": MODEL,
                "model_installed": any(n == MODEL or n.startswith(MODEL + ":") for n in names)}
    except Exception:
        return {"status": "degraded", "ollama": False, "model": MODEL, "model_installed": False}


@app.get("/api/modules", dependencies=[Depends(auth)])
def modules():
    return [
        {"id": "chat", "name": "AI Chat (run_agent)", "available": True,
         "note": "Tools: get_weather, calculate, search_old_conversations."},
        {"id": "history", "name": "Conversation history", "available": True, "note": "Uses conversation_store."},
        {"id": "study", "name": "Study Companion", "available": True, "note": "Upload PDF, Search, Generate Flashcards & Quizzes."},
        {"id": "data", "name": "Data Analysis", "available": True, "note": "Upload CSV/Excel, Clean, SQL Queries, Charts & Stats."},
        {"id": "code", "name": "Code Documentation", "available": True, "note": "Scan codebase, analyze functions, generate README, write docstrings."},
        {"id": "pay", "name": "x402 Payments", "available": False, "note": "Not implemented. No payments are made."},
    ]


@app.get("/api/conversations", dependencies=[Depends(auth)])
def conversations(user_id: str = Query(...)):
    check_ids(user_id)
    return {"conversations": sorted(list_conversations(user_id), reverse=True)}


@app.get("/api/conversations/{cid}", dependencies=[Depends(auth)])
def conversation(cid: str, user_id: str = Query(...)):
    check_ids(user_id, cid)
    if cid not in list_conversations(user_id):
        raise HTTPException(404, "Conversation not found.")
    msgs = load_conversation(user_id, cid)
    return {"messages": [{"role": m["role"], "content": m["content"]} for m in msgs
                         if m.get("role") in ("user", "assistant") and m.get("content")]}


@app.post("/api/chat", dependencies=[Depends(auth)])
def chat(req: ChatIn):
    uid = req.user_id
    cid = req.conversation_id or "chat_" + datetime.now().strftime("%Y%m%d_%H%M%S")
    check_ids(uid, cid)
    key = (uid, cid)
    try:
        with LOCK:
            history = load_conversation(uid, cid) if cid in list_conversations(uid) else []
            if not history:
                history = [{"role": "system", "content": agent.SYSTEM_PROMPT}]
            agent.session_facts["queried_cities"] = set(CITIES.get(key, set()))
            agent.tool_functions["search_old_conversations"] = (
                lambda query, _u=uid, _c=cid: agent.search_old_conversations(_u, _c, query))
            reply = agent.run_agent(history, req.message)
            CITIES[key] = set(agent.session_facts["queried_cities"])
            save_conversation(uid, cid, history)
        return {"reply": reply, "conversation_id": cid}
    except requests.exceptions.ConnectionError:
        raise HTTPException(503, "Cannot reach Ollama. Is it running (ollama serve)?")
    except requests.exceptions.Timeout:
        raise HTTPException(504, "Ollama took too long to respond.")
    except KeyError:
        raise HTTPException(502, f"Ollama returned an error. Is the model installed? Run: ollama pull {MODEL}")
    except HTTPException:
        raise
    except Exception:
        log.exception("chat failed")
        raise HTTPException(500, "Something went wrong while running the agent.")


# ==========================================
# STUDY COMPANION ENDPOINTS
# ==========================================

@app.post("/api/study/upload", dependencies=[Depends(auth)])
async def upload_pdf(file: UploadFile = File(...)):
    temp_dir = "temp_uploads"
    os.makedirs(temp_dir, exist_ok=True)
    file_path = os.path.join(temp_dir, file.filename)
    
    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
    
    result = load_pdf(file_path)
    
    if os.path.exists(file_path):
        os.remove(file_path)
        
    return {"message": result}


@app.post("/api/study/search", dependencies=[Depends(auth)])
async def search_pdf(query: str = Form(...), n_results: int = Form(5)):
    result = search_documents(query, n_results)
    return {"result": result}


@app.post("/api/study/flashcards", dependencies=[Depends(auth)])
async def make_flashcards(topic: str = Form(...), num_cards: int = Form(5)):
    result = generate_flashcards(topic, num_cards)
    return {"result": result}


@app.post("/api/study/quiz", dependencies=[Depends(auth)])
async def make_quiz(topic: str = Form(...), num_questions: int = Form(5), difficulty: str = Form("medium")):
    result = create_quiz(topic, num_questions, difficulty)
    return {"result": result}


# ==========================================
# DATA ANALYSIS ENDPOINTS
# ==========================================

@app.post("/api/data/upload", dependencies=[Depends(auth)])
async def data_upload(file: UploadFile = File(...)):
    temp_dir = "temp_data_uploads"
    os.makedirs(temp_dir, exist_ok=True)
    file_path = os.path.join(temp_dir, file.filename)
    
    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
        
    result = load_data(file_path)
    
    if os.path.exists(file_path):
        os.remove(file_path)
        
    return {"result": result}


@app.post("/api/data/clean", dependencies=[Depends(auth)])
async def data_clean():
    return {"result": clean_data()}


@app.post("/api/data/sql", dependencies=[Depends(auth)])
async def data_sql(query: str = Form(...)):
    return {"result": run_sql_query(query)}


@app.post("/api/data/charts", dependencies=[Depends(auth)])
async def data_charts():
    return {"result": generate_charts()}


@app.post("/api/data/stats", dependencies=[Depends(auth)])
async def data_stats():
    return {"result": statistical_analysis()}


# ==========================================
# CODE DOCUMENTATION ENDPOINTS
# ==========================================

@app.post("/api/code/scan", dependencies=[Depends(auth)])
async def code_scan(req: PathRequest):
    return {"result": scan_codebase(req.path)}


@app.post("/api/code/readme", dependencies=[Depends(auth)])
async def code_readme(req: PathRequest):
    return {"result": generate_readme(req.path)}


@app.post("/api/code/analyze", dependencies=[Depends(auth)])
async def code_analyze(file: UploadFile = File(...)):
    # Save uploaded .py file temporarily
    with tempfile.NamedTemporaryFile(delete=False, suffix=".py") as tmp:
        shutil.copyfileobj(file.file, tmp)
        tmp_path = tmp.name
    
    try:
        result = analyze_functions(tmp_path)
    finally:
        os.remove(tmp_path)
    
    return {"result": result}


@app.post("/api/code/docstrings", dependencies=[Depends(auth)])
async def code_docstrings(file: UploadFile = File(...)):
    with tempfile.NamedTemporaryFile(delete=False, suffix=".py") as tmp:
        shutil.copyfileobj(file.file, tmp)
        tmp_path = tmp.name
    
    try:
        result = write_docstrings(tmp_path)
    finally:
        os.remove(tmp_path)
    
    return {"result": result}