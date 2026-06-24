# Future Enhancements

Ideas worth considering for Signal, ordered by value-to-effort. The core pipeline (daily → weekly → monthly, social cards, GitHub Pages, RSS, CI) is stable; these items address operational resilience, intelligence depth, and polish.

---

## Tier 1 — Operational resilience (highest ROI)

Addresses failures already seen in production: Claude auth expiry, API outages, 4 AM run failures, silent feed rot, and social posts firing before packages exist.

### Pre-flight health check

Before Pass 1 (daily) or the single synthesis call (weekly/monthly), run a short sanity check:

- `claude -p "ping" --print` succeeds
- At least N articles collected (abort early if 0)
- Card PNGs exist before social slots fire (optional check in post script)

If pre-flight fails, log clearly and exit early with a distinct message (e.g. `SIGNAL_ABORT: claude_unavailable`) instead of failing mid-run or leaving social jobs to discover missing packages at 9 AM.

### Failure notification

Currently failures are only visible when checking logs manually. Add a lightweight webhook (ntfy.sh, Pushover, or similar) on:

- Daily run produced 0 articles
- Weekly/monthly synthesis failed
- Social post package missing at post time

One HTTP POST from `run_and_publish.sh`, `run_weekly_and_publish.sh`, or `post_scheduled.py` on non-zero exit. No new infrastructure beyond a URL in config or `.env`.

### Source health monitoring

Track which RSS feeds return 0 articles, HTTP errors, or timeouts per run. Log a warning rollup (e.g. `logs/feed_health.log`) or surface a summary in the daily report footer.

Over time sources break, change URLs, or go behind paywalls silently — you'd otherwise only notice when the brief feels thin. *(Four feed URLs were replaced June 2026: Politico, Axios, WSJ Opinion, RealClearPolitics. C-SPAN returned 410 Gone — candidate for replacement.)*

### Social post catch-up / retry window

When AM/noon/PM fails with "package missing" but the daily run completes later (manual or delayed), support recovery without re-running the full pipeline:

```bash
post_scheduled.py --slot pm --catch-up   # post today's package if it exists and is not yet posted
```

Alternatively, a single evening launchd job (e.g. 7 PM) that retries any unposted slots for the current UTC date.

### Claude auth monitoring

Weekly/monthly jobs fail with 401 when Claude CLI credentials expire. Document a periodic check (`claude -p "ping" --print`) and consider pre-flight integration above. Interactive re-auth via `/login` in Claude Code — not automatable from launchd.

**Note:** Automatic fallback to Ollama when Claude fails is **not recommended for launchd** — Ollama from a background daemon has caused Metal GPU kernel panics on macOS. Manual Ollama runs during outages only:

```bash
SIGNAL_LLM_PROVIDER=ollama .venv/bin/python main.py --no-venv
```

---

## Tier 2 — Intelligence layer (core product value)

### Monthly social card

Planned after first full scheduled monthly (Jul 1+). Purple-themed Playwright card from monthly brief sections (Month in Review + Watch List: Next Month). One Bluesky post on the 1st or 2nd of the month, same pattern as daily AM/noon/pm cards.

### Watch list scorecard automation

Pass 7 asks the LLM to score prior watch items, but nothing in the DB tracks predictions structurally. Store `recommended_watch` from Pass 4 as structured JSON per run, then compute programmatically in monthly synthesis: flagged date, first appearance in coverage, materialized / didn't. Makes the monthly **Watch List Scorecard** more rigorous than LLM recall alone.

### Entity frequency / trending actors

Entities are extracted in Pass 1 but not aggregated over time. Add an `entity_mentions` table (entity, run_id, count) to power weekly "Trending Actors" and feed monthly **Emerging Actors** with real counts, not just prose.

### Cross-run URL deduplication

Articles published late in the day can appear in consecutive daily runs (within the 24-hour window), inflating Pass 1 cost and skewing clustering. Before saving in `store.py`, query URLs seen in the last 48 hours:

```sql
SELECT url FROM articles
WHERE collected_at > datetime('now', '-48 hours')
AND url = ?
```

---

## Tier 3 — Quality of life & polish

### Pass 1 parallelization

Deferred — daily run completes within the 4 AM window today. If sources grow or runtime becomes tight, use `ThreadPoolExecutor` for Pass 1 Claude calls (~140–160 sequential today, ~22 min). Start with `max_workers=3–5`; tune for rate limits. Rich progress bar needs updating for out-of-order completion.

### Index path guard / `_update_index` tests

Prevent landing-page 404s when a non-existent report path is passed (e.g. dry-run test filename). Test that `_update_index()` falls back to the latest on-disk monthly/weekly file when the given path does not exist.

### Pipeline status page (static)

Generate `status.html` on each run: last successful daily/weekly/monthly timestamps, 7-day article count trend, feed health summary, last Claude pre-flight result. Useful when Claude is down and you need to see what's stale without reading logs.

### C-SPAN feed replacement

Cron log showed C-SPAN RSS returning **410 Gone**. Swap or remove before it wastes a collection slot each run.

### SonarQube cleanup

Cognitive complexity warnings in `reporter.py` and `main.py` (large HTML template functions). Test coverage is no longer a blocker (~93% overall).

---

## Tier 4 — Future horizon (don't rush)

Only after monthly synthesis is stable for 2+ full months.

### Pass 8 — Quarterly intelligence summary

Reads monthly briefs from a quarter; structural trend analysis, narrative lifecycle, actor trajectory, seasonal patterns, forecast accuracy review across monthly scorecards. See wiki `Future-Roadmap` Phase 4.

### Sentiment trend chart

Static SVG or JS sparkline on `archive.html` showing daily sentiment polarity over time. Nice visual; lower analytical value vs effort compared to entity tracking or watch list scoring.

### Email / subscriber delivery

Optional email or push of daily brief link via `smtplib`, SendGrid, or Pushover. Controlled by a `delivery:` section in `sources.yaml`. ntfy (Tier 1) is simpler for a personal pipeline.

### Source expansion

Additional feeds for spectrum balance (NYT, Atlantic, Dispatch, Intercept, etc.). See wiki `Future-Roadmap` source expansion table.

---

## Recommended implementation order

| Priority | Item | Rationale |
| -------- | ---- | --------- |
| 1 | Pre-flight health check | Prevents silent 4 AM failures and empty social days |
| 2 | Failure notification (ntfy/Pushover) | Learn about problems without checking logs |
| 3 | Source health logging | Feeds break constantly |
| 4 | Monthly social card | Natural extension of Pass 7 |
| 5 | Watch list DB tracking | Makes monthly scorecard real, not vibes-only |
| 6 | Cross-run deduplication | Reduces cost and duplicate analysis |
| 7 | Entity frequency tracking | Powers weekly/monthly actor sections |
| 8 | Pass 1 parallelization | Only if runtime becomes a constraint |

---

## Completed (formerly listed here)

- **RSS feed output** — `feed.xml` at repo root, updated on daily/weekly runs
- **GitHub Actions CI** — pytest on every PR/push to main
- **Formal test suite** — 239 tests, ~93% coverage
- **Weekly intelligence (Pass 6)** — Monday 6 AM launchd, gold theme
- **Monthly intelligence (Pass 7)** — see wiki `Monthly-Reports` page
- **Social cards (Bluesky)** — 3 cards/day, Playwright + atproto
- **Feed URL fixes (Jun 2026)** — Politico, Axios, WSJ Opinion, RealClearPolitics
- **Feed hang protection** — httpx fetch + feedparser parse-only in `collector.py`
