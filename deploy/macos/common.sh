# Shared helpers for the macOS scripts. Sourced, not run. Works with macOS's bash 3.2.

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
VENV_PYTHON="$APP_DIR/.venv/bin/python"

step() { printf '\033[36m==> %s\033[0m\n' "$*"; }
warn() { printf '\033[33mWarning: %s\033[0m\n' "$*" >&2; }
die()  { printf '\033[31mError: %s\033[0m\n' "$*" >&2; exit 1; }

# Prints the first Python 3.10+ found. macOS's own /usr/bin/python3 is 3.9, which is too old.
find_python() {
    local candidate
    for candidate in "${PYTHON:-}" python3.13 python3.12 python3.11 python3.10 python3; do
        [ -n "$candidate" ] || continue
        command -v "$candidate" >/dev/null 2>&1 || continue
        if "$candidate" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' 2>/dev/null; then
            command -v "$candidate"
            return 0
        fi
    done
    return 1
}

# Creates .venv if needed and installs requirements.txt when it has changed since the last install.
ensure_environment() {
    if [ ! -x "$VENV_PYTHON" ]; then
        local python
        python="$(find_python)" || die "Python 3.10 or newer not found. Install it with 'brew install python@3.12' \
(or from python.org), or pass its path with --python."
        step "Creating Python environment in .venv with $python"
        "$python" -m venv "$APP_DIR/.venv"
    fi
    "$VENV_PYTHON" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' \
        || die "The existing .venv uses Python older than 3.10. Delete the .venv folder and run this again."

    # Reinstall only when requirements.txt changes: installing is slow (PyTorch via sentence-transformers)
    local stamp="$APP_DIR/.venv/.requirements.sha256"
    local current
    current="$(shasum -a 256 "$APP_DIR/requirements.txt" | cut -d' ' -f1)"
    if [ ! -f "$stamp" ] || [ "$(cat "$stamp")" != "$current" ]; then
        step "Installing Python packages (the first run can take several minutes)"
        "$VENV_PYTHON" -m pip install --upgrade pip --quiet
        "$VENV_PYTHON" -m pip install -r "$APP_DIR/requirements.txt" --quiet
        echo "$current" > "$stamp"
    fi
}

# Prints Tesseract's language-data folder, or nothing. Services don't get your shell's PATH,
# so it's found here and passed to the app explicitly.
find_tessdata() {
    local dir tesseract
    for dir in "${TESSDATA_PREFIX:-}" /opt/homebrew/share/tessdata /usr/local/share/tessdata; do
        [ -n "$dir" ] && [ -f "$dir/eng.traineddata" ] && { echo "$dir"; return 0; }
    done
    tesseract="$(command -v tesseract 2>/dev/null || true)"
    if [ -n "$tesseract" ]; then
        # "List of available languages in "/path/tessdata/" (3):"
        dir="$("$tesseract" --list-langs 2>&1 | sed -n 's/.*"\(.*\)".*/\1/p' | head -1)"
        dir="${dir%/}"
        [ -n "$dir" ] && [ -f "$dir/eng.traineddata" ] && { echo "$dir"; return 0; }
    fi
    return 0
}
