#!/bin/bash
# Caption watchdog - ensures caption service is always running

CAPTION_USER="$(whoami)"

if ! sudo -u "$CAPTION_USER" XDG_RUNTIME_DIR="/run/user/$(id -u "$CAPTION_USER")" systemctl --user is-active --quiet caption; then
    echo "$(date): Caption service not running, restarting..." >> /var/log/caption-watchdog.log
    sudo -u "$CAPTION_USER" XDG_RUNTIME_DIR="/run/user/$(id -u "$CAPTION_USER")" systemctl --user restart caption
fi
