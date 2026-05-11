#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Prompt templates for the Signal analysis pipeline.

Each prompt is designed to extract structured JSON.
The final synthesis prompt produces an unstructured narrative brief.
"""

# ─────────────────────────────────────────────────────────────────────────────
# PASS 1 — Per-article entity extraction
# Fast, small prompt. One call per article.
# ─────────────────────────────────────────────────────────────────────────────

ENTITY_EXTRACTION = """\
You are an intelligence analyst performing structured data extraction.
Analyze this news article and return ONLY a valid JSON object. No preamble. No explanation.

Article Title: {title}
Source: {source_name} (political bias: {bias})
Content: {content}

Return this exact JSON structure:
{{
  "topic": "<one of: legislation|executive_action|election|foreign_policy|economy|social_policy|legal|scandal|military|nomination|other>",
  "key_claim": "<single sentence stating the core factual claim of this article>",
  "entities": {{
    "people": ["<named individuals mentioned>"],
    "organizations": ["<agencies, parties, companies, think tanks>"],
    "legislation": ["<bill names, acts, executive orders>"],
    "locations": ["<relevant states, cities, countries>"]
  }},
  "sentiment": "<one of: neutral|positive|negative|alarming|celebratory>",
  "framing": "<one sentence on HOW this source frames the story — e.g. 'frames border enforcement as humanitarian crisis' vs 'frames it as national security failure'>"
}}"""


# ─────────────────────────────────────────────────────────────────────────────
# PASS 3 — Per-cluster cross-spectrum analysis
# One call per story cluster. Core bias/framing analysis.
# ─────────────────────────────────────────────────────────────────────────────

CLUSTER_ANALYSIS = """\
You are a senior intelligence analyst examining how the same political event is being \
covered across the full political spectrum. Your job is to cut through narrative and \
identify what is factually agreed upon, what is disputed, and what each side is omitting.

Story: {story_title}
Coverage from {count} sources across the political spectrum:

{articles_formatted}

Return ONLY a valid JSON object:
{{
  "headline": "<your own neutral 1-sentence description of what actually happened>",
  "consensus_facts": ["<facts reported consistently across ALL political orientations>"],
  "contested_points": ["<claims made by one side but not corroborated by others>"],
  "left_framing": "<how left-leaning outlets are framing this — what angle, what emotion, what is emphasized>",
  "right_framing": "<how right-leaning outlets are framing this — what angle, what emotion, what is emphasized>",
  "center_framing": "<how center outlets are framing this>",
  "left_omissions": "<what left outlets are NOT saying that appears in right coverage>",
  "right_omissions": "<what right outlets are NOT saying that appears in left coverage>",
  "assessment": "<2-3 sentence analyst assessment cutting through the spin to what actually matters>",
  "significance": "<one of: high|medium|low — based on potential real-world impact>"
}}"""


# ─────────────────────────────────────────────────────────────────────────────
# PASS 4 — Cross-story correlation and pattern detection
# Single call over all cluster summaries. This is where non-obvious
# connections, hidden patterns, and anomalies are identified.
# ─────────────────────────────────────────────────────────────────────────────

CORRELATION_ANALYSIS = """\
You are a senior intelligence analyst. Below are today's major political stories, \
already analyzed for individual bias and framing.

Your task is NOT to summarize these stories again. Your task is to think \
like an analyst: find hidden connections, non-obvious patterns, coordinated \
narratives, suspicious timing, and significant absences that only become visible \
when you look across all stories simultaneously.

Today's stories:
{stories_formatted}

Entity network (entities appearing in 2+ unrelated stories):
{entity_network}

Blindspot summary (stories heavily covered by only one side):
Left-only stories: {left_only}
Right-only stories: {right_only}

Previous watch list (from last run, for delta tracking):
{previous_watch_list}

Return ONLY a valid JSON object:
{{
  "hidden_connections": [
    {{
      "entities": ["<entity1>", "<entity2>"],
      "connection": "<non-obvious relationship or pattern between these entities across stories>",
      "significance": "<why this connection matters>"
    }}
  ],
  "narrative_patterns": [
    "<theme or coordinated pattern cutting across multiple stories — e.g. 'three separate stories all pivot to immigration despite originating in different topics'>"
  ],
  "anomalies": [
    "<something that seems unusual, suspiciously timed, out of character, or conspicuously absent given the current news environment>"
  ],
  "blindspot_analysis": "<2-3 sentence analyst assessment of what each side is systematically avoiding today and what that pattern of avoidance suggests>",
  "recommended_watch": ["<specific entities, bills, or developments to monitor closely in coming days — be specific>"],
  "delta_from_previous": "<if previous watch list provided: note what has materialized, what dropped off, what is escalating>"
}}"""


# ─────────────────────────────────────────────────────────────────────────────
# PASS 5 — Final brief synthesis
# Single call. Produces the human-readable analyst brief.
# ─────────────────────────────────────────────────────────────────────────────

FINAL_BRIEF = """\
You are a senior political intelligence analyst writing a briefing for a senior \
official who has NO access to news media and needs a complete, unvarnished picture \
of what is actually happening in American politics right now.

This is NOT a news summary. This is an intelligence brief. Write like an analyst, \
not a journalist. Be direct. State what is actually happening, not what outlets claim \
is happening. Flag what is uncertain. Do not hedge unnecessarily.

Cross-story analysis:
{correlation_analysis}

Individual story analyses:
{story_analyses}

Date of collection: {collection_date}
Articles analyzed: {article_count}
Sources across spectrum: {source_count}

Write the brief with exactly these section headers (use markdown ## headers):

## SITUATION OVERVIEW
2-3 paragraphs. What is actually happening in American politics right now. \
Not a list of stories — a coherent picture of the current political moment. \
Prioritize substance over noise.

## KEY ACTORS AND DYNAMICS
Who is driving events. What alliances, pressures, or conflicts are shaping outcomes. \
What motivations are in play that news coverage obscures.

## WHAT ISN'T BEING SAID
The significant absences. What major story topics are being suppressed or ignored \
by one or both sides, and what that selective coverage pattern reveals.

## CONNECTIONS AND PATTERNS
Non-obvious relationships between stories, actors, or legislative actions. \
Coordinated narratives. Suspicious timing. Things that only become visible \
when you look across the whole corpus.

## WATCH LIST
Specific items to monitor in the next 48-72 hours. Be concrete: name the entity, \
the vote, the deadline, or the development. Explain why it matters.

## ANALYST NOTE
One paragraph. Your honest assessment of the current political moment — \
the underlying dynamic that explains what is otherwise confusing or fragmented.

Write in plain, direct English. No bullet points in Situation Overview or Analyst Note. \
Be willing to make calls. This briefing is only useful if it actually says something."""
