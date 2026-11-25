import os
import pytest
from fastapi.testclient import TestClient

# Set test environment variables before importing app
os.environ["DATABASE_URL"] = "sqlite:///./test_app.db"
os.environ["LLM_API_KEYS"] = "key_1_test_secret,key_2_test_secret"
os.environ["ENABLE_FAILURE_SIMULATION"] = "true"
os.environ["MOCK_LLM"] = "true"

from app.main import app
from app.database import init_db, get_db_path
from app.gateway import _CACHE_STORE

@pytest.fixture(autouse=True)
def setup_test_db():
    db_path = get_db_path()
    if os.path.exists(db_path):
        os.remove(db_path)
    init_db()
    _CACHE_STORE.clear()
    yield
    if os.path.exists(db_path):
        try:
            os.remove(db_path)
        except Exception:
            pass

client = TestClient(app)

def test_health_endpoint():
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["keys_configured"] == 2
    assert data["cache_enabled"] is True

def test_chat_live_inference_and_cache_hit():
    # 1. First call in session 1 -> LIVE_INFERENCE
    payload = {
        "session_id": "session-1",
        "message": "What is the capital of France?"
    }
    res1 = client.post("/chat", json=payload)
    assert res1.status_code == 200
    data1 = res1.json()
    assert data1["session_id"] == "session-1"
    assert data1["reply"] != ""
    assert data1["metadata"]["resolution_source"] == "LIVE_INFERENCE"
    assert data1["metadata"]["key_id"] == "key_1"
    assert data1["metadata"]["fallback_attempts"] == 0
    assert data1["metadata"]["input_tokens"] > 0
    assert data1["metadata"]["output_tokens"] > 0

    # 2. Same first message in a NEW session -> LLM_CACHE
    payload_new_session = {
        "session_id": "session-2",
        "message": "What is the capital of France?"
    }
    res2 = client.post("/chat", json=payload_new_session)
    assert res2.status_code == 200
    data2 = res2.json()
    assert data2["session_id"] == "session-2"
    assert data2["reply"] == data1["reply"]
    assert data2["metadata"]["resolution_source"] == "LLM_CACHE"
    assert data2["metadata"]["key_id"] is None
    assert data2["metadata"]["fallback_attempts"] == 0
    assert data2["metadata"]["input_tokens"] == data1["metadata"]["input_tokens"]
    assert data2["metadata"]["output_tokens"] == data1["metadata"]["output_tokens"]

def test_chat_different_message_does_not_hit_cache():
    # Initial message
    res1 = client.post("/chat", json={"session_id": "s-alpha", "message": "First unique query"})
    assert res1.status_code == 200
    assert res1.json()["metadata"]["resolution_source"] == "LIVE_INFERENCE"

    # Different message
    res2 = client.post("/chat", json={"session_id": "s-beta", "message": "Second unique query"})
    assert res2.status_code == 200
    assert res2.json()["metadata"]["resolution_source"] == "LIVE_INFERENCE"

def test_multi_turn_history_and_persistence():
    session_id = "s-multiturn-1"
    # Turn 1
    r1 = client.post("/chat", json={"session_id": session_id, "message": "My name is Alice"})
    assert r1.status_code == 200
    
    # Turn 2
    r2 = client.post("/chat", json={"session_id": session_id, "message": "What is my name?"})
    assert r2.status_code == 200

    # Query GET /sessions/{session_id}/messages
    history_res = client.get(f"/sessions/{session_id}/messages")
    assert history_res.status_code == 200
    hist = history_res.json()
    assert hist["session_id"] == session_id
    messages = hist["messages"]
    assert len(messages) == 4
    assert messages[0]["role"] == "user"
    assert messages[0]["content"] == "My name is Alice"
    assert messages[1]["role"] == "assistant"
    assert "metadata" in messages[1]
    assert messages[2]["role"] == "user"
    assert messages[2]["content"] == "What is my name?"
    assert messages[3]["role"] == "assistant"

def test_unknown_session_returns_404():
    res = client.get("/sessions/nonexistent-session/messages")
    assert res.status_code == 404
    assert res.json()["detail"] == "session not found"

def test_validation_errors_422():
    # Empty message
    r1 = client.post("/chat", json={"session_id": "s-1", "message": "   "})
    assert r1.status_code == 422
    assert "detail" in r1.json()

    # Missing session_id
    r2 = client.post("/chat", json={"message": "hello"})
    assert r2.status_code == 422

    # Message over 4000 characters
    long_msg = "x" * 4001
    r3 = client.post("/chat", json={"session_id": "s-1", "message": long_msg})
    assert r3.status_code == 422

def test_failover_single_key():
    # Simulate key_1 failing with 429
    headers = {"X-Simulate-Failure": "key_1=429"}
    payload = {"session_id": "s-failover-1", "message": "Testing failover to key_2"}
    res = client.post("/chat", json=payload, headers=headers)
    assert res.status_code == 200
    data = res.json()
    assert data["metadata"]["key_id"] == "key_2"
    assert data["metadata"]["fallback_attempts"] == 1
    assert data["metadata"]["resolution_source"] == "LIVE_INFERENCE"

def test_failover_all_keys_unavailable_503():
    # Simulate all keys failing with 429
    headers = {"X-Simulate-Failure": "*=429"}
    session_id = "s-failover-all"
    payload = {"session_id": session_id, "message": "All keys fail"}
    res = client.post("/chat", json=payload, headers=headers)
    assert res.status_code == 503
    assert res.json() == {"detail": "all providers unavailable"}

    # Verify that nothing was written to SQLite for this session
    hist_res = client.get(f"/sessions/{session_id}/messages")
    assert hist_res.status_code == 404
    assert hist_res.json()["detail"] == "session not found"
