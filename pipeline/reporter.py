#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
HTML report generator for Signal.

Produces a single self-contained HTML file styled as an intelligence brief.
Dark theme, clear section hierarchy, bias indicators, source attribution.
"""

from __future__ import annotations

import html
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

REPORTS_DIR = Path(__file__).parent.parent / "reports"

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

HTML_TEMPLATE = """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Signal — Political Intelligence Brief {date}</title>
<style>
  :root {{
    --bg:       #0d1117;
    --surface:  #161b22;
    --border:   #30363d;
    --text:     #c9d1d9;
    --muted:    #8b949e;
    --accent:   #58a6ff;
    --warn:     #e3b341;
    --danger:   #f85149;
    --success:  #3fb950;
    --code-bg:  #1f2937;
    --mono:     'JetBrains Mono', 'Fira Code', 'Courier New', monospace;
    --sans:     -apple-system, BlinkMacSystemFont, 'Segoe UI', Helvetica, Arial, sans-serif;
  }}

  * {{ box-sizing: border-box; margin: 0; padding: 0; }}

  body {{
    background: var(--bg);
    color: var(--text);
    font-family: var(--sans);
    font-size: 15px;
    line-height: 1.65;
    padding: 0 0 80px 0;
  }}

  /* ── Header ── */
  .header {{
    background: var(--surface);
    border-bottom: 1px solid var(--border);
    padding: 28px 40px 20px;
    position: sticky;
    top: 0;
    z-index: 100;
  }}

  .header-top {{
    display: flex;
    justify-content: space-between;
    align-items: flex-start;
    flex-wrap: wrap;
    gap: 12px;
  }}

  .wordmark {{
    font-family: var(--mono);
    font-size: 11px;
    letter-spacing: 0.25em;
    color: var(--muted);
    text-transform: uppercase;
    margin-bottom: 4px;
  }}

  .header h1 {{
    font-family: var(--mono);
    font-size: 22px;
    font-weight: 700;
    color: var(--accent);
    letter-spacing: -0.02em;
  }}

  .meta-pills {{
    display: flex;
    gap: 8px;
    flex-wrap: wrap;
    margin-top: 12px;
  }}

  .pill {{
    background: var(--code-bg);
    border: 1px solid var(--border);
    border-radius: 20px;
    padding: 3px 12px;
    font-size: 12px;
    font-family: var(--mono);
    color: var(--muted);
  }}

  .pill.accent {{ border-color: var(--accent); color: var(--accent); }}
  .pill.warn   {{ border-color: var(--warn);   color: var(--warn); }}

  /* ── Layout ── */
  .container {{ max-width: 960px; margin: 0 auto; padding: 0 24px; }}

  /* ── Brief sections ── */
  .brief-section {{
    margin: 40px 0;
    border-left: 3px solid var(--border);
    padding-left: 24px;
  }}

  .brief-section.highlight {{ border-left-color: var(--accent); }}
  .brief-section.warn-section {{ border-left-color: var(--warn); }}
  .brief-section.danger-section {{ border-left-color: var(--danger); }}

  .section-label {{
    font-family: var(--mono);
    font-size: 10px;
    letter-spacing: 0.25em;
    text-transform: uppercase;
    color: var(--muted);
    margin-bottom: 8px;
  }}

  .brief-section h2 {{
    font-size: 18px;
    font-weight: 700;
    color: var(--text);
    margin-bottom: 16px;
    padding-bottom: 8px;
    border-bottom: 1px solid var(--border);
  }}

  .brief-section p {{
    margin-bottom: 14px;
    color: var(--text);
  }}

  .brief-section ul {{
    list-style: none;
    padding: 0;
  }}

  .brief-section ul li {{
    padding: 8px 0 8px 20px;
    border-bottom: 1px solid var(--border);
    position: relative;
    color: var(--text);
  }}

  .brief-section ul li::before {{
    content: '›';
    position: absolute;
    left: 0;
    color: var(--accent);
    font-weight: bold;
  }}

  /* ── Story cards ── */
  .stories-grid {{
    display: grid;
    gap: 16px;
    margin: 24px 0;
  }}

  .story-card {{
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 20px;
    transition: border-color 0.15s;
  }}

  .story-card:hover {{ border-color: var(--accent); }}

  .story-card.high   {{ border-left: 4px solid var(--danger); }}
  .story-card.medium {{ border-left: 4px solid var(--warn); }}
  .story-card.low    {{ border-left: 4px solid var(--border); }}

  .story-headline {{
    font-size: 16px;
    font-weight: 600;
    color: var(--text);
    margin-bottom: 10px;
  }}

  .story-meta {{
    display: flex;
    gap: 8px;
    flex-wrap: wrap;
    margin-bottom: 12px;
  }}

  .bias-badge {{
    font-size: 11px;
    font-family: var(--mono);
    padding: 2px 8px;
    border-radius: 4px;
    font-weight: 600;
    background: rgba(255,255,255,0.07);
  }}

  .story-assessment {{
    font-size: 14px;
    color: var(--muted);
    margin: 10px 0;
    font-style: italic;
  }}

  .framing-grid {{
    display: grid;
    grid-template-columns: 1fr 1fr 1fr;
    gap: 10px;
    margin-top: 14px;
  }}

  @media (max-width: 640px) {{
    .framing-grid {{ grid-template-columns: 1fr; }}
  }}

  .framing-box {{
    background: var(--bg);
    border: 1px solid var(--border);
    border-radius: 6px;
    padding: 10px 12px;
    font-size: 12px;
  }}

  .framing-label {{
    font-family: var(--mono);
    font-size: 10px;
    text-transform: uppercase;
    letter-spacing: 0.1em;
    margin-bottom: 4px;
    font-weight: 700;
  }}

  .omissions-row {{
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 10px;
    margin-top: 10px;
  }}

  @media (max-width: 640px) {{
    .omissions-row {{ grid-template-columns: 1fr; }}
  }}

  .omission-box {{
    background: rgba(232, 63, 61, 0.06);
    border: 1px solid rgba(232, 63, 61, 0.2);
    border-radius: 6px;
    padding: 10px 12px;
    font-size: 12px;
    color: var(--muted);
  }}

  .omission-label {{
    font-family: var(--mono);
    font-size: 10px;
    text-transform: uppercase;
    letter-spacing: 0.1em;
    margin-bottom: 4px;
    color: var(--danger);
    font-weight: 700;
  }}

  /* ── Bias bar ── */
  .bias-bar-wrap {{ margin: 6px 0 12px; }}
  .bias-bar-label {{
    font-size: 11px;
    font-family: var(--mono);
    color: var(--muted);
    margin-bottom: 4px;
  }}
  .bias-bar {{
    display: flex;
    height: 8px;
    border-radius: 4px;
    overflow: hidden;
    gap: 1px;
  }}
  .bias-segment {{ flex: 1; min-width: 3px; }}

  /* ── Correlation section ── */
  .connection-card {{
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 16px 20px;
    margin-bottom: 12px;
  }}

  .connection-entities {{
    display: flex;
    gap: 6px;
    flex-wrap: wrap;
    margin-bottom: 8px;
  }}

  .entity-tag {{
    background: rgba(88,166,255,0.1);
    border: 1px solid rgba(88,166,255,0.3);
    border-radius: 4px;
    padding: 2px 8px;
    font-size: 12px;
    font-family: var(--mono);
    color: var(--accent);
  }}

  .connection-text {{
    font-size: 14px;
    color: var(--text);
    margin-bottom: 6px;
  }}

  .connection-sig {{
    font-size: 12px;
    color: var(--warn);
    font-style: italic;
  }}

  /* ── Anomaly / Pattern cards ── */
  .anomaly-item {{
    background: rgba(248, 81, 73, 0.05);
    border: 1px solid rgba(248, 81, 73, 0.2);
    border-radius: 6px;
    padding: 12px 16px;
    margin-bottom: 10px;
    font-size: 14px;
    color: var(--text);
  }}

  .pattern-item {{
    background: rgba(227, 179, 65, 0.05);
    border: 1px solid rgba(227, 179, 65, 0.2);
    border-radius: 6px;
    padding: 12px 16px;
    margin-bottom: 10px;
    font-size: 14px;
    color: var(--text);
  }}

  /* ── Watch list ── */
  .watch-item {{
    background: var(--surface);
    border: 1px solid var(--border);
    border-left: 4px solid var(--warn);
    border-radius: 6px;
    padding: 12px 16px;
    margin-bottom: 10px;
    font-size: 14px;
    font-family: var(--mono);
    color: var(--warn);
  }}

  /* ── Source index ── */
  .source-grid {{
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
    gap: 8px;
    margin-top: 16px;
  }}

  .source-item {{
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 6px;
    padding: 8px 12px;
    display: flex;
    align-items: center;
    gap: 8px;
    font-size: 13px;
  }}

  .source-dot {{
    width: 8px;
    height: 8px;
    border-radius: 50%;
    flex-shrink: 0;
  }}

  /* ── Divider ── */
  .divider {{
    border: none;
    border-top: 1px solid var(--border);
    margin: 40px 0;
  }}

  /* ── Analyst note ── */
  .analyst-note {{
    background: linear-gradient(135deg, rgba(88,166,255,0.05), rgba(88,166,255,0.02));
    border: 1px solid rgba(88,166,255,0.25);
    border-radius: 10px;
    padding: 24px 28px;
    margin: 40px 0;
  }}

  .analyst-note-header {{
    font-family: var(--mono);
    font-size: 10px;
    letter-spacing: 0.25em;
    text-transform: uppercase;
    color: var(--accent);
    margin-bottom: 14px;
  }}

  .analyst-note p {{
    font-size: 15px;
    line-height: 1.75;
    color: var(--text);
  }}

  /* ── Scrollbar ── */
  ::-webkit-scrollbar {{ width: 6px; }}
  ::-webkit-scrollbar-track {{ background: var(--bg); }}
  ::-webkit-scrollbar-thumb {{ background: var(--border); border-radius: 3px; }}
</style>
</head>
<body>

<div class="header">
  <div class="header-top">
    <div>
      <div class="wordmark">Signal // Political Intelligence</div>
      <h1>POLITICAL INTELLIGENCE BRIEF</h1>
    </div>
    <div><!-- spacer --></div>
  </div>
  <div class="meta-pills">
    <span class="pill accent">📅 {date}</span>
    <span class="pill">{article_count} articles</span>
    <span class="pill">{source_count} sources</span>
    <span class="pill">{cluster_count} story clusters</span>
    <span class="pill warn">🤖 {model}</span>
  </div>
</div>

<div class="container">

  {brief_sections}

  <hr class="divider">

  <!-- Story Analysis -->
  <div class="brief-section">
    <div class="section-label">Cross-Spectrum Story Analysis</div>
    <h2>INDIVIDUAL STORY BREAKDOWN</h2>
    <div class="stories-grid">
      {story_cards}
    </div>
  </div>

  <hr class="divider">

  <!-- Correlation / Patterns -->
  <div class="brief-section warn-section">
    <div class="section-label">Intelligence Layer</div>
    <h2>CONNECTIONS &amp; PATTERNS</h2>

    {connections_html}

    <h3 style="font-size:15px; color: var(--warn); margin: 24px 0 12px; font-family: var(--mono); letter-spacing: 0.1em;">NARRATIVE PATTERNS</h3>
    {patterns_html}

    <h3 style="font-size:15px; color: var(--danger); margin: 24px 0 12px; font-family: var(--mono); letter-spacing: 0.1em;">ANOMALIES</h3>
    {anomalies_html}
  </div>

  <hr class="divider">

  <!-- Blindspot analysis -->
  <div class="brief-section danger-section">
    <div class="section-label">Coverage Gaps</div>
    <h2>BLINDSPOT ANALYSIS</h2>
    <p style="margin-bottom: 16px;">{blindspot_analysis}</p>

    <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 16px;">
      <div>
        <div class="omission-label" style="color: #e07a7a;">Left-Only Coverage</div>
        {left_only_html}
      </div>
      <div>
        <div class="omission-label" style="color: #5ab56e;">Right-Only Coverage</div>
        {right_only_html}
      </div>
    </div>
  </div>

  <hr class="divider">

  <!-- Watch List -->
  <div class="brief-section warn-section">
    <div class="section-label">Forward Watch</div>
    <h2>WATCH LIST</h2>
    {watch_list_html}
  </div>

  <hr class="divider">

  <!-- Source Index -->
  <div class="brief-section">
    <div class="section-label">Sources Analyzed</div>
    <h2>SOURCE INDEX</h2>
    <div class="source-grid">
      {source_index_html}
    </div>
  </div>

</div>
</body>
</html>
"""


def _md_to_html(text: str) -> str:
    """
    Very lightweight markdown → HTML converter for the brief sections.

    Handles: ## headers, paragraphs, **bold**, bullet lists.
    """
    lines = text.split("\n")
    output = []
    in_list = False

    for line in lines:
        stripped = line.strip()

        if stripped.startswith("## "):
            if in_list:
                output.append("</ul>")
                in_list = False
            heading = html.escape(stripped[3:])
            output.append(f"<h2>{heading}</h2>")
        elif stripped.startswith("### "):
            if in_list:
                output.append("</ul>")
                in_list = False
            heading = html.escape(stripped[4:])
            output.append(f"<h3 style='font-size:15px; font-family:var(--mono); letter-spacing:0.08em; color:var(--accent); margin: 20px 0 8px;'>{heading}</h3>")
        elif stripped.startswith(("- ", "* ", "• ")):
            if not in_list:
                output.append("<ul>")
                in_list = True
            item = html.escape(stripped[2:])
            item = re.sub(r"\*\*(.*?)\*\*", r"<strong>\1</strong>", item)
            output.append(f"<li>{item}</li>")
        elif stripped == "":
            if in_list:
                output.append("</ul>")
                in_list = False
        else:
            if in_list:
                output.append("</ul>")
                in_list = False
            para = html.escape(stripped)
            para = re.sub(r"\*\*(.*?)\*\*", r"<strong>\1</strong>", para)
            output.append(f"<p>{para}</p>")

    if in_list:
        output.append("</ul>")

    return "\n".join(output)


def _parse_brief_sections(brief_text: str) -> Dict[str, str]:
    """
    Split brief text into named sections based on ## headings.

    Returns dict of {section_name: content}.
    """
    sections: Dict[str, str] = {}
    current_key = "preamble"
    current_lines: List[str] = []

    for line in brief_text.split("\n"):
        if line.startswith("## "):
            if current_lines:
                sections[current_key] = "\n".join(current_lines).strip()
            current_key = line[3:].strip().upper()
            current_lines = []
        else:
            current_lines.append(line)

    if current_lines:
        sections[current_key] = "\n".join(current_lines).strip()

    return sections


def _render_brief_sections(brief_text: str) -> str:
    """Render the main brief narrative into styled HTML sections."""
    sections = _parse_brief_sections(brief_text)
    output = []

    section_styles = {
        "SITUATION OVERVIEW": ("highlight", "📡"),
        "KEY ACTORS AND DYNAMICS": ("", "🎭"),
        "WHAT ISN'T BEING SAID": ("danger-section", "🔇"),
        "CONNECTIONS AND PATTERNS": ("warn-section", "🔗"),
        "WATCH LIST": ("warn-section", "👁"),
        "ANALYST NOTE": ("highlight", "🧠"),
    }

    for name, content in sections.items():
        if name == "preamble" or not content:
            continue

        style_class, icon = section_styles.get(name, ("", "▸"))
        content_html = _md_to_html(content)

        if name == "ANALYST NOTE":
            output.append(f"""
<div class="analyst-note">
  <div class="analyst-note-header">✦ Analyst Note</div>
  {content_html}
</div>""")
        else:
            output.append(f"""
<div class="brief-section {style_class}">
  <div class="section-label">{icon} Intelligence Brief</div>
  <h2>{html.escape(name)}</h2>
  {content_html}
</div>""")

    return "\n".join(output)


def _render_bias_bar(bias_spread: Dict[str, int]) -> str:
    """Render a horizontal bias distribution bar."""
    total = sum(bias_spread.values()) or 1
    segments = []
    for bias, count in sorted(bias_spread.items()):
        color = BIAS_COLORS.get(bias, "#888888")
        pct = (count / total) * 100
        segments.append(
            f'<div class="bias-segment" style="background:{color}; flex:{pct:.1f};" '
            f'title="{bias}: {count}"></div>'
        )
    bar = "".join(segments)
    return f'<div class="bias-bar-wrap"><div class="bias-bar-label">Coverage spectrum</div><div class="bias-bar">{bar}</div></div>'


def _render_story_cards(clusters: List[Dict[str, Any]]) -> str:
    """Render story cluster cards with framing breakdown."""
    cards = []
    multi_clusters = sorted(
        [c for c in clusters if not c.get("singleton")],
        key=lambda c: {"high": 0, "medium": 1, "low": 2}.get(
            c.get("analysis", {}).get("significance", "medium"), 1
        ),
    )

    for cluster in multi_clusters:
        analysis = cluster.get("analysis", {})
        headline = html.escape(analysis.get("headline", cluster["story_title"]))
        assessment = html.escape(analysis.get("assessment", ""))
        significance = analysis.get("significance", "medium")
        bias_spread = cluster.get("bias_spread", {})

        # Bias badges
        badges = "".join(
            f'<span class="bias-badge" style="color:{BIAS_COLORS.get(b, "#888")};">'
            f'{html.escape(b)} ({n})</span>'
            for b, n in sorted(bias_spread.items())
        )

        bias_bar = _render_bias_bar(bias_spread)

        # Framing boxes
        framing = ""
        left_f = analysis.get("left_framing", "")
        center_f = analysis.get("center_framing", "")
        right_f = analysis.get("right_framing", "")
        if any([left_f, center_f, right_f]):
            framing = f"""
<div class="framing-grid">
  <div class="framing-box">
    <div class="framing-label" style="color:{BIAS_COLORS['left']};">Left</div>
    {html.escape(left_f)}
  </div>
  <div class="framing-box">
    <div class="framing-label" style="color:{BIAS_COLORS['center']};">Center</div>
    {html.escape(center_f)}
  </div>
  <div class="framing-box">
    <div class="framing-label" style="color:{BIAS_COLORS['right']};">Right</div>
    {html.escape(right_f)}
  </div>
</div>"""

        # Omissions
        omissions = ""
        lo = analysis.get("left_omissions", "")
        ro = analysis.get("right_omissions", "")
        if lo or ro:
            omissions = f"""
<div class="omissions-row">
  <div class="omission-box">
    <div class="omission-label">Not said by left</div>
    {html.escape(lo)}
  </div>
  <div class="omission-box">
    <div class="omission-label">Not said by right</div>
    {html.escape(ro)}
  </div>
</div>"""

        cards.append(f"""
<div class="story-card {significance}">
  <div class="story-headline">{headline}</div>
  <div class="story-meta">{badges}</div>
  {bias_bar}
  <div class="story-assessment">{assessment}</div>
  {framing}
  {omissions}
</div>""")

    return "\n".join(cards) if cards else "<p style='color:var(--muted)'>No multi-source clusters identified.</p>"


def _render_connections(connections: List[Dict[str, Any]]) -> str:
    if not connections:
        return "<p style='color:var(--muted)'>No significant connections identified in this run.</p>"
    items = []
    for conn in connections:
        entities = "".join(
            f'<span class="entity-tag">{html.escape(str(e))}</span>'
            for e in conn.get("entities", [])
        )
        items.append(f"""
<div class="connection-card">
  <div class="connection-entities">{entities}</div>
  <div class="connection-text">{html.escape(conn.get('connection', ''))}</div>
  <div class="connection-sig">↳ {html.escape(conn.get('significance', ''))}</div>
</div>""")
    return "\n".join(items)


def _render_list_items(items: List[str], css_class: str) -> str:
    if not items:
        return f"<p style='color:var(--muted)'>None identified.</p>"
    return "\n".join(
        f'<div class="{css_class}">{html.escape(str(item))}</div>'
        for item in items
    )


def _render_source_index(articles: List[Dict[str, Any]]) -> str:
    """Render the source index grouped by source name."""
    sources: Dict[str, str] = {}
    for a in articles:
        name = a.get("source_name", "Unknown")
        bias = a.get("bias", "unknown")
        sources[name] = bias

    items = []
    for name, bias in sorted(sources.items()):
        color = BIAS_COLORS.get(bias, "#888888")
        items.append(
            f'<div class="source-item">'
            f'<div class="source-dot" style="background:{color};"></div>'
            f'<span>{html.escape(name)}</span>'
            f'</div>'
        )
    return "\n".join(items)


def _render_side_coverage(titles: List[str]) -> str:
    if not titles:
        return "<p style='color:var(--muted); font-size:13px;'>None identified.</p>"
    return "".join(
        f'<div style="font-size:13px; padding:6px 0; border-bottom:1px solid var(--border);">'
        f'› {html.escape(t)}</div>'
        for t in titles
    )


def generate_report(
    brief_text: str,
    clusters: List[Dict[str, Any]],
    correlation: Dict[str, Any],
    articles: List[Dict[str, Any]],
    run_id: int,
    model: str,
) -> Path:
    """
    Generate and write the HTML intelligence brief.

    Args:
        brief_text: Markdown brief from Pass 5.
        clusters: Analyzed story clusters from Pass 3.
        correlation: Cross-story correlation from Pass 4.
        articles: All collected articles.
        run_id: Pipeline run id.
        model: Ollama model used.

    Returns:
        Path to the generated HTML file.
    """
    REPORTS_DIR.mkdir(exist_ok=True)

    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    file_date = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M")

    multi_clusters = [c for c in clusters if not c.get("singleton")]

    brief_sections_html = _render_brief_sections(brief_text)
    story_cards_html = _render_story_cards(clusters)

    connections_html = _render_connections(correlation.get("hidden_connections", []))
    patterns_html = _render_list_items(correlation.get("narrative_patterns", []), "pattern-item")
    anomalies_html = _render_list_items(correlation.get("anomalies", []), "anomaly-item")

    blindspot_analysis = html.escape(correlation.get("blindspot_analysis", ""))
    left_only = correlation.get("_left_only", [])
    right_only = correlation.get("_right_only", [])
    left_only_html = _render_side_coverage(left_only)
    right_only_html = _render_side_coverage(right_only)

    watch_items = correlation.get("recommended_watch", [])
    watch_list_html = _render_list_items(watch_items, "watch-item")

    source_index_html = _render_source_index(articles)

    source_names = set(a["source_name"] for a in articles)

    rendered = HTML_TEMPLATE.format(
        date=date_str,
        article_count=len(articles),
        source_count=len(source_names),
        cluster_count=len(multi_clusters),
        model=html.escape(model),
        brief_sections=brief_sections_html,
        story_cards=story_cards_html,
        connections_html=connections_html,
        patterns_html=patterns_html,
        anomalies_html=anomalies_html,
        blindspot_analysis=blindspot_analysis,
        left_only_html=left_only_html,
        right_only_html=right_only_html,
        watch_list_html=watch_list_html,
        source_index_html=source_index_html,
    )

    out_path = REPORTS_DIR / f"brief_{file_date}_run{run_id}.html"
    out_path.write_text(rendered, encoding="utf-8")
    return out_path
