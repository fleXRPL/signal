#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
RSS 2.0 feed generator for Signal.

Produces feed.xml at the repo root, containing entries for all daily
and weekly reports in reverse chronological order. The feed is committed
to git alongside the reports and served via GitHub Pages.
"""
from __future__ import annotations

import html
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Tuple

REPORTS_DIR = Path(__file__).parent.parent / "reports"
FEED_PATH = Path(__file__).parent.parent / "feed.xml"

BASE_URL = "https://flexrpl.github.io/signal"
FEED_TITLE = "Signal — Political Intelligence Pipeline"
FEED_DESCRIPTION = (
    "Automated daily and weekly political intelligence briefs. "
    "Cross-spectrum framing analysis, pattern detection, and analyst-grade synthesis."
)
MAX_ITEMS = 30  # keep feed manageable; oldest items drop off


# ── Filename parsing ──────────────────────────────────────────────────────────

def _parse_daily_filename(stem: str) -> Tuple[str, str]:
    """
    Parse brief_YYYYMMDD_HHMM → (ISO date string, RFC 2822 pub date).

    Returns ("", "") on parse failure.
    """
    parts = stem.split("_")
    try:
        date_str = parts[1]
        time_str = parts[2]
        dt = datetime(
            int(date_str[:4]), int(date_str[4:6]), int(date_str[6:]),
            int(time_str[:2]), int(time_str[2:]),
            tzinfo=timezone.utc,
        )
        return date_str, _rfc2822(dt)
    except (IndexError, ValueError):
        return "", ""


def _parse_weekly_filename(stem: str) -> Tuple[str, str]:
    """
    Parse weekly_YYYYWNN_YYYYMMDD_HHMM → (week label, RFC 2822 pub date).

    Returns ("", "") on parse failure.
    """
    parts = stem.split("_")
    try:
        week_label = parts[1]          # e.g. "2026W21"
        date_str = parts[2]
        time_str = parts[3]
        dt = datetime(
            int(date_str[:4]), int(date_str[4:6]), int(date_str[6:]),
            int(time_str[:2]), int(time_str[2:]),
            tzinfo=timezone.utc,
        )
        return week_label, _rfc2822(dt)
    except (IndexError, ValueError):
        return "", ""


def _rfc2822(dt: datetime) -> str:
    """Format a datetime as RFC 2822 for RSS pubDate."""
    return dt.strftime("%a, %d %b %Y %H:%M:%S +0000")


# ── Feed item builders ────────────────────────────────────────────────────────

def _daily_item(path: Path) -> str:
    stem = path.stem
    date_str, pub_date = _parse_daily_filename(stem)
    if not pub_date:
        return ""

    yyyy, mm, dd = date_str[:4], date_str[4:6], date_str[6:]
    title = html.escape(f"Signal Daily Brief — {yyyy}-{mm}-{dd}")
    link = html.escape(f"{BASE_URL}/reports/{path.name}")
    guid = link
    description = html.escape(
        f"Political intelligence brief for {yyyy}-{mm}-{dd}. "
        "Cross-spectrum framing analysis, pattern detection, and analyst synthesis."
    )

    return f"""    <item>
      <title>{title}</title>
      <link>{link}</link>
      <guid isPermaLink="true">{guid}</guid>
      <pubDate>{pub_date}</pubDate>
      <description>{description}</description>
      <category>Daily Brief</category>
    </item>"""


def _weekly_item(path: Path) -> str:
    stem = path.stem
    week_label, pub_date = _parse_weekly_filename(stem)
    if not pub_date:
        return ""

    title = html.escape(f"Signal Weekly Intelligence Brief — {week_label}")
    link = html.escape(f"{BASE_URL}/reports/{path.name}")
    guid = link
    description = html.escape(
        f"Weekly intelligence summary for {week_label}. "
        "Story arc analysis, watch list evolution, blindspot detection, and strategic assessment."
    )

    return f"""    <item>
      <title>{title}</title>
      <link>{link}</link>
      <guid isPermaLink="true">{guid}</guid>
      <pubDate>{pub_date}</pubDate>
      <description>{description}</description>
      <category>Weekly Brief</category>
    </item>"""


# ── Public API ────────────────────────────────────────────────────────────────

def generate_feed(reports_dir: Path | None = None, feed_path: Path | None = None) -> Path:
    """
    Generate RSS 2.0 feed.xml from all reports in reports_dir.

    Combines daily and weekly reports, sorted newest-first, capped at
    MAX_ITEMS. Writes feed.xml to the repo root and returns its path.

    Args:
        reports_dir: Override for the reports directory (used in tests).
        feed_path: Override for the output path (used in tests).

    Returns:
        Path to the written feed.xml file.
    """
    rdir = reports_dir or REPORTS_DIR
    fpath = feed_path or FEED_PATH

    # Collect and sort all report files newest-first
    daily = sorted(rdir.glob("brief_*.html"), reverse=True)
    weekly = sorted(rdir.glob("weekly_*.html"), reverse=True)

    # Interleave by filename (which sorts chronologically by embedded date)
    all_reports: List[Tuple[str, Path]] = []
    for p in daily:
        all_reports.append((p.stem, p))
    for p in weekly:
        all_reports.append((p.stem, p))

    all_reports.sort(key=lambda x: x[0], reverse=True)
    all_reports = all_reports[:MAX_ITEMS]

    # Build items
    items: List[str] = []
    for stem, path in all_reports:
        if stem.startswith("brief_"):
            item = _daily_item(path)
        else:
            item = _weekly_item(path)
        if item:
            items.append(item)

    now_rfc = _rfc2822(datetime.now(timezone.utc))
    items_xml = "\n".join(items)

    feed = f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom">
  <channel>
    <title>{html.escape(FEED_TITLE)}</title>
    <link>{BASE_URL}</link>
    <description>{html.escape(FEED_DESCRIPTION)}</description>
    <language>en-us</language>
    <lastBuildDate>{now_rfc}</lastBuildDate>
    <atom:link href="{BASE_URL}/feed.xml" rel="self" type="application/rss+xml"/>
{items_xml}
  </channel>
</rss>
"""

    fpath.write_text(feed, encoding="utf-8")
    return fpath
