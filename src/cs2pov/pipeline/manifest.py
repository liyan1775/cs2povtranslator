from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from cs2pov.domain.assets import DemoAssetRef, validate_display_name
from cs2pov.domain.models import PipelineConfig, StageName, StageStatus, STAGE_ORDER, to_jsonable
from cs2pov.storage.jsonl import read_json, write_json

REDACTED_SECRET = "[已配置-已隐藏]"

_DEMO_ASSET_IDENTITY_KEYS = {"asset_id", "asset_manifest", "display_name"}
_DEMO_ASSET_METADATA_KEYS = {"map_name", "server_name", "players"}
_DEMO_ASSET_ALLOWED_KEYS = {"input_mode"} | _DEMO_ASSET_IDENTITY_KEYS | _DEMO_ASSET_METADATA_KEYS


@dataclass(slots=True)
class PipelineManifest:
    schema_version: int
    job_id: str
    created_at: str
    updated_at: str
    config: PipelineConfig
    # None means this is an old manifest that predates the workspace policy.
    # Keep that distinction when an old Job is read and saved again.
    path_policy_version: int | None = None
    legacy_external_output: bool | None = None
    stages: dict[str, str] = field(default_factory=dict)
    artifacts: dict[str, str] = field(default_factory=dict)
    demo: dict[str, Any] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    @classmethod
    def create(
        cls,
        job_id: str,
        config: PipelineConfig,
        *,
        path_policy_version: int | None = None,
        legacy_external_output: bool | None = None,
    ) -> "PipelineManifest":
        now = datetime.now().isoformat(timespec="seconds")
        return cls(
            schema_version=1,
            job_id=job_id,
            created_at=now,
            updated_at=now,
            config=config,
            path_policy_version=path_policy_version,
            legacy_external_output=legacy_external_output,
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

    def bind_demo_asset(self, ref: DemoAssetRef, display_name: str) -> None:
        if not isinstance(ref, DemoAssetRef):
            raise TypeError("ref 必须是 DemoAssetRef。")
        validate_display_name(display_name)
        input_mode = self.demo.get("input_mode")
        if input_mode == "legacy_job_copy":
            raise ValueError("legacy_job_copy 输入不能重新绑定为 demo_asset。")
        if input_mode not in {None, "demo_asset"}:
            raise ValueError("demo.input_mode 不受支持。")
        if input_mode == "demo_asset":
            current_ref = self.demo_asset_ref()
            current_display_name = self.demo_asset_display_name()
            if current_ref != ref or current_display_name != display_name:
                raise ValueError("已有 demo_asset 引用不能被静默替换。")
        metadata = {
            key: value
            for key, value in self.demo.items()
            if key in _DEMO_ASSET_METADATA_KEYS
        }
        self.demo = {
            **metadata,
            "input_mode": "demo_asset",
            "asset_id": ref.asset_id,
            "asset_manifest": ref.asset_manifest_relative_path,
            "display_name": display_name,
        }
        self.updated_at = datetime.now().isoformat(timespec="seconds")

    def mark_legacy_demo_input(self) -> None:
        input_mode = self.demo.get("input_mode")
        if input_mode == "demo_asset":
            raise ValueError("demo_asset 输入不能重新标记为 legacy_job_copy。")
        if input_mode not in {None, "legacy_job_copy"}:
            raise ValueError("demo.input_mode 不受支持。")
        if input_mode == "legacy_job_copy":
            self.demo_asset_ref()
        self.demo = {
            key: value
            for key, value in self.demo.items()
            if key not in {"asset_id", "asset_manifest", "display_name"}
        }
        self.demo["input_mode"] = "legacy_job_copy"
        self.updated_at = datetime.now().isoformat(timespec="seconds")

    def demo_asset_ref(self) -> DemoAssetRef | None:
        input_mode = self.demo.get("input_mode")
        if input_mode is None:
            return None
        if input_mode == "legacy_job_copy":
            conflicting = _DEMO_ASSET_IDENTITY_KEYS & self.demo.keys()
            if conflicting:
                raise ValueError("legacy_job_copy 不能包含 demo_asset 引用字段。")
            return None
        if input_mode != "demo_asset":
            raise ValueError("demo.input_mode 不受支持。")
        unknown = set(self.demo) - _DEMO_ASSET_ALLOWED_KEYS
        if unknown:
            raise ValueError(f"demo_asset 包含不受支持的字段：{', '.join(sorted(unknown))}。")
        try:
            return DemoAssetRef.from_dict(
                {
                    "asset_id": self.demo["asset_id"],
                    "asset_manifest_relative_path": self.demo["asset_manifest"],
                }
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("demo_asset 引用字段无效。") from exc

    def demo_asset_display_name(self) -> str | None:
        if self.demo.get("input_mode") is None or self.demo.get("input_mode") == "legacy_job_copy":
            return None
        self.demo_asset_ref()
        try:
            return validate_display_name(self.demo["display_name"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("demo_asset display_name 无效。") from exc

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
        # An absolute path that is not recognizably inside this Job must not
        # leak a workspace, legacy output, or user directory into a shareable
        # manifest.  Relative artifact names remain useful as-is.
        if text.startswith("/") or (len(text) >= 3 and text[1] == ":" and text[2] == "/"):
            return "[artifact-path]"
        return text

    def to_public_dict(self) -> dict[str, Any]:
        """Return a manifest safe to write into job folders and feedback packs.

        Job manifests are often shared for debugging.  They must never contain
        API keys even though the in-memory PipelineConfig still needs the key
        while the process is running.
        """
        demo_ref = self.demo_asset_ref()
        if demo_ref is not None:
            self.demo_asset_display_name()
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
        if self.path_policy_version is not None:
            data["path_policy_version"] = self.path_policy_version
        if self.legacy_external_output is not None:
            data["legacy_external_output"] = self.legacy_external_output
        cfg = dict(data["config"])
        api_key = cfg.get("llm_api_key")
        cfg["llm_api_key_configured"] = bool(api_key)
        if api_key:
            cfg["llm_api_key"] = REDACTED_SECRET
        cache_dir = cfg.get("whisper_cache_dir")
        cfg["whisper_cache_dir_configured"] = bool(cache_dir)
        if cache_dir:
            cfg["whisper_cache_dir"] = "[workspace-managed]" if self.path_policy_version is not None else "[legacy-unmanaged]"
        if self.legacy_external_output is True:
            cfg["output_root"] = "[legacy-external-output]"
        elif self.path_policy_version is not None:
            cfg["output_root"] = "[workspace-managed]"
        else:
            cfg["output_root"] = "[legacy-unmanaged]"
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
        if cfg_data.get("whisper_cache_dir") in {"[workspace-managed]", "[legacy-unmanaged]"}:
            cfg_data["whisper_cache_dir"] = None
        if cfg_data.get("output_root") in {"[workspace-managed]", "[legacy-external-output]", "[legacy-unmanaged]"}:
            cfg_data["output_root"] = "output"
        allowed = set(PipelineConfig.__dataclass_fields__.keys())
        cfg_data = {k: v for k, v in cfg_data.items() if k in allowed}
        config = PipelineConfig(**cfg_data)
        manifest = cls(
            schema_version=int(data["schema_version"]),
            job_id=str(data["job_id"]),
            created_at=str(data["created_at"]),
            updated_at=str(data["updated_at"]),
            config=config,
            path_policy_version=(int(data["path_policy_version"]) if data.get("path_policy_version") is not None else None),
            legacy_external_output=(bool(data["legacy_external_output"]) if data.get("legacy_external_output") is not None else None),
            stages=dict(data.get("stages", {})),
            artifacts=dict(data.get("artifacts", {})),
            demo=dict(data.get("demo", {})),
            notes=list(data.get("notes", [])),
        )
        demo_ref = manifest.demo_asset_ref()
        if demo_ref is not None:
            manifest.demo_asset_display_name()
        return manifest
