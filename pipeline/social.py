#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Bluesky social posting for Signal.

Handles authentication, image upload, post composition, and the
pre-generated post-package JSON that launchd jobs consume.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

POSTS_DIR = Path(__file__).parent.parent / "reports" / "posts"

log = logging.getLogger(__name__)

_SLOT_LABELS = {
    "am":   "Watch List",
    "noon": "Spectrum Breakdown",
    "pm":   "Blindspot Analysis",
}

_POST_TEMPLATES: Dict[str, str] = {
    "am": (
        "SIGNAL // {date}\n\n"
        "{watch_count} items on today's watch list — {window_summary}.\n\n"
        "Full brief → {report_url}"
    ),
    "noon": (
        "SIGNAL // {date}\n\n"
        "{headline}\n\n"
        "Left, center, and right are covering this — but not the same story.\n\n"
        "Full analysis → {report_url}"
    ),
    "pm": (
        "SIGNAL // {date}\n\n"
        "Today's blindspot: {blindspot_headline}\n\n"
        "What each side isn't showing you → {report_url}"
    ),
}


def _build_post_text(slot: str, brief_data: Dict[str, Any]) -> str:
    """Compose the post text for a given slot from brief_data."""
    date_display = brief_data.get("date", "")
    report_url   = brief_data.get("report_url", "https://flexrpl.github.io/signal")

    watch_items = brief_data.get("watch_items", [])
    windows = [w["window"] for w in watch_items]

    if "24hr" in windows:
        shortest = "24hr"
    elif "48hr" in windows:
        shortest = "48hr"
    else:
        shortest = "72hr"

    if "5d" in windows:
        longest = "5d"
    elif "72hr" in windows:
        longest = "72hr"
    else:
        longest = "48hr"
    _labels  = {"24hr": "24 hours", "48hr": "48 hours", "72hr": "72 hours", "5d": "5 days"}
    window_summary = (
        f"{_labels[shortest]} to {_labels[longest]}"
        if shortest != longest
        else _labels[shortest]
    )

    top = brief_data.get("top_cluster", {})
    headline = top.get("headline", "")
    if len(headline) > 120:
        headline = headline[:117] + "..."

    narrative = brief_data.get("blindspot_narrative", "")
    blindspot_headline = (narrative.split(".")[0].strip() or "coverage gaps detected")[:120]

    return _POST_TEMPLATES[slot].format(
        date=date_display,
        watch_count=len(watch_items),
        window_summary=window_summary,
        headline=headline,
        blindspot_headline=blindspot_headline,
        report_url=report_url,
    )


def build_post_package(
    slot: str,
    brief_data: Dict[str, Any],
    image_path: Path,
    date_slug: str | None = None,
) -> Path:
    """
    Write a JSON post-package for a given slot to reports/posts/.

    The launchd job loads this file and calls post_to_bluesky().
    """
    POSTS_DIR.mkdir(parents=True, exist_ok=True)

    if date_slug is None:
        date_slug = datetime.now(timezone.utc).strftime("%Y%m%d")

    package = {
        "slot": slot,
        "date": brief_data.get("date", date_slug),
        "text": _build_post_text(slot, brief_data),
        "image_path": str(image_path),
        "report_url": brief_data.get("report_url", "https://flexrpl.github.io/signal"),
        "posted": False,
    }

    out = POSTS_DIR / f"{slot}_{date_slug}.json"
    out.write_text(json.dumps(package, indent=2), encoding="utf-8")
    return out


def post_to_bluesky(text: str, image_path: Path, report_url: str) -> str:
    """
    Post to Bluesky with an image card.

    Credentials are loaded from environment variables:
      BLUESKY_HANDLE        — e.g. signal.bsky.social
      BLUESKY_APP_PASSWORD  — app password from Bluesky settings

    Returns the post URI on success.
    Raises RuntimeError if credentials are missing or the post fails.
    """
    from atproto import Client  # lazy import — optional dep

    handle   = os.environ.get("BLUESKY_HANDLE", "").strip()
    password = os.environ.get("BLUESKY_APP_PASSWORD", "").strip()

    if not handle or not password:
        raise RuntimeError(
            "BLUESKY_HANDLE and BLUESKY_APP_PASSWORD must be set in the environment"
        )

    img_bytes = Path(image_path).read_bytes()

    client = Client()
    client.login(handle, password)

    response = client.send_image(
        text=text,
        image=img_bytes,
        image_alt=f"Signal political intelligence card — {report_url}",
    )

    uri = getattr(response, "uri", str(response))
    log.info("Posted to Bluesky: %s", uri)
    return uri


def post_slot(slot: str, date_slug: str | None = None) -> str:
    """
    Load the pre-generated post package for a slot and post it.

    Marks the package as posted on success.
    Raises FileNotFoundError if the package doesn't exist (morning run failed).
    """
    from dotenv import load_dotenv  # lazy import — optional dep

    load_dotenv()

    if date_slug is None:
        date_slug = datetime.now(timezone.utc).strftime("%Y%m%d")

    package_path = POSTS_DIR / f"{slot}_{date_slug}.json"
    if not package_path.exists():
        raise FileNotFoundError(
            f"Post package not found: {package_path} — "
            "did the morning pipeline run successfully?"
        )

    package = json.loads(package_path.read_text(encoding="utf-8"))

    if package.get("posted"):
        log.info("Slot %s already posted for %s — skipping", slot, date_slug)
        return package.get("post_uri", "already-posted")

    uri = post_to_bluesky(
        text=package["text"],
        image_path=Path(package["image_path"]),
        report_url=package["report_url"],
    )

    package["posted"] = True
    package["post_uri"] = uri
    package["posted_at"] = datetime.now(timezone.utc).isoformat()
    package_path.write_text(json.dumps(package, indent=2), encoding="utf-8")

    return uri
