#!/bin/bash
# Run 'status' inside the container to see the full manifest wall

BOLD='\033[1m'; CYAN='\033[0;36m'; GREEN='\033[0;32m'; RED='\033[0;31m'
YELLOW='\033[1;33m'; DIM='\033[2m'; RESET='\033[0m'

svc_status() {
    local name=$1
    if systemctl is-active --quiet "$name" 2>/dev/null; then
        echo -e "  ${GREEN}●${RESET} ${BOLD}${name}${RESET}"
    else
        echo -e "  ${RED}○${RESET} ${BOLD}${name}${RESET}  ${RED}(stopped)${RESET}"
    fi
}

port_status() {
    local label=$1 port=$2 path=${3:-/}
    if curl -sf --max-time 2 "http://localhost:${port}${path}" > /dev/null 2>&1; then
        echo -e "  ${GREEN}✔${RESET}  ${label}  ${DIM}→ http://localhost:${port}${RESET}"
    else
        echo -e "  ${RED}✘${RESET}  ${label}  ${DIM}→ http://localhost:${port}${RESET}  ${RED}(not responding)${RESET}"
    fi
}

# ── System info ───────────────────────────────────────────────────────────────
command -v fastfetch &>/dev/null && fastfetch --logo none 2>/dev/null || true

# ── GPU ───────────────────────────────────────────────────────────────────────
echo -e "\n${CYAN}${BOLD}── GPU ─────────────────────────────────────────────${RESET}"
if command -v nvidia-smi &>/dev/null && nvidia-smi &>/dev/null 2>&1; then
    nvidia-smi --query-gpu=name,driver_version,temperature.gpu,utilization.gpu,memory.used,memory.total \
               --format=csv,noheader,nounits \
    | awk -F', ' '{
        printf "  %s  driver %s\n", $1, $2
        printf "  Temp: %s°C   GPU: %s%%   VRAM: %s / %s MiB\n", $3, $4, $5, $6
      }'
else
    echo -e "  ${YELLOW}No GPU / nvidia-smi not available${RESET}"
fi

# ── Services ──────────────────────────────────────────────────────────────────
echo -e "\n${CYAN}${BOLD}── Services ────────────────────────────────────────${RESET}"
svc_status ollama
svc_status n8n
svc_status reports-server

# ── Ports ─────────────────────────────────────────────────────────────────────
echo -e "\n${CYAN}${BOLD}── Endpoints ───────────────────────────────────────${RESET}"
port_status "Ollama   :11434" 11434 "/api/tags"
port_status "n8n      :5678 " 5678  "/"
port_status "Reports  :8080 " 8080  "/"

# ── Disk ──────────────────────────────────────────────────────────────────────
echo -e "\n${CYAN}${BOLD}── Disk ────────────────────────────────────────────${RESET}"
df -h / /eggshell 2>/dev/null | awk 'NR==1{print "  "$0} NR>1{print "  "$0}'

echo -e "\n${DIM}Run 'eggshell' to launch the backtester TUI.${RESET}\n"
