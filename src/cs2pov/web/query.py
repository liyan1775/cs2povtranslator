from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
import os
from pathlib import Path
import stat

from cs2pov.domain.job import JobCatalogEntry, JobInspection, JobPhase
from cs2pov.domain.media import AudioMediaReference
from cs2pov.storage.demo_asset_repository import FileSystemDemoAssetRepository
from cs2pov.storage.job_errors import JobRepositoryError
from cs2pov.storage.job_paths import JobPaths
from cs2pov.storage.job_repository import FileSystemJobRepository
from cs2pov.workspace.models import WorkspaceDiagnostic
from cs2pov.workspace.paths import WorkspacePaths
from cs2pov.workspace.service import WorkspaceService


@dataclass(frozen=True, slots=True)
class CurrentJobWebMediaFile:
    """Validated internal media handle; its filesystem path never enters JSON."""

    reference: AudioMediaReference
    path: Path


class CurrentJobWebQueryError(RuntimeError):
    """A public, stable error for the local Web query surface."""

    def __init__(
        self,
        code: str,
        message_zh: str,
        suggestion_zh: str,
        *,
        status: int = 400,
    ) -> None:
        self.code = code
        self.message_zh = message_zh
        self.suggestion_zh = suggestion_zh
        self.status = status
        super().__init__(message_zh)


def _enum_value(value: object) -> object:
    return None if value is None else getattr(value, "value", value)


def _issue_payload(issue: object) -> dict[str, object]:
    return {
        "code": getattr(issue, "code", "unknown"),
        "severity": getattr(issue, "severity", "error"),
        "message_zh": getattr(issue, "message_zh", "数据诊断失败。"),
        "suggestion_zh": getattr(issue, "suggestion_zh", "请检查 Job 后重试。"),
        "logical_path": getattr(issue, "logical_path", None),
    }


def _catalog_payload(entry: JobCatalogEntry) -> dict[str, object]:
    progress = entry.round_progress
    return {
        "discovery_id": entry.discovery_id,
        "job_id": entry.job_id,
        "display_name": entry.display_name,
        "created_at": entry.created_at,
        "updated_at": entry.updated_at,
        "demo_asset_id": entry.demo_asset_id,
        "demo_display_name": entry.demo_display_name,
        "map_name": entry.map_name,
        "target_player_id": entry.target_player_id,
        "phase": _enum_value(entry.phase),
        "durable_run_status": _enum_value(entry.durable_run_status),
        "effective_run_status": _enum_value(entry.effective_run_status),
        "round_progress": None if progress is None else progress.to_dict(),
        "final_artifact_kinds": [
            _enum_value(kind) for kind in entry.final_artifact_kinds
        ],
        "healthy": entry.healthy,
        "issues": [_issue_payload(issue) for issue in entry.issues],
    }


def _inspection_payload(inspection: JobInspection) -> dict[str, object]:
    return {
        "entry": _catalog_payload(inspection.entry),
        "marker": None
        if inspection.marker is None
        else inspection.marker.to_dict(),
        "manifest": None
        if inspection.manifest is None
        else inspection.manifest.to_dict(),
        "source": None
        if inspection.source is None
        else inspection.source.to_dict(),
        "events": [event.to_dict() for event in inspection.events],
        "event_tail_incomplete": inspection.event_tail_incomplete,
    }


def _sort_transcripts(values: Iterable[object]) -> tuple[object, ...]:
    return tuple(
        sorted(
            values,
            key=lambda cue: (
                cue.time_range.start_us,
                cue.time_range.end_us,
                cue.cue_id,
            ),
        )
    )


def _sort_results(values: Iterable[object], transcripts: Iterable[object]) -> tuple[object, ...]:
    starts = {cue.cue_id: cue.time_range.start_us for cue in transcripts}
    return tuple(sorted(values, key=lambda result: (starts.get(result.cue_id, 2**63), result.cue_id)))


class CurrentJobWebQueryService:
    """Build read-only Web projections from current application services.

    The service deliberately accepts repository-like dependencies so the HTTP
    boundary can be tested without opening a socket. Production construction
    uses the current-version filesystem repositories only.
    """

    def __init__(
        self,
        paths: WorkspacePaths | str | Path,
        *,
        workspace_service: WorkspaceService | None = None,
        demo_assets: object | None = None,
        jobs: object | None = None,
    ) -> None:
        self.paths = paths if isinstance(paths, WorkspacePaths) else WorkspacePaths(paths)
        self.workspace_service = workspace_service or WorkspaceService(self.paths)
        if demo_assets is None:
            demo_assets = FileSystemDemoAssetRepository(self.paths)
        self._demo_assets = demo_assets
        if jobs is None:
            jobs = FileSystemJobRepository(self.paths, demo_assets)
        self._jobs_repository = jobs

    @property
    def repository(self) -> object:
        """Expose the repository to application-service adapters only."""
        return self._jobs_repository

    @property
    def demo_assets(self) -> object:
        """Expose the DemoAsset boundary to application-service adapters only."""
        return self._demo_assets

    def _workspace_payload(self, diagnostic: WorkspaceDiagnostic) -> dict[str, object]:
        workspace_id = None
        try:
            workspace_id = self.workspace_service.load_config().workspace_id
        except Exception:
            # The diagnostic already contains the actionable public state. A
            # missing or malformed config must not leak a filesystem cause.
            pass
        return {
            "ok": bool(diagnostic.ok),
            "workspace_id": workspace_id,
            "diagnostic": diagnostic.to_dict(),
        }

    def workspace(self) -> dict[str, object]:
        return self._workspace_payload(self.workspace_service.diagnose())

    def health(self) -> dict[str, object]:
        workspace = self.workspace()
        diagnostic = workspace["diagnostic"]
        return {
            "ok": bool(diagnostic["ok"]),
            "service": "cs2pov-local-web",
            "api_version": 1,
            **workspace,
        }

    def demos(self) -> dict[str, object]:
        try:
            values = self._demo_assets.list_assets()
        except Exception as exc:
            raise self._repository_error(exc, "无法读取 Demo 素材列表。") from exc
        return {"ok": True, "items": [value.to_dict() for value in values]}

    def jobs(self) -> dict[str, object]:
        try:
            values = self._jobs_repository.list_jobs()
        except Exception as exc:
            raise self._repository_error(exc, "无法读取 Job 列表。") from exc
        return {"ok": True, "items": [_catalog_payload(value) for value in values]}

    def exports(self, job_id: str) -> dict[str, object]:
        """Return export gates and persisted final artifact references."""
        inspection = self._require_job(job_id)
        manifest = inspection.manifest
        if manifest is None:  # guarded by _require_job; keep the projection explicit
            raise CurrentJobWebQueryError(
                "job_not_readable",
                "当前 Job 还不能读取导出状态。",
                "请先修复 Job 诊断中列出的文件问题。",
                status=409,
            )
        draft_available = self._optional_timeline(job_id, "draft")
        reviewed_available = self._optional_timeline(job_id, "reviewed")
        artifacts = []
        for artifact in manifest.final_artifacts:
            artifacts.append(artifact.to_dict())
        return {
            "ok": True,
            "job_id": job_id,
            "phase": manifest.phase.value,
            "run_status": manifest.run_status.value,
            "gates": {
                "draft": draft_available,
                "reviewed": reviewed_available,
                "reviewed_subtitle_export": reviewed_available
                and manifest.phase
                in {
                    JobPhase.FINAL_TIMELINE_READY,
                    JobPhase.SUBTITLES_EXPORTED,
                    JobPhase.GREEN_SCREEN_RENDERED,
                    JobPhase.COMPLETED_WITHOUT_VIDEO,
                    JobPhase.READY_FOR_RENDER,
                    JobPhase.RENDERING,
                    JobPhase.VIDEO_READY,
                    JobPhase.COMPLETED_WITH_VIDEO,
                },
            },
            "artifacts": artifacts,
        }

    def _optional_timeline(self, job_id: str, source: str) -> bool:
        loader = getattr(
            self._jobs_repository,
            "load_draft_timeline" if source == "draft" else "load_reviewed_timeline",
            None,
        )
        if not callable(loader):
            return False
        try:
            loader(job_id)
        except Exception as exc:
            if self._is_missing_shard(exc):
                return False
            raise self._repository_error(exc, "无法读取当前导出门禁状态。") from exc
        return True

    def job(self, job_id: str) -> dict[str, object]:
        try:
            inspection = self._jobs_repository.inspect_job(job_id)
        except KeyError as exc:
            raise CurrentJobWebQueryError(
                "job_not_found",
                "找不到当前版本 Job。",
                "请从 Job 列表重新选择。",
                status=404,
            ) from exc
        except Exception as exc:
            raise self._repository_error(exc, "无法读取 Job 详情。") from exc
        if not isinstance(inspection, JobInspection):
            raise CurrentJobWebQueryError(
                "job_query_invalid",
                "Job 查询结果无效。",
                "请检查当前版本仓储后重试。",
                status=500,
            )
        return {"ok": True, **_inspection_payload(inspection)}

    def events(self, job_id: str) -> dict[str, object]:
        self._require_job(job_id)
        try:
            result = self._jobs_repository.read_events(job_id)
        except Exception as exc:
            raise self._repository_error(exc, "无法读取 Job 事件。") from exc
        return {
            "ok": True,
            "events": [event.to_dict() for event in result.events],
            "incomplete_tail": result.incomplete_tail,
            "issues": [_issue_payload(issue) for issue in result.issues],
        }

    def round(self, job_id: str, round_id: str) -> dict[str, object]:
        self._require_job(job_id)
        try:
            timeline = self._jobs_repository.load_demo_timeline(job_id)
        except Exception as exc:
            raise self._repository_error(exc, "无法读取 Job 时间线。") from exc
        round_value = next(
            (value for value in timeline.rounds.rounds if value.round_id == round_id),
            None,
        )
        if round_value is None:
            raise CurrentJobWebQueryError(
                "round_not_found",
                "找不到当前版本回合。",
                "请从 Job 的当前回合列表重新选择。",
                status=404,
            )

        try:
            transcripts = _sort_transcripts(
                self._jobs_repository.load_transcript_round(job_id, round_id)
            )
        except Exception as exc:
            if self._is_missing_shard(exc):
                transcripts = ()
            else:
                raise self._repository_error(exc, "无法读取回合转录。") from exc

        understanding = self._optional_round_document(job_id, round_id)
        draft = self._optional_draft(job_id, round_id)
        review = self._optional_review(job_id, round_id)
        understanding_payload = None
        if understanding is not None:
            understanding_payload = understanding.to_dict()
            understanding_payload["results"] = [
                result.to_dict()
                for result in _sort_results(understanding.results, transcripts)
            ]
        return {
            "ok": True,
            "round": round_value.to_dict(),
            "transcripts": [cue.to_dict() for cue in transcripts],
            "understanding": understanding_payload,
            "draft": [cue.to_dict() for cue in draft],
            "review": review,
        }

    def review(self, job_id: str, round_id: str) -> dict[str, object]:
        """Return the cue-oriented read model used by the review page.

        The durable shards remain the source of truth. This projection only
        joins them for presentation and keeps the original ASR alongside the
        model result, Draft value, and current review decision.
        """
        detail = self.round(job_id, round_id)
        transcripts = {
            value["cue_id"]: value for value in detail["transcripts"]
        }
        understanding = detail["understanding"] or {}
        results = {
            value["cue_id"]: value for value in understanding.get("results", [])
        }
        drafts = {value["cue_id"]: value for value in detail["draft"]}
        review_document = detail["review"] or {}
        decisions = {
            value["cue_id"]: value
            for value in review_document.get("decisions", [])
        }

        cue_ids = set(transcripts) | set(results) | set(drafts) | set(decisions)
        media_references = self._optional_audio_media(job_id)
        media_by_player = {
            value.player_id: value for value in media_references
        }

        def item_key(cue_id: str) -> tuple[int, int, str]:
            transcript = transcripts.get(cue_id)
            draft = drafts.get(cue_id)
            value = transcript or draft or {}
            return (
                int(value.get("start_us", 2**63)),
                int(value.get("end_us", 2**63)),
                cue_id,
            )

        items: list[dict[str, object]] = []
        for cue_id in sorted(cue_ids, key=item_key):
            transcript = transcripts.get(cue_id)
            result = results.get(cue_id)
            draft = drafts.get(cue_id)
            decision = decisions.get(cue_id)
            source = transcript or draft or result or {}
            risk_flags: list[str] = []
            if result is None:
                risk_flags.append("understanding_missing")
            elif float(result.get("confidence", 1.0)) < 0.7:
                risk_flags.append("low_confidence")
            if result and result.get("warnings"):
                risk_flags.append("has_warnings")
            if decision is None:
                risk_flags.append("review_pending")
            items.append(
                {
                    "cue_id": cue_id,
                    "round_id": round_id,
                    "player_id": source.get("player_id"),
                    "start_us": source.get("start_us"),
                    "end_us": source.get("end_us"),
                    "asr_original": (
                        transcript or result or draft or {}
                    ).get("asr_original"),
                    "asr_confidence": None
                    if transcript is None
                    else transcript.get("confidence"),
                    "understanding": result,
                    "draft": draft,
                    "decision": decision,
                    "risk_flags": risk_flags,
                    "media": self._media_payload(
                        media_by_player.get(source.get("player_id")),
                        job_id,
                        transcript,
                    ),
                }
            )
        pending_count = sum(item["decision"] is None for item in items)
        return {
            "ok": True,
            "job_id": job_id,
            "round": detail["round"],
            "review": {
                "status": "active" if review_document else "not_started",
                "review_id": review_document.get("review_id"),
                "source_draft_fingerprint": review_document.get(
                    "source_draft_fingerprint"
                ),
                "decision_count": len(decisions),
                "completed_count": len(items) - pending_count,
                "pending_count": pending_count,
                "items": items,
            },
            "media": {
                "status": "ready" if media_references else "unavailable",
                "items": [
                    self._media_summary(value, job_id)
                    for value in media_references
                ],
                "message_zh": (
                    "当前回合可使用受控音频引用。"
                    if media_references
                    else "当前 Job 没有可用的持久音频媒体。"
                ),
            },
        }

    def media_file(self, job_id: str, media_id: str) -> CurrentJobWebMediaFile:
        self._require_job(job_id)
        references = self._optional_audio_media(job_id)
        reference = next(
            (value for value in references if value.media_id == media_id),
            None,
        )
        if reference is None:
            raise CurrentJobWebQueryError(
                "media_not_found",
                "找不到当前 Job 的音频媒体。",
                "请从回合复核页面重新选择音频。",
                status=404,
            )
        try:
            path = JobPaths(self.paths, job_id).voice_audio(reference.media_id)
            state = os.lstat(path)
        except (OSError, ValueError) as exc:
            raise CurrentJobWebQueryError(
                "media_unavailable",
                "当前音频媒体暂时不可用。",
                "请重新运行语音阶段或检查 Job 诊断。",
                status=409,
            ) from exc
        if stat.S_ISLNK(state.st_mode) or not stat.S_ISREG(state.st_mode):
            raise CurrentJobWebQueryError(
                "media_unavailable",
                "当前音频媒体暂时不可用。",
                "请修复 Job 音频文件后重试。",
                status=409,
            )
        return CurrentJobWebMediaFile(reference, path)

    def _optional_audio_media(self, job_id: str) -> tuple[AudioMediaReference, ...]:
        loader = getattr(self._jobs_repository, "load_audio_media", None)
        if not callable(loader):
            return ()
        try:
            values = loader(job_id)
        except Exception as exc:
            if self._is_missing_shard(exc):
                return ()
            raise self._repository_error(exc, "无法读取 Job 音频媒体。") from exc
        if not isinstance(values, (tuple, list)) or any(
            type(value) is not AudioMediaReference for value in values
        ):
            raise CurrentJobWebQueryError(
                "media_query_invalid",
                "Job 音频媒体查询结果无效。",
                "请检查当前版本仓储后重试。",
                status=500,
            )
        return tuple(values)

    @staticmethod
    def _media_summary(reference: AudioMediaReference, job_id: str) -> dict[str, object]:
        return {
            "media_id": reference.media_id,
            "player_id": reference.player_id,
            "relative_path": reference.relative_path,
            "content_sha256": reference.content_sha256,
            "sample_rate": reference.sample_rate,
            "sample_count": reference.sample_count,
            "mime_type": reference.mime_type,
            "url": f"/api/v1/jobs/{job_id}/media/{reference.media_id}",
        }

    @classmethod
    def _media_payload(
        cls,
        reference: AudioMediaReference | None,
        job_id: str,
        transcript: dict[str, object] | None,
    ) -> dict[str, object]:
        if reference is None:
            return {
                "status": "unavailable",
                "message_zh": "该 Cue 没有可用的持久音频引用。",
            }
        payload = cls._media_summary(reference, job_id)
        payload["status"] = "ready"
        if transcript is not None:
            start_sample = transcript["source_start"]
            end_sample = transcript["source_end"]
            payload.update(
                {
                    "start_sample": start_sample,
                    "end_sample": end_sample,
                    "start_seconds": round(start_sample / reference.sample_rate, 6),
                    "end_seconds": round(end_sample / reference.sample_rate, 6),
                }
            )
            if end_sample > reference.sample_count:
                payload["status"] = "range_invalid"
                payload["message_zh"] = "该 Cue 的音频范围超出持久媒体。"
        return payload

    def _require_job(self, job_id: str) -> JobInspection:
        try:
            inspection = self._jobs_repository.inspect_job(job_id)
        except KeyError as exc:
            raise CurrentJobWebQueryError(
                "job_not_found",
                "找不到当前版本 Job。",
                "请从 Job 列表重新选择。",
                status=404,
            ) from exc
        except Exception as exc:
            raise self._repository_error(exc, "无法读取 Job。") from exc
        if not isinstance(inspection, JobInspection):
            raise CurrentJobWebQueryError(
                "job_query_invalid",
                "Job 查询结果无效。",
                "请检查当前版本仓储后重试。",
                status=500,
            )
        if inspection.manifest is None:
            raise CurrentJobWebQueryError(
                "job_not_readable",
                "当前 Job 还不能读取语言数据。",
                "请先修复 Job 诊断中列出的文件问题。",
                status=409,
            )
        return inspection

    def _optional_round_document(self, job_id: str, round_id: str):
        try:
            return self._jobs_repository.load_round_understanding(job_id, round_id)
        except Exception as exc:
            if self._is_missing_shard(exc):
                return None
            raise self._repository_error(exc, "无法读取回合理解翻译。") from exc

    def _optional_draft(self, job_id: str, round_id: str) -> tuple[object, ...]:
        try:
            draft = self._jobs_repository.load_draft_timeline(job_id)
        except Exception as exc:
            if self._is_missing_shard(exc):
                return ()
            raise self._repository_error(exc, "无法读取 Draft 时间线。") from exc
        return tuple(
            sorted(
                (cue for cue in draft.cues if cue.round_id == round_id),
                key=lambda cue: (cue.start_us, cue.end_us, cue.cue_id),
            )
        )

    def _optional_review(self, job_id: str, round_id: str) -> dict[str, object] | None:
        inspection = self._require_job(job_id)
        review_id = (
            inspection.manifest.active_review_id if inspection.manifest is not None else None
        )
        if review_id is None:
            return None
        try:
            bundle = self._jobs_repository.load_review_revision(job_id, review_id)
        except Exception as exc:
            if self._is_missing_shard(exc):
                return None
            raise self._repository_error(exc, "无法读取当前复核版本。") from exc
        document = next(
            (value for value in bundle.round_documents if value.round_id == round_id),
            None,
        )
        return None if document is None else document.to_dict()

    @staticmethod
    def _is_missing_shard(exc: BaseException) -> bool:
        return isinstance(exc, JobRepositoryError) and exc.code == "job_shard_missing"

    @staticmethod
    def _repository_error(exc: BaseException, fallback: str) -> CurrentJobWebQueryError:
        if isinstance(exc, CurrentJobWebQueryError):
            return exc
        if isinstance(exc, JobRepositoryError):
            status = 404 if exc.code in {"job_not_found", "job_shard_missing"} else 400
            return CurrentJobWebQueryError(
                exc.code,
                exc.message_zh,
                exc.suggestion_zh,
                status=status,
            )
        code = getattr(exc, "code", None)
        if isinstance(code, str) and code:
            return CurrentJobWebQueryError(
                code,
                getattr(exc, "message_zh", fallback),
                getattr(exc, "suggestion_zh", "请检查当前工作区后重试。"),
            )
        return CurrentJobWebQueryError(
            "query_failed",
            fallback,
            "请检查当前工作区和 Job 后重试。",
            status=500,
        )
