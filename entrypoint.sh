#!/bin/bash
# Container entrypoint — auto-detects available init system.
#
# With --privileged : /sys/fs/cgroup is writable → systemd runs as PID 1
#                     (ollama / reports-server managed by systemd units)
# Without --privileged : services are started directly in the background
#                        and this script stays alive as PID 1

# Vast.ai injects SSH public keys via PUBLIC_KEY env var — set up authorized_keys
if [[ -n "$PUBLIC_KEY" ]]; then
    mkdir -p /root/.ssh
    echo "$PUBLIC_KEY" >> /root/.ssh/authorized_keys
    chmod 700 /root/.ssh
    chmod 600 /root/.ssh/authorized_keys
fi

# Start sshd early so SSH access works regardless of init mode
mkdir -p /run/sshd
/usr/sbin/sshd

_start_direct() {
    echo "[eggshell] --privileged not set — starting services directly"
    mkdir -p /var/log/eggshell /eggshell/reports

    # Ollama: GPU optimization env vars (CUDA_VISIBLE_DEVICES intentionally not
    # set — CUDA_VISIBLE_DEVICES=all is invalid in CUDA 12.x and is removed from
    # the image ENV; leaving it unset lets Ollama find the GPU via numeric index)
    #
    # GPU saturation tuning (v2):
    #   OLLAMA_NUM_PARALLEL=16    — double concurrent KV-decode streams; keeps GPU fed
    #                               between consecutive requests from multiple workers.
    #                               Adaptive: can be overridden by EGGSHELL_OLLAMA_PARALLEL.
    #   OLLAMA_SCHED_SPREAD=1     — distribute requests across all KV slots evenly instead
    #                               of filling the first slot to capacity (reduces head-of-line
    #                               blocking and synchronised idle gaps).
    #   OLLAMA_MAX_LOADED_MODELS=1— keep only one model resident in VRAM; prevents accidental
    #                               context switches that cause VRAM churn and cold KV-cache.
    #   OLLAMA_NUM_BATCH=512      — prompt-eval micro-batch size; 512 is optimal for most
    #                               7B-and-smaller models on consumer GPUs (powers-of-two align
    #                               with CUDA warp size; larger values waste SRAM on small prompts).
    #   OLLAMA_FLASH_ATTENTION=1  — fused flash-attention kernel; mandatory for stable long-context
    #                               throughput without VRAM OOM spikes.
    #   OLLAMA_KV_CACHE_TYPE=q8_0 — quantize KV cache to 8-bit; halves KV VRAM footprint so
    #                               more parallel streams fit before VRAM is exhausted.
    #   OLLAMA_MAX_QUEUE=512      — large request queue; prevents rejection under burst load.
    _OLLAMA_PARALLEL="${EGGSHELL_OLLAMA_PARALLEL:-16}"
    env OLLAMA_NUM_PARALLEL="${_OLLAMA_PARALLEL}" \
        OLLAMA_SCHED_SPREAD=1 \
        OLLAMA_MAX_LOADED_MODELS=1 \
        OLLAMA_NUM_BATCH=512 \
        OLLAMA_FLASH_ATTENTION=1 \
        OLLAMA_KV_CACHE_TYPE=q8_0 \
        OLLAMA_MAX_QUEUE=512 \
        OLLAMA_KEEP_ALIVE=-1 \
        /usr/local/bin/ollama serve \
        >> /var/log/eggshell/ollama.log 2>&1 &

    # Reports server: use the venv python explicitly
    /opt/venv/bin/python3 -m http.server 8080 \
        --directory /eggshell/reports \
        >> /var/log/eggshell/reports.log 2>&1 &

    echo "[eggshell] services started — run 'status' or 'eggshell'"
}

# Use systemd when cgroup is writable (requires --privileged)
if [[ $$ -eq 1 && -x /sbin/init && -w /sys/fs/cgroup ]]; then
    exec /sbin/init
fi

_start_direct

# Stay alive as PID 1 when systemd is not running
if [[ $$ -eq 1 ]]; then
    trap 'kill 0; exit 0' TERM INT
    while :; do wait || true; done
fi
