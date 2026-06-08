---
name: signal-social
description: Bluesky social cards for Signal — card generation, post packages, launchd scheduling, and git publish. Use when working on pipeline/social.py, pipeline/infographic.py, post_scheduled.py, card templates, reports/posts/, reports/cards/, .env credentials, or social launchd plists.
---

# Signal — Social Cards (Bluesky)

## Architecture

```text
4 AM  main.py
        → brief HTML + brief_*.json (_extract_brief_data)
        → 3 PNG cards (infographic.py / Playwright)
        → 3 post packages (social.py → reports/posts/)
        → run_and_publish.sh → git push (reports/, index, archive, feed.xml)

9 AM / noon / 6 PM  post_scheduled.py --slot {am|noon|pm}
        → load reports/posts/{slot}_YYYYMMDD.json
        → post_to_bluesky() via atproto
        → git push reports/posts/
```

**Account:** `signal-pipeline.bsky.social` (credentials in `.env`, gitignored).

**Date slug:** UTC `YYYYMMDD` — used in filenames and `post_slot()` default.

## Key modules

| Module | Role |
|--------|------|
| `pipeline/reporter.py` | `_extract_brief_data()` → `brief_*.json` |
| `pipeline/infographic.py` | Jinja2 templates → 1200×630 PNG via Playwright |
| `pipeline/social.py` | Post text, packages, Bluesky upload/post |
| `post_scheduled.py` | launchd CLI; git publish after post |
| `pipeline/templates/card_*.html` | Jinja2 (not reporter f-strings) |

## Post text limits

Bluesky max **300 graphemes**. `social.py` uses `_BLUESKY_SAFE_GRAPHEMES = 295` and `_fit_bluesky_text()` at build and send time.

## Launchd plists

| Label | Time | Slot |
|-------|------|------|
| `com.flexrpl.signal` | 4:00 AM | pipeline + cards |
| `com.flexrpl.signal.social.am` | 9:00 AM | `--slot am` |
| `com.flexrpl.signal.social.noon` | 12:00 PM | `--slot noon` |
| `com.flexrpl.signal.social.pm` | 6:00 PM | `--slot pm` |

Reload after editing plists:

```bash
launchctl unload ~/Library/LaunchAgents/com.flexrpl.signal.social.am.plist
cp scripts/com.flexrpl.signal.social.am.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.flexrpl.signal.social.am.plist
```

## Git publish

`scripts/git_publish_if_changed.sh` — shared by daily and social scripts. Only commits/pushes when staged files changed. Always switches to `main` first.

## Testing

- `tests/test_social.py` — mock `atproto.Client`, patch `dotenv.load_dotenv`, use `tmp_path` for `POSTS_DIR`
- `tests/test_infographic.py` — mock `_screenshot`, use `tmp_path` for `CARDS_DIR`
- **Align tests with production logic** — do not change `_window_summary` or similar to satisfy tests

Mock Playwright in tests — never require headless Chromium in CI.

## Manual commands

```bash
.venv/bin/python post_scheduled.py --slot am --dry-run
.venv/bin/python post_scheduled.py --slot noon
.venv/bin/python post_scheduled.py --slot pm --date 20260604
```

Full runbook: `docs/social-cards-setup.md`

## Logs

```bash
tail -20 logs/social_am.log logs/social_noon.log logs/social_pm.log
tail -20 logs/cron.log
```

Common AM failure: `Post package not found` — pipeline not finished before 9 AM job, or Playwright card generation failed. Check pipeline finish time and Playwright errors in `cron.log`.
