"""Pure invalidation policy: revoke current authority, retain diagnostic history.

``first_invalid_phase`` is the checkpoint to resume from, as named in the
approved dependency table; it is not a claim that its own output is invalid.
Round scopes select upstream work. Manifest cleanup removes every indexed
artifact of the specified kinds because the active review is Job-wide.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
from enum import Enum
from types import MappingProxyType
from typing import Final, NoReturn

from .errors import DomainSchemaError
from .job import FinalArtifactKind, JobManifest, JobPhase, JobRunStatus
from .schema import require_canonical_utc_timestamp, require_path_identifier


class JobInputChange(str, Enum):
    DISPLAY_METADATA = "display_metadata"
    SUBTITLE_LAYOUT = "subtitle_layout"
    REVIEW_DECISION = "review_decision"
    TRANSLATION_CONFIGURATION = "translation_configuration"
    KNOWLEDGE_REVISION = "knowledge_revision"
    ASR_CONFIGURATION = "asr_configuration"
    ROUND_BOUNDARY = "round_boundary"
    DEMO_ASSET_IDENTITY = "demo_asset_identity"
    RENDER_CONFIGURATION = "render_configuration"
    POV_ADAPTER_UNAVAILABLE = "pov_adapter_unavailable"


class JobStage(str, Enum):
    DEMO_TIMELINE = "demo_timeline"
    VOICE = "voice"
    TRANSCRIPT = "transcript"
    CONTEXT = "context"
    UNDERSTANDING = "understanding"
    DRAFT_TIMELINE = "draft_timeline"
    REVIEWED_TIMELINE = "reviewed_timeline"
    SUBTITLES = "subtitles"
    GREEN_SCREEN = "green_screen"
    VIDEO = "video"


@dataclass(frozen=True, slots=True)
class _DependencyRule:
    first_invalid_phase: JobPhase
    invalid_stages: tuple[JobStage, ...]
    round_scoped: bool
    clear_active_review: bool
    remove_artifact_kinds: frozenset[FinalArtifactKind]


_EXPORT_STAGES = (JobStage.SUBTITLES, JobStage.GREEN_SCREEN, JobStage.VIDEO)
_REVIEW_STAGES = (JobStage.REVIEWED_TIMELINE, *_EXPORT_STAGES)
_UNDERSTANDING_STAGES = (
    JobStage.UNDERSTANDING, JobStage.DRAFT_TIMELINE, *_REVIEW_STAGES,
)
_TRANSCRIPT_STAGES = (JobStage.TRANSCRIPT, JobStage.CONTEXT, *_UNDERSTANDING_STAGES)
_ALL_ARTIFACTS = frozenset(
    {FinalArtifactKind.TIMELINE, FinalArtifactKind.SUBTITLE,
     FinalArtifactKind.GREEN_SCREEN, FinalArtifactKind.VIDEO}
)
_EXPORT_ARTIFACTS = frozenset(
    {FinalArtifactKind.SUBTITLE, FinalArtifactKind.GREEN_SCREEN, FinalArtifactKind.VIDEO}
)

# One immutable authority for both planning and validation of public plans.
_DEPENDENCIES: Final[Mapping[JobInputChange, _DependencyRule]] = MappingProxyType({
    JobInputChange.DISPLAY_METADATA: _DependencyRule(
        JobPhase.FINAL_TIMELINE_READY, _EXPORT_STAGES, False, False, _EXPORT_ARTIFACTS,
    ),
    JobInputChange.SUBTITLE_LAYOUT: _DependencyRule(
        JobPhase.FINAL_TIMELINE_READY, _EXPORT_STAGES, False, False, _EXPORT_ARTIFACTS,
    ),
    JobInputChange.REVIEW_DECISION: _DependencyRule(
        JobPhase.DRAFT_TIMELINE_READY, _REVIEW_STAGES, True, True, _ALL_ARTIFACTS,
    ),
    JobInputChange.TRANSLATION_CONFIGURATION: _DependencyRule(
        JobPhase.CONTEXT_READY, _UNDERSTANDING_STAGES, True, True, _ALL_ARTIFACTS,
    ),
    JobInputChange.KNOWLEDGE_REVISION: _DependencyRule(
        JobPhase.CONTEXT_READY, _UNDERSTANDING_STAGES, True, True, _ALL_ARTIFACTS,
    ),
    JobInputChange.ASR_CONFIGURATION: _DependencyRule(
        JobPhase.VOICE_READY, _TRANSCRIPT_STAGES, False, True, _ALL_ARTIFACTS,
    ),
    JobInputChange.ROUND_BOUNDARY: _DependencyRule(
        JobPhase.TIMELINE_READY, _TRANSCRIPT_STAGES, True, True, _ALL_ARTIFACTS,
    ),
    JobInputChange.DEMO_ASSET_IDENTITY: _DependencyRule(
        JobPhase.CREATED, (JobStage.DEMO_TIMELINE, JobStage.VOICE, *_TRANSCRIPT_STAGES),
        False, True, _ALL_ARTIFACTS,
    ),
    JobInputChange.RENDER_CONFIGURATION: _DependencyRule(
        JobPhase.GREEN_SCREEN_RENDERED, (JobStage.VIDEO,), False, False,
        frozenset({FinalArtifactKind.VIDEO}),
    ),
    JobInputChange.POV_ADAPTER_UNAVAILABLE: _DependencyRule(
        JobPhase.GREEN_SCREEN_RENDERED, (JobStage.VIDEO,), False, False,
        frozenset({FinalArtifactKind.VIDEO}),
    ),
})


def _invalid(path: str, *, transition: bool = False) -> NoReturn:
    raise DomainSchemaError(
        "domain_state_transition_invalid" if transition else "domain_field_invalid",
        "Job 失效状态转换无效。" if transition else "Job 失效计划无效。",
        "请核对输入变更、回合范围和当前阶段后重试。",
        path,
    )


def _canonical_round_ids(value: object, path: str) -> tuple[str, ...]:
    if type(value) is not tuple:
        _invalid(path)
    for index, round_id in enumerate(value):
        require_path_identifier(round_id, f"{path}[{index}]")
    if len(set(value)) != len(value):
        _invalid(path)
    # IDs are stable identities, not display numbers. This canonical set order
    # does not replace the timeline order used by task execution/aggregation.
    return tuple(sorted(value))


@dataclass(frozen=True, slots=True)
class InvalidationRequest:
    change: JobInputChange
    round_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.change, JobInputChange):
            _invalid("invalidation_request.change")
        rounds = _canonical_round_ids(self.round_ids, "invalidation_request.round_ids")
        if bool(rounds) != _DEPENDENCIES[self.change].round_scoped:
            _invalid("invalidation_request.round_ids")
        object.__setattr__(self, "round_ids", rounds)


@dataclass(frozen=True, slots=True)
class InvalidationPlan:
    first_invalid_phase: JobPhase
    invalid_stages: tuple[JobStage, ...]
    round_ids: tuple[str, ...]
    clear_active_review: bool
    remove_artifact_kinds: frozenset[FinalArtifactKind]

    def __post_init__(self) -> None:
        if not isinstance(self.first_invalid_phase, JobPhase):
            _invalid("invalidation_plan.first_invalid_phase")
        if type(self.invalid_stages) is not tuple or any(
            not isinstance(stage, JobStage) for stage in self.invalid_stages
        ):
            _invalid("invalidation_plan.invalid_stages")
        rounds = _canonical_round_ids(self.round_ids, "invalidation_plan.round_ids")
        if type(self.clear_active_review) is not bool:
            _invalid("invalidation_plan.clear_active_review")
        if type(self.remove_artifact_kinds) is not frozenset or any(
            not isinstance(kind, FinalArtifactKind) for kind in self.remove_artifact_kinds
        ):
            _invalid("invalidation_plan.remove_artifact_kinds")
        if not any(
            self.first_invalid_phase is rule.first_invalid_phase
            and self.invalid_stages == rule.invalid_stages
            and bool(rounds) == rule.round_scoped
            and self.clear_active_review is rule.clear_active_review
            and self.remove_artifact_kinds == rule.remove_artifact_kinds
            for rule in _DEPENDENCIES.values()
        ):
            # A frozen plan alone is insufficient: independent valid fields
            # could otherwise under-invalidate review or export authority.
            _invalid("invalidation_plan")
        object.__setattr__(self, "round_ids", rounds)


def plan_invalidation(request: InvalidationRequest) -> InvalidationPlan:
    """Return the exact dependency closure with a canonical immutable scope."""
    if not isinstance(request, InvalidationRequest):
        _invalid("invalidation_request")
    rule = _DEPENDENCIES[request.change]
    return InvalidationPlan(
        first_invalid_phase=rule.first_invalid_phase,
        invalid_stages=rule.invalid_stages,
        round_ids=request.round_ids,
        clear_active_review=rule.clear_active_review,
        remove_artifact_kinds=rule.remove_artifact_kinds,
    )


# Rewind ancestry follows the approved branches, never the Enum declaration
# order (COMPLETED_DRAFT and COMPLETED_WITHOUT_VIDEO are sibling terminals).
_COMMON_PHASES = (
    JobPhase.CREATED, JobPhase.TIMELINE_READY, JobPhase.VOICE_READY,
    JobPhase.TRANSCRIBED, JobPhase.CONTEXT_READY, JobPhase.UNDERSTANDING_TRANSLATING,
    JobPhase.UNDERSTOOD_TRANSLATED, JobPhase.DRAFT_TIMELINE_READY,
)
_REVIEW_PHASES = _COMMON_PHASES + (
    JobPhase.REVIEW_PENDING, JobPhase.REVIEWED, JobPhase.FINAL_TIMELINE_READY,
    JobPhase.SUBTITLES_EXPORTED, JobPhase.GREEN_SCREEN_RENDERED,
)
_PHASE_BRANCHES = (
    _COMMON_PHASES + (JobPhase.COMPLETED_DRAFT,),
    _REVIEW_PHASES + (JobPhase.COMPLETED_WITHOUT_VIDEO,),
    _REVIEW_PHASES + (JobPhase.READY_FOR_RENDER, JobPhase.RENDERING,
                      JobPhase.VIDEO_READY, JobPhase.COMPLETED_WITH_VIDEO),
)


def rewind_job_phase_for_invalidation(
    manifest: JobManifest,
    plan: InvalidationPlan,
    *,
    at: str,
) -> JobManifest:
    """Revoke indexed authority and return to an already reached checkpoint.

    Repeating an invalidation at its checkpoint is legal with a newer timestamp.
    A target ahead of the current phase or on an unreached branch is rejected,
    rather than manufacturing completed upstream work. Checkpoints use their
    default status: CREATED/PENDING, all other permitted targets/SUCCEEDED.
    The coordinator derives round progress from persisted tasks afterward.
    """
    if not isinstance(manifest, JobManifest):
        _invalid("job_manifest")
    if not isinstance(plan, InvalidationPlan):
        _invalid("invalidation_plan")
    updated_at = require_canonical_utc_timestamp(at, "at")
    if updated_at <= manifest.updated_at:
        _invalid("at")
    target = plan.first_invalid_phase
    if not any(
        manifest.phase in branch and target in branch
        and branch.index(target) <= branch.index(manifest.phase)
        for branch in _PHASE_BRANCHES
    ):
        _invalid("job_manifest.phase", transition=True)
    if target in {JobPhase.FINAL_TIMELINE_READY, JobPhase.GREEN_SCREEN_RENDERED}:
        if manifest.active_review_id is None:
            _invalid("job_manifest.active_review_id", transition=True)
    return replace(
        manifest,
        phase=target,
        run_status=JobRunStatus.PENDING if target is JobPhase.CREATED else JobRunStatus.SUCCEEDED,
        updated_at=updated_at,
        active_review_id=None if plan.clear_active_review else manifest.active_review_id,
        final_artifacts=tuple(
            artifact for artifact in manifest.final_artifacts
            if artifact.kind not in plan.remove_artifact_kinds
        ),
    )
