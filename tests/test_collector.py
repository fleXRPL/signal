"""
Tests for pipeline/collector.py.

Network calls (feedparser, httpx) are fully mocked so tests run
without hitting the internet.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict
from unittest.mock import MagicMock, patch

import pytest

from pipeline.collector import (
    _article_is_fresh,
    _parse_date,
    _strip_html,
    collect_feeds,
)


# ── _strip_html ───────────────────────────────────────────────────────────────

class TestStripHtml:
    def test_removes_tags(self):
        result = _strip_html("<p>Hello <b>world</b></p>")
        assert "<" not in result
        assert "Hello world" in result

    def test_normalizes_whitespace(self):
        result = _strip_html("<p>  too   many   spaces  </p>")
        assert "  " not in result

    def test_empty_string(self):
        assert _strip_html("") == ""

    def test_plain_text_unchanged(self):
        assert _strip_html("plain text") == "plain text"


# ── _parse_date ───────────────────────────────────────────────────────────────

class TestParseDate:
    def _make_entry(self, **kwargs) -> MagicMock:
        entry = MagicMock()
        for field in ("published", "updated", "created"):
            setattr(entry, field, kwargs.get(field, None))
        return entry

    def test_parses_published(self):
        entry = self._make_entry(published="Mon, 19 May 2026 10:00:00 +0000")
        result = _parse_date(entry)
        assert result is not None
        assert "2026-05-19" in result

    def test_falls_back_to_updated(self):
        entry = self._make_entry(updated="Mon, 19 May 2026 10:00:00 +0000")
        result = _parse_date(entry)
        assert result is not None
        assert "2026-05-19" in result

    def test_returns_none_when_no_date_fields(self):
        entry = self._make_entry()
        assert _parse_date(entry) is None

    def test_returns_none_on_unparseable_date(self):
        entry = self._make_entry(published="not-a-date")
        assert _parse_date(entry) is None

    def test_adds_utc_if_naive(self):
        entry = self._make_entry(published="2026-05-19T10:00:00")
        result = _parse_date(entry)
        assert result is not None
        assert "+00:00" in result


# ── _article_is_fresh ────────────────────────────────────────────────────────

class TestArticleIsFresh:
    def test_fresh_article_returns_true(self):
        recent = (datetime.now(timezone.utc) - timedelta(hours=6)).isoformat()
        assert _article_is_fresh(recent, max_age_hours=24) is True

    def test_old_article_returns_false(self):
        old = (datetime.now(timezone.utc) - timedelta(hours=48)).isoformat()
        assert _article_is_fresh(old, max_age_hours=24) is False

    def test_none_published_returns_true(self):
        assert _article_is_fresh(None, max_age_hours=24) is True

    def test_invalid_date_returns_true(self):
        assert _article_is_fresh("garbage", max_age_hours=24) is True

    def test_just_inside_cutoff_boundary(self):
        """Article published just inside the cutoff window should be fresh."""
        just_inside = (datetime.now(timezone.utc) - timedelta(hours=23, minutes=59)).isoformat()
        assert _article_is_fresh(just_inside, max_age_hours=24) is True


# ── collect_feeds ─────────────────────────────────────────────────────────────

def _make_feed_entry(
    title: str = "Test Article",
    link: str = "https://example.com/article",
    summary: str = "<p>Test snippet</p>",
    published: str | None = None,
) -> MagicMock:
    if published is None:
        # Always use a fresh timestamp so age filtering never drops the entry
        from datetime import datetime, timezone
        published = datetime.now(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S +0000")
    entry = MagicMock()
    entry.title = title
    entry.link = link
    entry.summary = summary
    entry.description = ""
    entry.published = published
    entry.updated = None
    entry.created = None
    return entry


def _make_config(
    sources: list | None = None,
    fetch_full: bool = False,
) -> Dict[str, Any]:
    if sources is None:
        sources = [{"name": "Test Source", "url": "https://example.com/rss", "bias": "center"}]
    return {
        "sources": sources,
        "collection": {
            "max_articles_per_source": 5,
            "article_age_hours": 48,
            "fetch_full_text": fetch_full,
            "fetch_timeout": 5,
        },
    }


class TestCollectFeeds:
    @patch("pipeline.collector.feedparser.parse")
    def test_returns_articles_from_feed(self, mock_parse):
        mock_feed = MagicMock()
        mock_feed.entries = [_make_feed_entry()]
        mock_parse.return_value = mock_feed

        articles = collect_feeds(_make_config())
        assert len(articles) == 1
        assert articles[0]["title"] == "Test Article"
        assert articles[0]["source_name"] == "Test Source"
        assert articles[0]["bias"] == "center"

    @patch("pipeline.collector.feedparser.parse")
    def test_deduplicates_by_url(self, mock_parse):
        """Two entries with the same URL should yield only one article."""
        entry = _make_feed_entry()
        mock_feed = MagicMock()
        mock_feed.entries = [entry, entry]
        mock_parse.return_value = mock_feed

        articles = collect_feeds(_make_config())
        assert len(articles) == 1

    @patch("pipeline.collector.feedparser.parse")
    def test_respects_max_per_source(self, mock_parse):
        entries = [
            _make_feed_entry(title=f"Article {i}", link=f"https://example.com/{i}")
            for i in range(10)
        ]
        mock_feed = MagicMock()
        mock_feed.entries = entries
        mock_parse.return_value = mock_feed

        articles = collect_feeds(_make_config(fetch_full=False))
        assert len(articles) <= 5

    @patch("pipeline.collector.feedparser.parse")
    def test_skips_feed_on_exception(self, mock_parse):
        mock_parse.side_effect = Exception("Connection refused")
        articles = collect_feeds(_make_config())
        assert articles == []

    @patch("pipeline.collector._fetch_full_text")
    @patch("pipeline.collector.feedparser.parse")
    def test_full_text_fetch_called_when_enabled(self, mock_parse, mock_fetch):
        mock_feed = MagicMock()
        mock_feed.entries = [_make_feed_entry()]
        mock_parse.return_value = mock_feed
        mock_fetch.return_value = "Full article body text."

        articles = collect_feeds(_make_config(fetch_full=True))
        assert len(articles) == 1
        mock_fetch.assert_called_once()
        assert articles[0]["full_text"] == "Full article body text."

    @patch("pipeline.collector.feedparser.parse")
    def test_empty_sources_returns_empty_list(self, mock_parse):
        articles = collect_feeds(_make_config(sources=[]))
        assert articles == []
        mock_parse.assert_not_called()

    @patch("pipeline.collector._fetch_full_text")
    @patch("pipeline.collector.feedparser.parse")
    def test_full_text_fallback_to_empty_on_none(self, mock_parse, mock_fetch):
        mock_feed = MagicMock()
        mock_feed.entries = [_make_feed_entry()]
        mock_parse.return_value = mock_feed
        mock_fetch.return_value = None

        articles = collect_feeds(_make_config(fetch_full=True))
        assert articles[0]["full_text"] == ""


# ── _fetch_full_text (unit) ───────────────────────────────────────────────────

class TestFetchFullText:
    @patch("pipeline.collector.httpx.get")
    def test_returns_none_on_non_200(self, mock_get):
        from pipeline.collector import _fetch_full_text
        mock_resp = MagicMock()
        mock_resp.status_code = 404
        mock_get.return_value = mock_resp
        assert _fetch_full_text("https://example.com/article") is None

    @patch("pipeline.collector.httpx.get")
    def test_returns_none_on_exception(self, mock_get):
        from pipeline.collector import _fetch_full_text
        mock_get.side_effect = Exception("Timeout")
        assert _fetch_full_text("https://example.com/article") is None

    @patch("pipeline.collector.httpx.get")
    def test_extracts_article_tag(self, mock_get):
        from pipeline.collector import _fetch_full_text
        html = "<html><body><article>" + "Body text. " * 30 + "</article></body></html>"
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = html
        mock_get.return_value = mock_resp

        result = _fetch_full_text("https://example.com/article")
        assert result is not None
        assert "Body text." in result
