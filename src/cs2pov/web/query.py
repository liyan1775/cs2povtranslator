from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from cs2pov.domain.job import JobCatalogEntry, JobInspection
from cs2pov.storage.demo_asset_repository import FileSystemDemoAssetRepository
from cs2pov.storage.job_errors import JobRepositoryError
from cs2pov.storage.job_repository import FileSystemJobRepository
from cs2pov.workspace.models import WorkspaceDiagnostic
from cs2pov.workspace.paths import WorkspacePaths
from cs2pov.workspace.service import WorkspaceService


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
