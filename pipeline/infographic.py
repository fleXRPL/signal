#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Social card image generator for Signal.

Renders Jinja2 HTML templates to 1200×630 PNG via Playwright headless Chromium.
One function per card type; all return the output Path on success.
"""

from __future__ import annotations

import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Tuple

from jinja2 import Environment, FileSystemLoader, select_autoescape

TEMPLATES_DIR = Path(__file__).parent / "templates"
CARDS_DIR = Path(__file__).parent.parent / "reports" / "cards"

_BIAS_SLUG = {
    "far-left":     "fl",
    "left":         "l",
    "center-left":  "cl",
    "center":       "c",
    "center-right": "cr",
    "right":        "r",
    "far-right":    "fr",
}

_BIAS_ORDER = ["far-left", "left", "center-left", "center", "center-right", "right", "far-right"]


def _jinja_env() -> Environment:
    return Environment(
        loader=FileSystemLoader(str(TEMPLATES_DIR)),
        autoescape=select_autoescape(["html"]),
    )


def _render_html(template_name: str, context: Dict[str, Any]) -> str:
    env = _jinja_env()
    tmpl = env.get_template(template_name)
    return tmpl.render(**context)


def _screenshot(html_content: str, output_path: Path) -> Path:
    """Write HTML to a temp file and screenshot it at 1200×630 via Playwright."""
    from playwright.sync_api import sync_playwright  # lazy import — optional dep

    output_path.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.NamedTemporaryFile(
        suffix=".html", mode="w", encoding="utf-8", delete=False
    ) as f:
        f.write(html_content)
        tmp_path = Path(f.name)

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page(viewport={"width": 1200, "height": 630})
            page.goto(f"file://{tmp_path}", wait_until="networkidle", timeout=15000)
            page.screenshot(path=str(output_path), clip={"x": 0, "y": 0, "width": 1200, "height": 630})
            browser.close()
    finally:
        tmp_path.unlink(missing_ok=True)

    return output_path


def _spectrum_segments(bias_spread: Dict[str, int]) -> List[Tuple[str, float]]:
    """Convert bias_spread dict → ordered (slug, flex) pairs for the spectrum bar."""
    total = sum(bias_spread.values()) or 1
    segments = []
    for label in _BIAS_ORDER:
        count = bias_spread.get(label, 0)
        if count:
            slug = _BIAS_SLUG.get(label, "c")
            segments.append((slug, round((count / total) * 100, 1)))
    if not segments:
        segments = [("c", 100.0)]
    return segments


def _window_summary(watch_items: List[Dict[str, str]]) -> str:
    """Produce a human-readable summary of the time windows present."""
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
    labels = {"24hr": "24 hours", "48hr": "48 hours", "72hr": "72 hours", "5d": "5 days"}
    if shortest == longest:
        return f"{labels[shortest]} window"
    return f"{labels[shortest]} to {labels[longest]}"


def _blindspot_headline(narrative: str) -> str:
    """Extract a short headline from the blindspot narrative text."""
    if not narrative:
        return "Coverage gaps detected across the political spectrum"
    first_sentence = narrative.split(".")[0].strip()
    return first_sentence[:160] if len(first_sentence) > 160 else first_sentence


def render_watch_card(brief_data: Dict[str, Any], date_slug: str) -> Path:
    """Render the AM watch list card → PNG."""
    watch_items = brief_data.get("watch_items", [])[:6]
    context = {
        "date": brief_data.get("date", date_slug),
        "watch_items": watch_items,
        "watch_count": len(watch_items),
        "window_summary": _window_summary(watch_items),
    }
    html_content = _render_html("card_watch.html", context)
    out = CARDS_DIR / f"am_{date_slug}.png"
    return _screenshot(html_content, out)


def render_spectrum_card(brief_data: Dict[str, Any], date_slug: str) -> Path:
    """Render the noon spectrum breakdown card → PNG."""
    top = brief_data.get("top_cluster", {})
    context = {
        "date": brief_data.get("date", date_slug),
        "article_count": brief_data.get("article_count", 0),
        "source_count": brief_data.get("source_count", 0),
        "cluster_count": brief_data.get("cluster_count", 0),
        "top_cluster": top,
        "spectrum_segments": _spectrum_segments(top.get("bias_spread", {})),
    }
    html_content = _render_html("card_spectrum.html", context)
    out = CARDS_DIR / f"noon_{date_slug}.png"
    return _screenshot(html_content, out)


def render_blindspot_card(brief_data: Dict[str, Any], date_slug: str) -> Path:
    """Render the PM blindspot analysis card → PNG."""
    left_only  = brief_data.get("left_only",  [])[:4]
    right_only = brief_data.get("right_only", [])[:4]
    context = {
        "date": brief_data.get("date", date_slug),
        "source_count": brief_data.get("source_count", 0),
        "blindspot_headline": _blindspot_headline(brief_data.get("blindspot_narrative", "")),
        "left_only":   left_only,
        "right_only":  right_only,
        "left_count":  len(brief_data.get("left_only", [])),
        "right_count": len(brief_data.get("right_only", [])),
    }
    html_content = _render_html("card_blindspot.html", context)
    out = CARDS_DIR / f"pm_{date_slug}.png"
    return _screenshot(html_content, out)


def render_all_cards(brief_data: Dict[str, Any]) -> Dict[str, Path]:
    """
    Render all three cards for a given brief_data dict.

    Returns:
        {"am": Path, "noon": Path, "pm": Path}
    """
    date_slug = datetime.now(timezone.utc).strftime("%Y%m%d")
    return {
        "am":   render_watch_card(brief_data, date_slug),
        "noon": render_spectrum_card(brief_data, date_slug),
        "pm":   render_blindspot_card(brief_data, date_slug),
    }
