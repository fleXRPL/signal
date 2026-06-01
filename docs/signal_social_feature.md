# Signal — Social Media Posting Feature

> **Operations (all shell commands):** [social-cards-setup.md](social-cards-setup.md) · Wiki: [Social-Cards](https://github.com/fleXRPL/signal.wiki/wiki/Social-Cards)

## Overview

Extend the existing Signal political intelligence pipeline to automatically generate
infographic cards and post them to Bluesky three times daily. The pipeline already
runs via `main.py` on a launchd schedule each morning. This feature adds card image
generation and three timed social posts as downstream steps.

Everything runs locally on the Mac. No cloud infrastructure. Credentials stay on
the machine.

---

## Goals

- Generate three visually consistent infographic cards per daily run
- Post each card to Bluesky at scheduled times with short teaser copy
- Drive traffic to the full report on GitHub Pages
- Build a predictable daily posting cadence that creates audience habit

---

## Post Schedule

| Slot | Time     | Card Type          | Purpose                                     |
| ---- | -------- | ------------------ | ------------------------------------------- |
| AM   | 7:00 AM  | Watch List         | Sets the daily agenda — what to track       |
| Noon | 12:00 PM | Spectrum Breakdown | Top story, all sides — main analytical post |
| PM   | 6:00 PM  | Blindspot Analysis | What your feed missed today                 |

Each slot is fired by a separate launchd plist. `main.py` generates all three card
images and post packages in the morning run. The noon and PM jobs simply load
pre-generated files and post — no model or rendering work at post time.

---

## Repository Changes

### New Files

```bash
pipeline/
  infographic.py              # Playwright renderer — HTML template → PNG
  social.py                   # Bluesky auth, image upload, post
  templates/
    card_watch.html           # AM watch list card template
    card_spectrum.html        # Noon spectrum breakdown card template
    card_blindspot.html       # PM blindspot analysis card template

post_scheduled.py             # CLI dispatcher: --slot [am|noon|pm]
launchd/
  signal.social.am.plist      # 7:00 AM launchd job
  signal.social.noon.plist    # 12:00 PM launchd job
  signal.social.pm.plist      # 6:00 PM launchd job
```

### Modified Files

```bash
main.py                       # Add card generation step after report generation
requirements.txt              # Add: playwright, atproto, python-dotenv
.env.example                  # Document required environment variables
.gitignore                    # Ensure .env is excluded
```

### New Output Structure

```bash
reports/
  cards/
    am_20260530.png
    noon_20260530.png
    pm_20260530.png
  posts/
    am_20260530.json
    noon_20260530.json
    pm_20260530.json
```

---

## Card Specifications

All cards render at **1200×630px** (standard social share ratio). Dark theme
matching the Signal site aesthetic. Each card includes the Signal wordmark,
date, source count, and the full report URL in the footer.

### Card 1 — Watch List (AM)

**Data source:** `watch_list` array from the brief synthesis output

**Layout:**

- Header bar: Signal branding + date + "Watch List" label
- Subheader: count of active tracking items + time horizon summary
- Body: 2-column grid of watch items, each showing:
  - Time window badge (24hr / 48hr / 72hr / 5-day), color-coded by urgency
    - 24hr → red
    - 48hr → orange
    - 72hr → amber
    - 5-day → green
  - One-sentence description of what to watch and why it matters
- Footer: `flexrpl.github.io/signal` URL + brief stats

**Post text formula:**

```bash
SIGNAL // {date}

{N} items on today's watch list — from {shortest window} to {longest window}.

Full brief → flexrpl.github.io/signal
```

---

### Card 2 — Spectrum Breakdown (Noon)

**Data source:** Top-ranked story cluster from the brief (highest article count
or highest cross-spectrum coverage — whichever Signal already computes)

**Layout:**

- Header bar: Signal branding + date + article/source counts
- Story block: Cluster headline with left red border accent
- Spectrum bar: Visual proportional bar showing source distribution across
  far-left / left / center-left / center / center-right / right / far-right,
  with color coding:
  - Far-left: purple
  - Left: blue
  - Center-left: light blue
  - Center: gray
  - Center-right: light orange
  - Right: red
  - Far-right: dark red
- Coverage columns (3-up grid):
  - Left frame: summary of how left-aligned outlets covered it + source tags
  - Center frame: summary of how center outlets covered it + source tags
  - Right frame: summary of how right-aligned outlets covered it + source tags
- Omissions row (2-up): "Left omits" and "Right omits" one-liners
- Footer: report URL + "Full brief · {N} story clusters · Watch list inside"

**Post text formula:**

```bash
SIGNAL // {date}

{Story headline — truncated to ~120 chars if needed}

Left, center, and right are covering this — but not the same story.

Full analysis → flexrpl.github.io/signal
```

---

### Card 3 — Blindspot Analysis (PM)

**Data source:** `blindspot_analysis` section from the brief — specifically the
left-only and right-only story lists

**Layout:**

- Header bar: Signal branding + date + "Blindspot Analysis" label
- Subheader: Most significant suppression story (the one called out in the
  brief's blindspot narrative, not just any left/right-only item)
- Body: 2-column grid
  - Left column (blue): Left-only stories — stories the right isn't covering
  - Right column (red): Right-only stories — stories the left isn't covering
  - Each column shows 3–4 story headlines as stacked cards
  - Column headers show story count
- Footer: report URL + "Cross-spectrum · {N} sources · Full analysis inside"

**Post text formula:**

```bash
SIGNAL // {date}

Today's blindspot: {one-line description of biggest suppressed story}

What each side isn't showing you → flexrpl.github.io/signal
```

---

## Implementation Detail

### `infographic.py`

Responsibilities:

- Accept structured data extracted from the brief (dict)
- Select the appropriate HTML template for the requested card type
- Inject data into the template via Jinja2 string substitution or direct
  DOM manipulation (whichever is simpler given the template structure)
- Launch Playwright headless Chromium
- Render the template at 1200×630 viewport
- Screenshot to PNG
- Return the output path

```python
# Rough interface
def render_card(card_type: str, data: dict, output_path: str) -> str:
    """
    card_type: 'am' | 'noon' | 'pm'
    data: extracted brief data for this card type
    output_path: where to write the PNG
    returns: output_path on success
    """
```

Dependencies:

- `playwright` (install via `pip install playwright && playwright install chromium`)
- Templates are static HTML/CSS files — no JS framework, no build step

---

### `social.py`

Responsibilities:

- Authenticate to Bluesky using app password (never the real account password)
- Upload image blob
- Compose post with text, image, and embedded link card pointing to the report
- Post and return the post URI for logging

```python
# Rough interface
def post_to_bluesky(text: str, image_path: str, report_url: str) -> str:
    """
    Returns the post URI on success
    """
```

Authentication:

- Credentials loaded from `.env` via `python-dotenv`
- Required env vars:
  - `BLUESKY_HANDLE` — the account handle (e.g. `signal.bsky.social`)
  - `BLUESKY_APP_PASSWORD` — app password generated in Bluesky settings
    (Settings → Privacy and Security → App Passwords)
  - Never use the real account password

Dependencies:

- `atproto` — official Bluesky AT Protocol Python client

---

### `post_scheduled.py`

Minimal CLI script. Accepts `--slot [am|noon|pm]`, loads the corresponding
pre-generated post JSON, calls `social.py`. No model, no rendering.

```python
# Usage
python post_scheduled.py --slot am
python post_scheduled.py --slot noon
python post_scheduled.py --slot pm
```

The JSON package format:

```json
{
  "slot": "noon",
  "date": "2026-05-30",
  "text": "SIGNAL // May 30\n\n...",
  "image_path": "reports/cards/noon_20260530.png",
  "report_url": "https://flexrpl.github.io/signal/reports/brief_20260530_1302.html"
}
```

Error handling: if the JSON file doesn't exist (main.py didn't run successfully
that morning), log and exit cleanly — no crash, no retry loop.

---

### `main.py` Changes

After the existing report generation step, add:

```python
# Generate social post packages
from pipeline.infographic import render_card
from pipeline.social import build_post_package

for slot in ['am', 'noon', 'pm']:
    data = extract_card_data(brief, slot)
    image_path = render_card(slot, data, output_path)
    build_post_package(slot, data, image_path, report_url)
```

`extract_card_data()` is a new function that maps the existing brief data
structure to what each card template needs. It should live in `infographic.py`.

---

### launchd Plists

Three new plists in `launchd/` for local reference. The user loads them manually
into `~/Library/LaunchAgents/`.

**`signal.social.am.plist`** — fires at 7:00 AM
**`signal.social.noon.plist`** — fires at 12:00 PM
**`signal.social.pm.plist`** — fires at 6:00 PM

All three follow the same pattern as the existing main pipeline plist,
substituting `post_scheduled.py --slot [am|noon|pm]` as the command.

Standard launchd fields:

- `StartCalendarInterval` with `Hour` and `Minute`
- `StandardOutPath` and `StandardErrorPath` to slot-specific log files
- `WorkingDirectory` set to the repo root
- `EnvironmentVariables` with `PATH` pointing to the venv Python

---

## Environment Setup

```bash
# Install new dependencies
pip install playwright atproto python-dotenv
playwright install chromium

# Create .env in repo root (gitignored)
cp .env.example .env
# Edit .env with actual credentials

# Load launchd jobs (run once)
cp launchd/*.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/signal.social.am.plist
launchctl load ~/Library/LaunchAgents/signal.social.noon.plist
launchctl load ~/Library/LaunchAgents/signal.social.pm.plist
```

---

## `.env.example`

```bash
BLUESKY_HANDLE=yourhandle.bsky.social
BLUESKY_APP_PASSWORD=xxxx-xxxx-xxxx-xxxx
```

---

## Bluesky Account Setup

1. Create a new Bluesky account for Signal
2. In account Settings → Privacy and Security → App Passwords
3. Generate a new app password named `signal-pipeline`
4. Add a bio note that the account posts automated daily intelligence briefs
   (standard practice for bot/automated accounts, keeps ToS clean)

---

## Out of Scope (v1)

- Multiple platform support (Mastodon, Threads, LinkedIn) — add later once
  Bluesky posting is stable and content is validated
- Dynamic noon post rotation across story clusters — top story only for now
- Retry logic for failed posts
- Web dashboard or posting UI
- Engagement analytics or reply handling

---

## Success Criteria

- `main.py` morning run produces 3 PNG cards and 3 JSON post packages without error
- Three launchd jobs fire at the correct times and post successfully
- Each post contains the correct card image, teaser text, and report URL
- Posts are visible on the Bluesky account within 1 minute of scheduled time
- No credentials appear in logs, git history, or output files
