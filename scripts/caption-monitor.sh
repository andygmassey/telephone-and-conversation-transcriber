#!/bin/bash
# caption-monitor.sh — Monitors caption service health and sends alerts
# Runs via systemd timer every 5 minutes
#
# Philosophy: only alert when the system NEEDS human attention.
# If it hit a problem but recovered on its own, that's success, not failure.
#
# Alert method: Uses Home Assistant notify service if HA_TOKEN is available
# in credentials.py. Customize the send_alert function for other methods
# (email, Pushover, ntfy.sh, etc.)

ALERT_COOLDOWN_FILE="/tmp/caption_alert_cooldown"
COOLDOWN_SECONDS=3600  # Don't send more than one alert per hour
LOG_FILE="$HOME/caption.log"
HA_URL="http://localhost:8123"
MAX_LOG_LINES=2000  # Rotate log when it exceeds this

# Try to read HA token from credentials.py
HA_TOKEN=$(python3 -c "exec(open('$HOME/gramps-transcriber/credentials.py').read()); print(HA_TOKEN)" 2>/dev/null)

send_alert() {
    local title="$1"
    local message="$2"

    # Check cooldown
    if [ -f "$ALERT_COOLDOWN_FILE" ]; then
        last_alert=$(cat "$ALERT_COOLDOWN_FILE")
        now=$(date +%s)
        elapsed=$((now - last_alert))
        if [ "$elapsed" -lt "$COOLDOWN_SECONDS" ]; then
            echo "$(date): Alert suppressed (cooldown: ${elapsed}s/${COOLDOWN_SECONDS}s)"
            return 0
        fi
    fi

    echo "$(date): SENDING ALERT - $title"

    # Send via Home Assistant (if configured)
    if [ -n "$HA_TOKEN" ]; then
        # Change notify/persistent_notification to your HA notify service name
        # e.g. notify/email_family, notify/mobile_app_phone, etc.
        curl -s -X POST \
            -H "Authorization: Bearer $HA_TOKEN" \
            -H "Content-Type: application/json" \
            -d "{\"message\": \"$message\", \"title\": \"$title\"}" \
            "$HA_URL/api/services/notify/persistent_notification" > /dev/null 2>&1
    fi

    # Update cooldown
    date +%s > "$ALERT_COOLDOWN_FILE"
}

# Rotate log if too large (keep last 500 lines)
if [ -f "$LOG_FILE" ]; then
    line_count=$(wc -l < "$LOG_FILE")
    if [ "$line_count" -gt "$MAX_LOG_LINES" ]; then
        tail -500 "$LOG_FILE" > "${LOG_FILE}.tmp" && mv "${LOG_FILE}.tmp" "$LOG_FILE"
        echo "$(date): Log rotated ($line_count -> 500 lines)"
    fi
fi

# Check 1: Is the service running?
if ! systemctl --user is-active --quiet caption.service; then
    send_alert \
        "Gramps Transcriber DOWN" \
        "The caption service has stopped. Attempting restart..."
    systemctl --user restart caption.service
    exit 0
fi

# Check 2: Is there an active arecord process?
if ! pgrep -f "arecord.*hw:" > /dev/null 2>&1; then
    send_alert \
        "Gramps Transcriber NO AUDIO" \
        "No arecord process found - audio capture may have stopped."
    exit 0
fi

# Check 3: Has the log file been updated in the last 10 minutes?
if [ -f "$LOG_FILE" ]; then
    log_age=$(( $(date +%s) - $(stat -c %Y "$LOG_FILE" 2>/dev/null || stat -f %m "$LOG_FILE" 2>/dev/null) ))
    if [ "$log_age" -gt 600 ]; then
        send_alert \
            "Gramps Transcriber STALE" \
            "The log file has not been updated in ${log_age} seconds. The transcriber may be frozen."
        exit 0
    fi
fi

# Check 4: Is the system currently healthy?
# We look at the LAST heartbeat. If it shows thread=True and proc=True, the system
# has recovered from any past restarts and is working fine — no alert needed.
if [ -f "$LOG_FILE" ]; then
    last_heartbeat=$(grep 'heartbeat:' "$LOG_FILE" | tail -1)

    if [ -n "$last_heartbeat" ]; then
        # If last heartbeat shows thread=False or proc=False, system is sick
        if echo "$last_heartbeat" | grep -qE 'thread=False|proc=False'; then
            send_alert \
                "Gramps Transcriber UNHEALTHY" \
                "Latest heartbeat shows a problem: $last_heartbeat"
            exit 0
        fi
        # Last heartbeat is healthy — system is fine, even if there were past restarts
        echo "$(date): Caption service healthy (last heartbeat OK)"
        exit 0
    fi

    # No heartbeats at all — check if there are restart messages (old-style detection)
    recent_restarts=$(tail -50 "$LOG_FILE" | grep -c "Health check.*restarting\|scheduling restart")
    if [ "$recent_restarts" -ge 5 ]; then
        send_alert \
            "Gramps Transcriber RESTART LOOP" \
            "The transcriber is stuck in a restart loop ($recent_restarts restarts in recent logs) with no recovery heartbeat."
        exit 0
    fi
fi

echo "$(date): Caption service healthy"
