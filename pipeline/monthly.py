#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Pass 7 — Monthly intelligence summary.

Reads daily briefs and weekly summaries for a calendar month from the
database and synthesizes a single monthly intelligence brief via one LLM call.
"""

from __future__ import annotations

from calendar import monthrange
from datetime import datetime, timezone
from typing import Any, Dict, List, Tuple

from rich.console import Console

from pipeline import store
from pipeline.prompts import MONTHLY_BRIEF
from pipeline.weekly import (
    _build_watch_list_evolution,
    _extract_section,
    _llm_call,
)

console = Console()

_WEEKLY_SECTIONS = (
    "WEEK IN REVIEW",
    "WHAT ESCALATED",
    "WHAT WAS BURIED",
    "BLINDSPOT OF THE WEEK",
    "WATCH LIST: NEXT WEEK",
)


def _parse_month(month: str) -> Tuple[int, int]:
    """Parse YYYY-MM into (year, month)."""
    try:
        dt = datetime.strptime(month, "%Y-%m")
    except ValueError as exc:
        raise ValueError(f"Invalid --month value {month!r}; use YYYY-MM") from exc
    return dt.year, dt.month


def _month_bounds(year: int, month: int) -> Tuple[str, str, str]:
    """Return (month_label, month_start, month_end) for a calendar month."""
    _, last_day = monthrange(year, month)
    month_start = f"{year:04d}-{month:02d}-01"
    month_end = f"{year:04d}-{month:02d}-{last_day:02d}"
    month_label = datetime(year, month, 1).strftime("%B %Y")
    return month_label, month_start, month_end


def _build_weekly_summaries(weeklies: List[Dict[str, Any]]) -> str:
    """Condense weekly briefs into blocks for the monthly prompt."""
    if not weeklies:
        return "No weekly summaries available for this month."

    blocks = []
    for weekly in weeklies:
        brief = weekly["brief_text"]
        block = (
            f"=== Week {weekly['week_start']} → {weekly['week_end']} ===\n"
        )
        for section in _WEEKLY_SECTIONS:
            content = _extract_section(brief, section)
            if content:
                block += f"\n{section}:\n{content[:900]}\n"
        blocks.append(block)
    return "\n\n".join(blocks)


def _build_monthly_daily_data(runs: List[Dict[str, Any]]) -> str:
    """Format daily runs with tighter limits for month-scale context."""
    sections = []
    for run in runs:
        date_str = run["started_at"][:10]
        brief = run["brief_text"]

        situation = _extract_section(brief, "SITUATION OVERVIEW")
        watch = _extract_section(brief, "WATCH LIST")
        analyst_note = _extract_section(brief, "ANALYST NOTE")

        block = f"=== {date_str} ({run.get('article_count', 0)} articles) ===\n"
        if situation:
            block += f"\nSITUATION:\n{situation[:350]}\n"
        if watch:
            block += f"\nWATCH LIST:\n{watch[:150]}\n"
        if analyst_note:
            block += f"\nANALYST NOTE:\n{analyst_note[:200]}\n"
        sections.append(block)
    return "\n\n".join(sections)


def run_monthly(
    config: Dict[str, Any],
    month: str,
) -> Tuple[str, Dict[str, Any]]:
    """
    Execute the monthly intelligence synthesis (Pass 7).

    Args:
        config: Loaded sources.yaml config.
        month: Calendar month as YYYY-MM (e.g. 2026-05).

    Returns:
        Tuple of (brief_text, metadata dict).
    """
    year, month_num = _parse_month(month)
    month_label, month_start, month_end = _month_bounds(year, month_num)

    console.print(
        "\n[bold cyan]▸ SIGNAL[/bold cyan] [dim]— Monthly Intelligence Summary[/dim]\n"
    )

    store.init_db()
    runs = store.get_runs_for_month(year, month_num)
    if not runs:
        raise RuntimeError(
            f"No complete daily runs found for {month_label}. "
            "Run the daily pipeline before generating a monthly summary."
        )

    run_ids = [r["id"] for r in runs]
    enriched = store.get_weekly_source_data(run_ids)
    if not enriched:
        raise RuntimeError("No brief data found for the qualifying runs.")

    weeklies = store.get_weekly_briefs_for_month(year, month_num)
    weekly_ids = [w["id"] for w in weeklies]

    data_start = enriched[0]["started_at"][:10]
    data_end = enriched[-1]["started_at"][:10]
    partial = data_start > month_start or data_end < month_end

    partial_note = ""
    if partial:
        partial_note = (
            f"NOTE: This is a PARTIAL month — daily coverage runs from {data_start} "
            f"to {data_end}, not the full calendar month. Label your analysis accordingly "
            f"and avoid implying completeness you do not have."
        )

    console.print(f"[dim]Month: {month_label}[/dim]")
    console.print(
        f"[dim]{len(enriched)} daily run(s), {len(weeklies)} weekly summar"
        f"{'ies' if len(weeklies) != 1 else 'y'}[/dim]"
    )
    if partial:
        console.print(
            f"[yellow]Partial coverage: {data_start} → {data_end}[/yellow]\n"
        )
    else:
        console.print("")

    weekly_summaries = _build_weekly_summaries(weeklies)
    daily_data = _build_monthly_daily_data(enriched)
    watch_list_evolution = _build_watch_list_evolution(enriched)

    prompt = MONTHLY_BRIEF.format(
        month_label=month_label,
        month_start=data_start if partial else month_start,
        month_end=data_end if partial else month_end,
        partial_note=partial_note,
        day_count=len(enriched),
        weekly_summaries=weekly_summaries,
        daily_data=daily_data,
        watch_list_evolution=watch_list_evolution,
    )

    console.print("[bold cyan]Pass 7[/bold cyan] — Monthly synthesis (single LLM call)...")
    try:
        brief_text = _llm_call(prompt, config)
        console.print("  [green]✓[/green] Monthly brief complete\n")
    except Exception as exc:  # noqa: BLE001
        console.print(f"  [red]✗[/red] LLM error: {exc}")
        raise

    monthly_id = store.save_monthly_brief(
        month_label=month_label,
        month_start=data_start if partial else month_start,
        month_end=data_end if partial else month_end,
        run_ids=run_ids,
        weekly_ids=weekly_ids,
        brief_text=brief_text,
        partial=partial,
    )

    metadata = {
        "monthly_id": monthly_id,
        "month": f"{year:04d}-{month_num:02d}",
        "month_label": month_label,
        "month_start": data_start if partial else month_start,
        "month_end": data_end if partial else month_end,
        "calendar_start": month_start,
        "calendar_end": month_end,
        "partial": partial,
        "run_ids": run_ids,
        "weekly_ids": weekly_ids,
        "day_count": len(enriched),
        "weekly_count": len(weeklies),
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
    }
    return brief_text, metadata
