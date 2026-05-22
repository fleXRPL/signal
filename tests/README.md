# Tests

Unit tests for the Signal pipeline. All tests run offline — LLM calls and
network I/O are mocked, so the suite completes in under two seconds with no
external dependencies.

## Running the tests

```bash
# From the repo root, using the project venv
.venv/bin/python -m pytest
```

Coverage report is printed to the terminal and written as HTML to `htmlcov/`
(gitignored). Open `htmlcov/index.html` in a browser for a line-by-line view.

To run a single file or test:

```bash
.venv/bin/python -m pytest tests/test_store.py
.venv/bin/python -m pytest tests/test_store.py::TestRuns::test_finish_run
```

To skip coverage (faster feedback loop during development):

```bash
.venv/bin/python -m pytest --no-cov
```

## File map

| File | What it tests |
| --- | --- |
| `conftest.py` | Shared fixtures used by all test files |
| `test_store.py` | SQLite persistence layer (`pipeline/store.py`) |
| `test_collector.py` | Feed collection and article normalization (`pipeline/collector.py`) |
| `test_analyzer.py` | Entity extraction, clustering, cluster analysis (`pipeline/analyzer.py`) |
| `test_reporter.py` | HTML report generation, GA snippet, markdown rendering (`pipeline/reporter.py`) |
| `test_weekly.py` | Pass 6 weekly synthesis logic (`pipeline/weekly.py`) |

## Key fixtures (`conftest.py`)

| Fixture | Description |
| --- | --- |
| `sample_article` | Single article dict with realistic field values |
| `sample_articles` | Three-article cross-spectrum set covering two stories |
| `mock_entity_response` | JSON string mimicking a Pass 1 LLM response |
| `mock_cluster_analysis_response` | JSON string mimicking a Pass 3 LLM response |
| `mock_correlation_response` | JSON string mimicking a Pass 4 LLM response |
| `mock_brief_response` | Markdown string mimicking a Pass 5 LLM response |
| `tmp_db` | Patches `store.DB_PATH` to a temporary SQLite file; auto-cleaned after each test |
| `sample_config` | Minimal `sources.yaml`-shaped config dict |

## Conventions

**Mocking LLM calls.** All tests that exercise code which calls an LLM use
`@patch("pipeline.analyzer._llm_call")` (or the equivalent in `weekly.py`).
Never let a test make a real subprocess call to Claude or an Ollama request.

**Database isolation.** Any test that touches the database must use the
`tmp_db` fixture. It patches `pipeline.store.DB_PATH` to a `tmp_path` file
scoped to the test, so tests never read from or write to `signal.db`.

**File system isolation.** Tests for `generate_report()` and
`generate_weekly_report()` patch `pipeline.reporter.REPORTS_DIR` with
`tmp_path` so no files are written to the real `reports/` directory.

## Adding a new test

1. Identify the module under test and add cases to the relevant existing file,
   or create a new `tests/test_<module>.py` if the module has no coverage yet.
2. Use `make_article()` from `conftest.py` to build article fixtures rather
   than hand-crafting dicts inline.
3. Mock any external I/O at the lowest practical boundary:
   - LLM calls: patch `_llm_call` in the module under test
   - HTTP requests: patch `httpx.get` or `feedparser.parse`
   - Database: use the `tmp_db` fixture
   - File writes: use `tmp_path` and patch the relevant `*_DIR` constant
4. Group related cases into a class (e.g. `class TestRuns:`) so test output
   is easy to scan.
5. Run `python -m pytest --no-cov` to verify, then `python -m pytest` to
   confirm coverage did not regress.

## Coverage targets

| Module | Current | Notes |
| --- | --- | --- |
| `analyzer.py` | **100%** | All passes, helpers, LLM dispatch, and error paths covered |
| `store.py` | 94% | Missing lines are error-path branches in JSON decode |
| `collector.py` | 92% | Missing: `load_config()` (reads real YAML), `_fetch_full_text` edge cases |
| `weekly.py` | 82% | Missing: Ollama provider branch (lines 101–127) — intentionally untested since Ollama is disabled in scheduled runs |
| `reporter.py` | 79% | Missing: large HTML template formatting helpers; covered by snapshot-style output assertions |

The remaining gaps are either intentional (Ollama branch in `weekly.py`) or
low-value boilerplate (`load_config` reading the real YAML on disk). The
primary candidates for future expansion are the remaining `reporter.py`
rendering helpers (`_render_story_cards`, `_render_connections`, etc.).
