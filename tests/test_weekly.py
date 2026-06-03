"""
Tests for pipeline/weekly.py — Pass 6, weekly synthesis.

The LLM call (_llm_call) is mocked throughout. Database interactions
use the tmp_db fixture from conftest.py for isolation.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

from pipeline.weekly import (
    _build_daily_data,
    _build_watch_list_evolution,
    _extract_section,
    _llm_call_claude,
    run_weekly,
)
import pipeline.store as store


# ── _extract_section ──────────────────────────────────────────────────────────

class TestExtractSection:
    def test_extracts_named_section(self):
        brief = "## SITUATION OVERVIEW\nContent here.\n## WATCH LIST\n- Item A"
        result = _extract_section(brief, "SITUATION OVERVIEW")
        assert result == "Content here."

    def test_extracts_last_section(self):
        brief = "## WATCH LIST\n- Item A\n- Item B"
        result = _extract_section(brief, "WATCH LIST")
        assert "Item A" in result
        assert "Item B" in result

    def test_returns_empty_string_for_missing_section(self):
        brief = "## SITUATION OVERVIEW\nContent here."
        result = _extract_section(brief, "ANALYST NOTE")
        assert result == ""

    def test_case_insensitive(self):
        brief = "## situation overview\nContent."
        result = _extract_section(brief, "SITUATION OVERVIEW")
        assert result == "Content."

    def test_does_not_bleed_into_next_section(self):
        brief = "## SECTION A\nA content.\n## SECTION B\nB content."
        result = _extract_section(brief, "SECTION A")
        assert "B content" not in result
        assert "A content." in result


# ── _llm_call_claude ──────────────────────────────────────────────────────────

class TestLlmCallClaude:
    @patch("pipeline.weekly.subprocess.run")
    def test_returns_stdout_on_success(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout="Weekly brief text", stderr="")
        assert _llm_call_claude("prompt", timeout=60) == "Weekly brief text"

    @patch("pipeline.weekly.subprocess.run")
    def test_retries_stream_idle_timeout(self, mock_run):
        mock_run.side_effect = [
            MagicMock(
                returncode=1,
                stdout="",
                stderr="API Error: Stream idle timeout - partial response received",
            ),
            MagicMock(returncode=0, stdout="Recovered brief", stderr=""),
        ]
        assert _llm_call_claude("prompt", timeout=60) == "Recovered brief"
        assert mock_run.call_count == 2

    @patch("pipeline.weekly.subprocess.run")
    def test_raises_other_errors_without_retry(self, mock_run):
        mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="auth failed")
        with pytest.raises(RuntimeError, match="auth failed"):
            _llm_call_claude("prompt", timeout=60)
        assert mock_run.call_count == 1


# ── _build_daily_data ─────────────────────────────────────────────────────────

class TestBuildDailyData:
    def _make_run(
        self,
        date: str = "2026-05-11",
        article_count: int = 25,
        brief_text: str = "## SITUATION OVERVIEW\nOverview here.\n## ANALYST NOTE\nNote here.",
        patterns: list | None = None,
        anomalies: list | None = None,
        watch_list: list | None = None,
    ) -> dict:
        return {
            "run_id": 1,
            "started_at": f"{date}T05:30:00+00:00",
            "article_count": article_count,
            "brief_text": brief_text,
            "narrative_patterns": patterns or [],
            "anomalies": anomalies or [],
            "watch_list": watch_list or [],
            "delta": "",
        }

    def test_includes_date(self):
        run = self._make_run(date="2026-05-11")
        result = _build_daily_data([run])
        assert "2026-05-11" in result

    def test_includes_article_count(self):
        run = self._make_run(article_count=42)
        result = _build_daily_data([run])
        assert "42" in result

    def test_includes_situation_overview(self):
        run = self._make_run(brief_text="## SITUATION OVERVIEW\nImportant overview content.")
        result = _build_daily_data([run])
        assert "Important overview content." in result

    def test_includes_narrative_patterns(self):
        run = self._make_run(patterns=["Pattern Alpha", "Pattern Beta"])
        result = _build_daily_data([run])
        assert "Pattern Alpha" in result

    def test_includes_anomalies(self):
        run = self._make_run(anomalies=["Anomaly X"])
        result = _build_daily_data([run])
        assert "Anomaly X" in result

    def test_multiple_runs_separated(self):
        runs = [
            self._make_run(date="2026-05-11"),
            self._make_run(date="2026-05-12"),
        ]
        result = _build_daily_data(runs)
        assert "2026-05-11" in result
        assert "2026-05-12" in result

    def test_empty_runs_returns_empty_string(self):
        result = _build_daily_data([])
        assert result == ""


# ── _build_watch_list_evolution ───────────────────────────────────────────────

class TestBuildWatchListEvolution:
    def _make_run(self, date: str, watch_list: list, delta: str = "") -> dict:
        return {
            "started_at": f"{date}T05:30:00+00:00",
            "watch_list": watch_list,
            "delta": delta,
        }

    def test_includes_dates_and_items(self):
        runs = [
            self._make_run("2026-05-11", ["Topic A", "Topic B"]),
            self._make_run("2026-05-12", ["Topic B", "Topic C"]),
        ]
        result = _build_watch_list_evolution(runs)
        assert "2026-05-11" in result
        assert "Topic A" in result
        assert "Topic C" in result

    def test_includes_delta_text(self):
        run = self._make_run("2026-05-11", ["Topic A"], delta="New: Topic B emerged.")
        result = _build_watch_list_evolution([run])
        assert "New: Topic B emerged." in result

    def test_skips_na_delta(self):
        run = self._make_run("2026-05-11", ["Topic A"], delta="N/A")
        result = _build_watch_list_evolution([run])
        assert "N/A" not in result

    def test_empty_runs_returns_fallback_message(self):
        result = _build_watch_list_evolution([])
        assert "Insufficient" in result

    def test_no_watch_items_skips_line(self):
        run = self._make_run("2026-05-11", [])
        result = _build_watch_list_evolution([run])
        # No items, no line for this date
        assert "2026-05-11" not in result


# ── run_weekly ────────────────────────────────────────────────────────────────

def _setup_complete_run(tmp_db, date_offset_days: int = 0) -> int:
    """Create a complete run with brief and correlation analysis in the test DB."""
    run_id = store.start_run()

    # Manually backdate the started_at to ensure it falls within the weekly window
    from datetime import datetime, timezone, timedelta
    import sqlite3
    import pipeline.store as store_module
    backdate = (datetime.now(timezone.utc) - timedelta(days=date_offset_days)).isoformat()
    conn = sqlite3.connect(str(store_module.DB_PATH))
    conn.execute("UPDATE runs SET started_at=? WHERE id=?", (backdate, run_id))
    conn.commit()
    conn.close()

    store.save_brief(run_id, "## SITUATION OVERVIEW\nTest overview.\n## ANALYST NOTE\nTest note.")
    store.save_correlation_analysis(run_id, {
        "narrative_patterns": ["Pattern A"],
        "anomalies": [],
        "recommended_watch": ["Topic X"],
        "delta_from_previous": "",
    })
    store.finish_run(run_id, 10, 2)
    return run_id


class TestRunWeekly:
    @patch("pipeline.weekly._llm_call")
    def test_returns_brief_and_metadata(self, mock_llm, tmp_db, sample_config, mock_brief_response):
        mock_llm.return_value = mock_brief_response
        _setup_complete_run(tmp_db, date_offset_days=1)

        brief_text, metadata = run_weekly(sample_config, days=7)

        assert isinstance(brief_text, str)
        assert len(brief_text) > 0
        assert "week_start" in metadata
        assert "week_end" in metadata
        assert "run_ids" in metadata
        assert metadata["day_count"] >= 1

    @patch("pipeline.weekly._llm_call")
    def test_persists_to_db(self, mock_llm, tmp_db, sample_config, mock_brief_response):
        mock_llm.return_value = mock_brief_response
        _setup_complete_run(tmp_db, date_offset_days=1)

        run_weekly(sample_config, days=7)

        weekly_briefs = store.get_weekly_briefs()
        assert len(weekly_briefs) == 1

    def test_raises_when_no_runs(self, tmp_db, sample_config):
        """Should raise RuntimeError if there are no qualifying runs in the window."""
        with pytest.raises(RuntimeError, match="No complete runs"):
            run_weekly(sample_config, days=7)

    @patch("pipeline.weekly._llm_call")
    def test_raises_on_llm_failure(self, mock_llm, tmp_db, sample_config):
        mock_llm.side_effect = RuntimeError("Claude CLI unavailable")
        _setup_complete_run(tmp_db, date_offset_days=1)

        with pytest.raises(RuntimeError):
            run_weekly(sample_config, days=7)

    @patch("pipeline.weekly._llm_call")
    def test_metadata_includes_iso_week_data(self, mock_llm, tmp_db, sample_config, mock_brief_response):
        mock_llm.return_value = mock_brief_response
        _setup_complete_run(tmp_db, date_offset_days=1)

        _, metadata = run_weekly(sample_config, days=7)

        assert "week_start" in metadata
        assert "week_end" in metadata
        # week_start should be a valid date string
        from datetime import datetime
        datetime.strptime(metadata["week_start"], "%Y-%m-%d")

    @patch("pipeline.weekly._llm_call")
    def test_multiple_runs_included(self, mock_llm, tmp_db, sample_config, mock_brief_response):
        mock_llm.return_value = mock_brief_response
        _setup_complete_run(tmp_db, date_offset_days=1)
        _setup_complete_run(tmp_db, date_offset_days=2)
        _setup_complete_run(tmp_db, date_offset_days=3)

        _, metadata = run_weekly(sample_config, days=7)
        assert metadata["day_count"] >= 3
