# ═══════════════════════════════════════════════════════════════════════════════
# EGGSHELL BACKTESTER — All-in-one image (systemd + ollama + n8n + backtester)
# ═══════════════════════════════════════════════════════════════════════════════

# ── Layer 1: OS + systemd + Ollama + Node.js ─────────────────────────────────
FROM ubuntu:24.04 AS base

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y --no-install-recommends \
        systemd systemd-sysv dbus \
        python3 python3-dev python3-venv \
        build-essential libffi-dev libssl-dev \
        ca-certificates curl git zstd \
    && rm -rf /var/lib/apt/lists/* \
    && ln -sf /usr/bin/python3 /usr/bin/python

# Ollama
RUN curl -fsSL https://ollama.com/install.sh | sh

# Node.js 20 LTS
RUN curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && rm -rf /var/lib/apt/lists/*

# ── Layer 2: n8n ─────────────────────────────────────────────────────────────
FROM base AS node-deps

RUN npm install -g n8n

# ── Layer 3: Python venv + dependencies ──────────────────────────────────────
FROM node-deps AS python-deps

RUN python3 -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

WORKDIR /app
COPY requirements.txt .

RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt && \
    pip install --no-cache-dir --only-binary :all: pyarrow \
    || pip install --no-cache-dir fastparquet \
    || echo "WARNING: no parquet backend — cache disabled"

# ── Layer 4: Bake AI models into image ───────────────────────────────────────
FROM python-deps AS model-pull

RUN ollama serve > /tmp/ollama-build.log 2>&1 & \
    until curl -sf http://localhost:11434/api/tags > /dev/null 2>&1; do sleep 1; done && \
    ollama pull qwen2.5:0.5b && \
    ollama pull 0xroyce/plutus:latest && \
    pkill -f "ollama serve" || true

# ── Layer 5: App source + submodules ─────────────────────────────────────────
FROM model-pull AS app-source

WORKDIR /app
COPY . .

RUN git submodule update --init --recursive 2>/dev/null || true

# ── Layer 6: Runtime — wire up systemd services ───────────────────────────────
FROM app-source AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app/src \
    PATH="/opt/venv/bin:$PATH" \
    MPLBACKEND=Agg \
    OLLAMA_HOST=http://localhost:11434 \
    N8N_WEBHOOK_URL=http://localhost:5678/webhook/b2e814d6-94af-4334-b6b8-5b85f68f19bd

# Install systemd service units
COPY systemd/ollama.service          /etc/systemd/system/ollama.service
COPY systemd/n8n.service             /etc/systemd/system/n8n.service
COPY systemd/reports-server.service  /etc/systemd/system/reports-server.service

# Enable services (creates symlinks so systemd starts them on boot)
RUN systemctl --root=/ enable ollama n8n reports-server

# Convenience command: type 'eggshell' after SSH in
RUN printf '#!/bin/bash\ncd /app/src && exec python main.py "$@"\n' \
    > /usr/local/bin/eggshell && chmod +x /usr/local/bin/eggshell

# systemd is PID 1 — starts ollama + n8n automatically
CMD ["/sbin/init"]
