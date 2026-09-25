#!/bin/bash
# shellcheck source-path=SCRIPTDIR
# Installs Searchables as a macOS background service (a launchd LaunchAgent): it starts when you log
# in, restarts if it crashes, and writes logs. Safe to re-run: it replaces the existing service.
#
#   deploy/macos/install-service.sh
#   deploy/macos/install-service.sh --port 8600 --data-dir ~/SearchablesLibrary
#
# Options:
#   --port N          Port to listen on (default 8501)
#   --address ADDR    127.0.0.1 = this Mac only (default); 0.0.0.0 = other machines too (no login!)
#   --data-dir DIR    Library location (default: the project's data folder, as when run by hand)
#   --label NAME      launchd label (default com.searchables.app); use another to run a second copy
#   --python PATH     Python 3.10+ used to create .venv
set -euo pipefail
# shellcheck source=common.sh
source "$(dirname "${BASH_SOURCE[0]}")/common.sh"

PORT=8501
ADDRESS=127.0.0.1
DATA_DIR="$APP_DIR/data"
LABEL=com.searchables.app
while [ $# -gt 0 ]; do
    case "$1" in
        --port) PORT="$2"; shift 2 ;;
        --address) ADDRESS="$2"; shift 2 ;;
        --data-dir) DATA_DIR="$2"; shift 2 ;;
        --label) LABEL="$2"; shift 2 ;;
        --python) PYTHON="$2"; shift 2 ;;
        -h|--help) awk 'NR > 2 && /^#/ { sub(/^# ?/, ""); print; next } NR > 2 { exit }' "$0"; exit 0 ;;
        *) die "Unknown option: $1 (see --help)" ;;
    esac
done

[ "$(uname -s)" = "Darwin" ] || die "This script is for macOS. On Windows use deploy/windows/install-service.ps1."
[ "$(id -u)" -ne 0 ] || die "Run this as your normal user, not with sudo: the service runs in your login session."
case "$PORT" in ''|*[!0-9]*) die "--port must be a number." ;; esac
case "$LABEL" in *[!A-Za-z0-9._-]*|'') die "--label may only contain letters, digits, dots, hyphens and underscores." ;; esac
case "$APP_DIR" in
    "$HOME/Documents"*|"$HOME/Desktop"*|"$HOME/Downloads"*|"$HOME/Library/Mobile Documents"*)
        warn "The project is in a folder macOS privacy controls protect ($APP_DIR). Background services can \
be blocked from reading it. If the service fails to start, move the project (e.g. to ~/Apps/Searchables)." ;;
esac

step "Project: $APP_DIR"
ensure_environment

DATA_DIR="$(mkdir -p "$DATA_DIR" && cd "$DATA_DIR" && pwd)"
LOG_DIR="$DATA_DIR/logs"
mkdir -p "$LOG_DIR"
step "Library: $DATA_DIR"

TESSDATA="$(find_tessdata)"
if [ -n "$TESSDATA" ]; then
    step "Tesseract language data: $TESSDATA"
else
    warn "Tesseract not found: scanned pages won't be searchable. Install it with 'brew install tesseract' and re-run this script."
fi

# ---- launchd configuration ------------------------------------------------------------------------
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
DOMAIN="gui/$(id -u)"
mkdir -p "$HOME/Library/LaunchAgents"

xml_escape() { printf '%s' "$1" | sed -e 's/&/\&amp;/g' -e 's/</\&lt;/g' -e 's/>/\&gt;/g' -e 's/"/\&quot;/g'; }
TESS_ENV=""
[ -n "$TESSDATA" ] && TESS_ENV="        <key>TESSDATA_PREFIX</key><string>$(xml_escape "$TESSDATA")</string>"

cat > "$PLIST" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key><string>$LABEL</string>
    <key>ProgramArguments</key>
    <array>
        <string>$(xml_escape "$VENV_PYTHON")</string>
        <string>-m</string><string>streamlit</string><string>run</string>
        <string>$(xml_escape "$APP_DIR/app.py")</string>
        <string>--server.port</string><string>$PORT</string>
        <string>--server.address</string><string>$(xml_escape "$ADDRESS")</string>
        <string>--server.headless</string><string>true</string>
        <string>--server.fileWatcherType</string><string>none</string>
        <string>--browser.gatherUsageStats</string><string>false</string>
    </array>
    <key>WorkingDirectory</key><string>$(xml_escape "$APP_DIR")</string>
    <key>EnvironmentVariables</key>
    <dict>
        <key>SEARCHABLES_DATA_DIR</key><string>$(xml_escape "$DATA_DIR")</string>
        <key>PYTHONUNBUFFERED</key><string>1</string>
$TESS_ENV
    </dict>
    <key>RunAtLoad</key><true/>
    <!-- Always restart; uninstall-service.sh unloads the service to stop it for good -->
    <key>KeepAlive</key><true/>
    <key>ThrottleInterval</key><integer>10</integer>
    <key>StandardOutPath</key><string>$(xml_escape "$LOG_DIR/searchables.out.log")</string>
    <key>StandardErrorPath</key><string>$(xml_escape "$LOG_DIR/searchables.err.log")</string>
</dict>
</plist>
PLIST
plutil -lint "$PLIST" >/dev/null || die "The generated service file $PLIST is invalid."
step "Service file: $PLIST"

# ---- (Re)start ------------------------------------------------------------------------------------
if launchctl print "$DOMAIN/$LABEL" >/dev/null 2>&1; then
    step "Replacing the running service"
    launchctl bootout "$DOMAIN/$LABEL" 2>/dev/null || true
    sleep 2
fi
launchctl bootstrap "$DOMAIN" "$PLIST"
launchctl enable "$DOMAIN/$LABEL"
# Start now rather than waiting for launchd: macOS can hold a new background item's automatic
# launches until it's allowed in System Settings → General → Login Items & Extensions
launchctl kickstart "$DOMAIN/$LABEL"

URL="http://127.0.0.1:$PORT"
step "Waiting for the app to answer"
for _ in $(seq 1 60); do
    if curl -sf "$URL/_stcore/health" >/dev/null 2>&1; then
        printf '\n\033[32mSearchables is running: %s\033[0m\n' "$URL"
        echo "If macOS shows a \"Background Items Added\" notification, keep it allowed so the service"
        echo "starts at login and restarts after a crash (System Settings → General → Login Items & Extensions)."
        [ "$ADDRESS" = "127.0.0.1" ] || warn "The app is reachable from the network and has no login. Anyone who can reach port $PORT can read and delete documents."
        exit 0
    fi
    sleep 1
done
die "The service started but the app didn't answer within 60 seconds. Check $LOG_DIR/searchables.err.log."
