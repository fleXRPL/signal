"""
Shared pytest fixtures for the Signal test suite.
"""
from __future__ import annotations

import json
import sqlite3
import tempfile
from pathlib import Path
from typing import Any, Dict, List
from unittest.mock import MagicMock

import pytest


# ── Article fixtures ──────────────────────────────────────────────────────────

def make_article(
    title: str = "Test Article",
    source_name: str = "Test Source",
    bias: str = "center",
    url: str = "https://example.com/article",
    text_snippet: str = "This is a test article snippet.",
    full_text: str = "Full text of the test article.",
    published_at: str = "2026-05-19T10:00:00+00:00",
    topic: str = "legislation",
    sentiment: str = "neutral",
    framing: str = "factual",
    key_claim: str = "A test claim.",
    entities: Dict[str, List[str]] | None = None,
) -> Dict[str, Any]:
    return {
        "title": title,
        "source_name": source_name,
        "bias": bias,
        "url": url,
        "text_snippet": text_snippet,
        "full_text": full_text,
        "published_at": published_at,
        "topic": topic,
        "sentiment": sentiment,
        "framing": framing,
        "key_claim": key_claim,
        "entities": (
            entities
            if entities is not None
            else {
                "people": ["John Smith"],
                "organizations": ["Congress"],
                "legislation": ["HR 1234"],
                "locations": ["Washington DC"],
            }
        ),
    }


@pytest.fixture
def sample_article() -> Dict[str, Any]:
    return make_article()


@pytest.fixture
def sample_articles() -> List[Dict[str, Any]]:
    """A small cross-spectrum article set covering two stories."""
    budget_entities = {
        "people": ["Sen. Smith"],
        "organizations": ["Senate"],
        "legislation": ["Budget Act"],
        "locations": ["DC"],
    }
    return [
        make_article(
            title="Senate passes budget bill",
            source_name="Left News",
            bias="left",
            url="https://leftnews.com/budget",
            key_claim="Senate passed the budget 60-40.",
            entities=budget_entities,
        ),
        make_article(
            title="Senate approves budget legislation",
            source_name="Right News",
            bias="right",
            url="https://rightnews.com/budget",
            key_claim="Budget bill passes with bipartisan support.",
            entities=budget_entities,
        ),
        make_article(
            title="President signs executive order on immigration",
            source_name="Center Daily",
            bias="center",
            url="https://centerdaily.com/immigration",
            key_claim="President issued executive order restricting immigration.",
            entities={"people": ["President"], "organizations": ["White House"], "legislation": [], "locations": ["Washington"]},
        ),
    ]


# ── LLM response fixtures ─────────────────────────────────────────────────────

@pytest.fixture
def mock_entity_response() -> str:
    return json.dumps({
        "topic": "legislation",
        "key_claim": "Senate passed the budget bill.",
        "entities": {
            "people": ["Sen. Smith"],
            "organizations": ["Senate"],
            "legislation": ["Budget Act"],
            "locations": ["Washington DC"],
        },
        "sentiment": "neutral",
        "framing": "factual reporting on legislative process",
    })


@pytest.fixture
def mock_cluster_analysis_response() -> str:
    return json.dumps({
        "headline": "Senate Passes Budget Bill With Bipartisan Support",
        "consensus_facts": ["The Senate voted 60-40 to pass the budget bill."],
        "contested_points": ["Impact on national debt differs by outlet."],
        "left_framing": "Victory for social spending priorities.",
        "center_framing": "Bipartisan compromise reaches passage.",
        "right_framing": "Fiscally irresponsible spending increase.",
        "left_omissions": "Debt ceiling concerns downplayed.",
        "right_omissions": "Social program benefits ignored.",
        "assessment": "Significant legislation with cross-spectrum coverage.",
        "significance": "high",
    })


@pytest.fixture
def mock_correlation_response() -> str:
    return json.dumps({
        "hidden_connections": [
            {
                "entities": ["Sen. Smith", "Budget Act"],
                "connection": "Sen. Smith was lead sponsor of the budget bill.",
                "significance": "Key actor in both stories this week.",
            }
        ],
        "narrative_patterns": ["Bipartisan cooperation framed differently by left and right."],
        "anomalies": ["Immigration executive order received minimal left coverage."],
        "blindspot_analysis": "Immigration order received limited analysis from left-leaning outlets.",
        "recommended_watch": ["Budget reconciliation process", "Immigration court challenges"],
        "delta_from_previous": "New: Immigration executive order. Continued: Budget debate.",
        "_left_only": [],
        "_right_only": ["Immigration executive order"],
    })


@pytest.fixture
def mock_brief_response() -> str:
    return """## SITUATION OVERVIEW
The week was dominated by the Senate budget bill and a presidential executive order on immigration.

## KEY ACTORS AND DYNAMICS
Sen. Smith led the budget bill through the Senate. The President issued the immigration order unilaterally.

## WHAT ISN'T BEING SAID
Left-leaning outlets largely ignored the immigration executive order.

## CONNECTIONS AND PATTERNS
The budget bill and immigration order represent two parallel uses of government power this week.

## WATCH LIST
- Budget reconciliation process
- Immigration court challenges

## ANALYST NOTE
This was a consequential week legislatively. The budget passage and immigration order signal an active policy agenda."""


# ── Database fixtures ─────────────────────────────────────────────────────────

@pytest.fixture
def tmp_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Patch store.DB_PATH to a temporary database for test isolation."""
    db_path = tmp_path / "test_signal.db"
    import pipeline.store as store_module
    monkeypatch.setattr(store_module, "DB_PATH", db_path)
    store_module.init_db()
    return db_path


# ── Config fixture ────────────────────────────────────────────────────────────

@pytest.fixture
def sample_config() -> Dict[str, Any]:
    return {
        "analytics": {"measurement_id": "G-TEST123"},
        "llm": {
            "provider": "claude",
            "ollama": {"model": "qwen2.5:14b", "base_url": "http://localhost:11434", "timeout": 120},
            "claude": {"timeout": 180},
        },
        "collection": {
            "max_articles_per_source": 10,
            "article_age_hours": 24,
            "fetch_full_text": True,
            "fetch_timeout": 10,
        },
        "analysis": {
            "min_cluster_size": 2,
            "entity_similarity_threshold": 0.75,
            "title_similarity_threshold": 0.70,
        },
    }
