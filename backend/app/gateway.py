import os
import time
import json
import hashlib
import logging
from typing import List, Dict, Any, Optional, Tuple
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
# Structure: { cache_key: { "reply": str, "input_tokens": int, "output_tokens": int, "model": str } }
_CACHE_STORE: Dict[str, Dict[str, Any]] = {}

def get_cache_key(model: str, messages: List[Dict[str, str]]) -> str:
    """
    Cache key: model + the full message list sent to the LLM (system prompt + history + new message).
    """
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
    """Safe fallback token estimator if provider does not return usage."""
    words = len(text.split())
    chars = len(text)
    # Approx 1 token ~ 4 chars / 0.75 words, min 1
    return max(1, int(chars / 4) if chars > 0 else 1)

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
        
        # Call LiteLLM with this key
        try:
            # Handle mock keys for offline/testing scenarios
            if api_key.startswith("mock_") or os.getenv("MOCK_LLM") == "true":
                user_msg = messages[-1]["content"] if messages else ""
                reply_text = f"Response to: {user_msg}"
                # Derive realistic token counts
                prompt_text = " ".join([m["content"] for m in messages])
                input_tokens = estimate_tokens(prompt_text)
                output_tokens = estimate_tokens(reply_text)
                chosen_key_id = k_id
                break
            
            # Live LiteLLM call
            response = litellm.completion(
                model=target_model,
                messages=messages,
                api_key=api_key,
                caching=True,
                drop_params=True
            )
            
            # Extract content
            choices = response.choices
            if choices and len(choices) > 0:
                reply_text = choices[0].message.content or ""
            else:
                reply_text = str(response)
                
            # Extract usage
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
        # Every key failed (rate-limited, quota exhausted or 5xx)
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
