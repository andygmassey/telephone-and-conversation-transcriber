#!/bin/bash
# =============================================================================
# Gramps Transcriber - Easy Installer
# Run with: curl -sSL https://raw.githubusercontent.com/andygmassey/telephone-and-conversation-transcriber/main/install.sh | bash
# =============================================================================

set -e

# Colours for friendly output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BLUE='\033[0;34m'
BOLD='\033[1m'
NC='\033[0m'

INSTALL_DIR="$HOME/gramps-transcriber"
VENV_DIR="$HOME/gramps-env"
VOSK_DIR="$HOME/vosk-uk"
SYSTEMD_DIR="$HOME/.config/systemd/user"
REPO_URL="https://github.com/andygmassey/telephone-and-conversation-transcriber.git"
BRANCH="${GRAMPS_BRANCH:-main}"
VOSK_MODEL_URL="https://alphacephei.com/vosk/models/vosk-model-small-en-gb-0.15.zip"

step() {
    echo ""
    echo -e "${BLUE}${BOLD}[$1/8]${NC} ${BOLD}$2${NC}"
}

ok() {
    echo -e "  ${GREEN}Done!${NC} $1"
}

warn() {
    echo -e "  ${YELLOW}Note:${NC} $1"
}

fail() {
    echo ""
    echo -e "  ${RED}Something went wrong:${NC} $1"
    echo -e "  ${YELLOW}Need help? Open an issue at:${NC}"
    echo -e "  https://github.com/andygmassey/telephone-and-conversation-transcriber/issues"
    exit 1
}

echo ""
echo -e "${BOLD}================================================${NC}"
echo -e "${BOLD}   Gramps Transcriber — Easy Installer${NC}"
echo -e "${BOLD}================================================${NC}"
echo ""
echo "This will set up everything you need."
echo "It usually takes about 5-10 minutes."
echo ""

# ─── Step 1: Check we're on a Raspberry Pi ───────────────────────────────────

step 1 "Checking your Raspberry Pi..."

if [ ! -f /etc/os-release ]; then
    fail "Can't detect your operating system. This installer is for Raspberry Pi OS."
fi

. /etc/os-release

if [[ "$ID" != "debian" && "$ID" != "raspbian" ]]; then
    fail "This installer is designed for Raspberry Pi OS (Bookworm). You seem to be running $PRETTY_NAME."
fi

# Check for 64-bit
if [[ "$(uname -m)" != "aarch64" ]]; then
    fail "You need the 64-bit version of Raspberry Pi OS. You're running 32-bit ($(uname -m))."
fi

# Check Python version
PYTHON_VERSION=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
PYTHON_MAJOR=$(echo "$PYTHON_VERSION" | cut -d. -f1)
PYTHON_MINOR=$(echo "$PYTHON_VERSION" | cut -d. -f2)

if [ "$PYTHON_MAJOR" -lt 3 ] || [ "$PYTHON_MINOR" -lt 11 ]; then
    fail "Python 3.11 or newer is required. You have Python $PYTHON_VERSION."
fi

ok "Raspberry Pi OS (64-bit), Python $PYTHON_VERSION"

# ─── Step 2: Install system packages ─────────────────────────────────────────

step 2 "Installing system packages (this may take a couple of minutes)..."

sudo apt-get update -qq || fail "Couldn't update package list. Are you connected to the internet?"

sudo apt-get install -y -qq \
    python3-pyqt6 \
    python3-venv \
    python3-dev \
    libasound2-dev \
    portaudio19-dev \
    git \
    curl \
    unzip \
    avahi-daemon \
    2>/dev/null || fail "Couldn't install required packages."

ok "All system packages installed"

# ─── Step 3: Download the transcriber ─────────────────────────────────────────

step 3 "Downloading the transcriber..."

if [ -d "$INSTALL_DIR" ]; then
    warn "Already downloaded — updating to latest version"
    cd "$INSTALL_DIR"
    git pull --quiet || warn "Couldn't update. Using existing version."
    cd - > /dev/null
else
    git clone --quiet --branch "$BRANCH" "$REPO_URL" "$INSTALL_DIR" || fail "Couldn't download the transcriber. Check your internet connection."
fi

ok "Transcriber downloaded to $INSTALL_DIR"

# ─── Step 4: Set up Python environment ────────────────────────────────────────

step 4 "Setting up Python environment..."

if [ -d "$VENV_DIR" ]; then
    warn "Python environment already exists — reusing it"
else
    python3 -m venv "$VENV_DIR" --system-site-packages || fail "Couldn't create Python environment."
fi

ok "Python environment ready"

# ─── Step 5: Install Python packages ─────────────────────────────────────────

step 5 "Installing Python packages..."

"$VENV_DIR/bin/pip" install --quiet --upgrade pip 2>/dev/null
"$VENV_DIR/bin/pip" install --quiet \
    vosk \
    sounddevice \
    numpy \
    websocket-client \
    flask \
    requests \
    || fail "Couldn't install Python packages."

ok "All Python packages installed"

# ─── Step 6: Download offline speech model ────────────────────────────────────

step 6 "Downloading offline speech model (~40 MB)..."

if [ -d "$VOSK_DIR" ]; then
    warn "Speech model already downloaded — skipping"
else
    VOSK_ZIP="/tmp/vosk-model.zip"
    curl -sSL "$VOSK_MODEL_URL" -o "$VOSK_ZIP" || fail "Couldn't download the speech model."
    unzip -q "$VOSK_ZIP" -d /tmp || fail "Couldn't unpack the speech model."
    mv /tmp/vosk-model-small-en-gb-0.15 "$VOSK_DIR" || fail "Couldn't move the speech model into place."
    rm -f "$VOSK_ZIP"
fi

ok "Offline speech model ready"

# ─── Step 7: Install services ─────────────────────────────────────────────────

step 7 "Setting up auto-start services..."

mkdir -p "$SYSTEMD_DIR"

# Copy all user services
for service_file in "$INSTALL_DIR"/systemd/caption.service \
                    "$INSTALL_DIR"/systemd/gramps-mute.service; do
    if [ -f "$service_file" ]; then
        cp "$service_file" "$SYSTEMD_DIR/"
    fi
done

# Install the setup wizard service
cp "$INSTALL_DIR/setup/gramps-setup.service" "$SYSTEMD_DIR/"

systemctl --user daemon-reload

ok "Services installed"

# ─── Step 8: Start the setup wizard ──────────────────────────────────────────

step 8 "Starting the setup wizard..."

systemctl --user enable --now gramps-setup 2>/dev/null || warn "Couldn't auto-start the wizard (you can start it manually)"

# Give it a moment to start
sleep 2

# Get the Pi's hostname
HOSTNAME=$(hostname).local

ok "Setup wizard is running!"

# ─── Done! ────────────────────────────────────────────────────────────────────

echo ""
echo -e "${GREEN}${BOLD}================================================${NC}"
echo -e "${GREEN}${BOLD}   All done! Just one more step...${NC}"
echo -e "${GREEN}${BOLD}================================================${NC}"
echo ""
echo -e "Open this address on your phone or computer:"
echo ""
echo -e "  ${BOLD}${BLUE}http://${HOSTNAME}:8080${NC}"
echo ""
echo -e "The setup page will walk you through the rest."
echo ""
echo -e "If that address doesn't work, try:"
echo ""
IP_ADDR=$(hostname -I 2>/dev/null | awk '{print $1}')
if [ -n "$IP_ADDR" ]; then
    echo -e "  ${BOLD}http://${IP_ADDR}:8080${NC}"
    echo ""
fi
echo -e "${YELLOW}Tip:${NC} You can come back to this setup page any time"
echo -e "     to change settings or check on things."
echo ""
