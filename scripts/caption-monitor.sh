#!/bin/bash
# caption-monitor.sh — Monitors caption service health and sends alerts
# Runs via systemd timer every 5 minutes
#
# Philosophy: only alert when the system NEEDS human attention.
# If it hit a problem but recovered on its own, that's success, not failure.
# When a problem is detected, ALWAYS try to fix it before alerting.
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

# Check 1: Is the service running at all?
if ! systemctl --user is-active --quiet caption.service; then
    # Service is completely down — restart it
    systemctl --user restart caption.service
    send_alert \
        "Gramps Transcriber DOWN" \
        "The caption service had stopped. Restarted automatically."
    exit 0
fi

# Check 2: Is there an active arecord process?
# If service is running but no arecord, the app is broken — restart it
if ! pgrep -f "arecord.*hw:" > /dev/null 2>&1; then
    echo "$(date): No arecord process — restarting service"
    systemctl --user restart caption.service
    sleep 5
    # Verify it came back
    if pgrep -f "arecord.*hw:" > /dev/null 2>&1; then
        echo "$(date): Service restarted successfully, arecord running"
        # Don't alert — we fixed it
        exit 0
    else
        send_alert \
            "Gramps Transcriber BROKEN" \
            "No arecord process. Restart attempted but arecord still not running. Manual investigation needed."
        exit 0
    fi
fi

# Check 3: Is the heartbeat file fresh?
if [ -f "$HEARTBEAT_FILE" ]; then
    hb_age=$(( $(date +%s) - $(stat -c %Y "$HEARTBEAT_FILE" 2>/dev/null || stat -f %m "$HEARTBEAT_FILE" 2>/dev/null) ))
    if [ "$hb_age" -gt 300 ]; then
        # No heartbeat for 5 minutes — restart the service
        echo "$(date): Heartbeat stale (${hb_age}s) — restarting service"
        systemctl --user restart caption.service
        sleep 5
        if pgrep -f "arecord.*hw:" > /dev/null 2>&1; then
            echo "$(date): Service restarted successfully after stale heartbeat"
            exit 0
        else
            send_alert \
                "Gramps Transcriber FROZEN" \
                "No heartbeat for ${hb_age}s. Restart attempted but still not healthy."
            exit 0
        fi
    fi

    # Check heartbeat contents for problems
    hb_content=$(cat "$HEARTBEAT_FILE")

    # Check for gave_up state — the app has given up internally
    if echo "$hb_content" | grep -q 'status=gave_up'; then
        echo "$(date): App in gave_up state — restarting service"
        systemctl --user restart caption.service
        sleep 5
        if pgrep -f "arecord.*hw:" > /dev/null 2>&1; then
            echo "$(date): Service restarted from gave_up state"
            exit 0
        else
            send_alert \
                "Gramps Transcriber GAVE UP" \
                "App exhausted restarts and gave up. Restart attempted but still not healthy."
            exit 0
        fi
    fi

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
