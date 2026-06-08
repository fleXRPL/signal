#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Signal — Scheduled social post dispatcher.

Loads the pre-generated post package for a given slot and posts it to Bluesky.
Called by three launchd jobs at 9 AM, 12 PM, and 6 PM.

Usage:
    python post_scheduled.py --slot am
    python post_scheduled.py --slot noon
    python post_scheduled.py --slot pm

Exit codes:
    0 — posted successfully (or already posted)
    1 — post package not found (morning run failed)
    2 — credentials missing or Bluesky API error
"""

from __future__ import annotations

import argparse
import logging
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("post_scheduled")


def _git_publish(message: str, *paths: str) -> None:
    """Push post-state (or other) file changes to main when the index changed."""
    script = ROOT / "scripts" / "git_publish_if_changed.sh"
    result = subprocess.run(
        ["bash", str(script), message, *paths],
        capture_output=True,
        text=True,
        check=False,
    )
    output = (result.stdout or "") + (result.stderr or "")
    if result.returncode != 0:
        log.warning("Git publish failed (exit %s): %s", result.returncode, output.strip())
    elif "Pushed to GitHub" in output:
        log.info("Pushed post state to GitHub")


def main() -> int:
    parser = argparse.ArgumentParser(description="Signal scheduled social post dispatcher")
    parser.add_argument(
        "--slot",
        required=True,
        choices=["am", "noon", "pm"],
        help="Which card slot to post (am=9AM watch list, noon=spectrum, pm=blindspot)",
    )
    parser.add_argument(
        "--date",
        default=None,
        help="Date slug YYYYMMDD (default: today UTC)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Load and print the post package without actually posting",
    )
    args = parser.parse_args()

    from pipeline.social import post_slot, POSTS_DIR
    from datetime import datetime, timezone
    import json

    date_slug = args.date or datetime.now(timezone.utc).strftime("%Y%m%d")

    if args.dry_run:
        package_path = POSTS_DIR / f"{args.slot}_{date_slug}.json"
        if not package_path.exists():
            log.error("Post package not found: %s", package_path)
            return 1
        package = json.loads(package_path.read_text(encoding="utf-8"))
        log.info("--- DRY RUN: %s ---", args.slot.upper())
        log.info("Text:\n%s", package["text"])
        log.info("Image: %s", package["image_path"])
        log.info("URL:   %s", package["report_url"])
        return 0

    try:
        uri = post_slot(args.slot, date_slug=date_slug)
        log.info("✓ Posted [%s] → %s", args.slot.upper(), uri)
        _git_publish(
            f"signal: {args.slot} bluesky post {date_slug}",
            "reports/posts/",
        )
        return 0
    except FileNotFoundError:
        log.exception("Post package missing")
        return 1
    except RuntimeError:
        log.exception("Post failed")
        return 2


if __name__ == "__main__":
    sys.exit(main())
