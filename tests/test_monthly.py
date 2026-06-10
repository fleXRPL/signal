"""
Tests for pipeline/monthly.py — Pass 7, monthly synthesis.

The LLM call (_llm_call) is mocked throughout. Database interactions
use the tmp_db fixture from conftest.py for isolation.
"""
from __future__ import annotations

import sqlite3
from unittest.mock import patch

import pytest

import pipeline.store as store
from pipeline.monthly import (
    _build_monthly_daily_data,
    _build_weekly_summaries,
    _month_bounds,
    _parse_month,
    run_monthly,
)


MOCK_MONTHLY_BRIEF = """## MONTH IN REVIEW
May was dominated by budget negotiations and immigration policy shifts.

## STORY ARC TRACKER
Budget bill: introduced mid-month, passed Senate by month end.

## WATCH LIST SCORECARD
Budget reconciliation — materialized. Immigration courts — still pending.

## COVERAGE PATTERN ANALYSIS
Left outlets emphasized budget; right outlets emphasized immigration.

## EMERGING ACTORS
Sen. Smith emerged as the central budget negotiator.

## WATCH LIST: NEXT MONTH
- Supreme Court term decisions
- Budget conference committee

## ANALYST NOTE
May showed an accelerating legislative agenda with uneven media attention."""


def _setup_run_on_date(tmp_db, date: str, article_count: int = 10) -> int:
    """Create a complete run backdated to a specific YYYY-MM-DD."""
    run_id = store.start_run()
    import pipeline.store as store_module

    conn = sqlite3.connect(str(store_module.DB_PATH))
    conn.execute(
        "UPDATE runs SET started_at=? WHERE id=?",
        (f"{date}T05:30:00+00:00", run_id),
    )
    conn.commit()
    conn.close()

    store.save_brief(
        run_id,
        "## SITUATION OVERVIEW\nTest overview.\n"
        "## WATCH LIST\n- Topic X\n## ANALYST NOTE\nTest note.",
    )
    store.save_correlation_analysis(
        run_id,
        {
            "narrative_patterns": ["Pattern A"],
            "anomalies": [],
            "recommended_watch": ["Topic X"],
            "delta_from_previous": "",
        },
    )
    store.finish_run(run_id, article_count, 2)
    return run_id


# ── _parse_month / _month_bounds ──────────────────────────────────────────────

class TestParseMonth:
    def test_valid_month(self):
        assert _parse_month("2026-05") == (2026, 5)

    def test_invalid_month_raises(self):
        with pytest.raises(ValueError, match="Invalid --month"):
            _parse_month("not-a-month")


class TestMonthBounds:
    def test_may_2026(self):
        label, start, end = _month_bounds(2026, 5)
        assert label == "May 2026"
        assert start == "2026-05-01"
        assert end == "2026-05-31"


# ── _build_weekly_summaries ───────────────────────────────────────────────────

class TestBuildWeeklySummaries:
    def test_empty_returns_fallback(self):
        assert "No weekly summaries" in _build_weekly_summaries([])

    def test_includes_week_range_and_sections(self):
        weeklies = [
            {
                "week_start": "2026-05-11",
                "week_end": "2026-05-17",
                "brief_text": (
                    "## WEEK IN REVIEW\nWeek content.\n"
                    "## WHAT ESCALATED\nEscalation here."
                ),
            }
        ]
        result = _build_weekly_summaries(weeklies)
        assert "2026-05-11" in result
        assert "WEEK IN REVIEW" in result
        assert "Week content." in result


# ── _build_monthly_daily_data ─────────────────────────────────────────────────

class TestBuildMonthlyDailyData:
    def test_includes_date_and_sections(self):
        runs = [
            {
                "started_at": "2026-05-11T05:30:00+00:00",
                "article_count": 42,
                "brief_text": (
                    "## SITUATION OVERVIEW\nOverview text.\n"
                    "## WATCH LIST\n- Item A\n## ANALYST NOTE\nNote text."
                ),
            }
        ]
        result = _build_monthly_daily_data(runs)
        assert "2026-05-11" in result
        assert "42" in result
        assert "Overview text." in result
        assert "Item A" in result


# ── run_monthly ───────────────────────────────────────────────────────────────

class TestRunMonthly:
    @patch("pipeline.monthly._llm_call")
    def test_returns_brief_and_metadata(self, mock_llm, tmp_db, sample_config):
        mock_llm.return_value = MOCK_MONTHLY_BRIEF
        _setup_run_on_date(tmp_db, "2026-05-11")
        _setup_run_on_date(tmp_db, "2026-05-12")

        brief_text, metadata = run_monthly(sample_config, month="2026-05")

        assert isinstance(brief_text, str)
        assert len(brief_text) > 0
        assert metadata["month"] == "2026-05"
        assert metadata["month_label"] == "May 2026"
        assert metadata["day_count"] == 2
        assert metadata["partial"] is True

    @patch("pipeline.monthly._llm_call")
    def test_persists_to_db(self, mock_llm, tmp_db, sample_config):
        mock_llm.return_value = MOCK_MONTHLY_BRIEF
        _setup_run_on_date(tmp_db, "2026-05-15")

        run_monthly(sample_config, month="2026-05")

        monthly_briefs = store.get_monthly_briefs()
        assert len(monthly_briefs) == 1
        assert monthly_briefs[0]["partial"] == 1

    @patch("pipeline.monthly._llm_call")
    def test_includes_weekly_briefs(self, mock_llm, tmp_db, sample_config):
        mock_llm.return_value = MOCK_MONTHLY_BRIEF
        run_id = _setup_run_on_date(tmp_db, "2026-05-15")
        store.save_weekly_brief(
            "2026-05-11",
            "2026-05-17",
            [run_id],
            "## WEEK IN REVIEW\nWeekly content.",
        )

        _, metadata = run_monthly(sample_config, month="2026-05")

        assert metadata["weekly_count"] == 1
        assert len(metadata["weekly_ids"]) == 1

    def test_raises_when_no_runs(self, tmp_db, sample_config):
        with pytest.raises(RuntimeError, match="No complete daily runs"):
            run_monthly(sample_config, month="2026-05")

    @patch("pipeline.monthly._llm_call")
    def test_raises_on_llm_failure(self, mock_llm, tmp_db, sample_config):
        mock_llm.side_effect = RuntimeError("Claude CLI unavailable")
        _setup_run_on_date(tmp_db, "2026-05-11")

        with pytest.raises(RuntimeError):
            run_monthly(sample_config, month="2026-05")
