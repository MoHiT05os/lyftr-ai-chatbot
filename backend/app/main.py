from contextlib import asynccontextmanager
from typing import Optional
from fastapi import FastAPI, Header, HTTPException, Request, status
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.exceptions import RequestValidationError

from app.config import settings
from app.database import init_db, check_db_health, get_session_messages, save_message_turn
from app.gateway import execute_chat_turn, get_key_pool
from app.schemas import (
    ChatRequest,
    ChatResponse,
    ChatMetadata,
    SessionHistoryResponse,
    HistoryMessage,
    HealthResponse
)

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Initialize SQLite database schema
    init_db()
    yield

app = FastAPI(
    title="Lyftr AI - Resilient LLM Gateway",
    version="1.0.0",
    lifespan=lifespan
)

# Configure CORS
origins = [o.strip() for o in settings.ALLOWED_ORIGINS.split(",") if o.strip()]
if not origins:
    origins = ["*"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins if "*" not in origins else ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["*"]
)

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    if isinstance(exc, HTTPException):
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": exc.detail}
        )
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"detail": "internal server error"}
    )

@app.get("/health", response_model=HealthResponse)
def health():
    db_ok = check_db_health()
    if not db_ok:
        raise HTTPException(status_code=500, detail="database unreachable")
    
    keys = get_key_pool()
    return HealthResponse(
        status="ok",
        keys_configured=len(keys),
        cache_enabled=True
    )

@app.post("/chat", response_model=ChatResponse)
def chat(
    payload: ChatRequest,
    x_simulate_failure: Optional[str] = Header(None, alias="X-Simulate-Failure")
):
    session_id = payload.session_id
    user_message = payload.message.strip()
    
    # 1. Fetch existing session history
    raw_history = get_session_messages(session_id) or []
    
    # 2. Build LLM message list: system prompt + history + new user message
    effective_system_prompt = payload.system_prompt or settings.DEFAULT_SYSTEM_PROMPT
    llm_messages = [{"role": "system", "content": effective_system_prompt}]
    
    for h in raw_history:
        llm_messages.append({"role": h["role"], "content": h["content"]})
        
    llm_messages.append({"role": "user", "content": user_message})
    
    # 3. Execute inference through gateway (with caching & key failover)
    result = execute_chat_turn(
        messages=llm_messages,
        model=settings.DEFAULT_MODEL,
        simulate_failure_header=x_simulate_failure
    )
    
    reply = result["reply"]
    metadata_dict = {
        "resolution_source": result["resolution_source"],
        "model": result["model"],
        "latency_ms": result["latency_ms"],
        "input_tokens": result["input_tokens"],
        "output_tokens": result["output_tokens"],
        "key_id": result["key_id"],
        "fallback_attempts": result["fallback_attempts"]
    }
    
    # 4. Save turn to database only upon successful completion
    assistant_db_metadata = {
        "resolution_source": result["resolution_source"],
        "input_tokens": result["input_tokens"],
        "output_tokens": result["output_tokens"]
    }
    save_message_turn(session_id, user_message, reply, assistant_db_metadata)
    
    return ChatResponse(
        session_id=session_id,
        reply=reply,
        metadata=ChatMetadata(**metadata_dict)
    )

@app.get("/sessions/{session_id}/messages", response_model=SessionHistoryResponse)
def get_session(session_id: str):
    history = get_session_messages(session_id)
    if history is None:
        raise HTTPException(status_code=404, detail="session not found")
    
    messages = [HistoryMessage(**m) for m in history]
    return SessionHistoryResponse(session_id=session_id, messages=messages)
