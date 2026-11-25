const BACKEND_URL = import.meta.env.VITE_BACKEND_URL || "http://localhost:8000";

export async function fetchHealth() {
  try {
    const res = await fetch(`${BACKEND_URL}/health`);
    if (!res.ok) {
      throw new Error(`Health check failed: ${res.status}`);
    }
    return await res.json();
  } catch (err) {
    return { status: "offline", error: err.message };
  }
}

export async function sendChatMessage({
  sessionId,
  message,
  systemPrompt,
  simulateFailureHeader,
}) {
  const headers = {
    "Content-Type": "application/json",
  };

  if (simulateFailureHeader && simulateFailureHeader.trim() !== "") {
    headers["X-Simulate-Failure"] = simulateFailureHeader.trim();
  }

  const payload = {
    session_id: sessionId,
    message: message,
  };

  if (systemPrompt && systemPrompt.trim() !== "") {
    payload.system_prompt = systemPrompt.trim();
  }

  const res = await fetch(`${BACKEND_URL}/chat`, {
    method: "POST",
    headers,
    body: JSON.stringify(payload),
  });

  const data = await res.json().catch(() => null);

  if (!res.ok) {
    let errorDetail = "An unexpected error occurred";
    if (data && data.detail) {
      if (typeof data.detail === "string") {
        errorDetail = data.detail;
      } else if (Array.isArray(data.detail)) {
        errorDetail = data.detail.map((d) => d.msg || JSON.stringify(d)).join(", ");
      } else {
        errorDetail = JSON.stringify(data.detail);
      }
    }
    const err = new Error(errorDetail);
    err.status = res.status;
    err.detail = errorDetail;
    throw err;
  }

  return data;
}

export async function fetchSessionHistory(sessionId) {
  const res = await fetch(`${BACKEND_URL}/sessions/${sessionId}/messages`);
  if (!res.ok) {
    const data = await res.json().catch(() => null);
    throw new Error(data?.detail || "Failed to load session history");
  }
  return await res.json();
}
