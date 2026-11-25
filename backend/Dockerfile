# ==========================================
# Stage 1: Build stage
# ==========================================
FROM python:3.11-slim AS builder

WORKDIR /build

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .

RUN python -m venv /opt/venv && \
    /opt/venv/bin/pip install --upgrade pip && \
    /opt/venv/bin/pip install --no-cache-dir -r requirements.txt

# ==========================================
# Stage 2: Minimal Runtime stage
# ==========================================
FROM python:3.11-slim AS runtime

WORKDIR /app

# Copy virtualenv from builder
COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Prepare SQLite storage directory for volume mount
RUN mkdir -p /data && chmod 777 /data

# Copy application source
COPY . /app

EXPOSE 8000

ENV PYTHONUNBUFFERED=1 \
    DATABASE_URL=sqlite:////data/app.db \
    ALLOWED_ORIGINS=http://localhost:3000,http://127.0.0.1:3000 \
    ENABLE_FAILURE_SIMULATION=true

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
