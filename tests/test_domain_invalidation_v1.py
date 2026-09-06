from dataclasses import FrozenInstanceError, replace
from itertools import permutations

import pytest

from cs2pov.domain.errors import DomainSchemaError
from cs2pov.domain.invalidation import (
    InvalidationPlan,
    InvalidationRequest,
    JobInputChange,
    JobStage,
    plan_invalidation,
    rewind_job_phase_for_invalidation,
)
from cs2pov.domain.job import (
    FinalArtifactEntry,
    FinalArtifactKind,
    FinalArtifactTimebase,
    JobManifest,
    JobPhase,
    JobRunStatus,
    RoundProgressSummary,
)


CREATED_AT = "2026-09-03T01:02:03.000000Z"
UPDATED_AT = "2026-09-03T01:02:04.000000Z"
REWOUND_AT = "2026-09-03T01:02:04.000001Z"
ROUNDS = ("round-001", "round-002")
ALL_ARTIFACTS = frozenset(
    {FinalArtifactKind.TIMELINE, FinalArtifactKind.SUBTITLE,
     FinalArtifactKind.GREEN_SCREEN, FinalArtifactKind.VIDEO}
)
EXPORT_ARTIFACTS = frozenset(
    {FinalArtifactKind.SUBTITLE, FinalArtifactKind.GREEN_SCREEN, FinalArtifactKind.VIDEO}
)

# Literal expectations from Task 4, independent of the production graph.
MATRIX = (
    (JobInputChange.DISPLAY_METADATA, JobPhase.FINAL_TIMELINE_READY,
     (JobStage.SUBTITLES, JobStage.GREEN_SCREEN, JobStage.VIDEO),
     False, EXPORT_ARTIFACTS, ()),
    (JobInputChange.SUBTITLE_LAYOUT, JobPhase.FINAL_TIMELINE_READY,
     (JobStage.SUBTITLES, JobStage.GREEN_SCREEN, JobStage.VIDEO),
     False, EXPORT_ARTIFACTS, ()),
    (JobInputChange.REVIEW_DECISION, JobPhase.DRAFT_TIMELINE_READY,
     (JobStage.REVIEWED_TIMELINE, JobStage.SUBTITLES, JobStage.GREEN_SCREEN,
      JobStage.VIDEO),
     True, ALL_ARTIFACTS, ROUNDS),
    (JobInputChange.TRANSLATION_CONFIGURATION, JobPhase.CONTEXT_READY,
     (JobStage.UNDERSTANDING, JobStage.DRAFT_TIMELINE, JobStage.REVIEWED_TIMELINE,
      JobStage.SUBTITLES, JobStage.GREEN_SCREEN, JobStage.VIDEO),
     True, ALL_ARTIFACTS, ROUNDS),
    (JobInputChange.KNOWLEDGE_REVISION, JobPhase.CONTEXT_READY,
     (JobStage.UNDERSTANDING, JobStage.DRAFT_TIMELINE, JobStage.REVIEWED_TIMELINE,
      JobStage.SUBTITLES, JobStage.GREEN_SCREEN, JobStage.VIDEO),
     True, ALL_ARTIFACTS, ROUNDS),
    (JobInputChange.ASR_CONFIGURATION, JobPhase.VOICE_READY,
     (JobStage.TRANSCRIPT, JobStage.CONTEXT, JobStage.UNDERSTANDING,
      JobStage.DRAFT_TIMELINE, JobStage.REVIEWED_TIMELINE, JobStage.SUBTITLES,
      JobStage.GREEN_SCREEN, JobStage.VIDEO),
     True, ALL_ARTIFACTS, ()),
    (JobInputChange.ROUND_BOUNDARY, JobPhase.TIMELINE_READY,
     (JobStage.TRANSCRIPT, JobStage.CONTEXT, JobStage.UNDERSTANDING,
      JobStage.DRAFT_TIMELINE, JobStage.REVIEWED_TIMELINE, JobStage.SUBTITLES,
      JobStage.GREEN_SCREEN, JobStage.VIDEO),
     True, ALL_ARTIFACTS, ROUNDS),
    (JobInputChange.DEMO_ASSET_IDENTITY, JobPhase.CREATED,
     (JobStage.DEMO_TIMELINE, JobStage.VOICE, JobStage.TRANSCRIPT,
      JobStage.CONTEXT, JobStage.UNDERSTANDING, JobStage.DRAFT_TIMELINE,
      JobStage.REVIEWED_TIMELINE, JobStage.SUBTITLES, JobStage.GREEN_SCREEN,
      JobStage.VIDEO),
     True, ALL_ARTIFACTS, ()),
    (JobInputChange.RENDER_CONFIGURATION, JobPhase.GREEN_SCREEN_RENDERED,
     (JobStage.VIDEO,), False, frozenset({FinalArtifactKind.VIDEO}), ()),
    (JobInputChange.POV_ADAPTER_UNAVAILABLE, JobPhase.GREEN_SCREEN_RENDERED,
     (JobStage.VIDEO,), False, frozenset({FinalArtifactKind.VIDEO}), ()),
)
MATRIX_IDS = [row[0].value for row in MATRIX]
SCOPED_CHANGES = (
    JobInputChange.REVIEW_DECISION, JobInputChange.TRANSLATION_CONFIGURATION,
    JobInputChange.KNOWLEDGE_REVISION, JobInputChange.ROUND_BOUNDARY,
)
GLOBAL_CHANGES = (
    JobInputChange.DISPLAY_METADATA, JobInputChange.SUBTITLE_LAYOUT,
    JobInputChange.ASR_CONFIGURATION, JobInputChange.DEMO_ASSET_IDENTITY,
    JobInputChange.RENDER_CONFIGURATION, JobInputChange.POV_ADAPTER_UNAVAILABLE,
)


def manifest():
    artifacts = tuple(
        FinalArtifactEntry(
            artifact_id=f"{kind.value}-{scope}", kind=kind,
            relative_path=f"final/{directory}/{scope}.{extension}",
            content_sha256="a" * 64, round_id=round_id,
            timebase=FinalArtifactTimebase.DEMO_GLOBAL,
        )
        for kind, directory, extension in (
            (FinalArtifactKind.TIMELINE, "timelines", "json"),
            (FinalArtifactKind.SUBTITLE, "subtitles", "srt"),
            (FinalArtifactKind.GREEN_SCREEN, "green_screen", "mov"),
            (FinalArtifactKind.VIDEO, "video", "mp4"),
        )
        for scope, round_id in (("match", None), ("round-001", "round-001"),
                                ("round-003", "round-003"))
    )
    return JobManifest(
        job_id="job-001", display_name="示例任务", created_at=CREATED_AT,
        updated_at=UPDATED_AT, demo_asset_id="b" * 64,
        demo_display_name="示例比赛", map_name="de_mirage", target_player_id="player-001",
        phase=JobPhase.COMPLETED_WITH_VIDEO, run_status=JobRunStatus.SUCCEEDED,
        round_progress=RoundProgressSummary(3, 2, 0, 1),
        configuration_snapshot_ids=("snapshot-old", "snapshot-current"),
        active_review_id="review-001", final_artifacts=artifacts,
    )


@pytest.mark.parametrize("change,phase,stages,clear,kinds,rounds", MATRIX, ids=MATRIX_IDS)
def test_exact_minimal_dependency_matrix(change, phase, stages, clear, kinds, rounds):
    result = plan_invalidation(InvalidationRequest(change, rounds))
    assert result.first_invalid_phase is phase
    assert result.invalid_stages == stages
    assert result.clear_active_review is clear
    assert result.remove_artifact_kinds == kinds
    assert result.round_ids == rounds
    assert type(result.invalid_stages) is tuple
    assert type(result.remove_artifact_kinds) is frozenset
    # Cleanup can only name final artifact references, never source/history files.
    assert result.remove_artifact_kinds <= ALL_ARTIFACTS


def test_matrix_covers_every_change_and_every_derived_stage():
    assert {row[0] for row in MATRIX} == set(JobInputChange)
    assert {stage for row in MATRIX for stage in row[2]} == set(JobStage)


@pytest.mark.parametrize("change", SCOPED_CHANGES)
@pytest.mark.parametrize("rounds", [(), ("round-001", "round-001")])
def test_round_scoped_requests_reject_empty_or_duplicate_ids(change, rounds):
    with pytest.raises(DomainSchemaError) as exc:
        InvalidationRequest(change, rounds)
    assert exc.value.code == "domain_field_invalid"
    assert exc.value.path == "invalidation_request.round_ids"


@pytest.mark.parametrize("change", GLOBAL_CHANGES)
def test_global_changes_reject_round_scope(change):
    with pytest.raises(DomainSchemaError) as exc:
        InvalidationRequest(change, ROUNDS)
    assert exc.value.path == "invalidation_request.round_ids"


@pytest.mark.parametrize("bad_id", [
    "", "Round-001", "round.001", "round-001 ", "round-001.", "../round-001",
    "round/001", "round\\001", "con", "nul", "lpt1", "回合", "x" * 65,
    None, True, 1, ["round-001"],
])
def test_round_scope_uses_strict_path_identifiers(bad_id):
    with pytest.raises(DomainSchemaError) as exc:
        InvalidationRequest(JobInputChange.REVIEW_DECISION, (bad_id,))
    assert exc.value.code == "domain_identifier_invalid"
    assert exc.value.path == "invalidation_request.round_ids[0]"


def test_plan_canonicalizes_round_scope_without_imposing_display_number_format():
    expected = ("overtime_a", "round-001", "x" * 64)
    plans = [
        plan_invalidation(InvalidationRequest(JobInputChange.ROUND_BOUNDARY, order))
        for order in permutations(expected)
    ]
    assert all(plan.round_ids == expected for plan in plans)
    assert len(set(plans)) == 1


@pytest.mark.parametrize("bad_change", ["review_decision", JobStage.VIDEO, None, True, {}])
def test_request_requires_typed_change(bad_change):
    with pytest.raises(DomainSchemaError) as exc:
        InvalidationRequest(bad_change, ROUNDS)
    assert exc.value.path == "invalidation_request.change"


@pytest.mark.parametrize("rounds", [[], ["round-001"], {"round-001"},
                                      frozenset({"round-001"}), "round-001", None])
def test_request_rejects_mutable_or_untyped_round_collections(rounds):
    with pytest.raises(DomainSchemaError) as exc:
        InvalidationRequest(JobInputChange.REVIEW_DECISION, rounds)
    assert exc.value.path == "invalidation_request.round_ids"


@pytest.mark.parametrize("bad_request", [None, "review_decision", {"change": "review_decision"}])
def test_planner_rejects_untyped_requests(bad_request):
    with pytest.raises(DomainSchemaError) as exc:
        plan_invalidation(bad_request)
    assert exc.value.path == "invalidation_request"


def test_requests_and_plans_are_immutable():
    request = InvalidationRequest(JobInputChange.TRANSLATION_CONFIGURATION, ROUNDS)
    plan = plan_invalidation(request)
    with pytest.raises(FrozenInstanceError):
        request.round_ids = ()
    with pytest.raises(FrozenInstanceError):
        plan.clear_active_review = False
    assert not hasattr(request, "__dict__")
    assert not hasattr(plan, "__dict__")


@pytest.mark.parametrize("changes", [
    {"first_invalid_phase": "context_ready"},
    {"first_invalid_phase": JobPhase.GREEN_SCREEN_RENDERED},
    {"invalid_stages": [JobStage.VIDEO]},
    {"invalid_stages": ("understanding",)},
    {"invalid_stages": ()},
    {"invalid_stages": (JobStage.VIDEO,)},
    {"round_ids": ["round-001"]},
    {"round_ids": ()},
    {"round_ids": ("round-001", "round-001")},
    {"round_ids": ("Round-001",)},
    {"clear_active_review": False},
    {"clear_active_review": 1},
    {"remove_artifact_kinds": set(ALL_ARTIFACTS)},
    {"remove_artifact_kinds": frozenset(kind.value for kind in ALL_ARTIFACTS)},
    {"remove_artifact_kinds": EXPORT_ARTIFACTS},
    {"remove_artifact_kinds": frozenset()},
])
def test_direct_plan_construction_cannot_bypass_dependency_contract(changes):
    valid = plan_invalidation(
        InvalidationRequest(JobInputChange.TRANSLATION_CONFIGURATION, ROUNDS)
    )
    with pytest.raises(DomainSchemaError):
        replace(valid, **changes)


def test_plan_rejects_reordered_or_duplicate_stages_and_scoped_global_cleanup():
    plan = plan_invalidation(InvalidationRequest(JobInputChange.SUBTITLE_LAYOUT))
    for stages in (tuple(reversed(plan.invalid_stages)), plan.invalid_stages * 2):
        with pytest.raises(DomainSchemaError):
            replace(plan, invalid_stages=stages)
    with pytest.raises(DomainSchemaError):
        replace(plan, round_ids=ROUNDS)


@pytest.mark.parametrize("change,phase,stages,clear,kinds,rounds", MATRIX, ids=MATRIX_IDS)
def test_rewind_removes_exact_manifest_authority_and_preserves_history(
    change, phase, stages, clear, kinds, rounds,
):
    original = manifest()
    before = original.to_dict()
    fingerprint = original.content_fingerprint()
    result = rewind_job_phase_for_invalidation(
        original, plan_invalidation(InvalidationRequest(change, rounds)), at=REWOUND_AT,
    )
    expected = dict(before)
    expected.update(
        phase=phase.value, updated_at=REWOUND_AT,
        run_status="pending" if phase is JobPhase.CREATED else "succeeded",
        active_review_id=None if clear else "review-001",
        final_artifacts=[a for a in before["final_artifacts"]
                         if FinalArtifactKind(a["kind"]) not in kinds],
    )
    assert result.to_dict() == expected
    assert result is not original
    assert original.to_dict() == before
    assert original.content_fingerprint() == fingerprint
    assert len(original.final_artifacts) == 12
    assert result.configuration_snapshot_ids == original.configuration_snapshot_ids
    assert result.round_progress is original.round_progress
    assert JobManifest.from_dict(result.to_dict()) == result


@pytest.mark.parametrize("status", list(JobRunStatus))
def test_rewind_resets_previous_run_outcome_to_destination_checkpoint_status(status):
    original = replace(manifest(), run_status=status)
    plan = plan_invalidation(
        InvalidationRequest(JobInputChange.TRANSLATION_CONFIGURATION, ROUNDS)
    )
    result = rewind_job_phase_for_invalidation(original, plan, at=REWOUND_AT)
    assert result.run_status is JobRunStatus.SUCCEEDED
    assert result.phase is JobPhase.CONTEXT_READY


@pytest.mark.parametrize("change,phase,stages,clear,kinds,rounds", MATRIX, ids=MATRIX_IDS)
def test_invalidation_can_reapply_at_same_checkpoint_with_new_timestamp(
    change, phase, stages, clear, kinds, rounds,
):
    plan = plan_invalidation(InvalidationRequest(change, rounds))
    first = rewind_job_phase_for_invalidation(manifest(), plan, at=REWOUND_AT)
    second = rewind_job_phase_for_invalidation(
        first, plan, at="2026-09-03T01:02:04.000002Z",
    )
    assert second == replace(first, updated_at="2026-09-03T01:02:04.000002Z")


# Each tuple is one real branch of the approved phase graph, not Enum order.
COMMON_PHASES = (
    JobPhase.CREATED, JobPhase.TIMELINE_READY, JobPhase.VOICE_READY,
    JobPhase.TRANSCRIBED, JobPhase.CONTEXT_READY, JobPhase.UNDERSTANDING_TRANSLATING,
    JobPhase.UNDERSTOOD_TRANSLATED, JobPhase.DRAFT_TIMELINE_READY,
)
REVIEW_PHASES = COMMON_PHASES + (
    JobPhase.REVIEW_PENDING, JobPhase.REVIEWED, JobPhase.FINAL_TIMELINE_READY,
    JobPhase.SUBTITLES_EXPORTED, JobPhase.GREEN_SCREEN_RENDERED,
)
PHASE_BRANCHES = (
    COMMON_PHASES + (JobPhase.COMPLETED_DRAFT,),
    REVIEW_PHASES + (JobPhase.COMPLETED_WITHOUT_VIDEO,),
    REVIEW_PHASES + (JobPhase.READY_FOR_RENDER, JobPhase.RENDERING,
                     JobPhase.VIDEO_READY, JobPhase.COMPLETED_WITH_VIDEO),
)


@pytest.mark.parametrize("source", list(JobPhase))
@pytest.mark.parametrize("change,phase,stages,clear,kinds,rounds", MATRIX, ids=MATRIX_IDS)
def test_rewind_never_advances_or_crosses_an_unreached_branch(
    source, change, phase, stages, clear, kinds, rounds,
):
    original = replace(manifest(), phase=source)
    plan = plan_invalidation(InvalidationRequest(change, rounds))
    reachable = any(
        source in branch and phase in branch and branch.index(phase) <= branch.index(source)
        for branch in PHASE_BRANCHES
    )
    if reachable:
        result = rewind_job_phase_for_invalidation(original, plan, at=REWOUND_AT)
        assert result.phase is phase
    else:
        with pytest.raises(DomainSchemaError) as exc:
            rewind_job_phase_for_invalidation(original, plan, at=REWOUND_AT)
        assert exc.value.code == "domain_state_transition_invalid"
        assert exc.value.path == "job_manifest.phase"


@pytest.mark.parametrize("change", [JobInputChange.DISPLAY_METADATA,
                                    JobInputChange.SUBTITLE_LAYOUT,
                                    JobInputChange.RENDER_CONFIGURATION,
                                    JobInputChange.POV_ADAPTER_UNAVAILABLE])
def test_rewind_cannot_claim_reviewed_checkpoint_without_active_review(change):
    original = replace(manifest(), active_review_id=None)
    with pytest.raises(DomainSchemaError) as exc:
        rewind_job_phase_for_invalidation(
            original, plan_invalidation(InvalidationRequest(change)), at=REWOUND_AT,
        )
    assert exc.value.code == "domain_state_transition_invalid"


def test_draft_terminal_can_rewind_for_translation_without_review():
    original = replace(manifest(), phase=JobPhase.COMPLETED_DRAFT,
                       active_review_id=None, final_artifacts=())
    result = rewind_job_phase_for_invalidation(
        original,
        plan_invalidation(InvalidationRequest(JobInputChange.KNOWLEDGE_REVISION, ROUNDS)),
        at=REWOUND_AT,
    )
    assert result.phase is JobPhase.CONTEXT_READY
    assert result.active_review_id is None


@pytest.mark.parametrize("at", [
    CREATED_AT, UPDATED_AT, "2026-09-03T01:02:03.999999Z",
    "2026-09-03T01:02:05Z", "2026-09-03T01:02:05.00000Z",
    "2026-09-03T01:02:05.0000000Z", "2026-09-03T01:02:05.000000+00:00",
    "2026-09-03T09:02:05.000000+08:00", "2026-09-03 01:02:05.000000Z",
    "2026-09-03T01:02:05.000000Z ", "2026-02-30T01:02:05.000000Z",
    None, True, 1,
])
def test_rewind_requires_strictly_newer_canonical_utc_timestamp(at):
    original = manifest()
    with pytest.raises(DomainSchemaError) as exc:
        rewind_job_phase_for_invalidation(
            original, plan_invalidation(InvalidationRequest(JobInputChange.SUBTITLE_LAYOUT)),
            at=at,
        )
    assert exc.value.code == "domain_field_invalid"
    assert exc.value.path == "at"
    assert original.updated_at == UPDATED_AT


@pytest.mark.parametrize("value", [None, {}, "manifest"])
def test_rewind_rejects_untyped_manifest(value):
    with pytest.raises(DomainSchemaError) as exc:
        rewind_job_phase_for_invalidation(
            value, plan_invalidation(InvalidationRequest(JobInputChange.SUBTITLE_LAYOUT)),
            at=REWOUND_AT,
        )
    assert exc.value.path == "job_manifest"


@pytest.mark.parametrize("value", [None, {}, InvalidationRequest(JobInputChange.SUBTITLE_LAYOUT)])
def test_rewind_rejects_untyped_plan(value):
    with pytest.raises(DomainSchemaError) as exc:
        rewind_job_phase_for_invalidation(manifest(), value, at=REWOUND_AT)
    assert exc.value.path == "invalidation_plan"


def test_direct_valid_plan_normalizes_scope_and_has_same_rewind_behavior():
    plan = InvalidationPlan(
        JobPhase.DRAFT_TIMELINE_READY,
        (JobStage.REVIEWED_TIMELINE, JobStage.SUBTITLES, JobStage.GREEN_SCREEN,
         JobStage.VIDEO),
        tuple(reversed(ROUNDS)), True, ALL_ARTIFACTS,
    )
    assert plan.round_ids == ROUNDS
    result = rewind_job_phase_for_invalidation(manifest(), plan, at=REWOUND_AT)
    assert result.phase is JobPhase.DRAFT_TIMELINE_READY
    assert result.active_review_id is None
    assert result.final_artifacts == ()
