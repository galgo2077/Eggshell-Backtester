# ── Layer: app ────────────────────────────────────────────────────────────────
# App source + systemd wiring
# Rebuild on every code or config change — fast, no heavy deps here
FROM eggshell-nvidia:latest

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/eggshell/src \
    PATH="/opt/venv/bin:$PATH" \
    MPLBACKEND=Agg \
    OLLAMA_HOST=http://localhost:11434 \
    N8N_WEBHOOK_URL=http://localhost:5678/webhook/b2e814d6-94af-4334-b6b8-5b85f68f19bd

WORKDIR /eggshell
COPY . .

# Wire up systemd services
COPY systemd/ollama.service          /etc/systemd/system/ollama.service
COPY systemd/n8n.service             /etc/systemd/system/n8n.service
COPY systemd/reports-server.service  /etc/systemd/system/reports-server.service
COPY systemd/model-pull.service      /etc/systemd/system/model-pull.service

RUN systemctl --root=/ enable ollama n8n reports-server model-pull

# Convenience alias: type 'eggshell' inside the container
RUN printf '#!/bin/bash\ncd /eggshell/src && exec python main.py "$@"\n' \
    > /usr/local/bin/eggshell && chmod +x /usr/local/bin/eggshell

# Manifest wall: 'status' command + show on SSH login (MOTD)
COPY status.sh /usr/local/bin/status
RUN chmod +x /usr/local/bin/status \
    && echo '[ -x /usr/local/bin/status ] && /usr/local/bin/status' >> /etc/bash.bashrc

# Health: ollama responding = container is healthy
HEALTHCHECK --interval=30s --timeout=10s --start-period=90s --retries=3 \
    CMD curl -sf http://localhost:11434/api/tags > /dev/null

CMD ["/sbin/init"]
