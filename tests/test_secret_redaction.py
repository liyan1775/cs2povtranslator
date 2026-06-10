from __future__ import annotations

import json
from pathlib import Path

from cs2pov.domain.models import PipelineConfig
from cs2pov.pipeline.manifest import PipelineManifest, REDACTED_SECRET
from cs2pov.storage.config_store import mask_config_for_display


def test_manifest_does_not_write_llm_api_key(tmp_path: Path) -> None:
    manifest = PipelineManifest.create(
        "job_secret_test",
        PipelineConfig(llm_base_url="https://api.example.com", llm_api_key="sk-super-secret", llm_model="demo-model"),
    )
    path = tmp_path / "manifest.json"
    manifest.save(path)

    raw = path.read_text(encoding="utf-8")
    data = json.loads(raw)

    assert "sk-super-secret" not in raw
    assert data["config"]["llm_api_key"] == REDACTED_SECRET
    assert data["config"]["llm_api_key_configured"] is True


def test_manifest_load_treats_redacted_key_as_missing(tmp_path: Path) -> None:
    manifest = PipelineManifest.create("job_secret_test", PipelineConfig(llm_api_key="sk-super-secret"))
    path = tmp_path / "manifest.json"
    manifest.save(path)

    loaded = PipelineManifest.load(path)

    assert loaded.config.llm_api_key is None


def test_config_display_masks_api_key() -> None:
    masked = mask_config_for_display({"llm_api_key": "sk-super-secret", "llm_model": "demo"})

    assert masked["llm_api_key"] == "[已配置-已隐藏]"
    assert masked["llm_api_key_configured"] is True
    assert "sk-super-secret" not in json.dumps(masked, ensure_ascii=False)
