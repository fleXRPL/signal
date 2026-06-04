#!/bin/bash
# Commit and push given paths when the index changed.
# Shared by run_and_publish.sh and post_scheduled.py.

set -euo pipefail

REPO="/Users/garotconklin/garotm/fleXRPL/signal"
cd "$REPO"

if [ "$#" -lt 2 ]; then
    echo "Usage: git_publish_if_changed.sh <commit message> <path> [path...]" >&2
    exit 1
fi

MSG="$1"
shift

CURRENT_BRANCH=$(git rev-parse --abbrev-ref HEAD)
if [ "$CURRENT_BRANCH" != "main" ]; then
    echo "On branch '$CURRENT_BRANCH' — switching to main for publish..."
    git checkout main
    git pull --ff-only origin main || echo "Warning: pull failed, continuing with local main"
fi

git add -- "$@"

if git diff --cached --quiet; then
    echo "No changes to commit — skipping push."
    exit 0
fi

git commit -m "$MSG"
git push origin main
echo "Pushed to GitHub."
