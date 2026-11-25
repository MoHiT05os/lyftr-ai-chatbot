# ⚡ Lyftr AI — Resilient LLM Chatbot with Key Failover & Response Caching

A production-grade, fault-tolerant Full-Stack LLM chatbot engineered with **FastAPI**, **LiteLLM Gateway**, **SQLite** volume persistence, and a modern **React** frontend. Built to guarantee zero downtime through automated key pool failover, deterministic response caching, and granular per-request token analytics.

---

## 1. Live URLs

| Service | Deployment Platform | URL / Endpoint |
| :--- | :--- | :--- |
| **Frontend Application** | Vercel / Cloudflare Pages | `https://lyftr-ai-chat.vercel.app` *(Placeholder / configurable via repository)* |
| **Backend API** | Render / Railway / Fly.io | `https://lyftr-ai-backend.onrender.com` |
| **API Health Status** | Public Status Check | `https://lyftr-ai-backend.onrender.com/health` |
| **API Documentation** | Swagger / OpenAPI | `https://lyftr-ai-backend.onrender.com/docs` |

---

## 2. Run Locally: With Docker and Without

### Option A: With Docker (Recommended)

Ensure you have Docker and Docker Compose installed.

1. **Clone the repository and copy the environment file:**
   ```bash
   git clone <repo-url>
   cd Lyftr
   cp .env.example .env
   ```
2. **Start the complete stack:**
   ```bash
   make up
   ```
   * Or directly using Docker Compose:
     ```bash
     docker compose up --build -d
     ```
3. **Access the applications:**
   * **Frontend UI:** [http://localhost:3000](http://localhost:3000)
   * **Backend API & Swagger Docs:** [http://localhost:8000/docs](http://localhost:8000/docs)
   * **Health Check:** [http://localhost:8000/health](http://localhost:8000/health)

4. **Stop the stack:**
   ```bash
   make down
   ```

---

### Option B: Without Docker (Local Development)

#### 1. Backend (FastAPI + LiteLLM)
* Requires Python 3.10+
```bash
# Navigate to backend directory
cd backend

# Create and activate virtual environment
python -m venv venv
# On Windows:
.\venv\Scripts\activate
# On Linux/macOS:
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Start backend server
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

#### 2. Frontend (React + Vite)
* Requires Node.js 18+
```bash
# Navigate to frontend directory in another terminal
cd frontend

# Install dependencies
npm install

# Start Vite dev server on port 3000
npm run dev
```

The frontend will run at [http://localhost:3000](http://localhost:3000) and communicate directly with `http://localhost:8000`.

#### 3. Run Backend Test Suite
```bash
python -m pytest backend/tests -v
```

---

## 3. Design Decisions

### Key Fallback Architecture
* **Sequential Failover Pool:** `LLM_API_KEYS` accepts a comma-delimited sequence of API keys, mapped predictably to `key_1`, `key_2`, etc.
* **Proactive Fault Interception:** When an upstream provider responds with HTTP `429` (Rate Limited/Quota Exhausted) or `5xx` (Internal Server / Bad Gateway / Unavailable), the gateway catches the exception, logs the event, increments `fallback_attempts`, and transparently routes the request to the subsequent key in the pool.
* **Zero-Leakage & Safety:** Raw API keys are never exposed in logs, responses, or UI. Only the identifier (e.g., `key_1`, `key_2`) or `null` (on cache hit) is returned.
* **Clean 503 Outage Handling:** If every configured key fails, the gateway immediately returns HTTP `503` with `{ "detail": "all providers unavailable" }` and ensures that failed attempts are **never written** to the SQLite session history.

### Response Caching Strategy
* **Exact Composite Cache Key:** Cache keys are calculated using SHA-256 over a canonical JSON serialization of:
  $$\text{Cache Key} = \text{SHA-256}\Big(\text{Model} + [(\text{role}, \text{content})_{1..N}]\Big)$$
  where the sequence contains the effective system prompt, prior conversation turns, and the current user message.
* **Deterministic Behavior:** 
  * The exact same initial message sent across different sessions shares identical context `[system_prompt, message]` and immediately hits the cache (`LLM_CACHE`), returning in `< 2 ms`.
  * If a user continues the conversation with subsequent turns, the expanded context sequence prevents invalid cache collisions.
* **Cache Hit Semantics:** On cache hit, `key_id` is returned as `null`, `fallback_attempts` is `0`, and latency is strictly measured at sub-millisecond execution times.

### SQLite Session Storage
* **Container Survival via Named Volumes:** In Docker, the database resides at `/data/app.db` mapped to the named volume `sqlite_data`. Restarts and redeployments preserve all chat conversations.
* **Automated Schema Initialization:** On startup, the `lifespan` handler automatically creates the `messages` table and an index on `session_id`:
  ```sql
  CREATE TABLE IF NOT EXISTS messages (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      session_id TEXT NOT NULL,
      role TEXT NOT NULL,
      content TEXT NOT NULL,
      metadata TEXT,
      created_at TEXT NOT NULL
  );
  CREATE INDEX IF NOT EXISTS idx_messages_session_id ON messages (session_id);
  ```
* **Stateless Multi-Turn Queries:** The client only sends the newest message. The backend fetches prior turns ordered by `id ASC`, constructs the full conversation context, executes the turn, and atomic writes both user and assistant records.

---

## 4. Verification: How to See Failover, Cache Hits & Token Usage

### A. Verifying Response Caching
1. **Send First Message:**
   ```bash
   curl -X POST http://localhost:8000/chat \
     -H "Content-Type: application/json" \
     -d '{"session_id": "session-cache-test-1", "message": "What is quantum computing?"}'
   ```
   * **Result:** `"resolution_source": "LIVE_INFERENCE"`, `"key_id": "key_1"`, latency ~800ms.
2. **Send Identical Message in New Session:**
   ```bash
   curl -X POST http://localhost:8000/chat \
     -H "Content-Type: application/json" \
     -d '{"session_id": "session-cache-test-2", "message": "What is quantum computing?"}'
   ```
   * **Result:** `"resolution_source": "LLM_CACHE"`, `"key_id": null`, `"fallback_attempts": 0`, latency ~1ms.

---

### B. Verifying Key Failover (via `X-Simulate-Failure`)
When `ENABLE_FAILURE_SIMULATION=true`, the backend accepts the `X-Simulate-Failure` header:

1. **Simulate Key 1 Rate Limit (429):**
   ```bash
   curl -X POST http://localhost:8000/chat \
     -H "Content-Type: application/json" \
     -H "X-Simulate-Failure: key_1=429" \
     -d '{"session_id": "test-failover", "message": "Hello from failover test"}'
   ```
   * **Result:** Returns HTTP 200, `"key_id": "key_2"`, `"fallback_attempts": 1`.

2. **Simulate Key 1 Server Error (500):**
   ```bash
   curl -X POST http://localhost:8000/chat \
     -H "Content-Type: application/json" \
     -H "X-Simulate-Failure: key_1=500" \
     -d '{"session_id": "test-failover-500", "message": "Testing 500 error"}'
   ```
   * **Result:** Transparently falls over to `key_2`.

3. **Simulate Total Outage (`*=429`):**
   ```bash
   curl -X POST http://localhost:8000/chat \
     -H "Content-Type: application/json" \
     -H "X-Simulate-Failure: *=429" \
     -d '{"session_id": "test-all-down", "message": "Will fail"}'
   ```
   * **Result:** Returns HTTP 503 `{"detail": "all providers unavailable"}`.
   * Verify nothing was saved:
     ```bash
     curl http://localhost:8000/sessions/test-all-down/messages
     # Returns 404 {"detail": "session not found"}
     ```

---

### C. Verifying Per-Message Token Usage
* Next to every assistant response in the UI:
  * `meta-input-tokens`: Count of input tokens for that specific request (system prompt + history + current message).
  * `meta-output-tokens`: Count of completion tokens generated for that answer.
* Compare two different initial requests of similar length; both will report consistent per-request input tokens rather than an unmanageable running total.

---

## 5. Setup Used: Editor and AI Tools

* **IDE / Environment:** Visual Studio Code & Antigravity AI Orchestrator.
* **Backend Runtime:** Python 3.11 / FastAPI / LiteLLM / SQLite / Pytest.
* **Frontend Runtime:** React 18 / Vite 5 / Vanilla Modern CSS / Glassmorphism Design System.
* **Containerization:** Docker Engine & Multi-stage Alpine/Slim images.
* **AI Tools:** Antigravity Agent for architecture scaffolding, automated test generation, and contract validation.

---

## 6. Bonus Features Added

1. **Interactive Failover Simulation Bar in UI:**
   * Instead of requiring reviewers to manually send curl headers, the UI includes one-click simulation buttons (`Normal`, `key_1=429`, `key_1=500`, `*=429`) directly in the header toolbar! Reviewers can test key failover and error recovery in real time.
2. **Visual Cache & Failover Status Pills:**
   * Glowing emerald badge for `LLM_CACHE` with sub-millisecond response badges.
   * Cyan badge for `LIVE_INFERENCE` with active key indicator.
   * Amber warning badge highlighting fallback attempts when secondary keys are activated.
3. **Session Switcher & Auto-Generation:**
   * Generates a new unique `session_id` on page load, with a prominent "+ New Session" button to facilitate testing fresh sessions and cache isolation.
4. **Collapsible Custom System Prompt:**
   * Includes the optional system prompt input (`data-testid="system-prompt-input"`) in a collapsible drawer.
5. **Resilient Docker Healthchecks:**
   * The `docker-compose.yml` includes automated healthcheck probes on `/health` ensuring the frontend waits until the backend and database volume are fully operational.
