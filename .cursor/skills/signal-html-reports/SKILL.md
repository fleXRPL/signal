---
name: signal-html-reports
description: HTML report generation conventions for Signal. Use when modifying report templates, adding new report sections, changing the visual theme, extending the weekly or daily report format, or working with reporter.py and the HTML template strings.
---

# Signal — HTML Reports

## Three report types

| Type           | Template               | Filename                           | Theme accent   |
| -------------- | ---------------------- | ---------------------------------- | -------------- |
| Daily brief    | `HTML_TEMPLATE`        | `reports/brief_YYYYMMDD_HHMM.html` | Blue `#58a6ff` |
| Weekly summary | `WEEKLY_HTML_TEMPLATE` | `reports/weekly_YYYYWNN_HHMM.html` | Gold `#e3b341` |
| Monthly summary | `MONTHLY_HTML_TEMPLATE` | `reports/monthly_YYYYMM[_partial]_HHMM.html` | Purple `#a371f7` |

All three share the same dark background (`#0d1117`) and overall CSS structure. **Do not change the color distinction without asking** — it is intentional.

## Template structure

Templates are multi-line Python f-strings in `pipeline/reporter.py`. They use `.format()` with named placeholders — not Jinja2.

```python
rendered = HTML_TEMPLATE.format(
    date=date_str,
    article_count=len(articles),
    ga_snippet=ga_snippet(ga_measurement_id),
    brief_sections=brief_sections_html,
    story_cards=story_cards_html,
    # ...
)
```

CSS variables are defined in `:root` and referenced throughout:

```css
:root {
  --bg: #0d1117;
  --surface: #161b22;
  --border: #30363d;
  --text: #e6edf3;
  --muted: #8b949e;
  --accent: #58a6ff; /* blue daily; gold #e3b341 weekly; purple #a371f7 monthly */
  --mono: "JetBrains Mono", "Fira Code", monospace;
}
```

## Report generation flow

```text
brief_text (markdown)
    ↓ _parse_brief_sections()     → Dict[section_name, content]
    ↓ _render_brief_sections()    → HTML string with section divs
    ↓ HTML_TEMPLATE.format(...)   → complete HTML page string
    ↓ out_path.write_text(...)    → reports/brief_YYYYMMDD_HHMM.html
    ↓ _extract_brief_data()       → reports/brief_YYYYMMDD_HHMM.json (social cards)
```

`generate_report(brief_text, clusters, correlation, articles, model, ga_measurement_id="")` — no `run_id` parameter.

Weekly uses `_render_weekly_sections()` instead of `_render_brief_sections()`.

Monthly uses `_render_monthly_sections()` with `MONTHLY_SECTION_STYLES`. Partial months add a `_partial` filename suffix and a **Partial Coverage** badge in the header.

## Social card templates (separate from reports)

Social cards use **Jinja2** in `pipeline/templates/card_{watch,spectrum,blindspot}.html`, rendered by `infographic.py` via Playwright — not the f-string templates in this file. Each template needs a `<title>` tag (SonarQube). Google Fonts CDN links are intentional for Playwright screenshots.

## Adding a new section to the daily brief

1. Add the section header to the LLM prompt in `pipeline/prompts.py` (`FINAL_BRIEF`).
2. Add a style entry to `section_styles` dict in `_render_brief_sections()`:

   ```python
   section_styles = {
       "NEW SECTION NAME": ("highlight", "▸"),
       # ...
   }
   ```

   CSS classes available: `""` (default), `"highlight"`, `"warn-section"`, `"danger-section"`.
3. The section will render automatically — no template changes required.

## Adding a new section to the weekly brief

Same pattern, but in `_render_weekly_sections()` with `WEEKLY_SECTION_STYLES`.

## Adding a new section to the monthly brief

Same pattern, but in `_render_monthly_sections()` with `MONTHLY_SECTION_STYLES`.

## Google Analytics snippet

```python
def ga_snippet(measurement_id: str) -> str:
    """Return GA4 script tags, or empty string if no ID."""
```

Both `generate_report()`, `generate_weekly_report()`, and `generate_monthly_report()` accept `ga_measurement_id: str = ""`. The snippet is injected via the `{ga_snippet}` placeholder in all templates. Measurement ID comes from `config["analytics"]["measurement_id"]`.

## Markdown-to-HTML rendering

`_md_to_html(text)` handles: `## headers`, `### sub-headers`, `**bold**`, `- bullet lists`, plain paragraphs. It does not handle tables, links, or code blocks — keep brief content to these supported elements.

## Bias colour mapping

```python
BIAS_COLORS = {
    "far-left":     "#e05252",
    "left":         "#e07a7a",
    "center-left":  "#e0a87a",
    "center":       "#7ab8e0",
    "libertarian":  "#a07ae0",
    "center-right": "#7ae09b",
    "right":        "#5ab56e",
    "far-right":    "#3a8a52",
    "unknown":      "#888888",
}
```

Used in story cards and the source index. Add new bias values here if a source uses a non-standard label.

## Testing reporter changes

Patch `pipeline.reporter.REPORTS_DIR` with `tmp_path` — never write to the real `reports/` directory in tests:

```python
def test_something(self, tmp_path):
    with patch("pipeline.reporter.REPORTS_DIR", tmp_path):
        path = generate_report(brief_text, clusters, correlation, articles, model)
    assert path.exists()
    assert "expected content" in path.read_text()
```

## What is gitignored vs tracked

- `reports/brief_*.html`, `reports/weekly_*.html`, and `reports/monthly_*.html` — **tracked** (served via GitHub Pages)
- `index.html` and `archive.html` — **tracked** (landing and archive pages)
- `feed.xml` — **tracked**; included in daily `run_and_publish.sh` git push
- `reports/cards/*.png`, `reports/posts/*.json` — **tracked** (social artifacts)
- Prettier ignores generated HTML (see `.prettierignore`) — never run Prettier on generated HTML
