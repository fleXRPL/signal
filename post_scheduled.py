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
    python post_scheduled.py --catch-up

Exit codes:
    0 — posted successfully (or already posted)
    1 — post package not found (morning run failed)
    2 — credentials missing or Bluesky API error
"""

from __future__ import annotations

import argparse
import json
import logging
import subprocess
import sys
from datetime import datetime, timezone
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


def _post_one_slot(slot: str, date_slug: str) -> int:
    from pipeline.collector import load_config
    from pipeline.ops import send_alert
    from pipeline.social import post_slot

    config = load_config()
    try:
        uri = post_slot(slot, date_slug=date_slug)
        log.info("✓ Posted [%s] → %s", slot.upper(), uri)
        _git_publish(
            f"signal: {slot} bluesky post {date_slug}",
            "reports/posts/",
        )
        return 0
    except FileNotFoundError as exc:
        log.exception("Post package missing")
        send_alert(
            f"Signal social {slot}: package missing",
            str(exc),
            config=config,
            tags=["signal", "social", slot],
        )
        return 1
    except RuntimeError:
        log.exception("Post failed")
        send_alert(
            f"Signal social {slot}: post failed",
            f"Slot {slot} for {date_slug} — see logs/social_{slot}.log",
            config=config,
            tags=["signal", "social", slot],
        )
        return 2


def _catch_up(date_slug: str) -> int:
    """Post any unposted slots for the given UTC date."""
    from pipeline.social import POSTS_DIR

    worst = 0
    posted_any = False
    for slot in ("am", "noon", "pm"):
        package_path = POSTS_DIR / f"{slot}_{date_slug}.json"
        if not package_path.exists():
            log.warning("Catch-up: no package for %s (%s)", slot, package_path.name)
            continue
        package = json.loads(package_path.read_text(encoding="utf-8"))
        if package.get("posted"):
            log.info("Catch-up: %s already posted", slot.upper())
            continue
        log.info("Catch-up: posting %s", slot.upper())
        code = _post_one_slot(slot, date_slug)
        worst = max(worst, code)
        if code == 0:
            posted_any = True

    if not posted_any and worst == 0:
        log.info("Catch-up: nothing to post for %s", date_slug)
    return worst


def main() -> int:
    parser = argparse.ArgumentParser(description="Signal scheduled social post dispatcher")
    parser.add_argument(
        "--slot",
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
    parser.add_argument(
        "--catch-up",
        action="store_true",
        help="Post all unposted slots for today (am, noon, pm)",
    )
    args = parser.parse_args()

    from pipeline.social import POSTS_DIR

    date_slug = args.date or datetime.now(timezone.utc).strftime("%Y%m%d")

    if args.catch_up:
        return _catch_up(date_slug)

    if not args.slot:
        parser.error("--slot is required unless --catch-up is set")

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

    return _post_one_slot(args.slot, date_slug)


if __name__ == "__main__":
    sys.exit(main())
