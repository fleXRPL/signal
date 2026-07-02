#!/bin/bash
# run_monthly_and_publish.sh
# Runs the Signal monthly intelligence synthesis (Pass 7) and pushes the
# generated report to GitHub Pages.
# Intended to be called by launchd on the 1st of each month at 7:00 AM.

set -euo pipefail

REPO="/Users/garotconklin/garotm/fleXRPL/signal"
PYTHON="$REPO/.venv/bin/python"
LOG="$REPO/logs/monthly.log"

# Rotate log if it exceeds 1MB
if [ -f "$LOG" ] && [ "$(stat -f%z "$LOG")" -gt 1048576 ]; then
    mv "$LOG" "$LOG.bak"
fi

exec >> "$LOG" 2>&1

echo ""
echo "========================================"
echo "Signal MONTHLY run started: $(date)"
echo "========================================"

cd "$REPO"

# Always publish from main — switch if on a feature branch
CURRENT_BRANCH=$(git rev-parse --abbrev-ref HEAD)
if [ "$CURRENT_BRANCH" != "main" ]; then
    echo "On branch '$CURRENT_BRANCH' — switching to main for publish..."
    git checkout main
    git pull --ff-only origin main || echo "Warning: pull failed, continuing with local main"
fi

# Claude is required for the monthly synthesis (large context, reliable in background)
export SIGNAL_LLM_PROVIDER="${SIGNAL_LLM_PROVIDER:-claude}"

# Previous calendar month (e.g. Jul 1 run → June report)
PREV_MONTH=$(date -v-1m +%Y-%m)

# Run the monthly synthesis pipeline
if ! "$PYTHON" main.py --monthly --month "$PREV_MONTH" --no-venv; then
    "$PYTHON" -c "from pipeline.ops import send_alert; send_alert('Signal monthly run failed', 'Check logs/monthly.log', tags=['signal','monthly'])" || true
    exit 1
fi

# Stage monthly report, updated index, and archive
git add reports/monthly_*.html index.html archive.html

# Only commit + push if something actually changed
if git diff --cached --quiet; then
    echo "No changes to commit — skipping push."
else
    git commit -m "signal: monthly brief ${PREV_MONTH}"
    git push origin main
    echo "Pushed monthly report to GitHub Pages."
fi

echo "Signal MONTHLY run complete: $(date)"
