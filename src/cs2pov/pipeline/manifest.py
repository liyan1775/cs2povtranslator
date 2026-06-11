from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from cs2pov.domain.models import PipelineConfig, StageName, StageStatus, STAGE_ORDER, to_jsonable
from cs2pov.storage.jsonl import read_json, write_json

REDACTED_SECRET = "[已配置-已隐藏]"


@dataclass(slots=True)
class PipelineManifest:
    schema_version: int
    job_id: str
    created_at: str
    updated_at: str
    config: PipelineConfig
    stages: dict[str, str] = field(default_factory=dict)
    artifacts: dict[str, str] = field(default_factory=dict)
    demo: dict[str, Any] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    @classmethod
    def create(cls, job_id: str, config: PipelineConfig) -> "PipelineManifest":
        now = datetime.now().isoformat(timespec="seconds")
        return cls(
            schema_version=1,
            job_id=job_id,
            created_at=now,
            updated_at=now,
            config=config,
            stages={stage.value: StageStatus.PENDING.value for stage in STAGE_ORDER},
        )

    def set_stage(self, stage: StageName, status: StageStatus) -> None:
        self.stages[stage.value] = status.value
        self.updated_at = datetime.now().isoformat(timespec="seconds")

    def set_artifact(self, key: str, path: Path) -> None:
        # Store raw paths internally while the process is running.  The public
        # manifest written to disk normalizes them to shareable job-relative
        # paths whenever possible.
        self.artifacts[key] = str(path)
        self.updated_at = datetime.now().isoformat(timespec="seconds")

    def _public_artifact_path(self, value: str) -> str:
        """Return a shareable artifact path for manifest.json.

        During pipeline execution some services return absolute Windows paths,
        especially after v0.6.0 introduced glossary reports and preset exports.
        Job manifests are commonly included in feedback packs, so they should
        not expose local directories such as ``D:\\个人项目\\...``.  If the
        value contains the current job id, keep only the path inside the job;
        otherwise normalize separators and keep the original value.
        """
        text = str(value).replace("\\", "/")
        marker = f"/{self.job_id}/"
        if marker in text:
            return text.split(marker, 1)[1]
        if text.startswith(f"{self.job_id}/"):
            return text[len(self.job_id) + 1 :]
        # Common relative form: output_root/job_id/...
        marker_no_lead = f"{self.job_id}/"
        if marker_no_lead in text:
            return text.split(marker_no_lead, 1)[1]
        return text

    def to_public_dict(self) -> dict[str, Any]:
        """Return a manifest safe to write into job folders and feedback packs.

        Job manifests are often shared for debugging.  They must never contain
        API keys even though the in-memory PipelineConfig still needs the key
        while the process is running.
        """
        data = {
            "schema_version": self.schema_version,
            "job_id": self.job_id,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "config": to_jsonable(self.config),
            "stages": dict(self.stages),
            "artifacts": {key: self._public_artifact_path(value) for key, value in self.artifacts.items()},
            "demo": dict(self.demo),
            "notes": list(self.notes),
        }
        cfg = dict(data["config"])
        api_key = cfg.get("llm_api_key")
        cfg["llm_api_key_configured"] = bool(api_key)
        if api_key:
            cfg["llm_api_key"] = REDACTED_SECRET
        cache_dir = cfg.get("whisper_cache_dir")
        cfg["whisper_cache_dir_configured"] = bool(cache_dir)
        if cache_dir:
            cfg["whisper_cache_dir"] = "[已配置-已隐藏]"
        data["config"] = cfg
        return data

    def save(self, path: Path) -> None:
        write_json(path, self.to_public_dict())

    @classmethod
    def load(cls, path: Path) -> "PipelineManifest":
        data = read_json(path)
        cfg_data = dict(data["config"])
        # Manifests are intentionally redacted.  The real API key should come
        # from ~/.cs2pov/config.json or the current process config, not from a
        # shareable job artifact.
        if cfg_data.get("llm_api_key") == REDACTED_SECRET:
            cfg_data["llm_api_key"] = None
        if cfg_data.get("whisper_cache_dir") == "[已配置-已隐藏]":
            cfg_data["whisper_cache_dir"] = None
        allowed = set(PipelineConfig.__dataclass_fields__.keys())
        cfg_data = {k: v for k, v in cfg_data.items() if k in allowed}
        config = PipelineConfig(**cfg_data)
        return cls(
            schema_version=int(data["schema_version"]),
            job_id=str(data["job_id"]),
            created_at=str(data["created_at"]),
            updated_at=str(data["updated_at"]),
            config=config,
            stages=dict(data.get("stages", {})),
            artifacts=dict(data.get("artifacts", {})),
            demo=dict(data.get("demo", {})),
            notes=list(data.get("notes", [])),
        )
