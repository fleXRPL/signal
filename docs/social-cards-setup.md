# Social Cards — Setup & Operations Runbook

Step-by-step commands for Bluesky social posting. Design details live in [signal_social_feature.md](signal_social_feature.md). Wiki mirror: [Social-Cards](https://github.com/fleXRPL/signal.wiki/wiki/Social-Cards).

All commands assume the repo root:

```bash
cd /Users/garotconklin/garotm/fleXRPL/signal
```

Use the **venv** for every `pip` and `python` call — not system `pip` (macOS will block it with PEP 668).

---

## 1. Install Python dependencies

```bash
cd /Users/garotconklin/garotm/fleXRPL/signal

.venv/bin/pip install playwright atproto python-dotenv
.venv/bin/playwright install chromium
```

Chromium is ~100MB, one-time, stored in your user profile (not in the repo).

---

## 2. Bluesky credentials (app password, not login password)

1. Log in at [bsky.app](https://bsky.app) with your Signal account (e.g. `signalls.bsky.social`).
2. **Settings → Privacy and Security → App Passwords**
3. **Add App Password** — name it `signal-pipeline`
4. Copy the one-time password (`xxxx-xxxx-xxxx-xxxx`). You cannot view it again.

Create `.env` from the template:

```bash
cp .env.example .env
```

Edit `.env` (never commit this file):

```bash
BLUESKY_HANDLE=signalls.bsky.social
BLUESKY_APP_PASSWORD=xxxx-xxxx-xxxx-xxxx
```

Confirm `.env` is ignored by git:

```bash
git status
# .env should NOT appear in the list
```

---

## 3. Generate cards and post packages

Cards are built during the **daily** pipeline run (4:00 AM launchd job), not at post time.

**Full pipeline** (articles + analysis + HTML + cards + post JSON):

```bash
.venv/bin/python main.py
```

**Or** wait for the scheduled daily job — then confirm today's artifacts exist:

```bash
DATE=$(date -u +%Y%m%d)
ls -la reports/brief_*_${DATE}*.json 2>/dev/null || ls -la reports/brief_*.json | tail -3
ls -la reports/cards/am_${DATE}.png reports/cards/noon_${DATE}.png reports/cards/pm_${DATE}.png
ls -la reports/posts/am_${DATE}.json reports/posts/noon_${DATE}.json reports/posts/pm_${DATE}.json
```

Expected after a successful run:

| Path                               | Purpose                   |
| ---------------------------------- | ------------------------- |
| `reports/brief_YYYYMMDD_HHMM.html` | Full brief                |
| `reports/brief_YYYYMMDD_HHMM.json` | Structured data for cards |
| `reports/cards/am_YYYYMMDD.png`    | Watch List image          |
| `reports/cards/noon_YYYYMMDD.png`  | Spectrum image            |
| `reports/cards/pm_YYYYMMDD.png`    | Blindspot image           |
| `reports/posts/am_YYYYMMDD.json`   | Bluesky post package (AM) |
| `reports/posts/noon_YYYYMMDD.json` | Noon package              |
| `reports/posts/pm_YYYYMMDD.json`   | PM package                |

Check the daily log if cards are missing:

```bash
grep -i social logs/cron.log | tail -20
```

---

## 4. Test without posting (dry run)

```bash
.venv/bin/python post_scheduled.py --slot am --dry-run
.venv/bin/python post_scheduled.py --slot noon --dry-run
.venv/bin/python post_scheduled.py --slot pm --dry-run
```

You should see post text, image path, and report URL. If you get **post package not found**, step 3 did not complete for today's UTC date.

Post for a specific date:

```bash
.venv/bin/python post_scheduled.py --slot am --date 20260601 --dry-run
```

---

## 5. Post manually to Bluesky

```bash
.venv/bin/python post_scheduled.py --slot am
.venv/bin/python post_scheduled.py --slot noon
.venv/bin/python post_scheduled.py --slot pm
```

Each successful run sets `"posted": true` in the JSON package so launchd will not double-post the same slot/date.

**Re-post the same slot** (only if intentional):

```bash
# Edit the package and set "posted": false, then:
.venv/bin/python post_scheduled.py --slot am --date 20260601
```

---

## 6. Install launchd jobs (one-time)

Copy plists from the repo into LaunchAgents, then load:

```bash
cd /Users/garotconklin/garotm/fleXRPL/signal

cp scripts/com.flexrpl.signal.social.am.plist   ~/Library/LaunchAgents/
cp scripts/com.flexrpl.signal.social.noon.plist ~/Library/LaunchAgents/
cp scripts/com.flexrpl.signal.social.pm.plist   ~/Library/LaunchAgents/

launchctl load ~/Library/LaunchAgents/com.flexrpl.signal.social.am.plist
launchctl load ~/Library/LaunchAgents/com.flexrpl.signal.social.noon.plist
launchctl load ~/Library/LaunchAgents/com.flexrpl.signal.social.pm.plist
```

**Verify all Signal jobs** (daily, weekly, three social):

```bash
launchctl list | grep flexrpl
```

Expected (exit code `0` in the second column = last run OK):

```text
-  0  com.flexrpl.signal
-  0  com.flexrpl.signal.weekly
-  0  com.flexrpl.signal.social.am
-  0  com.flexrpl.signal.social.noon
-  0  com.flexrpl.signal.social.pm
```

| Job                              | Schedule                                    |
| -------------------------------- | ------------------------------------------- |
| `com.flexrpl.signal`             | Daily 4:00 AM — pipeline + cards + git push |
| `com.flexrpl.signal.weekly`      | Monday 6:00 AM — weekly brief               |
| `com.flexrpl.signal.social.am`   | Daily 8:00 AM — post Watch List             |
| `com.flexrpl.signal.social.noon` | Daily 12:00 PM — post Spectrum              |
| `com.flexrpl.signal.social.pm`   | Daily 6:00 PM — post Blindspot              |

Social jobs only **post** pre-built files; they do not run the LLM or Playwright.

---

## 7. Trigger a social job immediately (optional)

Same as waiting for the schedule, but run now:

```bash
launchctl start com.flexrpl.signal.social.am
launchctl start com.flexrpl.signal.social.noon
launchctl start com.flexrpl.signal.social.pm
```

---

## 8. Watch logs

```bash
tail -f logs/social_am.log
tail -f logs/social_noon.log
tail -f logs/social_pm.log
```

Daily pipeline (card generation):

```bash
tail -f logs/cron.log
```

---

## 9. Reload plists after editing `scripts/*.plist`

```bash
launchctl unload ~/Library/LaunchAgents/com.flexrpl.signal.social.am.plist
cp scripts/com.flexrpl.signal.social.am.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.flexrpl.signal.social.am.plist
```

Repeat for `noon` and `pm` plists.

**Unload social jobs** (disable automated posting):

```bash
launchctl unload ~/Library/LaunchAgents/com.flexrpl.signal.social.am.plist
launchctl unload ~/Library/LaunchAgents/com.flexrpl.signal.social.noon.plist
launchctl unload ~/Library/LaunchAgents/com.flexrpl.signal.social.pm.plist
```

---

## 10. Git / branch workflow

Social posting is developed on **`feature/social-cards`**, not `main`, until reviewed.

```bash
git checkout feature/social-cards
git fetch origin
git merge origin/main    # stay current with main after weekly/daily merges

# Never commit .env
git status
```

---

## Troubleshooting (commands)

| Problem                                 | What to run                                                                     |
| --------------------------------------- | ------------------------------------------------------------------------------- |
| `externally-managed-environment` on pip | Use `.venv/bin/pip`, not `pip`                                                  |
| Post package not found                  | Run `.venv/bin/python main.py` or check `logs/cron.log`                         |
| Credentials error                       | Confirm `.env` at repo root; test with `--dry-run` from repo root               |
| Cards not generated                     | `.venv/bin/playwright install chromium`; grep `logs/cron.log` for social errors |
| Already posted                          | Set `"posted": false` in `reports/posts/{slot}_YYYYMMDD.json`                   |
| Wrong date slot                         | Use `--date YYYYMMDD` (UTC date used in filenames)                              |
