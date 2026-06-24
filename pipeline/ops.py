#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Operational helpers — pre-flight checks, alerts, feed health logging.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx

ROOT = Path(__file__).parent.parent
FEED_HEALTH_LOG = ROOT / "logs" / "feed_health.log"


class SignalAbort(Exception):
    """Raised when a pipeline run should exit before expensive work."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(f"SIGNAL_ABORT: {code} — {message}")


def resolve_llm_provider(config: Dict[str, Any]) -> str:
    llm_cfg = config.get("llm", {})
    return os.environ.get("SIGNAL_LLM_PROVIDER", llm_cfg.get("provider", "claude"))


def resolve_alert_url(config: Optional[Dict[str, Any]] = None) -> Optional[str]:
    env_url = os.environ.get("SIGNAL_ALERT_URL", "").strip()
    if env_url:
        return env_url
    if config:
        alerts = config.get("alerts") or {}
        url = (alerts.get("webhook_url") or "").strip()
        if url:
            return url
    return None


def send_alert(
    title: str,
    message: str,
    *,
    config: Optional[Dict[str, Any]] = None,
    priority: str = "high",
    tags: Optional[List[str]] = None,
) -> bool:
    """POST a notification to ntfy (or compatible webhook). Returns True if sent."""
    url = resolve_alert_url(config)
    if not url:
        return False

    headers: Dict[str, str] = {
        "Title": title,
        "Priority": priority,
    }
    if tags:
        headers["Tags"] = ",".join(tags)

    try:
        resp = httpx.post(
            url,
            content=message.encode("utf-8"),
            headers=headers,
            timeout=10.0,
        )
        resp.raise_for_status()
        return True
    except Exception:  # noqa: BLE001
        return False


def preflight_claude(timeout: int = 60) -> str:
    """Verify Claude CLI auth with a minimal prompt. Returns stdout on success."""
    claude_bin = shutil.which("claude") or "/opt/homebrew/bin/claude"
    if not Path(claude_bin).exists() and not shutil.which("claude"):
        raise SignalAbort("claude_unavailable", "Claude CLI not found on PATH")

    result = subprocess.run(
        [claude_bin, "-p", "ping", "--print"],
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or "Claude CLI non-zero exit"
        raise SignalAbort("claude_unavailable", detail)
    return result.stdout.strip()


def preflight_ollama(config: Dict[str, Any]) -> str:
    """Verify Ollama is reachable and the configured model is present."""
    import ollama as _ollama

    ollama_cfg = config.get("llm", {}).get("ollama", {})
    model = ollama_cfg.get("model", "qwen2.5:14b")
    base_url = ollama_cfg.get("base_url", "http://localhost:11434")

    try:
        client = _ollama.Client(host=base_url)
        available = [m.model for m in client.list().models]
    except Exception as exc:  # noqa: BLE001
        raise SignalAbort("ollama_unavailable", str(exc)) from exc

    if not any(model in m for m in available):
        raise SignalAbort(
            "ollama_unavailable",
            f"Model {model!r} not found (available: {', '.join(available) or 'none'})",
        )
    return model


def preflight_llm(config: Dict[str, Any]) -> str:
    """Run provider-specific pre-flight. Returns provider label."""
    provider = resolve_llm_provider(config)
    if provider == "claude":
        preflight_claude()
        return "claude"
    preflight_ollama(config)
    return "ollama"


def log_feed_health(
    records: List[Dict[str, Any]],
    *,
    context: str = "daily",
) -> None:
    """Append a one-line feed health summary to logs/feed_health.log."""
    if not records:
        return

    FEED_HEALTH_LOG.parent.mkdir(exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    parts = []
    for rec in records:
        name = rec.get("source", "?")
        status = rec.get("status", "?")
        count = rec.get("articles", 0)
        if status == "error":
            err = rec.get("error", "unknown")
            parts.append(f"{name}: ERROR ({err})")
        elif status == "empty":
            parts.append(f"{name}: empty")
        else:
            parts.append(f"{name}: ok ({count})")

    line = f"{ts} | {context} | " + " | ".join(parts) + "\n"
    with FEED_HEALTH_LOG.open("a", encoding="utf-8") as fh:
        fh.write(line)


def abort_with_alert(
    code: str,
    message: str,
    *,
    config: Optional[Dict[str, Any]] = None,
    title: str = "Signal pipeline aborted",
    tags: Optional[List[str]] = None,
) -> None:
    """Send alert (if configured) and raise SignalAbort."""
    send_alert(title, f"SIGNAL_ABORT: {code}\n\n{message}", config=config, tags=tags)
    raise SignalAbort(code, message)
