#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Analysis pipeline for Signal.

Five-pass architecture:
  Pass 1: Per-article entity extraction (fast model)
  Pass 2: Algorithmic clustering by entity overlap + title similarity
  Pass 3: Per-cluster cross-spectrum analysis (reasoning model)
  Pass 4: Cross-story correlation and pattern detection
  Pass 5: Final brief synthesis

All LLM calls go through Ollama running locally.
"""

from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import ollama
from rapidfuzz import fuzz
from rich.console import Console
from rich.progress import BarColumn, Progress, SpinnerColumn, TextColumn

from signal import store
from signal.prompts import (
    CLUSTER_ANALYSIS,
    CORRELATION_ANALYSIS,
    ENTITY_EXTRACTION,
    FINAL_BRIEF,
)

console = Console()


# ─────────────────────────────────────────────────────────────────────────────
# Ollama helpers
# ─────────────────────────────────────────────────────────────────────────────

def _llm_call(
    prompt: str,
    model: str,
    base_url: str = "http://localhost:11434",
    timeout: int = 120,
) -> str:
    """Make a single Ollama completion call; return raw text."""
    client = ollama.Client(host=base_url)
    response = client.generate(
        model=model,
        prompt=prompt,
        options={"temperature": 0.1, "num_predict": 2048},
    )
    return response.get("response", "")


def _parse_json_response(raw: str) -> Optional[Dict[str, Any]]:
    """
    Attempt to extract and parse a JSON object from LLM output.

    Handles common issues: markdown fences, leading text, trailing text.
    """
    # Strip markdown fences
    raw = re.sub(r"```(?:json)?", "", raw).strip()

    # Try direct parse
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass

    # Try to find a JSON object within the text
    match = re.search(r"\{[\s\S]*\}", raw)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            pass

    return None


# ─────────────────────────────────────────────────────────────────────────────
# Pass 1: Entity extraction
# ─────────────────────────────────────────────────────────────────────────────

def extract_entities(
    articles: List[Dict[str, Any]],
    run_id: int,
    article_db_ids: List[int],
    model: str,
    base_url: str,
    timeout: int,
) -> List[Dict[str, Any]]:
    """
    Run entity extraction on each article via the LLM.

    Updates the database with extracted fields and augments the article
    dicts in-place with extracted data.

    Args:
        articles: Raw article dicts from the collector.
        run_id: Current pipeline run id.
        article_db_ids: DB row ids corresponding to each article.
        model: Ollama model name.
        base_url: Ollama host.
        timeout: Request timeout seconds.

    Returns:
        Articles augmented with entities, key_claim, topic, sentiment, framing.
    """
    console.print(f"\n[bold cyan]Pass 1[/bold cyan] — Entity extraction ({len(articles)} articles)")

    with Progress(
        SpinnerColumn(),
        TextColumn("[cyan]{task.description}"),
        BarColumn(),
        TextColumn("{task.completed}/{task.total}"),
        console=console,
    ) as progress:
        task = progress.add_task("Extracting...", total=len(articles))

        for article, db_id in zip(articles, article_db_ids):
            content = (article.get("full_text") or article.get("text_snippet") or "")[:1500]
            prompt = ENTITY_EXTRACTION.format(
                title=article.get("title", ""),
                source_name=article.get("source_name", ""),
                bias=article.get("bias", "unknown"),
                content=content,
            )

            try:
                raw = _llm_call(prompt, model, base_url, timeout)
                parsed = _parse_json_response(raw)
            except Exception as exc:  # noqa: BLE001
                console.print(f"  [red]LLM error:[/red] {exc}")
                parsed = None

            if parsed:
                entities = parsed.get("entities", {})
                key_claim = parsed.get("key_claim", "")
                topic = parsed.get("topic", "other")
                sentiment = parsed.get("sentiment", "neutral")
                framing = parsed.get("framing", "")

                article["entities"] = entities
                article["key_claim"] = key_claim
                article["topic"] = topic
                article["sentiment"] = sentiment
                article["framing"] = framing

                store.update_article_analysis(
                    db_id, entities, key_claim, topic, sentiment, framing
                )
            else:
                article["entities"] = {"people": [], "organizations": [], "legislation": [], "locations": []}
                article["key_claim"] = article.get("title", "")
                article["topic"] = "other"
                article["sentiment"] = "neutral"
                article["framing"] = ""

            progress.advance(task)

    return articles


# ─────────────────────────────────────────────────────────────────────────────
# Pass 2: Algorithmic clustering
# ─────────────────────────────────────────────────────────────────────────────

def _entity_set(article: Dict[str, Any]) -> set[str]:
    """Flatten all entities for an article into a single set."""
    entities = article.get("entities", {})
    items: set[str] = set()
    for lst in entities.values():
        if isinstance(lst, list):
            for e in lst:
                if isinstance(e, str) and len(e) > 2:
                    items.add(e.lower().strip())
    return items


def cluster_articles(
    articles: List[Dict[str, Any]],
    run_id: int,
    title_threshold: float = 0.70,
    entity_overlap_min: int = 2,
) -> List[Dict[str, Any]]:
    """
    Group articles into story clusters using title similarity and entity overlap.

    Two articles are grouped if:
      - Their titles are >= title_threshold similar (rapidfuzz token_sort_ratio), OR
      - They share >= entity_overlap_min named entities

    Args:
        articles: Augmented articles from Pass 1.
        run_id: Current run id.
        title_threshold: Fuzzy match threshold (0–1).
        entity_overlap_min: Min shared entities to cluster.

    Returns:
        List of cluster dicts, each containing a list of member articles.
    """
    console.print(f"\n[bold cyan]Pass 2[/bold cyan] — Clustering {len(articles)} articles")

    n = len(articles)
    # Union-Find for efficient cluster assignment
    parent = list(range(n))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(x: int, y: int) -> None:
        parent[find(x)] = find(y)

    entity_sets = [_entity_set(a) for a in articles]

    for i in range(n):
        for j in range(i + 1, n):
            # Skip same source
            if articles[i]["source_name"] == articles[j]["source_name"]:
                continue

            # Title similarity
            title_sim = fuzz.token_sort_ratio(
                articles[i]["title"], articles[j]["title"]
            ) / 100.0
            if title_sim >= title_threshold:
                union(i, j)
                continue

            # Entity overlap
            overlap = entity_sets[i] & entity_sets[j]
            if len(overlap) >= entity_overlap_min:
                union(i, j)

    # Group by root
    groups: Dict[int, List[int]] = defaultdict(list)
    for i in range(n):
        groups[find(i)].append(i)

    clusters = []
    singletons = []

    for root, indices in groups.items():
        members = [articles[i] for i in indices]
        if len(members) < 2:
            singletons.append(members[0])
            continue

        # Representative title: most common words in titles
        all_titles = " ".join(m["title"] for m in members)
        title_words = [w for w in all_titles.split() if len(w) > 4]
        word_freq = Counter(title_words)
        story_title = members[0]["title"]  # fallback
        if word_freq:
            top_words = [w for w, _ in word_freq.most_common(5)]
            story_title = " ".join(top_words).title()

        bias_spread: Dict[str, int] = Counter(m["bias"] for m in members)  # type: ignore[assignment]

        db_ids = [m.get("_db_id") for m in members if m.get("_db_id")]
        cluster_id = store.save_cluster(run_id, story_title, db_ids, dict(bias_spread))

        clusters.append(
            {
                "cluster_id": cluster_id,
                "story_title": story_title,
                "articles": members,
                "bias_spread": dict(bias_spread),
                "source_count": len(members),
            }
        )

    # Add singletons as clusters of 1 (they still participate in correlation)
    for article in singletons:
        clusters.append(
            {
                "cluster_id": None,
                "story_title": article["title"],
                "articles": [article],
                "bias_spread": {article["bias"]: 1},
                "source_count": 1,
                "singleton": True,
            }
        )

    multi_clusters = [c for c in clusters if not c.get("singleton")]
    console.print(
        f"  [green]✓[/green] {len(multi_clusters)} story clusters, "
        f"{len(singletons)} singleton articles"
    )
    return clusters


# ─────────────────────────────────────────────────────────────────────────────
# Pass 3: Per-cluster analysis
# ─────────────────────────────────────────────────────────────────────────────

def _format_articles_for_cluster(articles: List[Dict[str, Any]]) -> str:
    """Format cluster articles for the cluster analysis prompt."""
    lines = []
    for a in articles:
        lines.append(
            f"[{a['bias'].upper()}] {a['source_name']}\n"
            f"  Title: {a['title']}\n"
            f"  Claim: {a.get('key_claim', a.get('text_snippet', '')[:200])}\n"
            f"  Framing: {a.get('framing', 'N/A')}"
        )
    return "\n\n".join(lines)


def analyze_clusters(
    clusters: List[Dict[str, Any]],
    run_id: int,
    model: str,
    base_url: str,
    timeout: int,
) -> List[Dict[str, Any]]:
    """
    Analyze each multi-source cluster for framing differences and omissions.

    Skips singleton clusters.

    Returns:
        Clusters augmented with 'analysis' key containing structured results.
    """
    multi = [c for c in clusters if not c.get("singleton") and len(c["articles"]) >= 2]
    console.print(f"\n[bold cyan]Pass 3[/bold cyan] — Cluster analysis ({len(multi)} clusters)")

    with Progress(
        SpinnerColumn(),
        TextColumn("[cyan]{task.description}"),
        BarColumn(),
        TextColumn("{task.completed}/{task.total}"),
        console=console,
    ) as progress:
        task = progress.add_task("Analyzing clusters...", total=len(multi))

        for cluster in multi:
            articles_fmt = _format_articles_for_cluster(cluster["articles"])
            prompt = CLUSTER_ANALYSIS.format(
                story_title=cluster["story_title"],
                count=len(cluster["articles"]),
                articles_formatted=articles_fmt,
            )

            try:
                raw = _llm_call(prompt, model, base_url, timeout)
                analysis = _parse_json_response(raw)
            except Exception as exc:  # noqa: BLE001
                console.print(f"  [red]LLM error:[/red] {exc}")
                analysis = None

            if analysis is None:
                analysis = {
                    "headline": cluster["story_title"],
                    "consensus_facts": [],
                    "contested_points": [],
                    "left_framing": "",
                    "right_framing": "",
                    "center_framing": "",
                    "left_omissions": "",
                    "right_omissions": "",
                    "assessment": "Analysis unavailable.",
                    "significance": "medium",
                }

            cluster["analysis"] = analysis

            if cluster.get("cluster_id"):
                store.save_cluster_analysis(run_id, cluster["cluster_id"], analysis)

            progress.update(task, description=f"[cyan]{cluster['story_title'][:50]}")
            progress.advance(task)

    return clusters


# ─────────────────────────────────────────────────────────────────────────────
# Pass 4: Cross-story correlation
# ─────────────────────────────────────────────────────────────────────────────

def _build_entity_network(clusters: List[Dict[str, Any]]) -> str:
    """
    Find entities appearing in 2+ separate clusters and format for prompt.
    """
    entity_to_clusters: Dict[str, List[str]] = defaultdict(list)

    for cluster in clusters:
        for article in cluster["articles"]:
            for entity_list in article.get("entities", {}).values():
                if isinstance(entity_list, list):
                    for e in entity_list:
                        if isinstance(e, str) and len(e) > 3:
                            entity_to_clusters[e].append(cluster["story_title"])

    cross_story = {
        entity: list(set(titles))
        for entity, titles in entity_to_clusters.items()
        if len(set(titles)) >= 2
    }

    if not cross_story:
        return "No cross-story entities detected."

    lines = []
    for entity, story_titles in sorted(cross_story.items(), key=lambda x: -len(x[1])):
        lines.append(f"  {entity}: appears in {len(story_titles)} stories ({', '.join(story_titles[:3])})")

    return "\n".join(lines[:30])  # cap for context window


def _get_blindspots(clusters: List[Dict[str, Any]]) -> Tuple[List[str], List[str]]:
    """
    Identify stories covered only by left-leaning or only by right-leaning outlets.

    Returns:
        Tuple of (left_only_titles, right_only_titles)
    """
    left_biases = {"left", "far-left", "center-left"}
    right_biases = {"right", "far-right", "center-right"}

    left_only = []
    right_only = []

    for cluster in clusters:
        biases = set(a["bias"] for a in cluster["articles"])
        has_left = bool(biases & left_biases)
        has_right = bool(biases & right_biases)
        has_center = "center" in biases or "libertarian" in biases

        if has_left and not has_right and not has_center:
            left_only.append(cluster["story_title"])
        elif has_right and not has_left and not has_center:
            right_only.append(cluster["story_title"])

    return left_only, right_only


def _format_cluster_summaries(clusters: List[Dict[str, Any]]) -> str:
    """Format analyzed clusters for the correlation prompt."""
    lines = []
    for cluster in clusters:
        if cluster.get("singleton"):
            continue
        analysis = cluster.get("analysis", {})
        headline = analysis.get("headline", cluster["story_title"])
        assessment = analysis.get("assessment", "")
        significance = analysis.get("significance", "medium")
        biases = ", ".join(
            f"{bias}({count})" for bias, count in cluster.get("bias_spread", {}).items()
        )
        lines.append(
            f"STORY: {headline} [significance: {significance}]\n"
            f"  Sources: {biases}\n"
            f"  Assessment: {assessment}"
        )
    return "\n\n".join(lines)


def correlate_stories(
    clusters: List[Dict[str, Any]],
    run_id: int,
    model: str,
    base_url: str,
    timeout: int,
) -> Dict[str, Any]:
    """
    Cross-story analysis: find patterns, connections, anomalies.

    This is the intelligence layer — where non-obvious relationships emerge.

    Returns:
        Structured correlation analysis dict.
    """
    console.print(f"\n[bold cyan]Pass 4[/bold cyan] — Cross-story correlation")

    stories_fmt = _format_cluster_summaries(clusters)
    entity_network = _build_entity_network(clusters)
    left_only, right_only = _get_blindspots(clusters)
    prev_watch = store.get_previous_watch_list(run_id)

    prompt = CORRELATION_ANALYSIS.format(
        stories_formatted=stories_fmt,
        entity_network=entity_network,
        left_only=", ".join(left_only) if left_only else "None identified",
        right_only=", ".join(right_only) if right_only else "None identified",
        previous_watch_list=", ".join(prev_watch) if prev_watch else "No previous run",
    )

    try:
        raw = _llm_call(prompt, model, base_url, timeout)
        analysis = _parse_json_response(raw)
    except Exception as exc:  # noqa: BLE001
        console.print(f"  [red]LLM error:[/red] {exc}")
        analysis = None

    if analysis is None:
        analysis = {
            "hidden_connections": [],
            "narrative_patterns": [],
            "anomalies": [],
            "blindspot_analysis": "Analysis unavailable.",
            "recommended_watch": [],
            "delta_from_previous": "N/A",
        }

    # Attach blindspot data for reporting
    analysis["_left_only"] = left_only
    analysis["_right_only"] = right_only

    store.save_correlation_analysis(run_id, analysis)
    console.print("  [green]✓[/green] Correlation analysis complete")
    return analysis


# ─────────────────────────────────────────────────────────────────────────────
# Pass 5: Final brief synthesis
# ─────────────────────────────────────────────────────────────────────────────

def synthesize_brief(
    clusters: List[Dict[str, Any]],
    correlation: Dict[str, Any],
    articles: List[Dict[str, Any]],
    model: str,
    base_url: str,
    timeout: int,
) -> str:
    """
    Generate the final analyst brief from all analysis passes.

    Returns:
        The brief as a markdown string.
    """
    console.print(f"\n[bold cyan]Pass 5[/bold cyan] — Brief synthesis")

    stories_fmt = "\n\n".join(
        f"## {c.get('analysis', {}).get('headline', c['story_title'])}\n"
        f"Significance: {c.get('analysis', {}).get('significance', 'medium')}\n"
        f"Assessment: {c.get('analysis', {}).get('assessment', '')}\n"
        f"Left omissions: {c.get('analysis', {}).get('left_omissions', '')}\n"
        f"Right omissions: {c.get('analysis', {}).get('right_omissions', '')}"
        for c in clusters
        if not c.get("singleton")
    )

    correlation_fmt = json.dumps(
        {k: v for k, v in correlation.items() if not k.startswith("_")},
        indent=2,
    )

    source_names = list({a["source_name"] for a in articles})

    prompt = FINAL_BRIEF.format(
        correlation_analysis=correlation_fmt,
        story_analyses=stories_fmt[:6000],  # cap for context
        collection_date=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        article_count=len(articles),
        source_count=len(source_names),
    )

    try:
        raw = _llm_call(prompt, model, base_url, min(timeout * 3, 360))
        brief = raw.strip()
    except Exception as exc:  # noqa: BLE001
        console.print(f"  [red]LLM error:[/red] {exc}")
        brief = "Brief synthesis failed. Check Ollama connection."

    store.save_brief(run_id=0, brief_text=brief)
    console.print("  [green]✓[/green] Brief complete")
    return brief


# ─────────────────────────────────────────────────────────────────────────────
# Pipeline entry point
# ─────────────────────────────────────────────────────────────────────────────

def run_pipeline(
    articles: List[Dict[str, Any]],
    article_db_ids: List[int],
    run_id: int,
    config: Dict[str, Any],
) -> Tuple[str, List[Dict[str, Any]], Dict[str, Any]]:
    """
    Execute the full analysis pipeline.

    Args:
        articles: Raw articles from the collector.
        article_db_ids: Corresponding DB ids.
        run_id: Current run id.
        config: Loaded sources.yaml config.

    Returns:
        Tuple of (brief_text, clusters, correlation_analysis)
    """
    ollama_cfg = config.get("ollama", {})
    model = ollama_cfg.get("model", "llama3.1:8b")
    analysis_model = ollama_cfg.get("analysis_model", model)
    base_url = ollama_cfg.get("base_url", "http://localhost:11434")
    timeout = ollama_cfg.get("timeout", 120)

    clustering_cfg = config.get("analysis", {})
    title_threshold = clustering_cfg.get("title_similarity_threshold", 0.70)

    # Attach db ids to articles for cluster formation
    for article, db_id in zip(articles, article_db_ids):
        article["_db_id"] = db_id

    # Pass 1
    articles = extract_entities(articles, run_id, article_db_ids, model, base_url, timeout)

    # Pass 2
    clusters = cluster_articles(articles, run_id, title_threshold=title_threshold)

    # Pass 3
    clusters = analyze_clusters(clusters, run_id, analysis_model, base_url, timeout)

    # Pass 4
    correlation = correlate_stories(clusters, run_id, analysis_model, base_url, timeout)

    # Pass 5
    brief = synthesize_brief(clusters, correlation, articles, analysis_model, base_url, timeout)

    # Fix the run_id in the brief store call
    store.save_brief(run_id, brief)

    return brief, clusters, correlation
