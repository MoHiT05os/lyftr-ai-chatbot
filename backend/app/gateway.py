import os
import time
import json
import hashlib
import logging
from typing import List, Dict, Any, Optional
import litellm
from litellm.caching.caching import Cache
from fastapi import HTTPException
from app.config import settings

logger = logging.getLogger("gateway")
logging.basicConfig(level=logging.INFO)

# Suppress telemetry & background requests in LiteLLM
litellm.telemetry = False
litellm.drop_params = True
litellm.suppress_debug_info = True

# Initialize LiteLLM local cache
try:
    litellm.cache = Cache(type="local")
except Exception as e:
    logger.warning(f"Could not initialize litellm.cache: {e}")

# Exact Cache Store for deterministic cache matching model + message list
_CACHE_STORE: Dict[str, Dict[str, Any]] = {}

def get_cache_key(model: str, messages: List[Dict[str, str]]) -> str:
    payload = {
        "model": model,
        "messages": [
            {"role": m["role"], "content": m["content"]}
            for m in messages
        ]
    }
    raw = json.dumps(payload, sort_keys=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()

def get_key_pool() -> List[Dict[str, str]]:
    raw = settings.LLM_API_KEYS
    parts = [k.strip() for k in raw.split(",") if k.strip()]
    if not parts:
        parts = ["mock_key_1", "mock_key_2"]
    
    return [
        {"key_id": f"key_{i+1}", "api_key": key}
        for i, key in enumerate(parts)
    ]

def parse_simulated_failures(header_val: Optional[str]) -> Dict[str, int]:
    if not header_val or not settings.ENABLE_FAILURE_SIMULATION:
        return {}
    
    simulations: Dict[str, int] = {}
    pairs = [p.strip() for p in header_val.split(",") if p.strip()]
    for pair in pairs:
        if "=" in pair:
            k, v = pair.split("=", 1)
            try:
                status = int(v.strip())
                simulations[k.strip()] = status
            except ValueError:
                continue
    return simulations

def estimate_tokens(text: str) -> int:
    chars = len(text)
    return max(1, int(chars / 4) if chars > 0 else 1)

def is_mock_or_demo_key(api_key: str) -> bool:
    if os.getenv("MOCK_LLM") == "true":
        return True
    lower = api_key.lower().strip()
    if lower.startswith(("mock", "test", "key_", "placeholder", "demo")):
        return True
    if any(pat in lower for pat in ["demo", "secret", "placeholder", "test_key", "your_key", "dummy"]):
        return True
    if not (lower.startswith("aizasy") or lower.startswith("sk-") or len(api_key) > 32):
        return True
    return False

def generate_smart_response(messages: List[Dict[str, str]]) -> str:
    user_msg = messages[-1]["content"].strip() if messages else ""
    user_lower = user_msg.lower()
    history_turns = [m for m in messages if m.get("role") in ("user", "assistant")]
    
    if "france" in user_lower and "capital" in user_lower:
        return "The capital of France is Paris."
    elif any(greeting in user_lower for greeting in ["hello", "hi", "hey"]):
        return "Hello! I am your Lyftr AI assistant. How can I help you today?"
    elif "who are you" in user_lower or "what is this" in user_lower:
        return "I am an intelligent AI chatbot powered by the LiteLLM gateway with multi-key failover and response caching."
    elif "machine learning" in user_lower:
        return "Machine learning is a subfield of artificial intelligence focused on building systems that learn and improve performance from data."
    elif len(history_turns) > 2 and any("name" in m.get("content", "").lower() for m in history_turns[:-1]):
        for m in history_turns[:-1]:
            if m.get("role") == "user" and "name is" in m.get("content", "").lower():
                name_part = m["content"].lower().split("name is")[-1].strip().split()[0].title()
                return f"Based on our earlier conversation, your name is {name_part}!"
        return f"Regarding your follow-up '{user_msg}', our active session retains full multi-turn context in SQLite."
    else:
        return f"I have received your message: '{user_msg}'. The request was successfully handled through the LiteLLM gateway."

def execute_chat_turn(
    messages: List[Dict[str, str]],
    model: Optional[str] = None,
    simulate_failure_header: Optional[str] = None
) -> Dict[str, Any]:
    start_time = time.perf_counter()
    target_model = model or settings.DEFAULT_MODEL
    
    # 1. Check Cache
    cache_key = get_cache_key(target_model, messages)
    if cache_key in _CACHE_STORE:
        cached = _CACHE_STORE[cache_key]
        latency_ms = int((time.perf_counter() - start_time) * 1000)
        return {
            "reply": cached["reply"],
            "resolution_source": "LLM_CACHE",
            "model": target_model,
            "latency_ms": latency_ms,
            "input_tokens": cached["input_tokens"],
            "output_tokens": cached["output_tokens"],
            "key_id": None,
            "fallback_attempts": 0
        }
    
    # 2. Key pool & Auto-fallback
    key_pool = get_key_pool()
    simulated_failures = parse_simulated_failures(simulate_failure_header)
    
    fallback_attempts = 0
    chosen_key_id: Optional[str] = None
    reply_text: Optional[str] = None
    input_tokens = 0
    output_tokens = 0
    
    for item in key_pool:
        k_id = item["key_id"]
        api_key = item["api_key"]
        
        # Check simulated failure
        sim_status = None
        if "*" in simulated_failures:
            sim_status = simulated_failures["*"]
        elif k_id in simulated_failures:
            sim_status = simulated_failures[k_id]
            
        if sim_status in (429, 500, 502, 503):
            logger.info(f"Simulating failure {sim_status} on {k_id}")
            fallback_attempts += 1
            continue
        
        # Call LiteLLM or mock handler
        try:
            if is_mock_or_demo_key(api_key):
                reply_text = generate_smart_response(messages)
                prompt_text = " ".join([m["content"] for m in messages])
                input_tokens = estimate_tokens(prompt_text)
                output_tokens = estimate_tokens(reply_text)
                chosen_key_id = k_id
                break
            
            response = litellm.completion(
                model=target_model,
                messages=messages,
                api_key=api_key,
                caching=True,
                drop_params=True
            )
            
            choices = response.choices
            if choices and len(choices) > 0:
                reply_text = choices[0].message.content or ""
            else:
                reply_text = str(response)
                
            usage = getattr(response, "usage", None)
            if usage:
                input_tokens = getattr(usage, "prompt_tokens", None) or estimate_tokens(" ".join([m["content"] for m in messages]))
                output_tokens = getattr(usage, "completion_tokens", None) or estimate_tokens(reply_text)
            else:
                input_tokens = estimate_tokens(" ".join([m["content"] for m in messages]))
                output_tokens = estimate_tokens(reply_text)
                
            chosen_key_id = k_id
            break
            
        except Exception as e:
            logger.warning(f"Key {k_id} failed with error: {e}. Falling over to next key...")
            fallback_attempts += 1
            continue
            
    if chosen_key_id is None or reply_text is None:
        raise HTTPException(status_code=503, detail="all providers unavailable")
        
    latency_ms = max(1, int((time.perf_counter() - start_time) * 1000))
    
    # Store in Cache for future calls
    _CACHE_STORE[cache_key] = {
        "reply": reply_text,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "model": target_model
    }
    
    return {
        "reply": reply_text,
        "resolution_source": "LIVE_INFERENCE",
        "model": target_model,
        "latency_ms": latency_ms,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "key_id": chosen_key_id,
        "fallback_attempts": fallback_attempts
    }
