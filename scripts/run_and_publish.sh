#!/bin/bash
# run_and_publish.sh
# Runs the Signal daily pipeline and pushes the generated report to GitHub Pages.
# Intended to be called by launchd daily at 4:00 AM.
# For weekly synthesis, see run_weekly_and_publish.sh.

set -euo pipefail

REPO="/Users/garotconklin/garotm/fleXRPL/signal"
PYTHON="$REPO/.venv/bin/python"
LOG="$REPO/logs/cron.log"

# Rotate log if it exceeds 1MB
if [ -f "$LOG" ] && [ "$(stat -f%z "$LOG")" -gt 1048576 ]; then
    mv "$LOG" "$LOG.bak"
fi

exec >> "$LOG" 2>&1

echo ""
echo "========================================"
echo "Signal run started: $(date)"
echo "========================================"

cd "$REPO"

# Always publish from main — switch if on a feature branch
CURRENT_BRANCH=$(git rev-parse --abbrev-ref HEAD)
if [ "$CURRENT_BRANCH" != "main" ]; then
    echo "On branch '$CURRENT_BRANCH' — switching to main for publish..."
    git checkout main
    git pull --ff-only origin main || echo "Warning: pull failed, continuing with local main"
fi

# Default to Claude; override with SIGNAL_LLM_PROVIDER=ollama if needed
export SIGNAL_LLM_PROVIDER="${SIGNAL_LLM_PROVIDER:-claude}"

# If using Ollama, ensure it is running
if [ "$SIGNAL_LLM_PROVIDER" = "ollama" ]; then
    if ! pgrep -x "ollama" > /dev/null; then
        echo "Starting Ollama..."
        /usr/local/bin/ollama serve &
        sleep 5
    fi
fi

# Run the pipeline (venv already exists, skip setup)
"$PYTHON" main.py --no-venv

# Stage report, index, archive, and RSS feed
bash "$REPO/scripts/git_publish_if_changed.sh" \
    "signal: daily brief $(date +%Y-%m-%d)" \
    reports/ index.html archive.html feed.xml

echo "Signal run complete: $(date)"
