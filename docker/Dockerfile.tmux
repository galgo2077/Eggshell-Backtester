# ── Layer: tmux ───────────────────────────────────────────────────────────────
# Terminal multiplexer
# Rebuild only when: tmux version changes
FROM eggshell-btop:latest

RUN apt-get update && apt-get install -y --no-install-recommends tmux \
    && rm -rf /var/lib/apt/lists/*
