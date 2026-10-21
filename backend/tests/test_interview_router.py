"""Tests for routers/interview.py — helper functions and model validation.

All external services (Supabase, Google ADK) are mocked.
"""

from __future__ import annotations

import json
import pytest
from unittest.mock import patch, MagicMock


# ── InterviewTurnRequest model ─────────────────────────────────────

class TestInterviewTurnRequest:
    """Test Pydantic model validation."""

    @pytest.fixture(autouse=True)
    def _import(self):
        from routers.interview import InterviewTurnRequest
        self.Model = InterviewTurnRequest

    def test_valid_minimal(self):
        req = self.Model(message="Hello")
        assert req.message == "Hello"
        assert req.last_question is None
        assert req.session_id is None

    def test_valid_full(self):
        req = self.Model(
            message="My answer",
            last_question="What is your name?",
            session_id="sess-123",
        )
        assert req.message == "My answer"
        assert req.last_question == "What is your name?"
        assert req.session_id == "sess-123"

    def test_empty_message_rejected(self):
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            self.Model(message="")

    def test_missing_message_rejected(self):
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            self.Model()


# ── _build_interviewer_prompt ──────────────────────────────────────

class TestBuildInterviewerPrompt:
    """Test system prompt construction."""

    @pytest.fixture(autouse=True)
    def _import(self):
        from routers.interview import _build_interviewer_prompt
        self._build = _build_interviewer_prompt

    def test_contains_profile_json(self):
        profile = {"name": "Alice", "occupation": "Engineer"}
        prompt = self._build(profile)
        # The profile should be serialized as JSON inside the prompt
        assert '"Alice"' in prompt
        assert '"Engineer"' in prompt

    def test_contains_interview_instructions(self):
        prompt = self._build({"name": "Test"})
        assert "ONE question" in prompt
        assert "WHAT WE ALREADY KNOW" in prompt
        assert "GAPS TO FILL" in prompt
        assert "HOW TO CONDUCT THE INTERVIEW" in prompt

    def test_contains_topic_areas(self):
        # The prompt is gap-driven: an empty profile surfaces every critical
        # and important gap field as a topic to cover.
        prompt = self._build({})
        assert "CRITICAL GAPS" in prompt
        assert "IMPORTANT GAPS" in prompt
        for field in (
            "occupation",
            "short_description",
            "speaking_style",
            "personality_traits",
            "key_achievements",
            "areas_of_expertise",
            "work_experience",
            "contributions",
        ):
            assert field in prompt

    def test_fully_populated_profile_deepens_on_opinions_and_stories(self):
        profile = {
            "occupation": "Engineer",
            "short_description": "Builds things",
            "speaking_style": "direct",
            "personality_traits": ["curious", "direct"],
            "key_achievements": ["a", "b"],
            "areas_of_expertise": ["x", "y"],
            "work_experience": [{"company": "A"}, {"company": "B"}],
            "contributions": ["c", "d"],
        }
        prompt = self._build(profile)
        assert "ALL KEY FIELDS ARE POPULATED" in prompt
        assert "CRITICAL GAPS" not in prompt
        assert "opinions" in prompt
        assert "stories" in prompt

    def test_empty_profile_still_produces_prompt(self):
        prompt = self._build({})
        assert len(prompt) > 100
        assert "WHAT WE ALREADY KNOW" in prompt

    def test_special_characters_in_profile(self):
        profile = {"name": "O'Brien & Co.", "bio": 'Says "hello" <world>'}
        prompt = self._build(profile)
        # json.dumps should handle special chars safely
        assert "O'Brien" in prompt
        assert "hello" in prompt


# ── _load_twin_profile ─────────────────────────────────────────────

class TestLoadTwinProfile:
    """Test loading twin profile from mocked Supabase."""

    @pytest.fixture(autouse=True)
    def _import(self):
        from routers.interview import _load_twin_profile
        self._load = _load_twin_profile

    def _mock_sb_with_data(self, data):
        mock_sb = MagicMock()
        mock_resp = MagicMock()
        mock_resp.data = data
        mock_sb.table.return_value.select.return_value.eq.return_value.single.return_value.execute.return_value = mock_resp
        return mock_sb

    @patch("routers.interview.get_supabase_client")
    def test_loads_profile_from_settings(self, mock_get_sb):
        mock_get_sb.return_value = self._mock_sb_with_data({
            "id": "twin-1",
            "name": "Alice",
            "settings": {
                "persona_profile": {"name": "Alice", "occupation": "Engineer"},
            },
        })
        profile = self._load("twin-1")
        assert profile["name"] == "Alice"
        assert profile["occupation"] == "Engineer"

    @patch("routers.interview.get_supabase_client")
    def test_falls_back_to_twin_name(self, mock_get_sb):
        mock_get_sb.return_value = self._mock_sb_with_data({
            "id": "twin-1",
            "name": "Bob",
            "settings": {},
        })
        profile = self._load("twin-1")
        assert profile["name"] == "Bob"

    @patch("routers.interview.get_supabase_client")
    def test_json_string_profile(self, mock_get_sb):
        mock_get_sb.return_value = self._mock_sb_with_data({
            "id": "twin-1",
            "name": "Carol",
            "settings": {
                "persona_profile": json.dumps({"occupation": "Artist"}),
            },
        })
        profile = self._load("twin-1")
        assert profile["occupation"] == "Artist"
        assert profile["name"] == "Carol"  # setdefault from twin name

    @patch("routers.interview.get_supabase_client")
    def test_invalid_json_string_profile(self, mock_get_sb):
        mock_get_sb.return_value = self._mock_sb_with_data({
            "id": "twin-1",
            "name": "Dave",
            "settings": {"persona_profile": "not-json"},
        })
        profile = self._load("twin-1")
        # Falls back to empty dict, then setdefault adds twin name
        assert profile == {"name": "Dave"}

    @patch("routers.interview.get_supabase_client")
    def test_twin_not_found_raises(self, mock_get_sb):
        mock_get_sb.return_value = self._mock_sb_with_data(None)
        with pytest.raises(Exception):
            self._load("nonexistent")

    @patch("routers.interview.get_supabase_client")
    def test_none_settings(self, mock_get_sb):
        mock_get_sb.return_value = self._mock_sb_with_data({
            "id": "twin-1",
            "name": "Eve",
            "settings": None,
        })
        profile = self._load("twin-1")
        assert profile["name"] == "Eve"


# ── _sse helper ────────────────────────────────────────────────────

class TestSseHelper:
    """Test SSE formatting."""

    @pytest.fixture(autouse=True)
    def _import(self):
        from routers.interview import _sse
        self._sse = _sse

    def test_format(self):
        result = self._sse("message", {"text": "hello"})
        assert result.startswith("event: message\n")
        assert "data: " in result
        assert result.endswith("\n\n")
        payload = json.loads(result.split("data: ")[1].strip())
        assert payload == {"text": "hello"}

    def test_done_event(self):
        result = self._sse("done", {"done": True})
        assert "event: done" in result
