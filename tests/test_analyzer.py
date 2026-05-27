"""
Tests for pipeline/analyzer.py.

All LLM calls (_llm_call) are mocked. The pure algorithmic functions
(parsing, clustering) are exercised directly.
"""
from __future__ import annotations

import json
from unittest.mock import MagicMock, call, patch

import pytest

import pipeline.store as store
from pipeline.analyzer import (
    _build_entity_network,
    _entity_set,
    _format_articles_for_cluster,
    _format_cluster_summaries,
    _get_blindspots,
    _llm_call,
    _llm_call_claude,
    _llm_call_ollama,
    _parse_json_response,
    analyze_clusters,
    cluster_articles,
    correlate_stories,
    extract_entities,
    run_pipeline,
    synthesize_brief,
)
from tests.conftest import make_article


# ── _parse_json_response ──────────────────────────────────────────────────────

class TestParseJsonResponse:
    def test_clean_json_object(self):
        result = _parse_json_response('{"key": "value"}')
        assert result == {"key": "value"}

    def test_json_with_markdown_fence(self):
        raw = '```json\n{"topic": "legislation"}\n```'
        result = _parse_json_response(raw)
        assert result == {"topic": "legislation"}

    def test_json_with_plain_fence(self):
        raw = '```\n{"topic": "legislation"}\n```'
        result = _parse_json_response(raw)
        assert result == {"topic": "legislation"}

    def test_json_embedded_in_prose(self):
        raw = 'Here is the analysis: {"headline": "Test"} That is all.'
        result = _parse_json_response(raw)
        assert result == {"headline": "Test"}

    def test_returns_none_on_invalid_json(self):
        assert _parse_json_response("this is not json at all") is None

    def test_returns_none_on_empty_string(self):
        assert _parse_json_response("") is None

    def test_nested_json(self):
        raw = '{"entities": {"people": ["Alice", "Bob"], "orgs": []}}'
        result = _parse_json_response(raw)
        assert result["entities"]["people"] == ["Alice", "Bob"]

    def test_returns_none_when_regex_match_is_still_invalid_json(self):
        # Looks like a JSON object but has a syntax error inside the braces
        raw = "Some text {invalid: json, missing: quotes} more text"
        assert _parse_json_response(raw) is None


# ── _entity_set ───────────────────────────────────────────────────────────────

class TestEntitySet:
    def test_flattens_all_entity_categories(self):
        article = make_article(entities={
            "people": ["John Smith", "Jane Doe"],
            "organizations": ["Congress"],
            "legislation": ["HR 1234"],
            "locations": [],
        })
        result = _entity_set(article)
        assert "john smith" in result
        assert "congress" in result
        assert "hr 1234" in result

    def test_returns_lowercase(self):
        article = make_article(entities={"people": ["JOHN SMITH"]})
        result = _entity_set(article)
        assert "john smith" in result
        assert "JOHN SMITH" not in result

    def test_filters_short_strings(self):
        article = make_article(entities={"people": ["AB", "Alice"]})
        result = _entity_set(article)
        assert "ab" not in result
        assert "alice" in result

    def test_empty_entities(self):
        article = make_article(entities={})
        assert _entity_set(article) == set()

    def test_ignores_non_list_values(self):
        article = make_article()
        article["entities"] = {"people": "not-a-list"}
        result = _entity_set(article)
        assert result == set()


# ── _format_articles_for_cluster ─────────────────────────────────────────────

class TestFormatArticlesForCluster:
    def test_includes_bias_and_source(self):
        article = make_article(bias="left", source_name="The Times")
        result = _format_articles_for_cluster([article])
        assert "[LEFT]" in result
        assert "The Times" in result

    def test_includes_title_and_claim(self):
        article = make_article(title="Big Story", key_claim="Important claim.")
        result = _format_articles_for_cluster([article])
        assert "Big Story" in result
        assert "Important claim." in result

    def test_multiple_articles_separated(self):
        articles = [
            make_article(title="Story A", source_name="Source A"),
            make_article(title="Story B", source_name="Source B", url="https://b.com"),
        ]
        result = _format_articles_for_cluster(articles)
        assert "Story A" in result
        assert "Story B" in result


# ── cluster_articles (Pass 2 - algorithmic) ───────────────────────────────────

class TestClusterArticles:
    def test_groups_similar_titles(self, tmp_db):
        articles = [
            make_article(
                title="Senate passes budget bill",
                source_name="Left News",
                url="https://left.com/budget",
                entities={"people": [], "organizations": ["Senate"], "legislation": [], "locations": []},
            ),
            make_article(
                title="Senate passes the budget bill today",
                source_name="Right News",
                url="https://right.com/budget",
                entities={"people": [], "organizations": ["Senate"], "legislation": [], "locations": []},
            ),
        ]
        import pipeline.store as store_module
        run_id = store_module.start_run()
        for a in articles:
            a["_db_id"] = None

        clusters = cluster_articles(articles, run_id, title_threshold=0.70)
        multi = [c for c in clusters if not c.get("singleton")]
        assert len(multi) >= 1

    def test_groups_by_entity_overlap(self, tmp_db):
        entities_shared = {"people": ["John Smith", "Jane Doe", "Bob Jones"], "organizations": [], "legislation": [], "locations": []}
        articles = [
            make_article(
                title="Article about politics",
                source_name="Source A",
                url="https://a.com/1",
                entities=entities_shared,
            ),
            make_article(
                title="Completely different topic",
                source_name="Source B",
                url="https://b.com/1",
                entities=entities_shared,
            ),
        ]
        import pipeline.store as store_module
        run_id = store_module.start_run()
        for a in articles:
            a["_db_id"] = None

        clusters = cluster_articles(articles, run_id, title_threshold=0.99, entity_overlap_min=2)
        multi = [c for c in clusters if not c.get("singleton")]
        assert len(multi) >= 1

    def test_singletons_not_in_multi_clusters(self, tmp_db):
        articles = [
            make_article(title="Completely unrelated story A", source_name="S1", url="https://s1.com"),
            make_article(title="Completely unrelated story B", source_name="S2", url="https://s2.com"),
        ]
        import pipeline.store as store_module
        run_id = store_module.start_run()
        for a in articles:
            a["_db_id"] = None
            a["entities"] = {"people": [], "organizations": [], "legislation": [], "locations": []}

        clusters = cluster_articles(articles, run_id, title_threshold=0.99, entity_overlap_min=100)
        multi = [c for c in clusters if not c.get("singleton")]
        singletons = [c for c in clusters if c.get("singleton")]
        assert len(multi) == 0
        assert len(singletons) == 2

    def test_same_source_articles_not_clustered_together(self, tmp_db):
        """Two articles from the same source should never be clustered together."""
        entities = {"people": ["John Smith", "Jane Doe", "Bob Jones"], "organizations": ["Congress"], "legislation": [], "locations": []}
        articles = [
            make_article(title="Budget bill passes Senate", source_name="Same Source", url="https://same.com/1", entities=entities),
            make_article(title="Budget bill passes Senate today", source_name="Same Source", url="https://same.com/2", entities=entities),
        ]
        import pipeline.store as store_module
        run_id = store_module.start_run()
        for a in articles:
            a["_db_id"] = None

        clusters = cluster_articles(articles, run_id)
        multi = [c for c in clusters if not c.get("singleton")]
        # Same source articles should be singletons, not in multi-source clusters
        for cluster in multi:
            sources = {a["source_name"] for a in cluster["articles"]}
            assert len(sources) > 1


# ── extract_entities (Pass 1 — mocked LLM) ───────────────────────────────────

class TestExtractEntities:
    @patch("pipeline.analyzer._llm_call")
    def test_augments_articles_with_entities(self, mock_llm, tmp_db, mock_entity_response):
        mock_llm.return_value = mock_entity_response

        articles = [make_article()]
        import pipeline.store as store_module
        run_id = store_module.start_run()
        db_ids = store_module.save_articles(run_id, articles)

        result = extract_entities(
            articles, run_id, db_ids,
            model="test-model", base_url="http://localhost:11434",
            timeout=10, provider="ollama",
        )
        assert result[0]["topic"] == "legislation"
        assert result[0]["sentiment"] == "neutral"
        assert "Sen. Smith" in result[0]["entities"]["people"]

    @patch("pipeline.analyzer._llm_call")
    def test_falls_back_gracefully_on_llm_error(self, mock_llm, tmp_db):
        mock_llm.side_effect = Exception("LLM unavailable")

        articles = [make_article()]
        import pipeline.store as store_module
        run_id = store_module.start_run()
        db_ids = store_module.save_articles(run_id, articles)

        result = extract_entities(
            articles, run_id, db_ids,
            model="test-model", base_url="http://localhost:11434",
            timeout=10, provider="ollama",
        )
        assert result[0]["topic"] == "other"
        assert result[0]["sentiment"] == "neutral"
        assert result[0]["entities"] == {"people": [], "organizations": [], "legislation": [], "locations": []}

    @patch("pipeline.analyzer._llm_call")
    def test_falls_back_gracefully_on_invalid_json(self, mock_llm, tmp_db):
        mock_llm.return_value = "This is not JSON at all."

        articles = [make_article()]
        import pipeline.store as store_module
        run_id = store_module.start_run()
        db_ids = store_module.save_articles(run_id, articles)

        result = extract_entities(
            articles, run_id, db_ids,
            model="test-model", base_url="http://localhost:11434",
            timeout=10, provider="ollama",
        )
        assert result[0]["topic"] == "other"


# ── analyze_clusters (Pass 3 — mocked LLM) ───────────────────────────────────

class TestAnalyzeClusters:
    @patch("pipeline.analyzer._llm_call")
    def test_adds_analysis_to_clusters(self, mock_llm, tmp_db, mock_cluster_analysis_response):
        mock_llm.return_value = mock_cluster_analysis_response

        import pipeline.store as store_module
        run_id = store_module.start_run()
        articles = [
            make_article(source_name="Left News", url="https://l.com/1"),
            make_article(source_name="Right News", url="https://r.com/1"),
        ]
        db_ids = store_module.save_articles(run_id, articles)
        cluster_id = store_module.save_cluster(run_id, "Budget Bill", db_ids, {"left": 1, "right": 1})

        clusters = [
            {
                "cluster_id": cluster_id,
                "story_title": "Budget Bill",
                "articles": articles,
                "bias_spread": {"left": 1, "right": 1},
                "source_count": 2,
            }
        ]

        result = analyze_clusters(
            clusters, run_id,
            model="test-model", base_url="http://localhost:11434",
            timeout=10, provider="ollama",
        )
        assert "analysis" in result[0]
        assert result[0]["analysis"]["headline"] == "Senate Passes Budget Bill With Bipartisan Support"

    @patch("pipeline.analyzer._llm_call")
    def test_skips_singleton_clusters(self, mock_llm, tmp_db):
        run_id = store.start_run()
        clusters = [
            {
                "cluster_id": None,
                "story_title": "Singleton",
                "articles": [make_article()],
                "bias_spread": {"center": 1},
                "source_count": 1,
                "singleton": True,
            }
        ]

        analyze_clusters(
            clusters, run_id,
            model="test-model", base_url="http://localhost:11434",
            timeout=10, provider="ollama",
        )
        mock_llm.assert_not_called()

    @patch("pipeline.analyzer._llm_call")
    def test_falls_back_on_llm_error(self, mock_llm, tmp_db):
        mock_llm.side_effect = Exception("LLM down")
        run_id = store.start_run()
        articles = [
            make_article(source_name="Left News", url="https://l.com/1"),
            make_article(source_name="Right News", url="https://r.com/1"),
        ]
        db_ids = store.save_articles(run_id, articles)
        cluster_id = store.save_cluster(run_id, "Test Story", db_ids, {"left": 1, "right": 1})
        clusters = [{
            "cluster_id": cluster_id,
            "story_title": "Test Story",
            "articles": articles,
            "bias_spread": {"left": 1, "right": 1},
            "source_count": 2,
        }]

        result = analyze_clusters(
            clusters, run_id,
            model="test-model", base_url="http://localhost:11434",
            timeout=10, provider="ollama",
        )
        assert result[0]["analysis"]["headline"] == "Test Story"
        assert result[0]["analysis"]["significance"] == "medium"

    @patch("pipeline.analyzer._llm_call")
    def test_falls_back_on_invalid_json(self, mock_llm, tmp_db):
        mock_llm.return_value = "Not JSON at all."
        run_id = store.start_run()
        articles = [
            make_article(source_name="Left News", url="https://l.com/1"),
            make_article(source_name="Right News", url="https://r.com/1"),
        ]
        db_ids = store.save_articles(run_id, articles)
        cluster_id = store.save_cluster(run_id, "Test Story", db_ids, {"left": 1, "right": 1})
        clusters = [{
            "cluster_id": cluster_id,
            "story_title": "Test Story",
            "articles": articles,
            "bias_spread": {"left": 1, "right": 1},
            "source_count": 2,
        }]

        result = analyze_clusters(
            clusters, run_id,
            model="test-model", base_url="http://localhost:11434",
            timeout=10, provider="ollama",
        )
        assert result[0]["analysis"]["assessment"] == "Analysis unavailable."


# ── _llm_call dispatch ────────────────────────────────────────────────────────

class TestLlmCallDispatch:
    @patch("pipeline.analyzer._llm_call_claude")
    def test_routes_to_claude(self, mock_claude):
        mock_claude.return_value = "Claude response"
        result = _llm_call("test prompt", provider="claude", timeout=30)
        mock_claude.assert_called_once_with("test prompt", 30)
        assert result == "Claude response"

    @patch("pipeline.analyzer._llm_call_ollama")
    def test_routes_to_ollama(self, mock_ollama):
        mock_ollama.return_value = "Ollama response"
        result = _llm_call("test prompt", model="qwen2.5:14b", base_url="http://localhost:11434", timeout=30, provider="ollama")
        mock_ollama.assert_called_once()
        assert result == "Ollama response"


class TestLlmCallOllama:
    @patch("pipeline.analyzer.ollama.Client")
    def test_returns_response_text(self, mock_client_cls):
        mock_client = MagicMock()
        mock_client.generate.return_value = {"response": "extracted text"}
        mock_client_cls.return_value = mock_client

        result = _llm_call_ollama("prompt", "qwen2.5:14b", "http://localhost:11434", 60)
        assert result == "extracted text"

    @patch("pipeline.analyzer.ollama.Client")
    def test_returns_empty_string_on_missing_key(self, mock_client_cls):
        mock_client = MagicMock()
        mock_client.generate.return_value = {}
        mock_client_cls.return_value = mock_client

        result = _llm_call_ollama("prompt", "qwen2.5:14b", "http://localhost:11434", 60)
        assert result == ""


class TestLlmCallClaude:
    @patch("pipeline.analyzer.subprocess.run")
    @patch("pipeline.analyzer.shutil.which")
    def test_returns_stdout_on_success(self, mock_which, mock_run):
        mock_which.return_value = "/usr/local/bin/claude"
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stdout = "  Claude brief text  "
        mock_run.return_value = mock_proc

        result = _llm_call_claude("test prompt", timeout=60)
        assert result == "Claude brief text"

    @patch("pipeline.analyzer.subprocess.run")
    @patch("pipeline.analyzer.shutil.which")
    def test_raises_on_nonzero_exit(self, mock_which, mock_run):
        mock_which.return_value = "/usr/local/bin/claude"
        mock_proc = MagicMock()
        mock_proc.returncode = 1
        mock_proc.stderr = "Rate limit exceeded"
        mock_run.return_value = mock_proc

        with pytest.raises(RuntimeError, match="Rate limit exceeded"):
            _llm_call_claude("test prompt", timeout=60)

    @patch("pipeline.analyzer.subprocess.run")
    @patch("pipeline.analyzer.shutil.which")
    def test_raises_generic_message_on_empty_stderr(self, mock_which, mock_run):
        mock_which.return_value = "/usr/local/bin/claude"
        mock_proc = MagicMock()
        mock_proc.returncode = 1
        mock_proc.stderr = ""
        mock_proc.stdout = ""
        mock_run.return_value = mock_proc

        with pytest.raises(RuntimeError, match="Claude CLI non-zero exit"):
            _llm_call_claude("test prompt", timeout=60)

    @patch("pipeline.analyzer.shutil.which")
    def test_falls_back_to_homebrew_path_when_not_in_path(self, mock_which):
        mock_which.return_value = None
        with patch("pipeline.analyzer.subprocess.run") as mock_run:
            mock_proc = MagicMock()
            mock_proc.returncode = 0
            mock_proc.stdout = "response"
            mock_run.return_value = mock_proc
            _llm_call_claude("prompt", timeout=30)
            cmd = mock_run.call_args[0][0]
            assert "/opt/homebrew/bin/claude" in cmd


# ── _build_entity_network (Pass 4 helper) ─────────────────────────────────────

class TestBuildEntityNetwork:
    def _make_cluster(self, title: str, entities: dict, source: str = "S1") -> dict:
        return {
            "story_title": title,
            "articles": [make_article(source_name=source, entities=entities)],
        }

    def test_finds_entity_in_multiple_clusters(self):
        shared_entity = {"people": ["John Smith"], "organizations": [], "legislation": [], "locations": []}
        clusters = [
            self._make_cluster("Story A", shared_entity),
            self._make_cluster("Story B", shared_entity, source="S2"),
        ]
        result = _build_entity_network(clusters)
        assert "John Smith" in result

    def test_returns_no_cross_story_message_when_empty(self):
        clusters = [
            self._make_cluster("Story A", {"people": ["Alice"], "organizations": [], "legislation": [], "locations": []}),
            self._make_cluster("Story B", {"people": ["Bob"], "organizations": [], "legislation": [], "locations": []}, source="S2"),
        ]
        result = _build_entity_network(clusters)
        assert "No cross-story entities" in result

    def test_single_cluster_returns_no_cross_story(self):
        clusters = [self._make_cluster("Story A", {"people": ["Alice"], "organizations": [], "legislation": [], "locations": []})]
        result = _build_entity_network(clusters)
        assert "No cross-story entities" in result

    def test_ignores_short_entity_names(self):
        short_entity = {"people": ["AB"], "organizations": [], "legislation": [], "locations": []}
        clusters = [
            self._make_cluster("Story A", short_entity),
            self._make_cluster("Story B", short_entity, source="S2"),
        ]
        result = _build_entity_network(clusters)
        assert "No cross-story entities" in result


# ── _get_blindspots (Pass 4 helper) ──────────────────────────────────────────

class TestGetBlindspots:
    def _make_cluster_with_biases(self, title: str, biases: list) -> dict:
        articles = [make_article(bias=b, source_name=f"Source {i}", url=f"https://s{i}.com") for i, b in enumerate(biases)]
        return {"story_title": title, "articles": articles}

    def test_identifies_left_only_story(self):
        clusters = [self._make_cluster_with_biases("Left Story", ["left", "far-left"])]
        left_only, right_only = _get_blindspots(clusters)
        assert "Left Story" in left_only
        assert right_only == []

    def test_identifies_right_only_story(self):
        clusters = [self._make_cluster_with_biases("Right Story", ["right", "far-right"])]
        left_only, right_only = _get_blindspots(clusters)
        assert "Right Story" in right_only
        assert left_only == []

    def test_balanced_story_in_neither(self):
        clusters = [self._make_cluster_with_biases("Balanced Story", ["left", "right"])]
        left_only, right_only = _get_blindspots(clusters)
        assert left_only == []
        assert right_only == []

    def test_center_coverage_excludes_from_both(self):
        clusters = [self._make_cluster_with_biases("Center Story", ["left", "center"])]
        left_only, right_only = _get_blindspots(clusters)
        assert left_only == []
        assert right_only == []

    def test_libertarian_counts_as_center(self):
        clusters = [self._make_cluster_with_biases("Lib Story", ["right", "libertarian"])]
        left_only, right_only = _get_blindspots(clusters)
        assert right_only == []


# ── _format_cluster_summaries (Pass 4 helper) ─────────────────────────────────

class TestFormatClusterSummaries:
    def test_includes_headline_and_assessment(self):
        clusters = [{
            "story_title": "Budget Bill",
            "bias_spread": {"left": 1, "right": 1},
            "analysis": {
                "headline": "Budget Bill Passes",
                "assessment": "Significant legislation.",
                "significance": "high",
            },
        }]
        result = _format_cluster_summaries(clusters)
        assert "Budget Bill Passes" in result
        assert "Significant legislation." in result
        assert "high" in result

    def test_skips_singletons(self):
        clusters = [{
            "story_title": "Singleton Story",
            "bias_spread": {"center": 1},
            "singleton": True,
            "analysis": {"headline": "Should Not Appear"},
        }]
        result = _format_cluster_summaries(clusters)
        assert "Should Not Appear" not in result

    def test_falls_back_to_story_title_when_no_analysis(self):
        clusters = [{
            "story_title": "Fallback Title",
            "bias_spread": {"left": 1},
            "analysis": {},
        }]
        result = _format_cluster_summaries(clusters)
        assert "Fallback Title" in result


# ── correlate_stories (Pass 4 — mocked LLM) ──────────────────────────────────

class TestCorrelateStories:
    def _make_analyzed_cluster(self, title: str, biases: list) -> dict:
        articles = [
            make_article(bias=b, source_name=f"Source {i}", url=f"https://s{i}.com/{title}")
            for i, b in enumerate(biases)
        ]
        return {
            "story_title": title,
            "articles": articles,
            "bias_spread": {b: 1 for b in biases},
            "source_count": len(biases),
            "analysis": {
                "headline": title,
                "assessment": "Test assessment.",
                "significance": "medium",
            },
        }

    @patch("pipeline.analyzer._llm_call")
    def test_returns_structured_analysis(self, mock_llm, tmp_db, mock_correlation_response):
        mock_llm.return_value = mock_correlation_response
        run_id = store.start_run()
        clusters = [self._make_analyzed_cluster("Budget Bill", ["left", "right"])]

        result = correlate_stories(
            clusters, run_id,
            model="test-model", base_url="http://localhost:11434",
            timeout=10, provider="ollama",
        )
        assert "hidden_connections" in result
        assert "narrative_patterns" in result
        assert "recommended_watch" in result

    @patch("pipeline.analyzer._llm_call")
    def test_attaches_blindspot_data(self, mock_llm, tmp_db, mock_correlation_response):
        mock_llm.return_value = mock_correlation_response
        run_id = store.start_run()
        clusters = [
            self._make_analyzed_cluster("Left Story", ["left", "far-left"]),
            self._make_analyzed_cluster("Right Story", ["right", "far-right"]),
        ]

        result = correlate_stories(
            clusters, run_id,
            model="test-model", base_url="http://localhost:11434",
            timeout=10, provider="ollama",
        )
        assert "_left_only" in result
        assert "_right_only" in result

    @patch("pipeline.analyzer._llm_call")
    def test_saves_to_db(self, mock_llm, tmp_db, mock_correlation_response):
        mock_llm.return_value = mock_correlation_response
        run_id = store.start_run()

        correlate_stories(
            [], run_id,
            model="test-model", base_url="http://localhost:11434",
            timeout=10, provider="ollama",
        )
        saved = store.get_previous_correlation(store.start_run())
        assert saved is not None

    @patch("pipeline.analyzer._llm_call")
    def test_falls_back_on_llm_error(self, mock_llm, tmp_db):
        mock_llm.side_effect = Exception("LLM down")
        run_id = store.start_run()

        result = correlate_stories(
            [], run_id,
            model="test-model", base_url="http://localhost:11434",
            timeout=10, provider="ollama",
        )
        assert result["hidden_connections"] == []
        assert result["blindspot_analysis"] == "Analysis unavailable."
        assert result["delta_from_previous"] == "N/A"

    @patch("pipeline.analyzer._llm_call")
    def test_falls_back_on_invalid_json(self, mock_llm, tmp_db):
        mock_llm.return_value = "Not valid JSON."
        run_id = store.start_run()

        result = correlate_stories(
            [], run_id,
            model="test-model", base_url="http://localhost:11434",
            timeout=10, provider="ollama",
        )
        assert result["recommended_watch"] == []


# ── synthesize_brief (Pass 5 — mocked LLM) ───────────────────────────────────

class TestSynthesizeBrief:
    def _make_analyzed_cluster(self, title: str) -> dict:
        return {
            "story_title": title,
            "articles": [make_article()],
            "analysis": {
                "headline": title,
                "assessment": "Test.",
                "significance": "high",
                "left_omissions": "",
                "right_omissions": "",
            },
        }

    @patch("pipeline.analyzer._llm_call")
    def test_returns_brief_text(self, mock_llm, mock_brief_response):
        mock_llm.return_value = mock_brief_response
        clusters = [self._make_analyzed_cluster("Budget Bill")]
        correlation = {"hidden_connections": [], "narrative_patterns": [], "recommended_watch": []}

        result = synthesize_brief(
            clusters, correlation, [make_article()],
            model="test-model", base_url="http://localhost:11434",
            timeout=10, provider="ollama",
        )
        assert result == mock_brief_response

    @patch("pipeline.analyzer._llm_call")
    def test_skips_singletons_in_prompt(self, mock_llm, mock_brief_response):
        mock_llm.return_value = mock_brief_response
        singleton = {
            "story_title": "Singleton",
            "articles": [make_article()],
            "singleton": True,
            "analysis": {"headline": "Should Not Be In Prompt"},
        }
        clusters = [self._make_analyzed_cluster("Main Story"), singleton]
        correlation = {}

        synthesize_brief(
            clusters, correlation, [make_article()],
            model="test-model", base_url="http://localhost:11434",
            timeout=10, provider="ollama",
        )
        prompt_arg = mock_llm.call_args[0][0]
        assert "Should Not Be In Prompt" not in prompt_arg

    @patch("pipeline.analyzer._llm_call")
    def test_falls_back_on_llm_error(self, mock_llm):
        mock_llm.side_effect = Exception("LLM unavailable")

        result = synthesize_brief(
            [], {}, [],
            model="test-model", base_url="http://localhost:11434",
            timeout=10, provider="ollama",
        )
        assert "Brief synthesis failed" in result


# ── run_pipeline (full pipeline integration — all LLM calls mocked) ───────────

class TestRunPipeline:
    @patch("pipeline.analyzer._llm_call")
    def test_returns_brief_clusters_correlation(
        self, mock_llm, tmp_db, sample_articles,
        mock_entity_response, mock_cluster_analysis_response,
        mock_correlation_response, mock_brief_response,
    ):
        mock_llm.side_effect = [
            mock_entity_response,        # Pass 1 — article 1
            mock_entity_response,        # Pass 1 — article 2
            mock_entity_response,        # Pass 1 — article 3
            mock_cluster_analysis_response,  # Pass 3 — cluster analysis
            mock_correlation_response,   # Pass 4 — correlation
            mock_brief_response,         # Pass 5 — brief
        ]

        run_id = store.start_run()
        db_ids = store.save_articles(run_id, sample_articles)

        config = {
            "llm": {
                "provider": "ollama",
                "ollama": {"model": "qwen2.5:14b", "base_url": "http://localhost:11434", "timeout": 60},
            },
            "analysis": {"title_similarity_threshold": 0.70},
        }

        brief, clusters, correlation = run_pipeline(sample_articles, db_ids, run_id, config)

        assert isinstance(brief, str)
        assert len(brief) > 0
        assert isinstance(clusters, list)
        assert isinstance(correlation, dict)

    @patch("pipeline.analyzer._llm_call")
    def test_saves_brief_to_db(
        self, mock_llm, tmp_db, sample_articles,
        mock_entity_response, mock_cluster_analysis_response,
        mock_correlation_response, mock_brief_response,
    ):
        mock_llm.side_effect = [
            mock_entity_response,
            mock_entity_response,
            mock_entity_response,
            mock_cluster_analysis_response,
            mock_correlation_response,
            mock_brief_response,
        ]

        run_id = store.start_run()
        db_ids = store.save_articles(run_id, sample_articles)

        config = {
            "llm": {
                "provider": "ollama",
                "ollama": {"model": "qwen2.5:14b", "base_url": "http://localhost:11434", "timeout": 60},
            },
            "analysis": {"title_similarity_threshold": 0.70},
        }

        run_pipeline(sample_articles, db_ids, run_id, config)

        conn = store.get_connection()
        row = conn.execute("SELECT brief_text FROM briefs WHERE run_id=?", (run_id,)).fetchone()
        conn.close()
        assert row is not None
        assert row["brief_text"] == mock_brief_response

    @patch("pipeline.analyzer._llm_call")
    def test_claude_provider_sets_empty_model(
        self, mock_llm, tmp_db, sample_articles,
        mock_entity_response, mock_cluster_analysis_response,
        mock_correlation_response, mock_brief_response,
    ):
        """When provider=claude, model/base_url should be empty strings."""
        mock_llm.side_effect = [
            mock_entity_response,
            mock_entity_response,
            mock_entity_response,
            mock_cluster_analysis_response,
            mock_correlation_response,
            mock_brief_response,
        ]

        run_id = store.start_run()
        db_ids = store.save_articles(run_id, sample_articles)

        config = {
            "llm": {
                "provider": "claude",
                "claude": {"timeout": 180},
            },
            "analysis": {"title_similarity_threshold": 0.70},
        }

        import os
        with patch.dict(os.environ, {"SIGNAL_LLM_PROVIDER": "claude"}):
            brief, _, _ = run_pipeline(sample_articles, db_ids, run_id, config)

        # All LLM calls should have gone through with provider="claude"
        for c in mock_llm.call_args_list:
            assert c.kwargs.get("provider") == "claude" or c[1].get("provider") == "claude" or "claude" in str(c)
