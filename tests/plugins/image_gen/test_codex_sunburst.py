"""Sunburst resolver and outbound-request regressions (no network/auth)."""
import importlib
import json

import pytest

plugin = importlib.import_module("plugins.image_gen.openai-codex")
NEW = "gpt-image-2.5-sunburst-high"
API = "gpt-image-2.5-sunburst"
OLD = "gpt-image-2-low"


def test_local_reference_guard_failure_never_reads_image(monkeypatch):
    from agent import file_safety

    def unavailable(_path):
        raise RuntimeError("read guard unavailable")

    monkeypatch.setattr(file_safety, "get_read_block_error", unavailable)
    with pytest.raises(RuntimeError, match="read guard unavailable"):
        plugin._local_image_to_data_url("/nonexistent-audit-image.png")


@pytest.fixture(autouse=True)
def isolated(monkeypatch):
    monkeypatch.delenv("OPENAI_IMAGE_MODEL", raising=False)
    monkeypatch.setattr(plugin, "load_image_gen_config", lambda: {})


@pytest.mark.parametrize("source", ["explicit", "env", "scoped", "top"])
def test_resolution_sources(source, monkeypatch):
    cfg = {}
    if source == "env":
        monkeypatch.setenv("OPENAI_IMAGE_MODEL", NEW)
    elif source == "scoped":
        cfg = {"openai-codex": {"model": NEW}, "model": OLD}
    elif source == "top":
        cfg = {"model": NEW}
    monkeypatch.setattr(plugin, "load_image_gen_config", lambda: cfg)
    model, meta = plugin._resolve_model(NEW if source == "explicit" else None)
    assert (model, meta["api_model"], meta["quality"]) == (NEW, API, "high")


def test_precedence_and_legacy(monkeypatch):
    monkeypatch.setattr(plugin, "load_image_gen_config", lambda: {
        "openai-codex": {"model": NEW}, "model": "gpt-image-2-high"})
    monkeypatch.setenv("OPENAI_IMAGE_MODEL", OLD)
    assert plugin._resolve_model()[0] == OLD  # inherited env still overrides config
    assert plugin._resolve_model(NEW)[0] == OLD
    monkeypatch.delenv("OPENAI_IMAGE_MODEL")
    assert plugin._resolve_model(OLD)[0] == NEW  # dispatcher passes top-level model
    monkeypatch.setattr(plugin, "load_image_gen_config", lambda: {})
    assert plugin._resolve_model()[0] == "gpt-image-2-medium"
    assert plugin._resolve_model("unrelated-legacy-id")[0] == "gpt-image-2-medium"
    for quality in ("low", "medium", "high"):
        _, meta = plugin._resolve_model(f"gpt-image-2-{quality}")
        assert (meta["api_model"], meta["quality"]) == ("gpt-image-2", quality)


@pytest.mark.parametrize("bad", ["gpt-image-2.5-sunburst", "gpt-image-2.5-sunburst-low", "gpt-image-2.5-typo", " gpt-image-2.5-sunburst-high "])
@pytest.mark.parametrize("source", ["env", "scoped", "top"])
def test_unknown_sunburst_never_falls_back(bad, source, monkeypatch):
    cfg = {"model": OLD}
    if source == "env":
        monkeypatch.setenv("OPENAI_IMAGE_MODEL", bad)
    elif source == "scoped":
        cfg["openai-codex"] = {"model": bad}
    else:
        cfg["model"] = bad
    monkeypatch.setattr(plugin, "load_image_gen_config", lambda: cfg)
    with pytest.raises(ValueError, match="Unsupported Codex image model"):
        plugin._resolve_model()


def test_invalid_explicit_returns_error_without_request(monkeypatch):
    monkeypatch.setattr(plugin, "_read_codex_credential", lambda: ("test-token", plugin._CODEX_BASE_URL))
    monkeypatch.setattr(plugin, "_collect_image_b64", lambda *a, **kw: pytest.fail("network attempted"))
    result = plugin.OpenAICodexImageGenProvider().generate("test", model="gpt-image-2.5-typo")
    assert result["error_type"] == "invalid_model"


def test_generate_through_http_payload_and_no_family_fallback(monkeypatch):
    import httpx
    calls = []

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def raise_for_status(self):
            pass

        def iter_lines(self):
            # Deliberately empty: retry must keep the same API family and quality.
            return iter(["data: " + json.dumps({"type": "response.completed"}), ""])

    class Client:
        def __init__(self, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def stream(self, method, url, json):
            assert method == "POST"
            assert url == "https://chatgpt.com/backend-api/codex/responses"
            calls.append(json)
            return Response()

    monkeypatch.setattr(httpx, "Client", Client)
    monkeypatch.setattr(plugin, "_read_codex_credential", lambda: ("test-token", plugin._CODEX_BASE_URL))
    result = plugin.OpenAICodexImageGenProvider().generate("test", model=NEW)
    assert result["error_type"] == "empty_response"
    assert len(calls) == 2
    for payload in calls:
        assert payload["model"] == "gpt-5.5"
        assert "tool_choice" not in payload
        assert payload["tools"][0]["model"] == API
        assert payload["tools"][0]["quality"] == "high"
    legacy = plugin._build_responses_payload(prompt="test", size="1024x1024", quality="low")
    assert legacy["tools"][0]["model"] == "gpt-image-2"


def test_api_failure_no_retry_or_downgrade(monkeypatch):
    calls = []
    monkeypatch.setattr(plugin, "_read_codex_credential", lambda: ("test-token", plugin._CODEX_BASE_URL))

    def fail(*args, **kwargs):
        calls.append(kwargs)
        raise RuntimeError("HTTP 400: model unavailable")

    monkeypatch.setattr(plugin, "_collect_image_b64", fail)
    result = plugin.OpenAICodexImageGenProvider().generate("test", model=NEW)
    assert result["error_type"] == "api_error"
    assert "HTTP 400: model unavailable" in result["error"]
    assert len(calls) == 1
    assert calls[0]["api_model"] == API


def test_api_key_and_oauth_catalogs_support_sunburst_independently():
    api_key_plugin = importlib.import_module("plugins.image_gen.openai")
    assert NEW in api_key_plugin.OpenAIImageGenProvider.models
    assert NEW in plugin.OpenAICodexImageGenProvider.models
    assert plugin._resolve_model(NEW)[1]["api_model"] == API
