"""Local patch: GPT Image 2.5 Sunburst High on the native Codex images route."""
import importlib.util
from pathlib import Path

import pytest

_PLUGIN = Path(__file__).resolve().parents[3] / "plugins/image_gen/openai-codex/__init__.py"


def _load():
    spec = importlib.util.spec_from_file_location("codex_img_sunburst_test", _PLUGIN)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_sunburst_tier_posts_sunburst_api_model(monkeypatch):
    mod = _load()
    monkeypatch.setenv("OPENAI_IMAGE_MODEL", "gpt-image-2.5-sunburst-high")
    tier, meta = mod._resolve_model()
    assert tier == "gpt-image-2.5-sunburst-high"
    path, body = mod._build_image_request(prompt="x", size="1024x1024", quality=meta["quality"],
                                          api_model=meta["api_model"])
    assert path == "images/generations"
    assert body["model"] == "gpt-image-2.5-sunburst" and body["quality"] == "high"


def test_legacy_tiers_keep_gpt_image_2(monkeypatch):
    mod = _load()
    monkeypatch.setenv("OPENAI_IMAGE_MODEL", "gpt-image-2-low")
    tier, meta = mod._resolve_model()
    assert tier == "gpt-image-2-low" and meta["api_model"] == "gpt-image-2"


def test_unknown_25_id_fails_closed(monkeypatch):
    mod = _load()
    monkeypatch.setenv("OPENAI_IMAGE_MODEL", "gpt-image-2.5-bogus")
    with pytest.raises(ValueError):
        mod._resolve_model()
