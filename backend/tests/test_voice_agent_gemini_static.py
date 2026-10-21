from __future__ import annotations

from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]


def test_voice_agent_gemini_uses_current_live_contract():
    html = (_REPO_ROOT / "backend/static/voice-agent-gemini.html").read_text(encoding="utf-8")

    for token in ("generationConfig", "realtimeInput", "toolResponse", "functionResponses", "sessionResumption", "access_token"):
        assert token in html
    for token in ("log_client_event", "ws_connect_start", "setup_complete", "connection_status"):
        assert token in html

    for deprecated in ("generation_config", "realtime_input", "tool_response", "media_chunks"):
        assert deprecated not in html


def test_voice_settings_exposes_expected_gemini_voice_options():
    component = (_REPO_ROOT / "frontend/components/settings/VoiceSettings.tsx").read_text(encoding="utf-8")

    for voice in ("Puck", "Charon", "Kore", "Fenrir", "Aoede", "Leda", "Orus", "Zephyr"):
        assert f"'{voice}'" in component

    assert "gemini_voice" in component
    assert "Save Meeting Bot Voice" in component
    assert "Gemini Meeting Voice" not in component
    assert "backend" not in component.lower()
