from typing import Optional, List, Dict, Any, Union
from pydantic import BaseModel, Field, field_validator

class ChatRequest(BaseModel):
    session_id: str = Field(..., min_length=1, max_length=128)
    message: str = Field(...)
    system_prompt: Optional[str] = None

    @field_validator("message")
    @classmethod
    def validate_message(cls, v: str) -> str:
        trimmed = v.strip()
        if len(trimmed) < 1:
            raise ValueError("message must be non-empty after trimming whitespace")
        if len(trimmed) > 4000:
            raise ValueError("message must not exceed 4000 characters after trimming whitespace")
        return trimmed

class ChatMetadata(BaseModel):
    resolution_source: str
    model: str
    latency_ms: int
    input_tokens: int
    output_tokens: int
    key_id: Optional[str] = None
    fallback_attempts: int

class ChatResponse(BaseModel):
    session_id: str
    reply: str
    metadata: ChatMetadata

class AssistantHistoryMetadata(BaseModel):
    resolution_source: str
    input_tokens: int
    output_tokens: int

class HistoryMessage(BaseModel):
    role: str
    content: str
    metadata: Optional[Dict[str, Any]] = None

class SessionHistoryResponse(BaseModel):
    session_id: str
    messages: List[HistoryMessage]

class HealthResponse(BaseModel):
    status: str
    keys_configured: int
    cache_enabled: bool
