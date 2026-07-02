#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Feed collector for Signal.

Reads sources.yaml, fetches RSS feeds, optionally retrieves full article
text, and returns normalized article dicts ready for the analysis pipeline.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import feedparser
import httpx
import yaml
from bs4 import BeautifulSoup
from dateutil import parser as dateparser
from rich.console import Console
from rich.progress import BarColumn, Progress, SpinnerColumn, TextColumn

from pipeline.ops import log_feed_health

console = Console()
CONFIG_PATH = Path(__file__).parent.parent / "config" / "sources.yaml"


def load_config() -> Dict[str, Any]:
    """Load sources.yaml configuration."""
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def _parse_date(entry: Any) -> Optional[str]:
    """Extract and normalize published date from a feed entry."""
    for field in ("published", "updated", "created"):
        raw = getattr(entry, field, None)
        if raw:
            try:
                dt = dateparser.parse(raw)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                return dt.isoformat()
            except (ValueError, TypeError):
                continue
    return None


def _strip_html(html: str) -> str:
    """Strip HTML tags and normalize whitespace."""
    soup = BeautifulSoup(html, "lxml")
    text = soup.get_text(separator=" ")
    return re.sub(r"\s+", " ", text).strip()


def _fetch_full_text(url: str, timeout: int = 10) -> Optional[str]:
    """
    Attempt to retrieve and extract the main body text of an article.

    Returns None on any failure — callers should fall back to snippet.
    """
    try:
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            )
        }
        resp = httpx.get(url, timeout=timeout, follow_redirects=True, headers=headers)
        if resp.status_code != 200:
            return None

        soup = BeautifulSoup(resp.text, "lxml")

        # Remove nav, ads, footers
        for tag in soup(["nav", "footer", "aside", "script", "style", "noscript"]):
            tag.decompose()

        # Try common article containers first
        for selector in [
            "article",
            '[role="main"]',
            ".article-body",
            ".post-content",
            ".entry-content",
            ".story-body",
            "main",
        ]:
            el = soup.select_one(selector)
            if el:
                text = re.sub(r"\s+", " ", el.get_text(separator=" ")).strip()
                if len(text) > 200:
                    return text[:4000]  # cap to keep LLM context manageable

        # Fallback: longest <p> block
        paragraphs = [p.get_text(" ").strip() for p in soup.find_all("p")]
        body = " ".join(p for p in paragraphs if len(p) > 80)
        return body[:4000] if body else None

    except Exception:  # noqa: BLE001
        return None


def _fetch_feed(url: str, timeout: int = 30) -> Any:
    """
    Fetch an RSS feed over HTTP with a hard timeout, then parse the bytes.

    feedparser's own URL fetching has no timeout (a stalled server hung the
    pipeline for 7 hours on 2026-06-09), so networking goes through httpx.
    """
    resp = httpx.get(
        url,
        timeout=timeout,
        follow_redirects=True,
        headers={"User-Agent": "signal/0.1"},
    )
    resp.raise_for_status()
    return feedparser.parse(resp.content)


def _article_is_fresh(published_at: Optional[str], max_age_hours: int) -> bool:
    """Return True if article is within the max age window."""
    if not published_at:
        return True  # can't tell; include it
    try:
        dt = dateparser.parse(published_at)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        cutoff = datetime.now(timezone.utc) - timedelta(hours=max_age_hours)
        return dt >= cutoff
    except (ValueError, TypeError):
        return True


def collect_feeds(config: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    """
    Fetch all configured RSS feeds and return normalized article list.

    Args:
        config: Loaded config dict; if None, loads from sources.yaml.

    Returns:
        List of article dicts with keys: title, url, source_name, bias,
        published_at, text_snippet, full_text.
    """
    if config is None:
        config = load_config()

    sources = config.get("sources", [])
    collection_cfg = config.get("collection", {})
    max_per_source = collection_cfg.get("max_articles_per_source", 20)
    max_age_hours = collection_cfg.get("article_age_hours", 48)
    fetch_full = collection_cfg.get("fetch_full_text", True)
    fetch_timeout = collection_cfg.get("fetch_timeout", 10)

    seen_urls: set[str] = set()
    articles: List[Dict[str, Any]] = []
    feed_health: List[Dict[str, Any]] = []

    with Progress(
        SpinnerColumn(),
        TextColumn("[cyan]{task.description}"),
        BarColumn(),
        TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
        console=console,
    ) as progress:
        task = progress.add_task("Collecting feeds...", total=len(sources))

        for source in sources:
            source_name = source.get("name", "Unknown")
            url = source.get("url", "")
            bias = source.get("bias", "unknown")

            progress.update(task, description=f"[cyan]{source_name}")

            try:
                feed = _fetch_feed(url)
            except Exception as exc:  # noqa: BLE001
                console.print(f"  [red]✗[/red] {source_name}: {exc}")
                feed_health.append(
                    {
                        "source": source_name,
                        "status": "error",
                        "articles": 0,
                        "error": str(exc),
                    }
                )
                progress.advance(task)
                continue

            count = 0
            for entry in feed.entries:
                if count >= max_per_source:
                    break

                entry_url = getattr(entry, "link", "") or ""
                if not entry_url or entry_url in seen_urls:
                    continue

                published_at = _parse_date(entry)
                if not _article_is_fresh(published_at, max_age_hours):
                    continue

                # Build text snippet from summary/description
                raw_summary = (
                    getattr(entry, "summary", "")
                    or getattr(entry, "description", "")
                    or ""
                )
                text_snippet = _strip_html(raw_summary)[:800]

                full_text = ""
                if fetch_full:
                    full_text = _fetch_full_text(entry_url, fetch_timeout) or ""

                seen_urls.add(entry_url)
                articles.append(
                    {
                        "title": getattr(entry, "title", "Untitled").strip(),
                        "url": entry_url,
                        "source_name": source_name,
                        "bias": bias,
                        "published_at": published_at,
                        "text_snippet": text_snippet,
                        "full_text": full_text,
                    }
                )
                count += 1

            feed_health.append(
                {
                    "source": source_name,
                    "status": "ok" if count > 0 else "empty",
                    "articles": count,
                    "error": None,
                }
            )
            progress.advance(task)

    log_feed_health(feed_health, context="collect")
    console.print(f"\n[green]✓[/green] Collected [bold]{len(articles)}[/bold] articles from {len(sources)} sources")
    return articles
