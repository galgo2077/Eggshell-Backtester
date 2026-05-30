# ── Layer: app (final) ────────────────────────────────────────────────────────
# Joins all layers. Only changes when health check or entrypoint logic changes.
FROM eggshell-data:latest

# Copy changed files directly into the final stage to avoid busting the data cache!
COPY src/               /eggshell/src/
COPY scripts/           /eggshell/scripts/
COPY config/            /eggshell/config/
COPY entrypoint.sh      /entrypoint.sh
COPY status.sh          /usr/local/bin/status
COPY systemd/ollama.service         /etc/systemd/system/ollama.service
COPY systemd/reports-server.service /etc/systemd/system/reports-server.service
COPY systemd/model-pull.service     /etc/systemd/system/model-pull.service

RUN chmod +x /usr/local/bin/status /entrypoint.sh

HEALTHCHECK --interval=30s --timeout=10s --start-period=90s --retries=3 \
    CMD curl -sf http://localhost:11434/api/tags > /dev/null

ENTRYPOINT ["/entrypoint.sh"]
