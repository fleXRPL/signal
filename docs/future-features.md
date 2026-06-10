# Future Enhancements

A few ideas worth considering, roughly in order of value-to-effort:

## High value, relatively straightforward

1. **Source health monitoring** — track which RSS feeds are returning 0 articles per run and log a warning. Over time sources break, change URLs, or go behind paywalls silently. Right now you'd only notice when the brief feels thin. *(Four feed URLs were replaced June 2026: Politico, Axios, WSJ Opinion, RealClearPolitics.)*

## More involved but analytically interesting

1. **Entity frequency tracking** — extend the DB to count how many times each named entity appears across runs, and surface a "Trending Actors" section in the weekly: who appeared in the most stories this week vs. last week. This feeds naturally into the monthly Emerging Actors section.

2. **Sentiment trend chart** — a simple static SVG or JS sparkline on the archive page showing daily sentiment polarity over time. Adds longitudinal visual context that's currently invisible.

## Completed (formerly listed here)

- **RSS feed output** — `feed.xml` at repo root, updated on daily/weekly runs
- **GitHub Actions CI** — pytest on every PR/push to main
- **Formal test suite** — 239 tests, ~93% coverage
- **Monthly intelligence (Pass 7)** — see wiki `Monthly-Reports` page
