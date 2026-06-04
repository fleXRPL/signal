---
name: signal-python
description: Python coding conventions, pipeline architecture, store patterns, LLM dispatch, and testing conventions for the Signal political intelligence pipeline. Use when writing or reviewing Python code in this project, adding a new pipeline pass, extending the store, writing tests, or working with the analyzer/collector/reporter/weekly modules.
---

# Signal — Python Conventions

## Pipeline architecture

Five-pass daily pipeline + one weekly synthesis pass:

```
Pass 1  extract_entities()     — per-article LLM entity extraction
Pass 2  cluster_articles()     — algorithmic clustering (no LLM)
Pass 3  analyze_clusters()     — per-cluster LLM framing analysis
Pass 4  correlate_stories()    — cross-story LLM correlation
Pass 5  synthesize_brief()     — final LLM brief synthesis
Pass 6  run_weekly()           — weekly synthesis from DB (weekly.py)

Post-pipeline (main.py):
  _extract_brief_data()        — brief_*.json for cards
  infographic.render_all_cards() — PNG cards + social.build_post_package()
```

Entry points: `run_pipeline()` in `analyzer.py`, `run_weekly()` in `weekly.py`, `post_scheduled.py` for Bluesky.

## Module responsibilities

| Module | Owns |
|---|---|
| `pipeline/store.py` | All SQLite reads/writes. No logic outside DB operations. |
| `pipeline/collector.py` | RSS feed fetching, article normalization, freshness filtering |
| `pipeline/analyzer.py` | All five daily passes + LLM dispatch (`_llm_call`) |
| `pipeline/weekly.py` | Pass 6 only. Reads from DB, one LLM call, saves result. |
| `pipeline/reporter.py` | HTML + `brief_*.json` generation. No DB access, no LLM calls. |
| `pipeline/infographic.py` | Social card PNGs via Jinja2 + Playwright (lazy import). |
| `pipeline/social.py` | Bluesky post packages and posting (lazy atproto/dotenv imports). |
| `pipeline/feed.py` | RSS `feed.xml` generation. |
| `pipeline/prompts.py` | Prompt constants only (`ENTITY_EXTRACTION`, `CLUSTER_ANALYSIS`, `CORRELATION_ANALYSIS`, `FINAL_BRIEF`, `WEEKLY_BRIEF`). |
| `main.py` | CLI, orchestration, `_update_index()`, social card wiring. |
| `post_scheduled.py` | launchd social dispatcher + git publish post state. |

## LLM dispatch pattern

All LLM calls go through `_llm_call()` in the calling module (not a shared util). `analyzer.py` and `weekly.py` each have their own dispatch.

Weekly Claude call uses `_llm_call_claude()` with `-p --print` only (no `--no-stream`), **3× config timeout**, and **one retry** on `Stream idle timeout`.

Provider resolved from `SIGNAL_LLM_PROVIDER` env var, falling back to `config["llm"]["provider"]`.

**Non-negotiable:** Never invoke Ollama from a `launchd` context — causes macOS Metal GPU kernel panics. Scheduled runs always use `claude`.

## Store patterns

Always use `get_connection()` — never construct the connection string directly:

```python
conn = store.get_connection()
rows = conn.execute("SELECT * FROM runs WHERE status=?", ("complete",)).fetchall()
conn.close()
return [dict(r) for r in rows]
```

`DB_PATH` is set at module level. In tests, it is patched via `monkeypatch` — never hardcode the path.

When adding a new table:
1. Add `CREATE TABLE IF NOT EXISTS` to the `executescript` block in `init_db()`
2. Add `CREATE INDEX IF NOT EXISTS` for any FK or frequently-queried column
3. Write typed helper functions (`save_*`, `get_*`) — no raw SQL outside `store.py`

## Error handling in passes

LLM calls are wrapped in `try/except Exception` with a fallback dict — never let a single article/cluster failure abort the whole run:

```python
try:
    raw = _llm_call(prompt, model, base_url, timeout, provider)
    parsed = _parse_json_response(raw)
except Exception as exc:  # noqa: BLE001
    console.print(f"  [red]LLM error:[/red] {exc}")
    parsed = None

if parsed is None:
    parsed = {<safe fallback defaults>}
```

## Type hints and imports

- All modules use `from __future__ import annotations`
- Use `List`, `Dict`, `Optional`, `Tuple`, `Any` from `typing` (not bare generics)
- `Optional[str]` not `str | None` (Python 3.9 compat)

## Testing conventions

See `tests/README.md` for full guidance. Core rules:

**Mock at the lowest boundary:**
```python
@patch("pipeline.analyzer._llm_call")   # patch in the module under test
def test_something(self, mock_llm, tmp_db, mock_entity_response):
    mock_llm.return_value = mock_entity_response
```

**Always use `tmp_db` for any test touching the database** — it patches `store.DB_PATH` to a temp file.

**Never let a test write to the real `reports/` directory** — patch `pipeline.reporter.REPORTS_DIR`, `pipeline.infographic.CARDS_DIR`, or `pipeline.social.POSTS_DIR` with `tmp_path`.

**Social/infographic tests:** mock `atproto.Client`, `dotenv.load_dotenv` (lazy import — not `pipeline.social.load_dotenv`), and `infographic._screenshot`. Align assertions with production behavior; do not change production code to pass tests.

**LLM fixtures in conftest.py:** `mock_entity_response`, `mock_cluster_analysis_response`, `mock_correlation_response`, `mock_brief_response` — add new shared fixtures there, not inline.

Run tests: `.venv/bin/python -m pytest`
Run without coverage: `.venv/bin/python -m pytest --no-cov`

## Code style non-negotiables

- No comments that narrate the code — only explain non-obvious intent
- No f-strings without replacement fields (`f"literal"` → `"literal"`)
- Fix linter warnings you introduce; leave pre-existing ones unless blocking
- Senior Python patterns: prefer comprehensions, avoid intermediate variables when not needed
- `noqa` comments are acceptable for intentional suppressions (e.g. `# noqa: ARG001`, `# noqa: BLE001`)
