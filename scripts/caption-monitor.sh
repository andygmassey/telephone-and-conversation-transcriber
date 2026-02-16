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
HEARTBEAT_FILE="/tmp/caption_heartbeat"
HA_URL="http://localhost:8123"

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
        "No arecord process found — audio capture may have stopped."
    exit 0
fi

# Check 3: Is the heartbeat file fresh? (written every few seconds by health_check)
if [ -f "$HEARTBEAT_FILE" ]; then
    hb_age=$(( $(date +%s) - $(stat -c %Y "$HEARTBEAT_FILE" 2>/dev/null || stat -f %m "$HEARTBEAT_FILE" 2>/dev/null) ))
    if [ "$hb_age" -gt 300 ]; then
        # No heartbeat for 5 minutes — something is seriously wrong
        send_alert \
            "Gramps Transcriber FROZEN" \
            "No heartbeat for ${hb_age} seconds. The application may be frozen or crashed."
        exit 0
    fi

    # Check heartbeat contents for problems
    hb_content=$(cat "$HEARTBEAT_FILE")

    if echo "$hb_content" | grep -qE 'thread=False|proc=False'; then
        send_alert \
            "Gramps Transcriber UNHEALTHY" \
            "Heartbeat shows a problem: $hb_content"
        exit 0
    fi

    echo "$(date): Caption service healthy (heartbeat ${hb_age}s ago: $hb_content)"
    exit 0
else
    # No heartbeat file at all — service may have just started
    echo "$(date): No heartbeat file yet, waiting..."
    exit 0
fi
