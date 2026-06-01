#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Signal — Political Intelligence Analysis Pipeline
Entry point.

Usage:
    python main.py                    # full run
    python main.py --collect-only     # just fetch articles, no analysis
    python main.py --model qwen2.5:14b  # override model
    python main.py --no-fetch         # skip full article text fetch (faster)
"""

import argparse
import shutil
import subprocess
import sys
import venv
from pathlib import Path


ROOT = Path(__file__).parent


def setup_venv() -> Path:
    """Create venv and install requirements; return path to venv Python."""
    venv_dir = ROOT / ".venv"
    if not venv_dir.exists():
        print("🔧  Creating virtual environment...")
        venv.create(venv_dir, with_pip=True)

    python = venv_dir / "bin" / "python"
    req = ROOT / "requirements.txt"
    if req.exists():
        print("📦  Installing requirements...")
        subprocess.run(
            [str(python), "-m", "pip", "install", "-q", "-r", str(req)],
            check=True,
        )
    return python


def run_weekly_signal(args: argparse.Namespace) -> None:
    """Weekly synthesis pipeline — reads DB, runs Pass 6, writes HTML report."""
    from rich.console import Console
    from pipeline.collector import load_config
    from pipeline.weekly import run_weekly
    from pipeline.reporter import generate_weekly_report

    console = Console()
    config = load_config()
    days = getattr(args, "days", 7)
    ga_id = config.get("analytics", {}).get("measurement_id", "")

    brief_text, metadata = run_weekly(config, days=days)

    console.print("[bold cyan]Generating weekly HTML report...[/bold cyan]")
    report_path = generate_weekly_report(brief_text, metadata, ga_measurement_id=ga_id)

    _update_index(latest_daily=None, latest_weekly=report_path, ga_id=ga_id)

    console.print("\n[bold green]✓ Weekly brief complete[/bold green]")
    console.print(f"  Report: [underline]{report_path}[/underline]")
    console.print(f"  Open:   [dim]open {report_path}[/dim]\n")


def run_signal(args: argparse.Namespace) -> None:
    """Main pipeline execution."""
    # Import here so venv is set up first when running via bootstrap
    from rich.console import Console
    from pipeline import store
    from pipeline.collector import collect_feeds, load_config
    from pipeline.analyzer import run_pipeline
    from pipeline.reporter import generate_report

    console = Console()
    console.print("\n[bold cyan]▸ SIGNAL[/bold cyan] [dim]— Political Intelligence Pipeline[/dim]\n")

    # Load config
    config = load_config()
    if args.no_fetch:
        config["collection"]["fetch_full_text"] = False
    ga_id = config.get("analytics", {}).get("measurement_id", "")

    # Init DB
    store.init_db()
    run_id = store.start_run()
    console.print(f"[dim]Run #{run_id} started[/dim]\n")

    # Collect
    articles = collect_feeds(config)
    if not articles:
        console.print("[red]No articles collected. Check feeds / network.[/red]")
        sys.exit(1)

    article_db_ids = store.save_articles(run_id, articles)

    if args.collect_only:
        console.print(f"\n[green]✓[/green] Collect-only mode. {len(articles)} articles saved to DB.")
        store.finish_run(run_id, len(articles), 0)
        return

    # Determine provider (env var overrides config)
    import os
    llm_cfg  = config.get("llm", {})
    provider = os.environ.get("SIGNAL_LLM_PROVIDER", llm_cfg.get("provider", "ollama"))

    if provider == "claude":
        claude_bin = shutil.which("claude") or "/opt/homebrew/bin/claude"
        console.print("[dim]Checking Claude Code CLI...[/dim]")
        try:
            result = subprocess.run(
                [claude_bin, "--version"], capture_output=True, text=True, timeout=10
            )
            if result.returncode != 0:
                raise RuntimeError(result.stderr.strip())
            console.print(f"[green]✓[/green] {result.stdout.strip()}\n")
        except Exception as exc:
            console.print(f"[red]✗[/red] Cannot reach Claude CLI: {exc}")
            console.print("  Install via: [bold]npm install -g @anthropic-ai/claude-code[/bold]")
            sys.exit(1)
        model = "claude"
    else:
        import ollama as _ollama
        ollama_cfg = llm_cfg.get("ollama", {})
        model      = ollama_cfg.get("model", "qwen2.5:14b")
        base_url   = ollama_cfg.get("base_url", "http://localhost:11434")
        console.print(f"[dim]Checking Ollama ({model})...[/dim]")
        try:
            client    = _ollama.Client(host=base_url)
            available = [m.model for m in client.list().models]
            if not any(model in m for m in available):
                console.print(f"\n[yellow]⚠[/yellow]  Model [bold]{model}[/bold] not found.")
                console.print(f"    Available: {', '.join(available) or 'none'}")
                console.print(f"    Run: [bold]ollama pull {model}[/bold]\n")
                sys.exit(1)
            console.print(f"[green]✓[/green] Ollama ready with {model}\n")
        except Exception as exc:
            console.print(f"[red]✗[/red] Cannot reach Ollama: {exc}")
            console.print("  Start it with: [bold]ollama serve[/bold]")
            sys.exit(1)

    # Run analysis pipeline
    brief, clusters, correlation = run_pipeline(
        articles, article_db_ids, run_id, config
    )

    # Update run record
    multi_clusters = [c for c in clusters if not c.get("singleton")]
    store.finish_run(run_id, len(articles), len(multi_clusters))

    # Generate report
    console.print("\n[bold cyan]Generating HTML report...[/bold cyan]")
    report_path = generate_report(brief, clusters, correlation, articles, run_id, model, ga_measurement_id=ga_id)

    # Generate social cards + post packages (requires playwright + .env credentials)
    _generate_social_cards(report_path, console)

    # Update index.html to redirect to the latest report
    _update_index(latest_daily=report_path, latest_weekly=None, ga_id=ga_id)

    console.print("\n[bold green]✓ Brief complete[/bold green]")
    console.print(f"  Report: [underline]{report_path}[/underline]")
    console.print(f"  Open:   [dim]open {report_path}[/dim]\n")


def _generate_social_cards(report_path: "Path", console: "Any") -> None:
    """
    Render the three social card PNGs and write post-package JSON files.

    Skips gracefully if:
    - playwright is not installed (optional dep)
    - brief_data.json was not written (unexpected reporter error)
    - any individual card fails (logs warning, continues)
    """
    import json as _json
    from datetime import datetime, timezone

    json_path = report_path.with_suffix(".json")
    if not json_path.exists():
        console.print("[yellow]⚠  brief_data.json not found — skipping social cards[/yellow]")
        return

    try:
        from pipeline.infographic import render_all_cards
        from pipeline.social import build_post_package
    except ImportError:
        console.print("[dim]Social cards skipped — playwright/atproto not installed[/dim]")
        return

    brief_data = _json.loads(json_path.read_text(encoding="utf-8"))
    date_slug  = datetime.now(timezone.utc).strftime("%Y%m%d")

    console.print("[bold cyan]Generating social cards...[/bold cyan]")
    try:
        card_paths = render_all_cards(brief_data)
        for slot, card_path in card_paths.items():
            pkg_path = build_post_package(slot, brief_data, card_path, date_slug)
            console.print(f"  [green]✓[/green] {slot.upper():4}  {card_path.name}  →  {pkg_path.name}")
    except Exception as exc:  # noqa: BLE001
        console.print(f"[yellow]⚠  Social card generation failed: {exc}[/yellow]")


def _update_index(
    latest_daily: "Path | None",
    latest_weekly: "Path | None",
    ga_id: str = "",
) -> None:
    """Regenerate index.html and archive.html after any report is generated."""
    from pipeline.reporter import ga_snippet as _ga_snippet
    ga_head = _ga_snippet(ga_id)

    reports_dir = ROOT / "reports"

    # Resolve the latest daily report (use argument or fall back to most recent file)
    daily_reports = sorted(reports_dir.glob("brief_*.html"), reverse=True)
    if latest_daily is None and daily_reports:
        latest_daily = daily_reports[0]

    # Resolve the latest weekly report
    weekly_reports = sorted(reports_dir.glob("weekly_*.html"), reverse=True)
    if latest_weekly is None and weekly_reports:
        latest_weekly = weekly_reports[0]

    # ── index.html ────────────────────────────────────────────────────────────
    daily_card = ""
    if latest_daily:
        rel = latest_daily.relative_to(ROOT)
        parts = latest_daily.stem.split("_")
        try:
            brief_date = f"{parts[1][:4]}-{parts[1][4:6]}-{parts[1][6:]}"
            brief_time = f"{parts[2][:2]}:{parts[2][2:]} UTC"
        except IndexError:
            brief_date, brief_time = "—", "—"
        daily_card = f"""
      <a href="{rel}" class="card">
        <div class="card-label">Latest Brief</div>
        <div class="card-title">Today's Intelligence Report</div>
        <div class="card-meta">{brief_date} · {brief_time}</div>
      </a>"""

    weekly_card = ""
    if latest_weekly:
        w_rel = latest_weekly.relative_to(ROOT)
        w_parts = latest_weekly.stem.split("_")
        try:
            # weekly_2026W20_20260519_2200 → week label from stem
            w_label = f"Week {w_parts[1]}"
        except IndexError:
            w_label = latest_weekly.stem
        weekly_card = f"""
      <a href="{w_rel}" class="card weekly">
        <div class="card-label">Weekly Summary</div>
        <div class="card-title">Weekly Intelligence Brief</div>
        <div class="card-meta">{w_label}</div>
      </a>"""

    (ROOT / "index.html").write_text(
        f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Signal — Political Intelligence Pipeline</title>
<link rel="alternate" type="application/rss+xml" title="Signal — Political Intelligence Pipeline" href="https://flexrpl.github.io/signal/feed.xml">
{ga_head}
<style>
  :root {{
    --bg: #0d1117; --surface: #161b22; --border: #30363d;
    --text: #c9d1d9; --muted: #8b949e; --accent: #58a6ff; --gold: #e3b341;
    --mono: 'JetBrains Mono', 'Fira Code', monospace;
    --sans: -apple-system, BlinkMacSystemFont, 'Segoe UI', Helvetica, Arial, sans-serif;
  }}
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{
    background-color: var(--bg);
    background-image: url('images/signal_banner.png');
    background-size: cover;
    background-position: center;
    background-repeat: no-repeat;
    color: var(--text); font-family: var(--sans);
    min-height: 100vh; display: flex; flex-direction: column;
    align-items: center; justify-content: center; padding: 40px 24px;
    position: relative;
  }}
  body::before {{
    content: '';
    position: fixed; inset: 0;
    background: rgba(13, 17, 23, 0.82);
    z-index: 0;
  }}
  .content {{
    position: relative; z-index: 1;
    display: flex; flex-direction: column;
    align-items: center;
  }}
  .wordmark {{ font-family: var(--mono); font-size: 11px; letter-spacing: .3em;
               color: var(--muted); text-transform: uppercase; margin-bottom: 12px;
               text-align: center; }}
  h1 {{ font-family: var(--mono); font-size: 28px; font-weight: 700;
        color: var(--accent); letter-spacing: -.02em; margin-bottom: 8px;
        text-align: center; }}
  .tagline {{ color: var(--muted); font-size: 14px; margin-bottom: 48px;
              text-align: center; }}
  .cards {{ display: flex; gap: 16px; flex-wrap: wrap; justify-content: center; }}
  .card {{ background: rgba(22, 27, 34, 0.85); border: 1px solid var(--border);
           border-radius: 10px; padding: 28px 32px; text-decoration: none;
           color: var(--text); width: 260px; transition: border-color .15s;
           backdrop-filter: blur(6px); }}
  .card:hover {{ border-color: var(--accent); }}
  .card.weekly:hover {{ border-color: var(--gold); }}
  .card-label {{ font-family: var(--mono); font-size: 10px; letter-spacing: .2em;
                 text-transform: uppercase; color: var(--muted); margin-bottom: 10px; }}
  .card-title {{ font-size: 17px; font-weight: 600; color: var(--accent);
                 margin-bottom: 8px; }}
  .card.weekly .card-title {{ color: var(--gold); }}
  .card-meta {{ font-size: 12px; color: var(--muted); font-family: var(--mono); }}
  .card.archive .card-title {{ color: var(--text); }}
  .rss-bar {{ margin-top: 36px; text-align: center; }}
  .rss-link {{ display: inline-flex; align-items: center; gap: 7px;
               font-family: var(--mono); font-size: 11px; letter-spacing: .12em;
               color: var(--muted); text-decoration: none; border: 1px solid var(--border);
               border-radius: 6px; padding: 7px 14px; transition: border-color .15s, color .15s; }}
  .rss-link:hover {{ border-color: #f0822a; color: #f0822a; }}
  .rss-icon {{ width: 13px; height: 13px; fill: currentColor; flex-shrink: 0; }}
</style>
</head>
<body>
  <div class="content">
    <div class="wordmark">Signal // Political Intelligence</div>
    <h1>SIGNAL</h1>
    <p class="tagline">Daily cross-spectrum political intelligence — powered by local AI</p>
    <div class="cards">
      {daily_card}
      {weekly_card}
      <a href="archive.html" class="card archive">
        <div class="card-label">History</div>
        <div class="card-title">Browse Past Briefs</div>
        <div class="card-meta">All previous reports</div>
      </a>
    </div>
    <div class="rss-bar">
      <a href="feed.xml" class="rss-link">
        <svg class="rss-icon" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">
          <path d="M6.18 15.64a2.18 2.18 0 0 1 2.18 2.18C8.36 19.01 7.38 20 6.18 20C4.98 20 4 19.01 4 17.82a2.18 2.18 0 0 1 2.18-2.18M4 4.44A15.56 15.56 0 0 1 19.56 20h-2.83A12.73 12.73 0 0 0 4 7.27V4.44m0 5.66a9.9 9.9 0 0 1 9.9 9.9h-2.83A7.07 7.07 0 0 0 4 12.93V10.1z"/>
        </svg>
        Subscribe via RSS
      </a>
    </div>
  </div>
</body>
</html>
""",
        encoding="utf-8",
    )

    # ── archive.html — grouped by ISO week ───────────────────────────────────
    from datetime import datetime as _dt

    def _iso_week(p: Path) -> str:
        """Return 'YYYYWNN' for a brief_YYYYMMDD or weekly_YYYYWNN file."""
        parts = p.stem.split("_")
        if p.stem.startswith("weekly_"):
            return parts[1]  # already YYYYWNN
        try:
            d = _dt.strptime(parts[1], "%Y%m%d")
            iso_y, iso_w, _ = d.isocalendar()
            return f"{iso_y}W{iso_w:02d}"
        except (IndexError, ValueError):
            return "unknown"

    def _week_label(iso_wk: str) -> str:
        """Convert '2026W20' → 'Week 20 · May 11–17, 2026'."""
        try:
            year = int(iso_wk[:4])
            week = int(iso_wk[5:])
            # ISO weeks start on Monday
            mon = _dt.fromisocalendar(year, week, 1)
            sun = _dt.fromisocalendar(year, week, 7)
            month_fmt = "%b %-d"
            return f"Week {week} · {mon.strftime(month_fmt)}–{sun.strftime('%-d')}, {year}"
        except (ValueError, AttributeError):
            return iso_wk

    def _daily_row(p: Path, is_latest: bool) -> str:
        parts = p.stem.split("_")
        try:
            date_str = f"{parts[1][:4]}-{parts[1][4:6]}-{parts[1][6:]}"
            time_str = f"{parts[2][:2]}:{parts[2][2:]} UTC"
            label = f"{date_str} · {time_str}"
        except IndexError:
            label = p.stem
        badge = (
            ' <span class="badge badge-latest">latest</span>'
            if is_latest else ""
        )
        return f'<li class="daily-row"><a href="reports/{p.name}">{label}</a>{badge}</li>'

    def _weekly_row_html(p: Path, is_latest: bool) -> str:
        parts = p.stem.split("_")
        try:
            w_label = parts[1]
        except IndexError:
            w_label = p.stem
        badge = (
            ' <span class="badge badge-week">latest week</span>'
            if is_latest else ""
        )
        return (
            f'<li class="weekly-row">'
            f'<a href="reports/{p.name}">📊 Weekly Brief — {w_label}</a>{badge}</li>'
        )

    # Build a map: iso_week → {daily: [Path], weekly: Path|None}
    # For weekly reports, deduplicate — keep only latest file per week number
    weekly_by_week: dict = {}
    for p in weekly_reports:
        wk = _iso_week(p)
        if wk not in weekly_by_week or p.stem > weekly_by_week[wk].stem:
            weekly_by_week[wk] = p

    daily_by_week: dict = {}
    for p in daily_reports:
        wk = _iso_week(p)
        daily_by_week.setdefault(wk, []).append(p)

    all_weeks = sorted(
        set(list(weekly_by_week.keys()) + list(daily_by_week.keys())),
        reverse=True,
    )

    week_sections_html = []
    for wk in all_weeks:
        label = _week_label(wk)
        items = []

        # Weekly summary at the top of the group (if it exists for this week)
        if wk in weekly_by_week:
            wp = weekly_by_week[wk]
            is_latest_w = (wp == latest_weekly)
            items.append(_weekly_row_html(wp, is_latest_w))

        # Daily briefs for this week, most recent first
        for dp in daily_by_week.get(wk, []):
            is_latest_d = (dp == latest_daily)
            items.append(_daily_row(dp, is_latest_d))

        rows = "\n        ".join(items)
        week_sections_html.append(f"""
  <div class="week-group">
    <div class="week-header">{label}</div>
    <ul>
        {rows}
    </ul>
  </div>""")

    total_daily = len(daily_reports)
    total_weekly = len(weekly_by_week)
    summary_line = f"{total_daily} daily brief{'s' if total_daily != 1 else ''}"
    if total_weekly:
        summary_line += f" · {total_weekly} weekly summar{'ies' if total_weekly != 1 else 'y'}"

    (ROOT / "archive.html").write_text(
        f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Signal — Brief Archive</title>
<link rel="alternate" type="application/rss+xml" title="Signal — Political Intelligence Pipeline" href="https://flexrpl.github.io/signal/feed.xml">
{ga_head}
<style>
  :root {{
    --bg: #0d1117; --surface: #161b22; --border: #30363d;
    --text: #c9d1d9; --muted: #8b949e; --accent: #58a6ff; --gold: #e3b341;
    --mono: 'JetBrains Mono', 'Fira Code', monospace;
    --sans: -apple-system, BlinkMacSystemFont, 'Segoe UI', Helvetica, Arial, sans-serif;
  }}
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ background: var(--bg); color: var(--text); font-family: var(--sans);
          font-size: 15px; line-height: 1.65; padding: 0 0 80px; }}
  .header {{ background: var(--surface); border-bottom: 1px solid var(--border);
             padding: 28px 40px 20px; }}
  .wordmark {{ font-family: var(--mono); font-size: 11px; letter-spacing: .25em;
               color: var(--muted); text-transform: uppercase; margin-bottom: 4px; }}
  h1 {{ font-family: var(--mono); font-size: 22px; font-weight: 700; color: var(--accent); }}
  .container {{ max-width: 720px; margin: 40px auto; padding: 0 24px; }}
  .summary {{ font-family: var(--mono); font-size: 12px; letter-spacing: .1em;
              text-transform: uppercase; color: var(--muted); margin-bottom: 32px; }}
  .week-group {{ margin-bottom: 32px; }}
  .week-header {{
    font-family: var(--mono); font-size: 11px; font-weight: 700;
    letter-spacing: .2em; text-transform: uppercase;
    color: var(--muted); padding: 10px 0 8px;
    border-top: 1px solid var(--border);
    margin-bottom: 0;
  }}
  ul {{ list-style: none; }}
  li {{ border-bottom: 1px solid var(--border); padding: 11px 0 11px 16px; }}
  li.weekly-row {{ padding-left: 0; background: rgba(227,179,65,0.04); }}
  a {{ text-decoration: none; font-size: 14px; }}
  li.daily-row a {{ color: var(--accent); }}
  li.weekly-row a {{ color: var(--gold); font-weight: 500; }}
  a:hover {{ text-decoration: underline; }}
  .badge {{
    display: inline-block; font-size: 10px; padding: 2px 8px;
    border-radius: 10px; font-family: monospace; vertical-align: middle;
    margin-left: 8px;
  }}
  .badge-latest {{ background: #1f6feb; color: #fff; }}
  .badge-week   {{ background: #6e4c00; color: var(--gold); }}
  .back {{ display: inline-block; margin-top: 32px; font-family: var(--mono);
           font-size: 12px; color: var(--muted); text-decoration: none;
           border: 1px solid var(--border); border-radius: 6px; padding: 6px 14px; }}
  .back:hover {{ color: var(--accent); border-color: var(--accent); }}
  .rss-link {{ display: inline-flex; align-items: center; gap: 7px; margin-top: 12px;
               font-family: var(--mono); font-size: 11px; letter-spacing: .12em;
               color: var(--muted); text-decoration: none; border: 1px solid var(--border);
               border-radius: 6px; padding: 7px 14px; transition: border-color .15s, color .15s; }}
  .rss-link:hover {{ border-color: #f0822a; color: #f0822a; }}
  .rss-icon {{ width: 13px; height: 13px; fill: currentColor; flex-shrink: 0; }}
</style>
</head>
<body>
<div class="header">
  <div class="wordmark">Signal // Political Intelligence</div>
  <h1>BRIEF ARCHIVE</h1>
</div>
<div class="container">
  <div class="summary">{summary_line} — grouped by week</div>
  {"".join(week_sections_html)}
  <a href="index.html" class="back">▸ Back to home</a>
  <a href="feed.xml" class="rss-link">
    <svg class="rss-icon" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">
      <path d="M6.18 15.64a2.18 2.18 0 0 1 2.18 2.18C8.36 19.01 7.38 20 6.18 20C4.98 20 4 19.01 4 17.82a2.18 2.18 0 0 1 2.18-2.18M4 4.44A15.56 15.56 0 0 1 19.56 20h-2.83A12.73 12.73 0 0 0 4 7.27V4.44m0 5.66a9.9 9.9 0 0 1 9.9 9.9h-2.83A7.07 7.07 0 0 0 4 12.93V10.1z"/>
    </svg>
    Subscribe via RSS
  </a>
</div>
</body>
</html>
""",
        encoding="utf-8",
    )

    # ── feed.xml ──────────────────────────────────────────────────────────────
    from pipeline.feed import generate_feed
    generate_feed()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Signal — Political Intelligence Analysis Pipeline",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Model recommendations for M1 Max 32GB:
  llama3.1:8b     Fast, ~5GB — good for development
  qwen2.5:14b     Best reasoning, ~9GB — recommended for production
  mistral:7b      Compact baseline, ~4GB

Examples:
  python main.py                       # daily run
  python main.py --weekly              # weekly synthesis (reads DB, no fetching)
  python main.py --weekly --days 5     # weekly synthesis over past 5 days
  python main.py --model qwen2.5:14b
  python main.py --no-fetch --model llama3.1:8b
  python main.py --collect-only
        """,
    )
    parser.add_argument("--model", type=str, default=None, help="Ollama model override")
    parser.add_argument("--no-venv", action="store_true", help="Skip venv setup")
    parser.add_argument("--collect-only", action="store_true", help="Fetch articles only, skip analysis")
    parser.add_argument("--no-fetch", action="store_true", help="Skip full article text fetch")
    parser.add_argument(
        "--weekly",
        action="store_true",
        help="Generate weekly intelligence summary from DB (no fetching)",
    )
    parser.add_argument(
        "--days",
        type=int,
        default=7,
        help="Number of days to include in weekly synthesis (default: 7)",
    )
    args = parser.parse_args()

    if args.no_venv:
        if args.weekly:
            run_weekly_signal(args)
        else:
            run_signal(args)
    else:
        python = setup_venv()
        cmd = [str(python), str(Path(__file__).resolve()), "--no-venv"]
        if args.weekly:
            cmd.append("--weekly")
            cmd += ["--days", str(args.days)]
        else:
            if args.model:
                cmd += ["--model", args.model]
            if args.collect_only:
                cmd.append("--collect-only")
            if args.no_fetch:
                cmd.append("--no-fetch")
        result = subprocess.run(cmd, cwd=str(ROOT))
        sys.exit(result.returncode)


if __name__ == "__main__":
    main()
