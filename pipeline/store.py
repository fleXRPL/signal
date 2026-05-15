#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SQLite persistence layer for Signal.

Stores articles, analysis runs, clusters, and briefs so that
delta detection works across multiple runs over time.
"""

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional


DB_PATH = Path(__file__).parent.parent / "signal.db"


def get_connection() -> sqlite3.Connection:
    """Return a configured SQLite connection."""
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db() -> None:
    """Create schema if it doesn't exist."""
    conn = get_connection()
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS runs (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            started_at  TEXT NOT NULL,
            finished_at TEXT,
            article_count INTEGER DEFAULT 0,
            cluster_count INTEGER DEFAULT 0,
            status      TEXT DEFAULT 'running'
        );

        CREATE TABLE IF NOT EXISTS articles (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id       INTEGER NOT NULL REFERENCES runs(id),
            title        TEXT NOT NULL,
            url          TEXT NOT NULL,
            source_name  TEXT NOT NULL,
            bias         TEXT NOT NULL,
            published_at TEXT,
            collected_at TEXT NOT NULL,
            text_snippet TEXT,
            full_text    TEXT,
            entities_json TEXT,
            key_claim    TEXT,
            topic        TEXT,
            sentiment    TEXT,
            framing      TEXT
        );

        CREATE TABLE IF NOT EXISTS clusters (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id       INTEGER NOT NULL REFERENCES runs(id),
            story_title  TEXT NOT NULL,
            article_ids  TEXT NOT NULL,
            source_count INTEGER DEFAULT 0,
            bias_spread  TEXT
        );

        CREATE TABLE IF NOT EXISTS cluster_analyses (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            cluster_id      INTEGER NOT NULL REFERENCES clusters(id),
            run_id          INTEGER NOT NULL REFERENCES runs(id),
            analysis_json   TEXT NOT NULL,
            created_at      TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS correlation_analyses (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id        INTEGER NOT NULL REFERENCES runs(id),
            analysis_json TEXT NOT NULL,
            created_at    TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS briefs (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id     INTEGER NOT NULL REFERENCES runs(id),
            brief_text TEXT NOT NULL,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS weekly_briefs (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            week_start  TEXT NOT NULL,
            week_end    TEXT NOT NULL,
            run_ids     TEXT NOT NULL,
            brief_text  TEXT NOT NULL,
            created_at  TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_articles_run ON articles(run_id);
        CREATE INDEX IF NOT EXISTS idx_clusters_run ON clusters(run_id);
        CREATE INDEX IF NOT EXISTS idx_articles_url  ON articles(url);
        """
    )
    conn.commit()
    conn.close()


def now_utc() -> str:
    """Return current UTC time as ISO string."""
    return datetime.now(timezone.utc).isoformat()


# ── Runs ─────────────────────────────────────────────────────────────────────

def start_run() -> int:
    """Create a new run record and return its id."""
    conn = get_connection()
    cur = conn.execute(
        "INSERT INTO runs (started_at, status) VALUES (?, 'running')",
        (now_utc(),),
    )
    run_id = cur.lastrowid
    conn.commit()
    conn.close()
    return run_id


def finish_run(run_id: int, article_count: int, cluster_count: int) -> None:
    """Mark run as finished."""
    conn = get_connection()
    conn.execute(
        """UPDATE runs
           SET finished_at=?, article_count=?, cluster_count=?, status='complete'
           WHERE id=?""",
        (now_utc(), article_count, cluster_count, run_id),
    )
    conn.commit()
    conn.close()


def get_last_completed_run() -> Optional[Dict[str, Any]]:
    """Return the most recent completed run, or None."""
    conn = get_connection()
    row = conn.execute(
        "SELECT * FROM runs WHERE status='complete' ORDER BY id DESC LIMIT 1"
    ).fetchone()
    conn.close()
    return dict(row) if row else None


# ── Articles ─────────────────────────────────────────────────────────────────

def save_articles(run_id: int, articles: List[Dict[str, Any]]) -> List[int]:
    """Bulk insert articles; returns list of inserted ids."""
    conn = get_connection()
    ids = []
    for a in articles:
        cur = conn.execute(
            """INSERT INTO articles
               (run_id, title, url, source_name, bias, published_at,
                collected_at, text_snippet, full_text)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (
                run_id,
                a.get("title", ""),
                a.get("url", ""),
                a.get("source_name", ""),
                a.get("bias", "unknown"),
                a.get("published_at"),
                now_utc(),
                a.get("text_snippet", ""),
                a.get("full_text", ""),
            ),
        )
        ids.append(cur.lastrowid)
    conn.commit()
    conn.close()
    return ids


def update_article_analysis(
    article_id: int,
    entities: Dict[str, Any],
    key_claim: str,
    topic: str,
    sentiment: str,
    framing: str,
) -> None:
    """Update an article with LLM-extracted fields."""
    conn = get_connection()
    conn.execute(
        """UPDATE articles
           SET entities_json=?, key_claim=?, topic=?, sentiment=?, framing=?
           WHERE id=?""",
        (json.dumps(entities), key_claim, topic, sentiment, framing, article_id),
    )
    conn.commit()
    conn.close()


def get_articles_for_run(run_id: int) -> List[Dict[str, Any]]:
    """Return all articles for a run."""
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM articles WHERE run_id=?", (run_id,)
    ).fetchall()
    conn.close()
    result = []
    for row in rows:
        d = dict(row)
        if d.get("entities_json"):
            try:
                d["entities"] = json.loads(d["entities_json"])
            except json.JSONDecodeError:
                d["entities"] = {}
        else:
            d["entities"] = {}
        result.append(d)
    return result


# ── Clusters ─────────────────────────────────────────────────────────────────

def save_cluster(
    run_id: int,
    story_title: str,
    article_ids: List[int],
    bias_spread: Dict[str, int],
) -> int:
    """Save a story cluster; returns cluster id."""
    conn = get_connection()
    cur = conn.execute(
        """INSERT INTO clusters
           (run_id, story_title, article_ids, source_count, bias_spread)
           VALUES (?,?,?,?,?)""",
        (
            run_id,
            story_title,
            json.dumps(article_ids),
            len(article_ids),
            json.dumps(bias_spread),
        ),
    )
    cluster_id = cur.lastrowid
    conn.commit()
    conn.close()
    return cluster_id


def save_cluster_analysis(
    run_id: int, cluster_id: int, analysis: Dict[str, Any]
) -> None:
    """Save analysis for a cluster."""
    conn = get_connection()
    conn.execute(
        """INSERT INTO cluster_analyses
           (cluster_id, run_id, analysis_json, created_at)
           VALUES (?,?,?,?)""",
        (cluster_id, run_id, json.dumps(analysis), now_utc()),
    )
    conn.commit()
    conn.close()


def save_correlation_analysis(run_id: int, analysis: Dict[str, Any]) -> None:
    """Save the cross-story correlation analysis."""
    conn = get_connection()
    conn.execute(
        """INSERT INTO correlation_analyses
           (run_id, analysis_json, created_at) VALUES (?,?,?)""",
        (run_id, json.dumps(analysis), now_utc()),
    )
    conn.commit()
    conn.close()


def get_previous_correlation(run_id: int) -> Optional[Dict[str, Any]]:
    """Return correlation analysis from the run before the current one."""
    conn = get_connection()
    row = conn.execute(
        """SELECT analysis_json FROM correlation_analyses
           WHERE run_id < ? ORDER BY run_id DESC LIMIT 1""",
        (run_id,),
    ).fetchone()
    conn.close()
    if row:
        try:
            return json.loads(row["analysis_json"])
        except json.JSONDecodeError:
            return None
    return None


def save_brief(run_id: int, brief_text: str) -> None:
    """Save the final brief text."""
    conn = get_connection()
    conn.execute(
        "INSERT INTO briefs (run_id, brief_text, created_at) VALUES (?,?,?)",
        (run_id, brief_text, now_utc()),
    )
    conn.commit()
    conn.close()


def get_previous_watch_list(run_id: int) -> List[str]:
    """Pull the watch list items from the last run's correlation analysis."""
    prev = get_previous_correlation(run_id)
    if prev:
        return prev.get("recommended_watch", [])
    return []


# ── Weekly briefs ─────────────────────────────────────────────────────────────

def get_runs_for_weekly(days: int = 7) -> List[Dict[str, Any]]:
    """Return complete runs from the past N days, one per calendar date (latest per day)."""
    conn = get_connection()
    rows = conn.execute(
        """
        SELECT r.id, r.started_at, r.article_count, r.cluster_count
        FROM runs r
        WHERE r.status = 'complete'
          AND r.started_at >= datetime('now', ? || ' days')
          AND EXISTS (SELECT 1 FROM briefs b WHERE b.run_id = r.id)
        ORDER BY r.started_at
        """,
        (f"-{days}",),
    ).fetchall()
    conn.close()

    # Deduplicate: keep only the latest complete run per calendar date
    seen_dates: dict = {}
    for row in rows:
        date_key = row["started_at"][:10]
        seen_dates[date_key] = dict(row)

    return list(seen_dates.values())


def get_weekly_source_data(run_ids: List[int]) -> List[Dict[str, Any]]:
    """
    For each run, return the brief text and correlation analysis.

    Returns a list of dicts with keys: run_id, started_at, brief_text,
    correlation, watch_list.
    """
    if not run_ids:
        return []

    conn = get_connection()
    placeholders = ",".join("?" * len(run_ids))

    briefs_rows = conn.execute(
        f"SELECT run_id, brief_text FROM briefs WHERE run_id IN ({placeholders})",
        run_ids,
    ).fetchall()

    corr_rows = conn.execute(
        f"""SELECT run_id, analysis_json FROM correlation_analyses
            WHERE run_id IN ({placeholders})
            ORDER BY id DESC""",
        run_ids,
    ).fetchall()

    run_rows = conn.execute(
        f"SELECT id, started_at, article_count FROM runs WHERE id IN ({placeholders})",
        run_ids,
    ).fetchall()
    conn.close()

    brief_map = {r["run_id"]: r["brief_text"] for r in briefs_rows}
    run_map = {r["id"]: dict(r) for r in run_rows}

    # Keep only the latest correlation per run
    corr_map: dict = {}
    for r in corr_rows:
        if r["run_id"] not in corr_map:
            try:
                corr_map[r["run_id"]] = json.loads(r["analysis_json"])
            except json.JSONDecodeError:
                corr_map[r["run_id"]] = {}

    result = []
    for run_id in run_ids:
        if run_id not in brief_map:
            continue
        corr = corr_map.get(run_id, {})
        result.append(
            {
                "run_id": run_id,
                "started_at": run_map.get(run_id, {}).get("started_at", ""),
                "article_count": run_map.get(run_id, {}).get("article_count", 0),
                "brief_text": brief_map[run_id],
                "narrative_patterns": corr.get("narrative_patterns", []),
                "anomalies": corr.get("anomalies", []),
                "watch_list": corr.get("recommended_watch", []),
                "delta": corr.get("delta_from_previous", ""),
            }
        )

    return sorted(result, key=lambda x: x["started_at"])


def save_weekly_brief(
    week_start: str,
    week_end: str,
    run_ids: List[int],
    brief_text: str,
) -> int:
    """Save a weekly brief and return its id."""
    conn = get_connection()
    cur = conn.execute(
        """INSERT INTO weekly_briefs
           (week_start, week_end, run_ids, brief_text, created_at)
           VALUES (?,?,?,?,?)""",
        (week_start, week_end, json.dumps(run_ids), brief_text, now_utc()),
    )
    weekly_id = cur.lastrowid
    conn.commit()
    conn.close()
    return weekly_id


def get_weekly_briefs() -> List[Dict[str, Any]]:
    """Return all weekly briefs in reverse chronological order."""
    conn = get_connection()
    rows = conn.execute(
        "SELECT id, week_start, week_end, created_at FROM weekly_briefs ORDER BY id DESC"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]
