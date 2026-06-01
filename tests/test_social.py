"""
Tests for pipeline/social.py — Bluesky post packages and posting.

Uses tmp_path for post JSON files; mocks atproto Client for network calls.
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

import pipeline.social as social


@pytest.fixture
def posts_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    posts = tmp_path / "posts"
    posts.mkdir()
    monkeypatch.setattr(social, "POSTS_DIR", posts)
    return posts


@pytest.fixture
def brief_data() -> dict:
    return {
        "date": "2026-06-01 13:09 UTC",
        "article_count": 85,
        "source_count": 11,
        "cluster_count": 8,
        "report_url": "https://flexrpl.github.io/signal/reports/brief_20260601_1309.html",
        "watch_items": [
            {"window": "24hr", "text": "Patel / FBI child rescue narrative"},
            {"window": "72hr", "text": "Kennedy Center ruling compliance"},
        ],
        "top_cluster": {
            "headline": "Federal judge orders Trump's name removed from Kennedy Center",
            "bias_spread": {"left": 5, "center-left": 10, "center": 5, "right": 6},
            "article_count": 40,
            "left_framing": "Legal check on executive overreach.",
            "center_framing": "Procedural legal development.",
            "right_framing": "Political framing of judge appointment.",
            "left_omissions": "Operational justification omitted.",
            "right_omissions": "Statutory argument omitted.",
        },
        "blindspot_narrative": (
            "Bondi / Epstein accountability dominates left-only coverage. "
            "Right outlets focus on Patel FBI operation."
        ),
        "left_only": ["Bondi refuses questions under oath", "ICE agent arrested in Minnesota"],
        "right_only": ["Kash Patel: FBI rescues 87 children"],
    }


class TestFitBlueskyText:
    def test_unchanged_when_under_limit(self):
        text = "Short post"
        assert social._fit_bluesky_text(text) == text

    def test_truncates_with_ellipsis_when_over_limit(self):
        long_text = "word " * 80
        result = social._fit_bluesky_text(long_text, max_graphemes=50)
        assert len(result) <= 50
        assert result.endswith("…")

    def test_truncates_without_word_boundary(self):
        blob = "x" * 400
        result = social._fit_bluesky_text(blob, max_graphemes=20)
        assert len(result) <= 20
        assert result.endswith("…")


class TestBuildPostText:
    def test_am_slot(self, brief_data):
        text = social._build_post_text("am", brief_data)
        assert "SIGNAL // 2026-06-01" in text
        assert "watch list" in text
        assert len(text) <= social._BLUESKY_SAFE_GRAPHEMES

    def test_noon_slot_fits_grapheme_limit(self, brief_data):
        text = social._build_post_text("noon", brief_data)
        assert "Left, center, and right" in text
        assert len(text) <= social._BLUESKY_SAFE_GRAPHEMES

    def test_noon_truncates_very_long_headline(self, brief_data):
        data = {**brief_data, "top_cluster": {
            **brief_data["top_cluster"],
            "headline": "X" * 500,
        }}
        text = social._build_post_text("noon", data)
        assert len(text) <= social._BLUESKY_SAFE_GRAPHEMES

    def test_pm_slot(self, brief_data):
        text = social._build_post_text("pm", brief_data)
        assert "blindspot" in text.lower()
        assert len(text) <= social._BLUESKY_SAFE_GRAPHEMES

    def test_window_summary_single_5d_only(self):
        data = {
            "date": "2026-06-01",
            "report_url": "https://example.com/brief.html",
            "watch_items": [{"window": "5d", "text": "Cuba policy watch"}],
            "top_cluster": {"headline": "Story"},
            "blindspot_narrative": "",
        }
        text = social._build_post_text("am", data)
        assert "72 hours to 5 days" in text

    def test_am_empty_watch_items_uses_default_bounds(self):
        data = {
            "date": "2026-06-01",
            "report_url": "https://example.com/brief.html",
            "watch_items": [],
            "top_cluster": {"headline": "Story"},
            "blindspot_narrative": "",
        }
        text = social._build_post_text("am", data)
        assert "72 hours to 48 hours" in text

    def test_final_fit_when_template_still_too_long(self):
        data = {
            "date": "2026-06-01 13:09 UTC extra",
            "report_url": "https://flexrpl.github.io/signal/" + "x" * 200,
            "watch_items": [{"window": "24hr", "text": "w"}] * 20,
            "top_cluster": {"headline": "H" * 500},
            "blindspot_narrative": "B" * 500,
        }
        text = social._build_post_text("noon", data)
        assert len(text) <= social._BLUESKY_SAFE_GRAPHEMES


class TestBuildPostPackage:
    @patch("pipeline.social.datetime")
    def test_default_date_slug_from_utc_now(self, mock_dt, posts_dir, brief_data, tmp_path: Path):
        from datetime import datetime, timezone

        mock_dt.now.return_value = datetime(2026, 6, 1, tzinfo=timezone.utc)
        image = tmp_path / "am.png"
        image.write_bytes(b"png")
        out = social.build_post_package("am", brief_data, image)
        assert out.name == "am_20260601.json"

    def test_writes_json_package(self, posts_dir, brief_data, tmp_path: Path):
        image = tmp_path / "am_test.png"
        image.write_bytes(b"png")

        out = social.build_post_package("am", brief_data, image, date_slug="20260601")

        assert out == posts_dir / "am_20260601.json"
        package = json.loads(out.read_text(encoding="utf-8"))
        assert package["slot"] == "am"
        assert package["posted"] is False
        assert package["image_path"] == str(image)
        assert len(package["text"]) <= social._BLUESKY_SAFE_GRAPHEMES


class TestPostToBluesky:
    def test_raises_without_credentials(self, tmp_path: Path):
        with patch.dict("os.environ", {}, clear=True):
            with pytest.raises(RuntimeError, match="BLUESKY_HANDLE"):
                social.post_to_bluesky("hi", tmp_path / "img.png", "https://example.com")

    @patch("atproto.Client")
    def test_posts_with_credentials(self, mock_client_cls, tmp_path: Path):
        img = tmp_path / "card.png"
        img.write_bytes(b"fake-png")
        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client
        mock_response = MagicMock()
        mock_response.uri = "at://did:plc:test/app.bsky.feed.post/abc"
        mock_client.send_image.return_value = mock_response

        env = {
            "BLUESKY_HANDLE": "test.bsky.social",
            "BLUESKY_APP_PASSWORD": "test-pass",
        }
        with patch.dict("os.environ", env, clear=True):
            uri = social.post_to_bluesky(
                "SIGNAL // test\n\nBrief → https://example.com",
                img,
                "https://example.com/brief.html",
            )

        assert uri == "at://did:plc:test/app.bsky.feed.post/abc"
        mock_client.login.assert_called_once_with("test.bsky.social", "test-pass")
        call_kwargs = mock_client.send_image.call_args.kwargs
        assert call_kwargs["text"] == "SIGNAL // test\n\nBrief → https://example.com"
        assert call_kwargs["image"] == b"fake-png"


class TestPostSlot:
    def test_raises_when_package_missing(self, posts_dir):
        with patch("dotenv.load_dotenv"):
            with pytest.raises(FileNotFoundError, match="Post package not found"):
                social.post_slot("am", date_slug="19990101")

    def test_skips_when_already_posted(self, posts_dir):
        path = posts_dir / "noon_20260601.json"
        path.write_text(
            json.dumps({
                "slot": "noon",
                "posted": True,
                "post_uri": "at://existing",
                "text": "done",
                "image_path": "/tmp/x.png",
                "report_url": "https://example.com",
            }),
            encoding="utf-8",
        )
        with patch("dotenv.load_dotenv"):
            uri = social.post_slot("noon", date_slug="20260601")
        assert uri == "at://existing"

    @patch("pipeline.social.post_to_bluesky")
    def test_posts_and_marks_package(self, mock_post, posts_dir, tmp_path: Path):
        img = tmp_path / "am.png"
        img.write_bytes(b"png")
        path = posts_dir / "am_20260601.json"
        path.write_text(
            json.dumps({
                "slot": "am",
                "posted": False,
                "text": "SIGNAL // 2026-06-01\n\nWatch list.\n\nhttps://example.com",
                "image_path": str(img),
                "report_url": "https://flexrpl.github.io/signal/reports/brief.html",
            }),
            encoding="utf-8",
        )
        mock_post.return_value = "at://did:plc:test/post/1"

        with patch("dotenv.load_dotenv"):
            uri = social.post_slot("am", date_slug="20260601")

        assert uri == "at://did:plc:test/post/1"
        updated = json.loads(path.read_text(encoding="utf-8"))
        assert updated["posted"] is True
        assert updated["post_uri"] == "at://did:plc:test/post/1"
        assert "posted_at" in updated
