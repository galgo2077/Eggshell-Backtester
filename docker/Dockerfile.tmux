# ── Layer: tmux ───────────────────────────────────────────────────────────────
# Terminal multiplexer
# Rebuild only when: tmux version changes
FROM eggshell-btop:latest

RUN apt-get update && apt-get install -y --no-install-recommends tmux \
    && rm -rf /var/lib/apt/lists/*

# Bake tmux config: mouse support + sane defaults
RUN cat > /root/.tmux.conf <<'EOF'
# Mouse: click panes, scroll, resize
set -g mouse on

# Start windows and panes at 1 (easier keyboard switching)
set -g base-index 1
setw -g pane-base-index 1

# Renumber windows when one is closed
set -g renumber-windows on

# Bigger scrollback
set -g history-limit 50000

# 256-colour + true colour
set -g default-terminal "tmux-256color"
set -ga terminal-overrides ",xterm-256color:Tc"

# Faster key repeat (no lag after ESC)
set -sg escape-time 10

# Status bar
set -g status-style bg=colour235,fg=colour250
set -g status-left " #[bold]eggshell#[nobold] "
set -g status-right " %H:%M "
EOF

# Auto-start tmux for interactive bash shells (but not nested inside tmux)
RUN echo '' >> /etc/bash.bashrc \
    && echo '# Auto-attach or create tmux session on login' >> /etc/bash.bashrc \
    && echo '[[ -z "$TMUX" && "$-" == *i* ]] && exec tmux new-session -A -s main' >> /etc/bash.bashrc
