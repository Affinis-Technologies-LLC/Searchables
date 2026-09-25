#!/bin/bash
# shellcheck source-path=SCRIPTDIR
# Starts Searchables in this terminal window (no background service). Stop it with Ctrl+C.
#
#   deploy/macos/run.sh                  # http://127.0.0.1:8501, library in the project's data folder
#   deploy/macos/run.sh --port 8600      # Any other options are passed to Streamlit
#
# Sets up .venv and installs requirements on first use, and again whenever requirements.txt changes.
set -euo pipefail
# shellcheck source=common.sh
source "$(dirname "${BASH_SOURCE[0]}")/common.sh"

PORT=8501
ARGS=()
while [ $# -gt 0 ]; do
    case "$1" in
        --port) PORT="$2"; shift 2 ;;
        --python) PYTHON="$2"; shift 2 ;;
        *) ARGS+=("$1"); shift ;;
    esac
done

ensure_environment
TESSDATA="$(find_tessdata)"
if [ -n "$TESSDATA" ]; then
    export TESSDATA_PREFIX="$TESSDATA"
else
    warn "Tesseract not found: scanned pages won't be searchable (brew install tesseract)."
fi

cd "$APP_DIR"
step "Starting Searchables on http://127.0.0.1:$PORT (Ctrl+C to stop)"
# "${ARGS[@]+...}" keeps bash 3.2 happy when no extra options were given
exec "$VENV_PYTHON" -m streamlit run app.py --server.port "$PORT" --server.address 127.0.0.1 \
    --browser.gatherUsageStats false ${ARGS[@]+"${ARGS[@]}"}
