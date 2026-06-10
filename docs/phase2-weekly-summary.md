# Phase 2 — Weekly Intelligence Summary

> **Note:** Historical design spec from May 2026. Implemented schedule is **Monday 6:00 AM** (not Sunday 11:00 PM). See wiki Weekly-Reports and Scheduling pages for current docs.

## Concept

At the end of each week, synthesize all daily briefs into a single weekly report.
The weekly brief is where the real intelligence value emerges — it captures how stories
evolved, what escalated, what dropped off, and what the dominant pattern of the week was.
No single daily run can see this; it requires looking across the full corpus.

---

## Implementation Plan

### 1. New CLI flag

```bash
python3 main.py --weekly
```

Triggers a separate pipeline path that reads from the database rather than fetching
new articles.

### 2. Data source

All the data needed already exists in the DB from daily runs:

| Table | What it provides |
| --- | --- |
| `cluster_analyses` | Per-story framing, omissions, significance ratings |
| `correlation_analyses` | Hidden connections, narrative patterns, anomalies |
| `briefs` | Final analyst text for each day |
| `runs` | Timestamps to scope to the past 7 days |

No new article fetching or entity extraction needed — Pass 1 and Pass 2 are skipped entirely.

### 3. New Pass 6 prompt

A single LLM call over the week's aggregated data:

- How did each major story evolve day-by-day?
- Which watch list items from Monday materialised by Friday?
- What narrative patterns persisted across the full week?
- What stories dominated early in the week and then disappeared?
- What was the single most significant under-reported story of the week?
- What should be on the watch list going into next week?

### 4. New report template

`weekly_YYYYWNN.html` — same dark theme, different section structure:

- **WEEK IN REVIEW** — the dominant political dynamic of the week
- **STORY ARC TRACKER** — how the top 5 stories evolved day by day
- **WHAT ESCALATED** — items that grew in significance across the week
- **WHAT WAS BURIED** — stories that appeared then vanished from coverage
- **WATCH LIST REVIEW** — how last week's watch list items played out
- **WATCH LIST: NEXT WEEK** — forward-looking items

### 5. Scheduling

A second launchd plist firing Sunday at 11:00 PM:

```xml
<key>StartCalendarInterval</key>
<dict>
    <key>Weekday</key>
    <integer>0</integer>   <!-- 0 = Sunday -->
    <key>Hour</key>
    <integer>23</integer>
    <key>Minute</key>
    <integer>0</integer>
</dict>
```

### 6. Archive integration

`archive.html` updated to show daily and weekly reports in separate sections,
with weekly reports visually distinguished (different badge/color).

---

## Key Design Decisions for Phase 2

**Read from DB, not files** — the structured JSON in `cluster_analyses` and
`correlation_analyses` is richer than re-parsing the HTML reports. Use that directly.

**One LLM call, not many** — unlike daily Pass 1 (one call per article), the weekly
synthesis is a single large-context call. Claude will outperform Ollama here due to
the larger context window needed.

**Delta tracking is the core value** — the weekly brief is not a summary of summaries.
It is specifically about *change over time*: what moved, what didn't, what that pattern means.
The prompt must be written to force this framing.

**Keep it separate from daily** — weekly runs write to their own table (`weekly_briefs`)
and generate their own HTML file series. No mixing with daily report filenames.

---

## Files to Create in Phase 2

```bash
pipeline/
  weekly.py          # Pass 6 logic — reads DB, calls LLM, returns brief
  prompts.py         # Add WEEKLY_BRIEF prompt constant

main.py              # Add --weekly flag and routing

pipeline/
  reporter.py        # Add generate_weekly_report() function

signal.db            # Add weekly_briefs table (schema migration)

scripts/
  com.flexrpl.signal.weekly.plist   # launchd entry for Sunday nights

docs/
  phase2-weekly-summary.md          # this file
```
