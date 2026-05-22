---
name: signal-yaml-config
description: Configuration structure and conventions for Signal's sources.yaml. Use when adding or removing news sources, adjusting LLM or collection settings, changing the analytics ID, or modifying any config/sources.yaml value.
---

# Signal — YAML Configuration

Config file: `config/sources.yaml`. Loaded by `pipeline/collector.py:load_config()` and passed as a dict throughout the pipeline.

## Top-level sections

```yaml
analytics:      # GA4 tracking
llm:            # LLM provider settings
collection:     # Feed fetch behaviour
analysis:       # Clustering thresholds
sources:        # List of RSS feeds
```

## analytics

```yaml
analytics:
  measurement_id: "G-XXXXXXXXXX"   # GA4 — set to "" to disable
```

The measurement ID is injected into every generated HTML page. It is not a secret — GA4 IDs are public. Store it here, not hardcoded in Python.

## llm

```yaml
llm:
  provider: claude          # ollama | claude
                            # override at runtime: SIGNAL_LLM_PROVIDER=claude
  ollama:
    model: "qwen2.5:14b"
    base_url: "http://localhost:11434"
    timeout: 120
  claude:
    timeout: 180
```

**Never set provider to `ollama` in the plist files.** Ollama causes macOS Metal GPU kernel panics when invoked from a `launchd` daemon context. Scheduled runs must use `claude`.

## collection

```yaml
collection:
  max_articles_per_source: 10    # reduce if hitting Claude token limits
  article_age_hours: 24          # skip articles older than this
  fetch_full_text: true          # fetch full article body via httpx
  fetch_timeout: 10              # seconds per HTTP request
```

`max_articles_per_source: 10` was intentionally reduced from 20 to manage Claude Pro burst rate limits during a full manual run.

## analysis

```yaml
analysis:
  min_cluster_size: 2              # minimum articles to form a real cluster
  entity_similarity_threshold: 0.75
  title_similarity_threshold: 0.70   # rapidfuzz token_sort_ratio threshold
```

Lowering `title_similarity_threshold` below 0.60 causes false-positive clustering. Raising `entity_similarity_threshold` above 0.85 reduces cluster formation on entity-sparse articles.

## sources — adding a new feed

```yaml
sources:
  - name: "Source Display Name"   # shown in reports and source index
    url: "https://example.com/rss.xml"
    bias: "center"                # see bias values below
    type: rss
```

**Valid bias values** (must match exactly — used in clustering logic and BIAS_COLORS in reporter.py):

```
far-left | left | center-left | center | libertarian | center-right | right | far-right
```

Group sources in the file with comments by bias tier. Maintain spectrum balance — if adding a left-leaning source, consider adding a corresponding right-leaning one.

## sources — current lineup (18 feeds)

| Bias tier | Sources |
|---|---|
| Center | AP Politics, Reuters Politics, C-SPAN, The Hill, Axios Politics |
| Center-left | NPR Politics, PBS NewsHour, Politico |
| Left | Washington Post Politics, The Guardian US |
| Far-left | Mother Jones |
| Center-right | Wall Street Journal Politics, RealClearPolitics |
| Right | Fox News Politics, Washington Examiner, National Review |
| Far-right | Breitbart |
| Libertarian | Reason |

## Config is not validated at startup

There is no schema validation on load — a typo in a bias value will silently produce `"unknown"` in reports. If adding a source, verify the bias string against the list above.
