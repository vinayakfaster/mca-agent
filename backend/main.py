"""FastAPI wrapper around the REAL run_agent() in step4_agent_loop.py.
Run from the project root:  uvicorn backend.main:app --port 8000
step4_agent_loop.py is NOT modified."""

from typing import Literal, Optional
import os, re, secrets, threading, logging
from datetime import datetime

import requests
from dotenv import load_dotenv
from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

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

import step4_agent_loop as agent  # safe: CLI is under __main__ guard
from conversation_store import save_conversation, load_conversation, list_conversations
from tools_registry import make_ctx
from files_api import create_router

agent.url = f"{OLLAMA}/api/chat"  # env-configurable Ollama URL
agent.MODEL = MODEL               # and the model name

app = FastAPI(title="MCA Agent API")
app.add_middleware(CORSMiddleware, allow_origins=ORIGINS, allow_methods=["GET", "POST", "DELETE"],
                   allow_headers=["Content-Type", "X-API-Key", "ngrok-skip-browser-warning"])

UID_RE = re.compile(r"^[A-Za-z0-9_.@-]{1,64}$")      # blocks path traversal in conversation files
CID_RE = re.compile(r"^chat_[A-Za-z0-9_]{1,40}$")
LOCK = threading.Lock()   # one agent turn at a time: keeps conversation load/save and the single local Ollama orderly


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
    # Which tab the user is on. Optional: the current frontend does not send it yet.
    module: Optional[Literal["study", "data", "code", "pay"]] = None


# File upload / list / download / delete  ->  /api/files   (same access key as everything else)
app.include_router(create_router(auth))


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
        {"id": "study", "name": "Study Companion", "available": False, "note": "Not wired yet: no study tool is registered in step4_agent_loop.py."},
        {"id": "data", "name": "Data Analysis", "available": False, "note": "Not implemented in the agent yet."},
        {"id": "code", "name": "Code Documentation", "available": False, "note": "Not implemented in the agent yet."},
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
    try:
        with LOCK:
            history = load_conversation(uid, cid) if cid in list_conversations(uid) else []
            if not history:
                history = [{"role": "system", "content": agent.SYSTEM_PROMPT}]
            # ctx tells tools who is asking (for past-chat search and the user's files).
            # The agent keeps its own per-conversation facts now, so no globals are patched here any more.
            ctx = make_ctx(uid, cid, req.module)
            reply = agent.run_agent(history, req.message, module=req.module, ctx=ctx)
            save_conversation(uid, cid, history)
        return {"reply": reply, "conversation_id": cid}
    except requests.exceptions.ConnectionError:
        raise HTTPException(503, "Cannot reach Ollama. Is it running (ollama serve)?")
    except requests.exceptions.Timeout:
        raise HTTPException(504, "Ollama took too long to respond.")
    except (KeyError, requests.exceptions.HTTPError):
        raise HTTPException(502, f"Ollama returned an error. Is the model installed? Run: ollama pull {MODEL}")
    except HTTPException:
        raise
    except Exception:
        log.exception("chat failed")
        raise HTTPException(500, "Something went wrong while running the agent.")
