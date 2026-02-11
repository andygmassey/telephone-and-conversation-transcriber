#!/bin/bash
# Network watchdog - restarts WiFi if the internet drops

CONFIG_FILE="$HOME/gramps-transcriber/config.json"
DEFAULT_GATEWAY="192.168.1.1"

# Read gateway from config.json if it exists, otherwise use default
if [ -f "$CONFIG_FILE" ] && command -v python3 &> /dev/null; then
    GATEWAY=$(python3 -c "
import json, sys
try:
    cfg = json.load(open('$CONFIG_FILE'))
    gw = cfg.get('gateway_ip', '').strip()
    print(gw if gw else '$DEFAULT_GATEWAY')
except:
    print('$DEFAULT_GATEWAY')
" 2>/dev/null)
else
    GATEWAY="$DEFAULT_GATEWAY"
fi

if ! ping -c 1 -W 5 "$GATEWAY" > /dev/null 2>&1; then
    echo "$(date): Network down (gateway $GATEWAY), restarting wlan0" >> /var/log/network-watchdog.log
    nmcli radio wifi off && sleep 2 && nmcli radio wifi on
fi
