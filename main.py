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
    if args.model:
        config["ollama"]["model"] = args.model
        config["ollama"]["analysis_model"] = args.model
    if args.no_fetch:
        config["collection"]["fetch_full_text"] = False

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

    # Check Ollama is reachable
    model = config["ollama"].get("model", "qwen2.5:14b")
    console.print(f"[dim]Checking Ollama ({model})...[/dim]")
    try:
        import ollama as _ollama
        client = _ollama.Client(host=config["ollama"].get("base_url", "http://localhost:11434"))
        models = client.list()
        available = [m.model for m in models.models]
        if not any(model in m for m in available):
            console.print(f"\n[yellow]⚠[/yellow]  Model [bold]{model}[/bold] not found in Ollama.")
            console.print(f"    Available: {', '.join(available) or 'none'}")
            console.print(f"    Run: [bold]ollama pull {model}[/bold]\n")
            sys.exit(1)
        console.print(f"[green]✓[/green] Ollama ready with {model}\n")
    except Exception as exc:
        console.print(f"[red]✗[/red] Cannot reach Ollama: {exc}")
        console.print("  Make sure Ollama is running: [bold]ollama serve[/bold]")
        sys.exit(1)

    # Run analysis pipeline
    brief, clusters, correlation = run_pipeline(
        articles, article_db_ids, run_id, config
    )

    # Update run record
    multi_clusters = [c for c in clusters if not c.get("singleton")]
    store.finish_run(run_id, len(articles), len(multi_clusters))

    # Generate report
    console.print(f"\n[bold cyan]Generating HTML report...[/bold cyan]")
    report_path = generate_report(brief, clusters, correlation, articles, run_id, model)

    console.print(f"\n[bold green]✓ Brief complete[/bold green]")
    console.print(f"  Report: [underline]{report_path}[/underline]")
    console.print(f"  Open:   [dim]open {report_path}[/dim]\n")


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
  python main.py
  python main.py --model qwen2.5:14b
  python main.py --no-fetch --model llama3.1:8b
  python main.py --collect-only
        """,
    )
    parser.add_argument("--model", type=str, default=None, help="Ollama model override")
    parser.add_argument("--no-venv", action="store_true", help="Skip venv setup")
    parser.add_argument("--collect-only", action="store_true", help="Fetch articles only, skip analysis")
    parser.add_argument("--no-fetch", action="store_true", help="Skip full article text fetch")
    args = parser.parse_args()

    if args.no_venv:
        run_signal(args)
    else:
        python = setup_venv()
        # Re-run under venv Python
        cmd = [str(python), str(Path(__file__).resolve()), "--no-venv"]
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
