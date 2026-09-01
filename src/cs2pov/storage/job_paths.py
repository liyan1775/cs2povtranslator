from __future__ import annotations

import os
from pathlib import Path

from cs2pov.domain.job import FinalArtifactKind
from cs2pov.domain.schema import require_path_identifier, require_artifact_relative_path
from cs2pov.workspace.paths import WorkspacePaths
from cs2pov.workspace.errors import WorkspacePathOutsideRootError


class JobPaths:
    """Canonical paths for one current-version Job.

    Construction performs no filesystem writes. Existing symlink components are
    rejected so a path returned by this object cannot silently escape a
    workspace through a link or junction.
    """

    def __init__(self, workspace: WorkspacePaths, job_id: str) -> None:
        if not isinstance(workspace, WorkspacePaths):
            raise TypeError("workspace must be WorkspacePaths")
        self.workspace = workspace
        self.job_id = require_path_identifier(job_id, "job_id")
        self._assert_safe_existing_components(workspace.jobs_dir)
        self._assert_inside(workspace.jobs_dir)
        self._assert_safe_existing_components(workspace.jobs_dir / self.job_id)

    def _assert_inside(self, path: Path) -> Path:
        try:
            return self.workspace._inside(path)
        except WorkspacePathOutsideRootError:
            raise

    def _assert_safe_existing_components(self, path: Path) -> None:
        # Check each existing component without resolving links. This catches
        # links pointing inside the workspace too: they still violate the
        # repository's no-link invariant and are vulnerable to later swaps.
        try:
            relative = path.absolute().relative_to(self.workspace.root)
        except ValueError as exc:
            raise WorkspacePathOutsideRootError("路径超出工作区。") from exc
        current = self.workspace.root
        for component in relative.parts:
            current = current / component
            try:
                st = os.lstat(current)
            except FileNotFoundError:
                break
            if os.path.islink(current) or not (os.path.isdir(current) or os.path.isfile(current)):
                raise WorkspacePathOutsideRootError("路径包含链接或无效文件系统节点。")

    @property
    def jobs_dir(self) -> Path:
        return self.workspace.jobs_dir

    @property
    def job_dir(self) -> Path:
        return self.jobs_dir / self.job_id

    @property
    def repository_marker(self) -> Path:
        return self.job_dir / "repository.json"

    @property
    def manifest(self) -> Path:
        return self.job_dir / "job.json"

    @property
    def source_dir(self) -> Path:
        return self.job_dir / "source"

    @property
    def demo_source(self) -> Path:
        return self.source_dir / "demo_ref.json"

    @property
    def timeline_dir(self) -> Path:
        return self.job_dir / "timeline"

    @property
    def demo_timeline(self) -> Path:
        return self.timeline_dir / "demo.json"

    @property
    def timeline_rounds(self) -> Path:
        return self.timeline_dir / "rounds.json"

    @property
    def time_anchors(self) -> Path:
        return self.timeline_dir / "time_anchors.jsonl"

    @property
    def voice_dir(self) -> Path:
        return self.job_dir / "voice"

    @property
    def voice_activities(self) -> Path:
        return self.voice_dir / "activities.jsonl"

    @property
    def models_dir(self) -> Path:
        return self.job_dir / "models"

    @property
    def snapshots_dir(self) -> Path:
        return self.models_dir / "snapshots"

    @property
    def invocations_dir(self) -> Path:
        return self.models_dir / "invocations"

    @property
    def transcript_dir(self) -> Path:
        return self.job_dir / "transcript"

    @property
    def understanding_dir(self) -> Path:
        return self.job_dir / "understanding"

    @property
    def review_dir(self) -> Path:
        return self.job_dir / "review"

    @property
    def review_revisions_dir(self) -> Path:
        return self.review_dir / "revisions"

    @property
    def tasks_dir(self) -> Path:
        return self.job_dir / "tasks"

    @property
    def events_dir(self) -> Path:
        return self.job_dir / "events"

    @property
    def event_journal(self) -> Path:
        return self.events_dir / "job_events.jsonl"

    @property
    def write_lock(self) -> Path:
        return self.events_dir / ".write.lock"

    @property
    def writer_claim_dir(self) -> Path:
        return self.events_dir / ".writer_claim"

    @property
    def writer_claim(self) -> Path:
        return self.writer_claim_dir / "claim.json"

    @property
    def final_dir(self) -> Path:
        return self.job_dir / "final"

    @property
    def final_timelines_dir(self) -> Path:
        return self.final_dir / "timelines"

    @property
    def final_subtitles_dir(self) -> Path:
        return self.final_dir / "subtitles"

    @property
    def final_green_screen_dir(self) -> Path:
        return self.final_dir / "green_screen"

    @property
    def final_video_dir(self) -> Path:
        return self.final_dir / "video"

    def snapshot(self, snapshot_id: str) -> Path:
        return self.snapshots_dir / f"snapshot_{require_path_identifier(snapshot_id, 'snapshot_id')}.json"

    def task_invocations(self, task_id: str) -> Path:
        return self.invocations_dir / f"task_{require_path_identifier(task_id, 'task_id')}.jsonl"

    def round_transcript(self, round_id: str) -> Path:
        return self.transcript_dir / f"round_{require_path_identifier(round_id, 'round_id')}.jsonl"

    def unassigned_transcript(self) -> Path:
        return self.transcript_dir / "unassigned.jsonl"

    def round_understanding(self, round_id: str) -> Path:
        return self.understanding_dir / f"round_{require_path_identifier(round_id, 'round_id')}.json"

    def review_revision(self, review_id: str) -> Path:
        return self.review_revisions_dir / f"review_{require_path_identifier(review_id, 'review_id')}"

    def review_revision_manifest(self, review_id: str) -> Path:
        return self.review_revision(review_id) / "revision.json"

    def review_round(self, review_id: str, round_id: str) -> Path:
        return self.review_revision(review_id) / f"round_{require_path_identifier(round_id, 'round_id')}.json"

    def task_round(self, round_id: str) -> Path:
        return self.tasks_dir / f"round_{require_path_identifier(round_id, 'round_id')}.json"

    def artifact_path(self, kind: FinalArtifactKind, relative_path: str) -> Path:
        if not isinstance(kind, FinalArtifactKind):
            raise ValueError("kind must be FinalArtifactKind")
        require_artifact_relative_path(relative_path, kind)
        parts = relative_path.split("/")
        candidate = self.job_dir.joinpath(*parts)
        self._assert_safe_existing_components(candidate.parent)
        self._assert_inside(candidate.parent)
        return candidate

    def final_artifact_path(self, relative_path: str, *, kind: FinalArtifactKind | None = None) -> Path:
        if kind is None:
            if not isinstance(relative_path, str):
                raise ValueError("relative_path")
            parts = relative_path.split("/")
            roots = {"timelines": FinalArtifactKind.TIMELINE, "subtitles": FinalArtifactKind.SUBTITLE, "green_screen": FinalArtifactKind.GREEN_SCREEN, "video": FinalArtifactKind.VIDEO}
            if len(parts) < 3 or parts[0] != "final" or parts[1] not in roots:
                raise ValueError("artifact path")
            kind = roots[parts[1]]
        return self.artifact_path(kind, relative_path)
