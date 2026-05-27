"""
Tests for pipeline/feed.py — RSS 2.0 feed generation.

Uses tmp_path to write reports and feed.xml so the real filesystem
is never touched.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from pipeline.feed import (
    MAX_ITEMS,
    _daily_item,
    _parse_daily_filename,
    _parse_weekly_filename,
    _rfc2822,
    _weekly_item,
    generate_feed,
)


# ── _parse_daily_filename ─────────────────────────────────────────────────────

class TestParseDailyFilename:
    def test_valid_stem(self):
        date_str, pub_date = _parse_daily_filename("brief_20260519_1500")
        assert date_str == "20260519"
        assert "19 May 2026" in pub_date
        assert "+0000" in pub_date

    def test_returns_empty_on_invalid_stem(self):
        date_str, pub_date = _parse_daily_filename("brief_baddata")
        assert date_str == ""
        assert pub_date == ""

    def test_returns_empty_on_non_numeric(self):
        date_str, pub_date = _parse_daily_filename("brief_YYYYMMDD_HHMM")
        assert date_str == ""
        assert pub_date == ""


# ── _parse_weekly_filename ────────────────────────────────────────────────────

class TestParseWeeklyFilename:
    def test_valid_stem(self):
        week_label, pub_date = _parse_weekly_filename("weekly_2026W21_20260525_1500")
        assert week_label == "2026W21"
        assert "25 May 2026" in pub_date
        assert "+0000" in pub_date

    def test_returns_empty_on_invalid_stem(self):
        week_label, pub_date = _parse_weekly_filename("weekly_bad")
        assert week_label == ""
        assert pub_date == ""


# ── _daily_item ───────────────────────────────────────────────────────────────

class TestDailyItem:
    def test_returns_rss_item_xml(self, tmp_path):
        p = tmp_path / "brief_20260519_1500.html"
        p.write_text("<html/>")
        result = _daily_item(p)
        assert "<item>" in result
        assert "2026-05-19" in result
        assert "Daily Brief" in result
        assert "flexrpl.github.io/signal/reports/" in result

    def test_returns_empty_on_unparseable_filename(self, tmp_path):
        p = tmp_path / "brief_bad.html"
        p.write_text("<html/>")
        assert _daily_item(p) == ""

    def test_contains_guid(self, tmp_path):
        p = tmp_path / "brief_20260519_1500.html"
        p.write_text("<html/>")
        result = _daily_item(p)
        assert "<guid" in result
        assert "isPermaLink" in result


# ── _weekly_item ──────────────────────────────────────────────────────────────

class TestWeeklyItem:
    def test_returns_rss_item_xml(self, tmp_path):
        p = tmp_path / "weekly_2026W21_20260525_1500.html"
        p.write_text("<html/>")
        result = _weekly_item(p)
        assert "<item>" in result
        assert "2026W21" in result
        assert "Weekly Brief" in result
        assert "flexrpl.github.io/signal/reports/" in result

    def test_returns_empty_on_unparseable_filename(self, tmp_path):
        p = tmp_path / "weekly_bad.html"
        p.write_text("<html/>")
        assert _weekly_item(p) == ""


# ── generate_feed ─────────────────────────────────────────────────────────────

class TestGenerateFeed:
    def _make_reports(self, tmp_path: Path, daily: int = 3, weekly: int = 1) -> Path:
        rdir = tmp_path / "reports"
        rdir.mkdir()
        for i in range(daily):
            day = f"1{i}"
            (rdir / f"brief_202605{day:0>2}_0500.html").write_text("<html/>")
        for i in range(weekly):
            (rdir / f"weekly_2026W2{i}_20260525_0600.html").write_text("<html/>")
        return rdir

    def test_creates_feed_xml(self, tmp_path):
        rdir = self._make_reports(tmp_path)
        fpath = tmp_path / "feed.xml"
        result = generate_feed(reports_dir=rdir, feed_path=fpath)
        assert result.exists()
        assert result.suffix == ".xml"

    def test_feed_is_valid_rss(self, tmp_path):
        rdir = self._make_reports(tmp_path)
        fpath = tmp_path / "feed.xml"
        generate_feed(reports_dir=rdir, feed_path=fpath)
        content = fpath.read_text()
        assert '<?xml version="1.0"' in content
        assert '<rss version="2.0"' in content
        assert "<channel>" in content
        assert "</channel>" in content
        assert "</rss>" in content

    def test_contains_daily_and_weekly_items(self, tmp_path):
        rdir = self._make_reports(tmp_path, daily=2, weekly=1)
        fpath = tmp_path / "feed.xml"
        generate_feed(reports_dir=rdir, feed_path=fpath)
        content = fpath.read_text()
        assert "Daily Brief" in content
        assert "Weekly Brief" in content

    def test_items_sorted_newest_first(self, tmp_path):
        rdir = tmp_path / "reports"
        rdir.mkdir()
        (rdir / "brief_20260519_0500.html").write_text("<html/>")
        (rdir / "brief_20260520_0500.html").write_text("<html/>")
        (rdir / "brief_20260521_0500.html").write_text("<html/>")
        fpath = tmp_path / "feed.xml"
        generate_feed(reports_dir=rdir, feed_path=fpath)
        content = fpath.read_text()
        pos_21 = content.find("2026-05-21")
        pos_19 = content.find("2026-05-19")
        assert pos_21 < pos_19

    def test_respects_max_items_cap(self, tmp_path):
        rdir = tmp_path / "reports"
        rdir.mkdir()
        for i in range(MAX_ITEMS + 10):
            day = i % 28 + 1
            month = "05" if i < 28 else "06"
            (rdir / f"brief_2026{month}{day:02d}_0500.html").write_text("<html/>")
        fpath = tmp_path / "feed.xml"
        generate_feed(reports_dir=rdir, feed_path=fpath)
        content = fpath.read_text()
        assert content.count("<item>") <= MAX_ITEMS

    def test_empty_reports_dir_generates_valid_feed(self, tmp_path):
        rdir = tmp_path / "reports"
        rdir.mkdir()
        fpath = tmp_path / "feed.xml"
        generate_feed(reports_dir=rdir, feed_path=fpath)
        content = fpath.read_text()
        assert "<channel>" in content
        assert "<item>" not in content

    def test_contains_atom_self_link(self, tmp_path):
        rdir = self._make_reports(tmp_path)
        fpath = tmp_path / "feed.xml"
        generate_feed(reports_dir=rdir, feed_path=fpath)
        content = fpath.read_text()
        assert 'rel="self"' in content
        assert "feed.xml" in content

    def test_html_entities_escaped_in_titles(self, tmp_path):
        rdir = tmp_path / "reports"
        rdir.mkdir()
        (rdir / "brief_20260519_0500.html").write_text("<html/>")
        fpath = tmp_path / "feed.xml"
        generate_feed(reports_dir=rdir, feed_path=fpath)
        content = fpath.read_text()
        assert "&amp;" not in content or "&#" not in content  # no double-escaping
        assert "<title>Signal" in content
