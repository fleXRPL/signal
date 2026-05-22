"""
Tests for pipeline/reporter.py — HTML generation.

Reports are written to a tmp_path directory so the real reports/ folder
is never touched during tests.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from pipeline.reporter import (
    BIAS_COLORS,
    _md_to_html,
    _parse_brief_sections,
    _render_brief_sections,
    _render_list_items,
    _render_weekly_sections,
    ga_snippet,
    generate_report,
    generate_weekly_report,
)
from tests.conftest import make_article


# ── ga_snippet ────────────────────────────────────────────────────────────────

class TestGaSnippet:
    def test_empty_id_returns_empty_string(self):
        assert ga_snippet("") == ""

    def test_valid_id_returns_script_tags(self):
        result = ga_snippet("G-TEST12345")
        assert "googletagmanager.com" in result
        assert "G-TEST12345" in result
        assert "<script" in result

    def test_escapes_html_in_id(self):
        result = ga_snippet('<script>alert(1)</script>')
        assert "<script>alert(1)</script>" not in result


# ── _md_to_html ───────────────────────────────────────────────────────────────

class TestMdToHtml:
    def test_converts_h2_header(self):
        result = _md_to_html("## Section Title")
        assert "<h2>Section Title</h2>" in result

    def test_converts_h3_header(self):
        result = _md_to_html("### Sub-section")
        assert "<h3" in result
        assert "Sub-section" in result

    def test_converts_bullet_list(self):
        result = _md_to_html("- Item one\n- Item two")
        assert "<ul>" in result
        assert "<li>Item one</li>" in result
        assert "<li>Item two</li>" in result

    def test_converts_bold(self):
        result = _md_to_html("This is **important** text.")
        assert "<strong>important</strong>" in result

    def test_wraps_plain_text_in_paragraph(self):
        result = _md_to_html("Plain paragraph text.")
        assert "<p>Plain paragraph text.</p>" in result

    def test_closes_list_before_new_section(self):
        result = _md_to_html("- Item\n\n## New Section")
        assert "</ul>" in result
        assert "<h2>New Section</h2>" in result

    def test_empty_string(self):
        assert _md_to_html("") == ""

    def test_escapes_html_entities(self):
        result = _md_to_html("A & B > C")
        assert "&amp;" in result or "A &amp; B" in result


# ── _parse_brief_sections ─────────────────────────────────────────────────────

class TestParseBriefSections:
    def test_parses_named_sections(self):
        text = "## SITUATION OVERVIEW\nSome content here.\n\n## WATCH LIST\n- Topic A"
        sections = _parse_brief_sections(text)
        assert "SITUATION OVERVIEW" in sections
        assert "WATCH LIST" in sections
        assert "Some content here." in sections["SITUATION OVERVIEW"]

    def test_preamble_key_for_content_before_first_header(self):
        text = "Intro text here.\n## SECTION\nContent."
        sections = _parse_brief_sections(text)
        assert "preamble" in sections
        assert "Intro text here." in sections["preamble"]

    def test_no_sections_returns_preamble_only(self):
        text = "Just a body with no headers."
        sections = _parse_brief_sections(text)
        assert "preamble" in sections

    def test_empty_string(self):
        sections = _parse_brief_sections("")
        assert isinstance(sections, dict)


# ── _render_brief_sections ────────────────────────────────────────────────────

class TestRenderBriefSections:
    def test_renders_known_section(self, mock_brief_response):
        result = _render_brief_sections(mock_brief_response)
        assert "SITUATION OVERVIEW" in result or "Situation Overview" in result.replace("SITUATION OVERVIEW", "Situation Overview")
        assert isinstance(result, str)
        assert len(result) > 0

    def test_analyst_note_gets_special_treatment(self, mock_brief_response):
        result = _render_brief_sections(mock_brief_response)
        assert "analyst-note" in result

    def test_skips_empty_sections(self):
        brief = "## SITUATION OVERVIEW\n\n## WATCH LIST\n- Item A"
        result = _render_brief_sections(brief)
        # SITUATION OVERVIEW has no content so should be skipped
        assert "Item A" in result


# ── _render_list_items ────────────────────────────────────────────────────────

class TestRenderListItems:
    def test_renders_items_with_class(self):
        result = _render_list_items(["Item A", "Item B"], "watch-item")
        assert "watch-item" in result
        assert "Item A" in result
        assert "Item B" in result

    def test_empty_list_returns_something(self):
        result = _render_list_items([], "watch-item")
        assert isinstance(result, str)


# ── _render_weekly_sections ───────────────────────────────────────────────────

class TestRenderWeeklySections:
    def test_renders_week_in_review(self):
        brief = "## WEEK IN REVIEW\nThis was a significant week.\n## ANALYST NOTE\nAnalysis here."
        result = _render_weekly_sections(brief)
        assert "significant week" in result

    def test_handles_all_weekly_section_headers(self):
        brief = "\n".join([
            "## WEEK IN REVIEW\nContent A.",
            "## STORY ARC TRACKER\nContent B.",
            "## WHAT ESCALATED\nContent C.",
            "## WHAT WAS BURIED\nContent D.",
            "## BLINDSPOT OF THE WEEK\nContent E.",
            "## WATCH LIST: NEXT WEEK\n- Item F.",
            "## ANALYST NOTE\nContent G.",
        ])
        result = _render_weekly_sections(brief)
        assert "Content A." in result
        assert "Content G." in result


# ── generate_report ───────────────────────────────────────────────────────────

class TestGenerateReport:
    def test_creates_html_file(self, tmp_path, mock_brief_response, sample_articles):
        with patch("pipeline.reporter.REPORTS_DIR", tmp_path):
            path = generate_report(
                brief_text=mock_brief_response,
                clusters=[],
                correlation={
                    "hidden_connections": [],
                    "narrative_patterns": [],
                    "anomalies": [],
                    "blindspot_analysis": "",
                    "_left_only": [],
                    "_right_only": [],
                    "recommended_watch": ["Topic A"],
                },
                articles=sample_articles,
                run_id=1,
                model="qwen2.5:14b",
            )
        assert path.exists()
        assert path.suffix == ".html"

    def test_html_contains_article_count(self, tmp_path, mock_brief_response, sample_articles):
        with patch("pipeline.reporter.REPORTS_DIR", tmp_path):
            path = generate_report(
                brief_text=mock_brief_response,
                clusters=[],
                correlation={
                    "hidden_connections": [], "narrative_patterns": [],
                    "anomalies": [], "blindspot_analysis": "",
                    "_left_only": [], "_right_only": [], "recommended_watch": [],
                },
                articles=sample_articles,
                run_id=1,
                model="qwen2.5:14b",
            )
        content = path.read_text()
        assert str(len(sample_articles)) in content

    def test_injects_ga_snippet_when_id_provided(self, tmp_path, mock_brief_response, sample_articles):
        with patch("pipeline.reporter.REPORTS_DIR", tmp_path):
            path = generate_report(
                brief_text=mock_brief_response,
                clusters=[],
                correlation={
                    "hidden_connections": [], "narrative_patterns": [],
                    "anomalies": [], "blindspot_analysis": "",
                    "_left_only": [], "_right_only": [], "recommended_watch": [],
                },
                articles=sample_articles,
                run_id=1,
                model="qwen2.5:14b",
                ga_measurement_id="G-TEST123",
            )
        assert "G-TEST123" in path.read_text()

    def test_no_ga_snippet_when_id_empty(self, tmp_path, mock_brief_response, sample_articles):
        with patch("pipeline.reporter.REPORTS_DIR", tmp_path):
            path = generate_report(
                brief_text=mock_brief_response,
                clusters=[],
                correlation={
                    "hidden_connections": [], "narrative_patterns": [],
                    "anomalies": [], "blindspot_analysis": "",
                    "_left_only": [], "_right_only": [], "recommended_watch": [],
                },
                articles=sample_articles,
                run_id=1,
                model="qwen2.5:14b",
                ga_measurement_id="",
            )
        assert "googletagmanager" not in path.read_text()

    def test_filename_format(self, tmp_path, mock_brief_response):
        with patch("pipeline.reporter.REPORTS_DIR", tmp_path):
            path = generate_report(
                brief_text=mock_brief_response,
                clusters=[],
                correlation={
                    "hidden_connections": [], "narrative_patterns": [],
                    "anomalies": [], "blindspot_analysis": "",
                    "_left_only": [], "_right_only": [], "recommended_watch": [],
                },
                articles=[],
                run_id=1,
                model="test",
            )
        assert path.name.startswith("brief_")
        assert path.name.endswith(".html")


# ── generate_weekly_report ────────────────────────────────────────────────────

class TestGenerateWeeklyReport:
    def _metadata(self) -> dict:
        return {
            "week_start": "2026-05-11",
            "week_end": "2026-05-17",
            "day_count": 7,
            "run_ids": [1, 2, 3],
            "generated_at": "2026-05-18T23:00:00+00:00",
        }

    def test_creates_html_file(self, tmp_path, tmp_db, mock_brief_response):
        with patch("pipeline.reporter.REPORTS_DIR", tmp_path):
            path = generate_weekly_report(
                brief_text=mock_brief_response,
                metadata=self._metadata(),
            )
        assert path.exists()
        assert path.suffix == ".html"

    def test_filename_includes_iso_week(self, tmp_path, tmp_db, mock_brief_response):
        with patch("pipeline.reporter.REPORTS_DIR", tmp_path):
            path = generate_weekly_report(
                brief_text=mock_brief_response,
                metadata=self._metadata(),
            )
        # 2026-05-11 is ISO week 20
        assert "2026W20" in path.name

    def test_ga_snippet_injected(self, tmp_path, tmp_db, mock_brief_response):
        with patch("pipeline.reporter.REPORTS_DIR", tmp_path):
            path = generate_weekly_report(
                brief_text=mock_brief_response,
                metadata=self._metadata(),
                ga_measurement_id="G-WEEKLY123",
            )
        assert "G-WEEKLY123" in path.read_text()

    def test_weekly_html_has_dark_theme(self, tmp_path, tmp_db, mock_brief_response):
        with patch("pipeline.reporter.REPORTS_DIR", tmp_path):
            path = generate_weekly_report(
                brief_text=mock_brief_response,
                metadata=self._metadata(),
            )
        content = path.read_text()
        assert "#0d1117" in content or "0d1117" in content


# ── BIAS_COLORS ───────────────────────────────────────────────────────────────

class TestBiasColors:
    def test_all_standard_biases_present(self):
        for bias in ("far-left", "left", "center-left", "center", "center-right", "right", "far-right"):
            assert bias in BIAS_COLORS, f"Missing bias: {bias}"

    def test_unknown_bias_present(self):
        assert "unknown" in BIAS_COLORS
