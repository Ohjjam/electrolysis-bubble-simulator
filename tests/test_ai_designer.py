import pytest

from bubblesim3d.params3d import DESIGNER_DEFAULTS, decode_mask
import server3d_app as app
from server3d_app import (
    _openai_output_text,
    _validate_ai_apply,
    _valid_ai_model,
    normalize_ai_plan,
)


def _base(flow):
    return {
        "summary": "test plan",
        "numeric_changes": [],
        "enum_changes": [],
        "flow": flow,
        "tests": [],
        "warnings": [],
    }


def test_model_parameter_is_labeled_and_validated():
    raw = _base({
        "action": "keep", "template": "serp", "ny": 0, "nz": 0, "rows": [],
        "in_face": "bottom", "out_face": "top", "reason": "",
    })
    raw["numeric_changes"] = [
        {"key": "u_flow", "value": 0.5, "reason": "increase flushing"},
        {"key": "departure_diameter_um", "value": 260.0,
         "reason": "measured zero-flow departure diameter"},
    ]
    plan = normalize_ai_plan(raw, dict(DESIGNER_DEFAULTS), 1.0)
    by_key = {item["key"]: item for item in plan["changes"]}
    assert by_key["u_flow"]["classification"] == "physical_or_operating"
    assert by_key["departure_diameter_um"]["classification"] == "model_or_fitted"
    assert plan["apply"]["u_flow"] == 0.5
    assert plan["apply"]["departure_diameter_um"] == 260.0
    assert any("Model/material/fitted" in warning for warning in plan["warnings"])


def test_connected_custom_surface_flow_is_encoded():
    rows = ["110111"] * 6
    raw = _base({
        "action": "custom", "template": "serp", "ny": 6, "nz": 6, "rows": rows,
        "in_face": "bottom", "out_face": "top", "reason": "one connected channel",
    })
    plan = normalize_ai_plan(raw, dict(DESIGNER_DEFAULTS), 1.0)
    assert plan["flow"]["connected"] is True
    assert plan["apply"]["ff"] == "custom"
    mask = decode_mask(plan["apply"]["mask"])
    assert mask.shape == (6, 6)
    assert not mask[:, 2].any()


def test_disconnected_custom_flow_is_not_applied():
    rows = [
        "101111", "101111", "111111",
        "111101", "111101", "111101",
    ]
    raw = _base({
        "action": "custom", "template": "serp", "ny": 6, "nz": 6, "rows": rows,
        "in_face": "bottom", "out_face": "top", "reason": "disconnected",
    })
    plan = normalize_ai_plan(raw, dict(DESIGNER_DEFAULTS), 1.0)
    assert plan["flow"]["action"] == "keep"
    assert "mask" not in plan["apply"]
    assert any("no connected" in warning for warning in plan["warnings"])


def test_interdigitated_ai_flow_is_blocked_without_penetration_model():
    raw = _base({
        "action": "template", "template": "inter", "ny": 0, "nz": 0, "rows": [],
        "in_face": "bottom", "out_face": "top", "reason": "not supported",
    })
    plan = normalize_ai_plan(raw, dict(DESIGNER_DEFAULTS), 1.0)
    assert plan["flow"]["action"] == "keep"
    assert "ff" not in plan["apply"]
    assert any("through-PTL" in warning for warning in plan["warnings"])
    with pytest.raises(ValueError, match="through-PTL"):
        _validate_ai_apply({"ff": "inter"})


def test_response_output_text_extraction():
    payload = {
        "output": [{
            "type": "message",
            "content": [{"type": "output_text", "text": '{"summary":"ok"}'}],
        }],
    }
    assert _openai_output_text(payload) == '{"summary":"ok"}'


def test_provider_model_validation_allows_openrouter_custom_only():
    assert _valid_ai_model("google", "gemini-3.1-flash-lite")
    assert _valid_ai_model("anthropic", "claude-haiku-4-5")
    assert _valid_ai_model("openrouter", "qwen/qwen3.5-flash-02-23")
    assert not _valid_ai_model("google", "qwen/qwen3.5-flash-02-23")
    assert not _valid_ai_model("openrouter", "https://evil.example/model")


def test_provider_keys_are_isolated_and_clearable(monkeypatch):
    for names in app.AI_ENV_KEYS.values():
        for name in names:
            monkeypatch.delenv(name, raising=False)
    app.AI_SESSIONS.clear()
    session_a = "test-browser-session-aaaaaaaa"
    session_b = "test-browser-session-bbbbbbbb"
    app._ai_set_session({
        "provider": "openai", "model": "gpt-5.6-terra",
        "key": "sk-test-openai-not-real-123456",
    }, session_id=session_a, allow_environment=False)
    assert app._ai_key_status(
        "openai", session_id=session_a, allow_environment=False)["configured"] is True
    assert app._ai_key_status(
        "openai", session_id=session_b, allow_environment=False)["configured"] is False
    assert app._ai_key_status(
        "google", session_id=session_a, allow_environment=False)["configured"] is False
    app._ai_set_session({
        "provider": "openai", "model": "gpt-5.6-terra", "clear": True,
    }, session_id=session_a, allow_environment=False)
    assert app._ai_key_status(
        "openai", session_id=session_a, allow_environment=False)["configured"] is False


def test_public_session_cannot_use_host_environment_key(monkeypatch):
    app.AI_SESSIONS.clear()
    monkeypatch.setenv("OPENAI_API_KEY", "sk-host-key-not-for-public-visitors")
    sid = "test-browser-session-public-cccc"
    public = app._ai_key_status("openai", session_id=sid, allow_environment=False)
    local = app._ai_key_status("openai", session_id=sid, allow_environment=True)
    assert public["configured"] is False
    assert local["configured"] is True
    assert local["source"] == "environment"


def test_expired_browser_session_key_is_deleted(monkeypatch):
    for names in app.AI_ENV_KEYS.values():
        for name in names:
            monkeypatch.delenv(name, raising=False)
    app.AI_SESSIONS.clear()
    sid = "test-browser-session-expired-dddd"
    app._ai_set_session({
        "provider": "openai", "model": "gpt-5.6-terra",
        "key": "sk-test-expiring-key-not-real-123",
        "ttl_minutes": 5,
    }, session_id=sid, allow_environment=False)
    app.AI_SESSIONS[sid]["expires"] = 0
    status = app._ai_key_status("openai", session_id=sid, allow_environment=False)
    assert status["configured"] is False
    assert sid not in app.AI_SESSIONS


def test_non_openai_adapters_parse_structured_text(monkeypatch):
    def fake(provider, url, body, headers):
        if provider == "Google Gemini":
            return {"candidates": [{"content": {"parts": [{"text": '{"provider":"google"}'}]}}]}
        if provider == "Anthropic":
            return {"content": [{"type": "text", "text": '{"provider":"anthropic"}'}]}
        return {"choices": [{"message": {"content": '{"provider":"openrouter"}'}}]}

    monkeypatch.setattr(app, "_http_ai_json", fake)
    current = dict(DESIGNER_DEFAULTS)
    assert app._call_google_plan(
        "fake-key", "test", current, 1.0, "ko", "gemini-3.1-flash-lite"
    )["provider"] == "google"
    assert app._call_anthropic_plan(
        "fake-key", "test", current, 1.0, "ko", "claude-haiku-4-5"
    )["provider"] == "anthropic"
    assert app._call_openrouter_plan(
        "fake-key", "test", current, 1.0, "ko", "openrouter/free"
    )["provider"] == "openrouter"
