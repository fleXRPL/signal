"""
Tests for pipeline/store.py — SQLite persistence layer.

All tests use the tmp_db fixture from conftest.py which patches DB_PATH
to a temporary file, ensuring full isolation from signal.db.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

import pipeline.store as store
from tests.conftest import make_article


# ── Schema / init ─────────────────────────────────────────────────────────────

class TestInitDb:
    def test_tables_created(self, tmp_db):
        """All expected tables exist after init_db()."""
        conn = store.get_connection()
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        conn.close()
        expected = {"runs", "articles", "clusters", "cluster_analyses", "correlation_analyses", "briefs", "weekly_briefs"}
        assert expected.issubset(tables)

    def test_idempotent(self, tmp_db):
        """Calling init_db() twice does not raise."""
        store.init_db()


# ── Runs ─────────────────────────────────────────────────────────────────────

class TestRuns:
    def test_start_run_returns_id(self, tmp_db):
        run_id = store.start_run()
        assert isinstance(run_id, int)
        assert run_id >= 1

    def test_start_multiple_runs_unique_ids(self, tmp_db):
        ids = [store.start_run() for _ in range(3)]
        assert len(set(ids)) == 3

    def test_finish_run(self, tmp_db):
        run_id = store.start_run()
        store.finish_run(run_id, article_count=15, cluster_count=4)

        conn = store.get_connection()
        row = conn.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
        conn.close()

        assert row["status"] == "complete"
        assert row["article_count"] == 15
        assert row["cluster_count"] == 4
        assert row["finished_at"] is not None

    def test_get_last_completed_run_none_when_empty(self, tmp_db):
        assert store.get_last_completed_run() is None

    def test_get_last_completed_run_returns_most_recent(self, tmp_db):
        r1 = store.start_run()
        store.finish_run(r1, 10, 2)
        r2 = store.start_run()
        store.finish_run(r2, 20, 5)

        result = store.get_last_completed_run()
        assert result["id"] == r2

    def test_running_run_not_returned_by_get_last_completed(self, tmp_db):
        store.start_run()  # left as 'running'
        result = store.get_last_completed_run()
        assert result is None


# ── Articles ─────────────────────────────────────────────────────────────────

class TestArticles:
    def test_save_articles_returns_ids(self, tmp_db, sample_articles):
        run_id = store.start_run()
        ids = store.save_articles(run_id, sample_articles)
        assert len(ids) == len(sample_articles)
        assert all(isinstance(i, int) for i in ids)

    def test_save_articles_stores_fields(self, tmp_db, sample_article):
        run_id = store.start_run()
        (db_id,) = store.save_articles(run_id, [sample_article])

        conn = store.get_connection()
        row = conn.execute("SELECT * FROM articles WHERE id=?", (db_id,)).fetchone()
        conn.close()

        assert row["title"] == sample_article["title"]
        assert row["url"] == sample_article["url"]
        assert row["source_name"] == sample_article["source_name"]
        assert row["bias"] == sample_article["bias"]

    def test_update_article_analysis(self, tmp_db, sample_article):
        run_id = store.start_run()
        (db_id,) = store.save_articles(run_id, [sample_article])

        entities = {"people": ["A"], "organizations": [], "legislation": [], "locations": []}
        store.update_article_analysis(db_id, entities, "Key claim.", "policy", "negative", "alarming")

        conn = store.get_connection()
        row = conn.execute("SELECT * FROM articles WHERE id=?", (db_id,)).fetchone()
        conn.close()

        assert json.loads(row["entities_json"]) == entities
        assert row["key_claim"] == "Key claim."
        assert row["topic"] == "policy"
        assert row["sentiment"] == "negative"
        assert row["framing"] == "alarming"

    def test_get_articles_for_run(self, tmp_db, sample_articles):
        run_id = store.start_run()
        store.save_articles(run_id, sample_articles)

        results = store.get_articles_for_run(run_id)
        assert len(results) == len(sample_articles)

    def test_get_articles_for_run_isolated_by_run_id(self, tmp_db, sample_articles):
        r1 = store.start_run()
        store.save_articles(r1, sample_articles[:1])
        r2 = store.start_run()
        store.save_articles(r2, sample_articles[1:])

        assert len(store.get_articles_for_run(r1)) == 1
        assert len(store.get_articles_for_run(r2)) == len(sample_articles) - 1


# ── Clusters ─────────────────────────────────────────────────────────────────

class TestClusters:
    def test_save_cluster_returns_id(self, tmp_db):
        run_id = store.start_run()
        cluster_id = store.save_cluster(run_id, "Budget Bill Story", [1, 2], {"left": 1, "right": 1})
        assert isinstance(cluster_id, int)

    def test_save_cluster_analysis(self, tmp_db):
        run_id = store.start_run()
        cluster_id = store.save_cluster(run_id, "Budget", [1], {"left": 1})
        analysis = {"headline": "Budget passes", "significance": "high"}
        store.save_cluster_analysis(run_id, cluster_id, analysis)

        conn = store.get_connection()
        row = conn.execute(
            "SELECT analysis_json FROM cluster_analyses WHERE cluster_id=?", (cluster_id,)
        ).fetchone()
        conn.close()

        assert json.loads(row["analysis_json"]) == analysis


# ── Correlation ───────────────────────────────────────────────────────────────

class TestCorrelation:
    def test_save_and_retrieve_correlation(self, tmp_db):
        r1 = store.start_run()
        analysis = {"narrative_patterns": ["Pattern A"], "recommended_watch": ["Topic X"]}
        store.save_correlation_analysis(r1, analysis)

        r2 = store.start_run()
        prev = store.get_previous_correlation(r2)
        assert prev == analysis

    def test_get_previous_correlation_returns_none_for_first_run(self, tmp_db):
        run_id = store.start_run()
        assert store.get_previous_correlation(run_id) is None

    def test_get_previous_watch_list(self, tmp_db):
        r1 = store.start_run()
        store.save_correlation_analysis(r1, {"recommended_watch": ["Watch A", "Watch B"]})
        r2 = store.start_run()
        watch = store.get_previous_watch_list(r2)
        assert watch == ["Watch A", "Watch B"]

    def test_get_previous_watch_list_empty_when_no_prior(self, tmp_db):
        run_id = store.start_run()
        assert store.get_previous_watch_list(run_id) == []


# ── Briefs ────────────────────────────────────────────────────────────────────

class TestBriefs:
    def test_save_brief(self, tmp_db):
        run_id = store.start_run()
        store.save_brief(run_id, "This is the final brief text.")

        conn = store.get_connection()
        row = conn.execute("SELECT brief_text FROM briefs WHERE run_id=?", (run_id,)).fetchone()
        conn.close()

        assert row["brief_text"] == "This is the final brief text."


# ── Weekly briefs ─────────────────────────────────────────────────────────────

class TestWeeklyBriefs:
    def test_save_weekly_brief_returns_id(self, tmp_db):
        weekly_id = store.save_weekly_brief(
            week_start="2026-05-11",
            week_end="2026-05-17",
            run_ids=[1, 2, 3],
            brief_text="Weekly summary text.",
        )
        assert isinstance(weekly_id, int)

    def test_get_weekly_briefs_empty(self, tmp_db):
        assert store.get_weekly_briefs() == []

    def test_get_weekly_briefs_reverse_order(self, tmp_db):
        store.save_weekly_brief("2026-05-04", "2026-05-10", [1], "Week 19 summary.")
        store.save_weekly_brief("2026-05-11", "2026-05-17", [2, 3], "Week 20 summary.")

        briefs = store.get_weekly_briefs()
        assert len(briefs) == 2
        assert briefs[0]["week_start"] == "2026-05-11"
        assert briefs[1]["week_start"] == "2026-05-04"

    def test_get_weekly_source_data_empty_run_ids(self, tmp_db):
        result = store.get_weekly_source_data([])
        assert result == []

    def test_get_weekly_source_data_with_data(self, tmp_db, sample_article):
        run_id = store.start_run()
        store.save_articles(run_id, [sample_article])
        store.save_brief(run_id, "Day brief text.")
        store.save_correlation_analysis(run_id, {
            "narrative_patterns": ["Pattern A"],
            "anomalies": [],
            "recommended_watch": ["Topic X"],
            "delta_from_previous": "New: Topic X",
        })
        store.finish_run(run_id, 1, 0)

        result = store.get_weekly_source_data([run_id])
        assert len(result) == 1
        assert result[0]["brief_text"] == "Day brief text."
        assert result[0]["watch_list"] == ["Topic X"]
        assert result[0]["narrative_patterns"] == ["Pattern A"]

    def test_get_runs_for_weekly_excludes_running(self, tmp_db, sample_article):
        run_id = store.start_run()
        store.save_articles(run_id, [sample_article])
        # Not finished — should be excluded

        result = store.get_runs_for_weekly(days=7)
        assert result == []
