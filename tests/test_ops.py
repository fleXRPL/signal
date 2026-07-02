"""Tests for pipeline/ops.py — pre-flight, alerts, feed health logging."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from pipeline.ops import (
    SignalAbort,
    abort_with_alert,
    log_feed_health,
    preflight_claude,
    preflight_llm,
    preflight_ollama,
    resolve_alert_url,
    resolve_llm_provider,
    send_alert,
)


class TestResolveLlmProvider:
    def test_env_overrides_config(self, monkeypatch, sample_config):
        monkeypatch.setenv("SIGNAL_LLM_PROVIDER", "ollama")
        assert resolve_llm_provider(sample_config) == "ollama"

    def test_config_default(self, sample_config):
        assert resolve_llm_provider(sample_config) == "claude"


class TestResolveAlertUrl:
    def test_env_takes_precedence(self, monkeypatch, sample_config):
        monkeypatch.setenv("SIGNAL_ALERT_URL", "https://ntfy.sh/env-topic")
        sample_config["alerts"] = {"webhook_url": "https://ntfy.sh/yaml-topic"}
        assert resolve_alert_url(sample_config) == "https://ntfy.sh/env-topic"

    def test_yaml_fallback(self, sample_config):
        sample_config["alerts"] = {"webhook_url": "https://ntfy.sh/yaml-topic"}
        assert resolve_alert_url(sample_config) == "https://ntfy.sh/yaml-topic"

    def test_empty_when_unconfigured(self, sample_config):
        assert resolve_alert_url(sample_config) is None

    def test_loads_from_env_file(self, monkeypatch, tmp_path, sample_config):
        import pipeline.ops as ops_module

        env_file = tmp_path / ".env"
        env_file.write_text(
            "SIGNAL_ALERT_URL=https://ntfy.sh/from-dotenv\n",
            encoding="utf-8",
        )
        monkeypatch.delenv("SIGNAL_ALERT_URL", raising=False)
        monkeypatch.setenv("SIGNAL_ENV_FILE", str(env_file))
        monkeypatch.setattr(ops_module, "_dotenv_loaded", False)
        assert resolve_alert_url(sample_config) == "https://ntfy.sh/from-dotenv"


class TestSendAlert:
    @patch("pipeline.ops.httpx.post")
    def test_posts_to_configured_url(self, mock_post, sample_config):
        sample_config["alerts"] = {"webhook_url": "https://ntfy.sh/test-topic"}
        mock_post.return_value = MagicMock(status_code=200)
        assert send_alert("Title", "Body", config=sample_config) is True
        mock_post.assert_called_once()

    @patch("pipeline.ops.httpx.post")
    def test_includes_tags_header(self, mock_post, sample_config):
        sample_config["alerts"] = {"webhook_url": "https://ntfy.sh/test-topic"}
        mock_post.return_value = MagicMock(status_code=200)
        send_alert("Title", "Body", config=sample_config, tags=["signal", "daily"])
        headers = mock_post.call_args.kwargs["headers"]
        assert headers["Tags"] == "signal,daily"

    @patch("pipeline.ops.httpx.post")
    def test_returns_false_on_http_error(self, mock_post, sample_config):
        sample_config["alerts"] = {"webhook_url": "https://ntfy.sh/test-topic"}
        mock_post.side_effect = Exception("network down")
        assert send_alert("Title", "Body", config=sample_config) is False

    @patch("pipeline.ops.httpx.post")
    def test_no_op_when_unconfigured(self, mock_post, monkeypatch, sample_config):
        import pipeline.ops as ops_module

        monkeypatch.delenv("SIGNAL_ALERT_URL", raising=False)
        monkeypatch.setenv("SIGNAL_ENV_FILE", "/nonexistent/.env")
        monkeypatch.setattr(ops_module, "_dotenv_loaded", False)
        assert send_alert("Title", "Body", config=sample_config) is False
        mock_post.assert_not_called()


class TestAbortWithAlert:
    @patch("pipeline.ops.send_alert")
    def test_sends_alert_then_raises(self, mock_send, sample_config):
        sample_config["alerts"] = {"webhook_url": "https://ntfy.sh/test-topic"}
        with pytest.raises(SignalAbort, match="no_articles"):
            abort_with_alert("no_articles", "Nothing collected", config=sample_config)
        mock_send.assert_called_once()
        assert "SIGNAL_ABORT: no_articles" in mock_send.call_args.args[1]


class TestPreflightClaude:
    @patch("pipeline.ops.subprocess.run")
    @patch("pipeline.ops.shutil.which")
    def test_success(self, mock_which, mock_run):
        mock_which.return_value = "/usr/bin/claude"
        mock_run.return_value = MagicMock(returncode=0, stdout="pong", stderr="")
        assert preflight_claude() == "pong"

    @patch("pipeline.ops.subprocess.run")
    @patch("pipeline.ops.shutil.which")
    def test_auth_failure(self, mock_which, mock_run):
        mock_which.return_value = "/usr/bin/claude"
        mock_run.return_value = MagicMock(
            returncode=1,
            stdout="",
            stderr="Invalid authentication credentials",
        )
        with pytest.raises(SignalAbort, match="claude_unavailable"):
            preflight_claude()

    @patch("pipeline.ops.Path.exists", return_value=False)
    @patch("pipeline.ops.shutil.which", return_value=None)
    def test_cli_not_found(self, _mock_which, _mock_exists):
        with pytest.raises(SignalAbort, match="Claude CLI not found"):
            preflight_claude()


class TestPreflightOllama:
    @patch("ollama.Client")
    def test_success(self, mock_client_cls, sample_config):
        mock_client = MagicMock()
        mock_client.list.return_value.models = [MagicMock(model="qwen2.5:14b")]
        mock_client_cls.return_value = mock_client
        assert preflight_ollama(sample_config) == "qwen2.5:14b"
        mock_client_cls.assert_called_once_with(host="http://localhost:11434")

    @patch("ollama.Client")
    def test_connection_failure(self, mock_client_cls, sample_config):
        mock_client_cls.side_effect = ConnectionError("refused")
        with pytest.raises(SignalAbort, match="ollama_unavailable"):
            preflight_ollama(sample_config)

    @patch("ollama.Client")
    def test_model_missing(self, mock_client_cls, sample_config):
        mock_client = MagicMock()
        mock_client.list.return_value.models = [MagicMock(model="llama3:8b")]
        mock_client_cls.return_value = mock_client
        with pytest.raises(SignalAbort, match="qwen2.5:14b"):
            preflight_ollama(sample_config)


class TestPreflightLlm:
    @patch("pipeline.ops.preflight_claude")
    def test_claude_path(self, mock_claude, sample_config, monkeypatch):
        monkeypatch.setenv("SIGNAL_LLM_PROVIDER", "claude")
        assert preflight_llm(sample_config) == "claude"
        mock_claude.assert_called_once()

    @patch("pipeline.ops.preflight_ollama")
    def test_ollama_path(self, mock_ollama, sample_config, monkeypatch):
        monkeypatch.setenv("SIGNAL_LLM_PROVIDER", "ollama")
        mock_ollama.return_value = "qwen2.5:14b"
        assert preflight_llm(sample_config) == "ollama"


class TestLogFeedHealth:
    def test_no_op_on_empty_records(self, tmp_path, monkeypatch):
        import pipeline.ops as ops_module

        log_path = tmp_path / "feed_health.log"
        monkeypatch.setattr(ops_module, "FEED_HEALTH_LOG", log_path)
        log_feed_health([], context="collect")
        assert not log_path.exists()

    def test_writes_summary_line(self, tmp_path, monkeypatch):
        import pipeline.ops as ops_module

        log_path = tmp_path / "feed_health.log"
        monkeypatch.setattr(ops_module, "FEED_HEALTH_LOG", log_path)
        records = [
            {"source": "AP Politics", "status": "ok", "articles": 5, "error": None},
            {"source": "C-SPAN", "status": "error", "articles": 0, "error": "410 Gone"},
            {"source": "Empty Feed", "status": "empty", "articles": 0, "error": None},
        ]
        log_feed_health(records, context="collect")
        text = log_path.read_text(encoding="utf-8")
        assert "AP Politics: ok (5)" in text
        assert "C-SPAN: ERROR (410 Gone)" in text
        assert "Empty Feed: empty" in text
        assert "collect" in text
