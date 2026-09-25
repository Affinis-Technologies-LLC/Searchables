#!/bin/bash
# shellcheck source-path=SCRIPTDIR
# Stops and removes the Searchables macOS service. The library (PDFs, index, collections) is kept.
#
#   deploy/macos/uninstall-service.sh
#   deploy/macos/uninstall-service.sh --label com.searchables.test
set -euo pipefail
# shellcheck source=common.sh
source "$(dirname "${BASH_SOURCE[0]}")/common.sh"

LABEL=com.searchables.app
while [ $# -gt 0 ]; do
    case "$1" in
        --label) LABEL="$2"; shift 2 ;;
        -h|--help) awk 'NR > 2 && /^#/ { sub(/^# ?/, ""); print; next } NR > 2 { exit }' "$0"; exit 0 ;;
        *) die "Unknown option: $1" ;;
    esac
done

PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
if launchctl print "gui/$(id -u)/$LABEL" >/dev/null 2>&1; then
    launchctl bootout "gui/$(id -u)/$LABEL"
    step "Stopped the $LABEL service."
else
    step "No running service named $LABEL."
fi
if [ -f "$PLIST" ]; then
    rm "$PLIST"
    step "Removed $PLIST."
fi
step "The library was kept. Delete its folder yourself if you no longer need it."
