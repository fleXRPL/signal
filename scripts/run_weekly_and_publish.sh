#!/bin/bash
# run_weekly_and_publish.sh
# Runs the Signal weekly intelligence synthesis (Pass 6) and pushes the
# generated report to GitHub Pages.
# Intended to be called by launchd every Sunday at 11:00 PM.

set -euo pipefail

REPO="/Users/garotconklin/garotm/fleXRPL/signal"
PYTHON="$REPO/.venv/bin/python"
LOG="$REPO/logs/weekly.log"

# Rotate log if it exceeds 1MB
if [ -f "$LOG" ] && [ "$(stat -f%z "$LOG")" -gt 1048576 ]; then
    mv "$LOG" "$LOG.bak"
fi

exec >> "$LOG" 2>&1

echo ""
echo "========================================"
echo "Signal WEEKLY run started: $(date)"
echo "========================================"

cd "$REPO"

# Always publish from main — switch if on a feature branch
CURRENT_BRANCH=$(git rev-parse --abbrev-ref HEAD)
if [ "$CURRENT_BRANCH" != "main" ]; then
    echo "On branch '$CURRENT_BRANCH' — switching to main for publish..."
    git checkout main
    git pull --ff-only origin main || echo "Warning: pull failed, continuing with local main"
fi

# Claude is required for the weekly synthesis (large context, reliable in background)
export SIGNAL_LLM_PROVIDER="${SIGNAL_LLM_PROVIDER:-claude}"

# Run the weekly synthesis pipeline
if ! "$PYTHON" main.py --weekly --no-venv; then
    "$PYTHON" -c "from pipeline.ops import send_alert; send_alert('Signal weekly run failed', 'Check logs/weekly.log', tags=['signal','weekly'])" || true
    exit 1
fi

# Stage weekly report, updated index, and archive
git add reports/weekly_*.html index.html archive.html

# Only commit + push if something actually changed
if git diff --cached --quiet; then
    echo "No changes to commit — skipping push."
else
    git commit -m "signal: weekly brief $(date +%Y-W%V)"
    git push origin main
    echo "Pushed weekly report to GitHub Pages."
fi

echo "Signal WEEKLY run complete: $(date)"
