#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Pass 6 — Weekly intelligence summary.

Reads the past N days of daily briefs and correlation analyses from the
database and synthesizes a single weekly intelligence brief via one LLM call.

No article fetching or entity extraction is performed — this pass works
entirely from previously stored analysis.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from datetime import datetime, timezone
from typing import Any, Dict, List, Tuple

import ollama
from rich.console import Console

from pipeline import store
from pipeline.prompts import WEEKLY_BRIEF

console = Console()

_SECTION_HEADERS = [
    "SITUATION OVERVIEW",
    "KEY ACTORS AND DYNAMICS",
    "WHAT ISN'T BEING SAID",
    "CONNECTIONS AND PATTERNS",
    "WATCH LIST",
    "ANALYST NOTE",
]


def _extract_section(brief_text: str, section: str) -> str:
    """Extract a named ## section from a markdown brief."""
    pattern = rf"##\s+{re.escape(section)}\s*\n([\s\S]*?)(?=\n##\s|\Z)"
    match = re.search(pattern, brief_text, re.IGNORECASE)
    return match.group(1).strip() if match else ""


def _build_daily_data(runs: List[Dict[str, Any]]) -> str:
    """
    Format each day's brief into a condensed summary for the weekly prompt.

    Uses only SITUATION OVERVIEW, WATCH LIST, and ANALYST NOTE from each
    daily brief to keep the context window manageable.
    """
    sections = []
    for run in runs:
        date_str = run["started_at"][:10]
        brief = run["brief_text"]

        situation = _extract_section(brief, "SITUATION OVERVIEW")
        analyst_note = _extract_section(brief, "ANALYST NOTE")
        watch = _extract_section(brief, "WATCH LIST")

        patterns = run.get("narrative_patterns", [])
        anomalies = run.get("anomalies", [])

        block = f"=== {date_str} ({run.get('article_count', 0)} articles) ===\n"
        if situation:
            block += f"\nSITUATION:\n{situation[:800]}\n"
        if watch:
            block += f"\nWATCH LIST:\n{watch[:400]}\n"
        if patterns:
            block += "\nNARRATIVE PATTERNS:\n" + "\n".join(f"- {p}" for p in patterns[:3]) + "\n"
        if anomalies:
            block += "\nANOMALIES:\n" + "\n".join(f"- {a}" for a in anomalies[:2]) + "\n"
        if analyst_note:
            block += f"\nANALYST NOTE:\n{analyst_note[:400]}\n"

        sections.append(block)

    return "\n\n".join(sections)


def _build_watch_list_evolution(runs: List[Dict[str, Any]]) -> str:
    """
    Format the watch list from each day to show how items evolved across the week.
    """
    lines = []
    for run in runs:
        date_str = run["started_at"][:10]
        items = run.get("watch_list", [])
        if items:
            lines.append(f"{date_str}: " + " | ".join(str(i) for i in items[:5]))
        delta = run.get("delta", "")
        if delta and delta not in ("N/A", "No previous run"):
            lines.append(f"  → Delta: {delta[:200]}")
    return "\n".join(lines) if lines else "Insufficient data for watch list evolution."


_TRANSIENT_CLAUDE_ERRORS = (
    "stream idle timeout",
    "connection closed mid-response",
    "connection reset",
    "broken pipe",
    "eof",
)


def _is_retryable_claude_error(detail: str) -> bool:
    """Return True for transient Claude CLI failures worth retrying."""
    lowered = detail.lower()
    return any(token in lowered for token in _TRANSIENT_CLAUDE_ERRORS)


def _llm_call_claude(prompt: str, timeout: int, attempts: int = 3) -> str:
    """Call Claude Code CLI; retry on transient stream/connection errors."""
    claude_bin = shutil.which("claude") or "/opt/homebrew/bin/claude"
    last_error = ""
    for attempt in range(attempts):
        result = subprocess.run(
            [claude_bin, "-p", prompt, "--print"],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        if result.returncode == 0:
            return result.stdout.strip()
        detail = result.stderr.strip() or result.stdout.strip() or "Claude CLI non-zero exit"
        last_error = detail
        if not _is_retryable_claude_error(detail) or attempt >= attempts - 1:
            raise RuntimeError(detail)
    raise RuntimeError(last_error)


def _llm_call(prompt: str, config: Dict[str, Any]) -> str:
    """Dispatch the weekly synthesis LLM call to the configured provider."""
    llm_cfg = config.get("llm", {})
    provider = os.environ.get("SIGNAL_LLM_PROVIDER", llm_cfg.get("provider", "claude"))

    if provider == "claude":
        timeout = llm_cfg.get("claude", {}).get("timeout", 180)
        return _llm_call_claude(prompt, timeout=timeout * 3)

    # Ollama fallback
    ollama_cfg = llm_cfg.get("ollama", {})
    model = ollama_cfg.get("model", "qwen2.5:14b")
    base_url = ollama_cfg.get("base_url", "http://localhost:11434")
    client = ollama.Client(host=base_url)
    response = client.generate(
        model=model,
        prompt=prompt,
        options={"temperature": 0.1, "num_predict": 4096},
    )
    return response.get("response", "")


def run_weekly(
    config: Dict[str, Any],
    days: int = 7,
) -> Tuple[str, Dict[str, Any]]:
    """
    Execute the weekly intelligence synthesis (Pass 6).

    Reads the past `days` days of complete runs from the database,
    builds a structured summary, and makes a single LLM call to produce
    the weekly brief.

    Args:
        config: Loaded sources.yaml config.
        days: Number of past days to include (default 7).

    Returns:
        Tuple of (brief_text, metadata dict).
    """
    console.print("\n[bold cyan]▸ SIGNAL[/bold cyan] [dim]— Weekly Intelligence Summary[/dim]\n")

    # Pull qualifying runs
    store.init_db()
    runs = store.get_runs_for_weekly(days)

    if not runs:
        raise RuntimeError(
            f"No complete runs with briefs found in the past {days} days. "
            "Run the daily pipeline at least once before generating a weekly summary."
        )

    run_ids = [r["id"] for r in runs]
    console.print(f"[dim]Found {len(runs)} daily run(s) for the past {days} days[/dim]")

    # Enrich with brief text and correlation data
    enriched = store.get_weekly_source_data(run_ids)

    if not enriched:
        raise RuntimeError("No brief data found for the qualifying runs.")

    week_start = enriched[0]["started_at"][:10]
    week_end = enriched[-1]["started_at"][:10]

    console.print(f"[dim]Week: {week_start} → {week_end}[/dim]\n")

    # Build prompt inputs
    daily_data = _build_daily_data(enriched)
    watch_list_evolution = _build_watch_list_evolution(enriched)

    prompt = WEEKLY_BRIEF.format(
        day_count=len(enriched),
        week_start=week_start,
        week_end=week_end,
        daily_data=daily_data,
        watch_list_evolution=watch_list_evolution,
    )

    # Pass 6 — single LLM call
    console.print("[bold cyan]Pass 6[/bold cyan] — Weekly synthesis (single LLM call)...")
    try:
        brief_text = _llm_call(prompt, config)
        console.print("  [green]✓[/green] Weekly brief complete\n")
    except Exception as exc:  # noqa: BLE001
        console.print(f"  [red]✗[/red] LLM error: {exc}")
        raise

    # Persist
    weekly_id = store.save_weekly_brief(week_start, week_end, run_ids, brief_text)

    metadata = {
        "weekly_id": weekly_id,
        "week_start": week_start,
        "week_end": week_end,
        "run_ids": run_ids,
        "day_count": len(enriched),
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
    }

    return brief_text, metadata
