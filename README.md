# Signal — Political Intelligence Pipeline

[![Signal Logo](images/signal_banner.png)](https://flexrpl.github.io/signal/)

A five-pass analysis pipeline that ingests political news across the full spectrum, finds non-obvious patterns and connections, and generates an analyst-style intelligence brief rather than a news summary.

## What it does

```text
[RSS Feeds across 18 sources] 
         ↓
[Pass 1] Entity extraction per article (people, orgs, legislation, locations)
         ↓
[Pass 2] Algorithmic clustering (same story, multiple sources)
         ↓
[Pass 3] Per-cluster framing analysis (how left vs right vs center covers it)
         ↓
[Pass 4] Cross-story correlation (non-obvious connections, patterns, anomalies)
         ↓
[Pass 5] Final brief synthesis (analyst narrative, not news summary)
         ↓
[HTML report — open in any browser]
```

Everything runs locally via Ollama. Nothing leaves your machine.

## Requirements

- Python 3.11+
- [Ollama](https://ollama.ai) running locally
- At least one model pulled

## Quick start

```bash
# 1. Pull a model (if you haven't)
ollama pull llama3.1:8b        # fast, good for dev (~5GB)
ollama pull qwen2.5:14b        # better reasoning, recommended (~9GB)

# 2. Make sure Ollama is running
ollama serve

# 3. Run Signal
python main.py

# With a specific model
python main.py --model qwen2.5:14b

# Skip full article fetch (faster, less context)
python main.py --no-fetch
```

## Model recommendations (M1 Max 32GB)

| Model | Size | Speed | Quality | Use for |
| ------- | ------ | ------- | --------- | ---------- |
| `llama3.1:8b` | ~5GB | Fast | Good | Development, quick runs |
| `qwen2.5:14b` | ~9GB | Medium | Excellent | Production analysis |
| `mistral:7b` | ~4GB | Fastest | Moderate | Low-resource fallback |

With 32GB unified memory you can comfortably run `qwen2.5:14b`. It meaningfully
outperforms 8b models on the correlation and synthesis passes.

## Output

Each run generates:

- `reports/brief_YYYYMMDD_HHMM_runN.html` — self-contained HTML report
- `signal.db` — SQLite database with all articles, clusters, and analyses

The HTML report includes:

- Full intelligence brief (Situation Overview, Key Dynamics, What Isn't Being Said, etc.)
- Per-story breakdown with left/center/right framing and omissions
- Cross-story connections and patterns
- Blindspot analysis (stories only covered by one side)
- Watch list for the next 48-72 hours
- Source index

## Configuration

Edit `config/sources.yaml` to:

- Change the Ollama model
- Add/remove RSS sources
- Adjust article age limits
- Tune clustering thresholds

## How the intelligence layer works

The key insight is that Pass 4 doesn't see the articles at all — it sees the
*analyses* of clusters, plus an entity network showing which actors appear
across multiple unrelated stories. This is where non-obvious connections emerge.

Pass 5 is explicitly instructed NOT to summarize the news — it's prompted to
write like an analyst who has read everything and is telling you what's actually
happening, not what the outlets claim is happening.

## Database

`signal.db` accumulates across runs. This enables:

- Delta detection (what changed since the last run)
- Watch list tracking (did watched items materialize?)
- Trend analysis over time

```bash
# Inspect the database
sqlite3 signal.db
.tables
SELECT count(*), source_name FROM articles GROUP BY source_name;
```

## Project structure

```bash
signal/
├── config/
│   └── sources.yaml       # feed list + model config
├── signal/
│   ├── __init__.py
│   ├── store.py           # SQLite persistence
│   ├── collector.py       # RSS + article scraping
│   ├── prompts.py         # all LLM prompts
│   ├── analyzer.py        # 5-pass analysis pipeline
│   └── reporter.py        # HTML report generation
├── reports/               # output reports (gitignored)
├── main.py                # entry point + venv bootstrap
├── requirements.txt
└── signal.db              # runtime database (gitignored)
```

## Infographic

![Signal Infographic](/images/signal_infographic.png)
