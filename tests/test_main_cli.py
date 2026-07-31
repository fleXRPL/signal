"""Tests for main.py CLI argument validation."""
from __future__ import annotations

import argparse

import pytest

from main import _parse_model_arg, _parse_month_arg


class TestParseMonthArg:
    def test_accepts_valid_month(self):
        assert _parse_month_arg("2026-05") == "2026-05"

    def test_rejects_injection_chars(self):
        with pytest.raises(argparse.ArgumentTypeError):
            _parse_month_arg("2026-05; rm -rf /")

    def test_rejects_invalid_month_number(self):
        with pytest.raises(argparse.ArgumentTypeError):
            _parse_month_arg("2026-13")


class TestParseModelArg:
    def test_accepts_ollama_style_name(self):
        assert _parse_model_arg("qwen2.5:14b") == "qwen2.5:14b"

    def test_rejects_shell_metacharacters(self):
        with pytest.raises(argparse.ArgumentTypeError):
            _parse_model_arg("model;whoami")
