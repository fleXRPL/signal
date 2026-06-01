"""
Tests for pipeline/infographic.py — social card HTML rendering and PNG export.

Playwright is mocked; card output goes to tmp_path.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

import pipeline.infographic as infographic


@pytest.fixture
def cards_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    cards = tmp_path / "cards"
    cards.mkdir()
    monkeypatch.setattr(infographic, "CARDS_DIR", cards)
    return cards


@pytest.fixture
def brief_data() -> dict:
    return {
        "date": "2026-06-01",
        "article_count": 85,
        "source_count": 11,
        "cluster_count": 8,
        "report_url": "https://flexrpl.github.io/signal/reports/brief_20260601_1309.html",
        "watch_items": [
            {"window": "24hr", "text": "Patel / FBI child rescue narrative"},
            {"window": "48hr", "text": "Kennedy Center compliance signal"},
            {"window": "72hr", "text": "Bondi testimony break"},
        ],
        "top_cluster": {
            "headline": "Federal judge orders Trump's name removed from Kennedy Center",
            "bias_spread": {"far-left": 4, "left": 5, "center-left": 10, "center": 5, "right": 6},
            "article_count": 40,
            "left_framing": "Legal check on executive overreach.",
            "center_framing": "Procedural legal development.",
            "right_framing": "Political framing of judge appointment.",
            "left_omissions": "Operational justification omitted.",
            "right_omissions": "Statutory argument omitted.",
        },
        "blindspot_narrative": "Bondi accountability story suppressed on the right.",
        "left_only": ["Bondi refuses questions under oath", "ICE agent arrested"],
        "right_only": ["Kash Patel: FBI rescues 87 children", "Cubans wish Rubio happy birthday"],
    }


@pytest.fixture
def mock_screenshot(tmp_path: Path):
    """Replace Playwright screenshot with writing a stub PNG file."""

    def _fake_screenshot(html_content: str, output_path: Path) -> Path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(b"\x89PNG\r\n\x1a\n")
        return output_path

    with patch.object(infographic, "_screenshot", side_effect=_fake_screenshot):
        yield


class TestSpectrumSegments:
    def test_builds_ordered_segments(self):
        spread = {"left": 2, "center": 1, "right": 3}
        segments = infographic._spectrum_segments(spread)
        slugs = [s[0] for s in segments]
        assert slugs == ["l", "c", "r"]
        assert sum(s[1] for s in segments) == pytest.approx(100.0, abs=0.2)

    def test_defaults_to_center_when_empty(self):
        assert infographic._spectrum_segments({}) == [("c", 100.0)]


class TestWindowSummary:
    def test_range_across_windows(self, brief_data):
        summary = infographic._window_summary(brief_data["watch_items"])
        assert "24 hours" in summary
        assert "72 hours" in summary

    def test_single_5d_only_uses_default_shortest(self):
        items = [{"window": "5d", "text": "Cuba policy"}]
        assert infographic._window_summary(items) == "72 hours to 5 days"

    def test_empty_watch_items_uses_default_bounds(self):
        assert infographic._window_summary([]) == "72 hours to 48 hours"


class TestBlindspotHeadline:
    def test_empty_narrative(self):
        assert "Coverage gaps" in infographic._blindspot_headline("")

    def test_first_sentence_truncated(self):
        narrative = "First sentence here. Second sentence ignored."
        assert infographic._blindspot_headline(narrative) == "First sentence here"

    def test_long_sentence_capped_at_160(self):
        narrative = "A" * 200 + ". More text."
        assert len(infographic._blindspot_headline(narrative)) == 160


class TestRenderHtml:
    def test_watch_template_renders(self, brief_data):
        html = infographic._render_html("card_watch.html", {
            "date": brief_data["date"],
            "watch_items": brief_data["watch_items"][:2],
            "watch_count": 2,
            "window_summary": "24 hours to 48 hours",
        })
        assert "Signal" in html
        assert "Watch List" in html
        assert "Patel" in html


class TestRenderCards:
    def test_render_watch_card(self, cards_dir, brief_data, mock_screenshot):
        out = infographic.render_watch_card(brief_data, "20260601")
        assert out == cards_dir / "am_20260601.png"
        assert out.exists()

    def test_render_spectrum_card(self, cards_dir, brief_data, mock_screenshot):
        out = infographic.render_spectrum_card(brief_data, "20260601")
        assert out == cards_dir / "noon_20260601.png"
        assert out.exists()

    def test_render_blindspot_card(self, cards_dir, brief_data, mock_screenshot):
        out = infographic.render_blindspot_card(brief_data, "20260601")
        assert out == cards_dir / "pm_20260601.png"
        assert out.exists()

    def test_render_all_cards(self, cards_dir, brief_data, mock_screenshot):
        stubs = {
            "am": cards_dir / "am_20260601.png",
            "noon": cards_dir / "noon_20260601.png",
            "pm": cards_dir / "pm_20260601.png",
        }
        for path in stubs.values():
            path.write_bytes(b"\x89PNG\r\n\x1a\n")

        with patch.object(
            infographic, "render_watch_card", return_value=stubs["am"]
        ), patch.object(
            infographic, "render_spectrum_card", return_value=stubs["noon"]
        ), patch.object(
            infographic, "render_blindspot_card", return_value=stubs["pm"]
        ):
            paths = infographic.render_all_cards(brief_data)
        assert set(paths.keys()) == {"am", "noon", "pm"}
        for path in paths.values():
            assert path.exists()


class TestScreenshotPlaywright:
    def test_screenshot_invokes_playwright(self, tmp_path: Path):
        out = tmp_path / "out.png"
        html = "<html><body>Signal</body></html>"

        mock_page = MagicMock()
        mock_browser = MagicMock()
        mock_browser.new_page.return_value = mock_page
        mock_pw = MagicMock()
        mock_pw.chromium.launch.return_value = mock_browser
        mock_ctx = MagicMock()
        mock_ctx.__enter__ = MagicMock(return_value=mock_pw)
        mock_ctx.__exit__ = MagicMock(return_value=False)

        with patch("playwright.sync_api.sync_playwright", return_value=mock_ctx):
            infographic._screenshot(html, out)

        mock_page.screenshot.assert_called_once()
        mock_browser.close.assert_called_once()
