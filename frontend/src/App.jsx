import React, { useState, useEffect, useRef } from 'react';
import { fetchHealth, sendChatMessage } from './api';

function generateSessionId() {
  const rand = Math.random().toString(36).substring(2, 8);
  return `s-${rand}`;
}

export default function App() {
  // A new session starts on each page load
  const [sessionId, setSessionId] = useState(() => generateSessionId());
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState('');
  const [systemPrompt, setSystemPrompt] = useState('');
  const [showSystemPrompt, setShowSystemPrompt] = useState(false);
  const [simulateFailureHeader, setSimulateFailureHeader] = useState('');
  const [isSending, setIsSending] = useState(false);
  const [health, setHealth] = useState({ status: 'checking', keys_configured: 0, cache_enabled: false });

  const messagesEndRef = useRef(null);
  const textareaRef = useRef(null);

  useEffect(() => {
    // Check backend health on mount and poll every 4 seconds
    const check = () => {
      fetchHealth().then((res) => {
        setHealth(res);
      });
    };
    check();
    const interval = setInterval(check, 4000);
    return () => clearInterval(interval);
  }, []);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, isSending]);

  const handleStartNewSession = () => {
    const newId = generateSessionId();
    setSessionId(newId);
    setMessages([]);
    setInput('');
  };

  const handleSend = async (e) => {
    if (e) e.preventDefault();
    const trimmed = input.trim();
    if (!trimmed || isSending) return;

    // Reset input immediately so chat-input is empty after sending
    setInput('');

    // Append user message to UI
    const userMsg = {
      role: 'user',
      content: trimmed,
      timestamp: new Date().toLocaleTimeString(),
    };
    setMessages((prev) => [...prev, userMsg]);
    setIsSending(true);

    try {
      const data = await sendChatMessage({
        sessionId,
        message: trimmed,
        systemPrompt: systemPrompt || undefined,
        simulateFailureHeader: simulateFailureHeader || undefined,
      });

      const assistantMsg = {
        role: 'assistant',
        content: data.reply,
        metadata: data.metadata,
        timestamp: new Date().toLocaleTimeString(),
      };
      setMessages((prev) => [...prev, assistantMsg]);
    } catch (err) {
      // Errors (422, 503) show as a readable message in the chat, never a blank screen
      const errorMsg = {
        role: 'error',
        status: err.status || 500,
        content: err.detail || err.message || 'An error occurred while connecting to the LLM Gateway.',
        timestamp: new Date().toLocaleTimeString(),
      };
      setMessages((prev) => [...prev, errorMsg]);
    } finally {
      setIsSending(false);
    }
  };

  const handleKeyDown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  return (
    <div className="app-container">
      {/* Top Header */}
      <header className="app-header">
        <div className="brand-section">
          <div className="logo-badge">L</div>
          <div>
            <h1 className="brand-title">Lyftr AI Gateway</h1>
            <div className="brand-subtitle">
              <span>Fault-Tolerant LLM with Multi-Key Failover & Deterministic Caching</span>
            </div>
          </div>
        </div>

        <div className="header-actions">
          <div className={`status-pill ${health.status === 'ok' ? '' : 'offline'}`}>
            <span className="pulse-dot"></span>
            <span>{health.status === 'ok' ? `Gateway Ready (${health.keys_configured} Keys)` : 'Connecting...'}</span>
          </div>

          <div className="session-badge">
            <span>Session:</span>
            <strong>{sessionId}</strong>
          </div>

          <button className="new-session-btn" onClick={handleStartNewSession} title="Start fresh session">
            + New Session
          </button>
        </div>
      </header>

      {/* Control & Failover Simulation Toolbar */}
      <section className="control-toolbar">
        <div className="toolbar-row">
          <div className="sim-group">
            <span className="sim-label">Failover Hook:</span>
            <button
              type="button"
              className={`sim-btn ${simulateFailureHeader === '' ? 'active' : ''}`}
              onClick={() => setSimulateFailureHeader('')}
            >
              Normal (No Failure)
            </button>
            <button
              type="button"
              className={`sim-btn ${simulateFailureHeader === 'key_1=429' ? 'active' : ''}`}
              onClick={() => setSimulateFailureHeader('key_1=429')}
              title="Simulates 429 RateLimit on key_1, auto-fails over to key_2"
            >
              key_1=429 (Failover)
            </button>
            <button
              type="button"
              className={`sim-btn ${simulateFailureHeader === 'key_1=500' ? 'active' : ''}`}
              onClick={() => setSimulateFailureHeader('key_1=500')}
              title="Simulates 500 Server Error on key_1, auto-fails over to key_2"
            >
              key_1=500
            </button>
            <button
              type="button"
              className={`sim-btn ${simulateFailureHeader === '*=429' ? 'active danger' : ''}`}
              onClick={() => setSimulateFailureHeader('*=429')}
              title="Simulates 429 on all keys, returns HTTP 503 cleanly"
            >
              *=429 (All Keys Down)
            </button>
          </div>

          <button
            type="button"
            className="sys-prompt-toggle"
            onClick={() => setShowSystemPrompt(!showSystemPrompt)}
          >
            {showSystemPrompt ? '▲ Hide System Prompt' : '▼ Custom System Prompt'}
          </button>
        </div>

        {showSystemPrompt && (
          <div className="sys-prompt-container">
            <textarea
              data-testid="system-prompt-input"
              className="sys-prompt-input"
              rows={2}
              placeholder="Set custom system prompt for this session (e.g. 'You are an expert full-stack engineer...')"
              value={systemPrompt}
              onChange={(e) => setSystemPrompt(e.target.value)}
            />
          </div>
        )}
      </section>

      {/* Chat Messages Display */}
      <main className="chat-window">
        {messages.length === 0 && (
          <div className="empty-state">
            <div className="empty-icon">⚡</div>
            <h2 className="empty-title">Ready for Conversation</h2>
            <p className="empty-subtitle">
              Send a prompt to test multi-turn SQLite memory, response caching, and resilient key failover.
            </p>
            <div className="features-pills">
              <span className="feature-pill">✦ Auto-Failover (429/5xx)</span>
              <span className="feature-pill">✦ Exact Response Caching</span>
              <span className="feature-pill">✦ Per-Request Token Usage</span>
              <span className="feature-pill">✦ SQLite History</span>
            </div>
          </div>
        )}

        {messages.map((msg, index) => {
          if (msg.role === 'user') {
            return (
              <div key={index} className="message-row user">
                <div className="user-bubble">{msg.content}</div>
              </div>
            );
          }

          if (msg.role === 'error') {
            return (
              <div key={index} className="message-row assistant">
                <div className="error-card">
                  <span className="error-badge">HTTP {msg.status}</span>
                  <div>
                    <strong>Request Error: </strong>
                    <span>{msg.content}</span>
                  </div>
                </div>
              </div>
            );
          }

          // Assistant message (strictly conforms to contract in section 5)
          const meta = msg.metadata || {};
          const isCache = meta.resolution_source === 'LLM_CACHE';

          return (
            <div key={index} className="message-row assistant">
              <div className="assistant-card" data-testid="assistant-message">
                <div className="assistant-text">{msg.content}</div>

                <div className="metadata-grid">
                  {/* data-testid="meta-source" */}
                  <span
                    className={`meta-chip ${isCache ? 'source-cache' : 'source-live'}`}
                    data-testid="meta-source"
                  >
                    {meta.resolution_source}
                  </span>

                  {/* data-testid="meta-model" */}
                  <span className="meta-chip" data-testid="meta-model">
                    {meta.model}
                  </span>

                  {/* data-testid="meta-latency" */}
                  <span className="meta-chip" data-testid="meta-latency">
                    {meta.latency_ms} ms
                  </span>

                  {/* data-testid="meta-input-tokens" */}
                  <span className="meta-chip">
                    in: <strong data-testid="meta-input-tokens">{meta.input_tokens}</strong>
                  </span>

                  {/* data-testid="meta-output-tokens" */}
                  <span className="meta-chip">
                    out: <strong data-testid="meta-output-tokens">{meta.output_tokens}</strong>
                  </span>

                  {/* Key used & fallback info */}
                  {meta.key_id ? (
                    <span className="meta-chip key-chip">
                      key: {meta.key_id}
                    </span>
                  ) : (
                    <span className="meta-chip key-chip">cache-hit</span>
                  )}

                  {meta.fallback_attempts > 0 && (
                    <span className="meta-chip fallback-warning">
                      ⚠️ {meta.fallback_attempts} fallback(s)
                    </span>
                  )}
                </div>
              </div>
            </div>
          );
        })}

        {isSending && (
          <div className="message-row assistant">
            <div className="assistant-card" style={{ opacity: 0.8 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 10, fontSize: 13, color: '#94a3b8' }}>
                <span className="spinner"></span>
                <span>Generating response through LiteLLM Gateway...</span>
              </div>
            </div>
          </div>
        )}

        <div ref={messagesEndRef} />
      </main>

      {/* Input Dock */}
      <footer className="input-dock">
        <form onSubmit={handleSend} className="input-row">
          <textarea
            ref={textareaRef}
            data-testid="chat-input"
            className="chat-textarea"
            rows={1}
            placeholder="Type your message... (Enter to send, Shift+Enter for new line)"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
          />
          <button
            type="submit"
            data-testid="send-button"
            className="send-action-btn"
            disabled={!input.trim() || isSending}
          >
            {isSending ? <span className="spinner"></span> : <span>Send ↵</span>}
          </button>
        </form>

        <div className="input-footer">
          <span>Session persistent in SQLite volume</span>
          <span>Failover Simulation Header: {simulateFailureHeader || 'None (Normal Execution)'}</span>
        </div>
      </footer>
    </div>
  );
}
