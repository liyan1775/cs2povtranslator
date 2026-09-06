"""Replay a fixed three-round lifecycle exclusively through production policy."""

# Standalone checkout execution requires bootstrapping src before domain imports.
# ruff: noqa: E402

from __future__ import annotations

import json
import sys
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from cs2pov.domain.errors import DomainSchemaError
from cs2pov.domain.invalidation import (
    InvalidationRequest,
    JobInputChange,
    plan_invalidation,
    rewind_job_phase_for_invalidation,
)
from cs2pov.domain.job import (
    FinalArtifactEntry,
    FinalArtifactKind,
    FinalArtifactTimebase,
    JobManifest,
    JobPhase as P,
    JobRunStatus,
    RoundProgressSummary,
)
from cs2pov.domain.job_state import (
    advance_job_phase,
    derive_round_progress,
    derive_translation_run_status,
)
from cs2pov.domain.job_task_state import (
    cancel_task,
    reset_task,
    retry_task,
    start_task,
    succeed_task,
    supersede_task,
)
from cs2pov.domain.job_tasks import (
    RetryPolicy,
    RoundTaskError,
    RoundTaskSpec,
    RoundTranslationTask,
)
from cs2pov.domain.schema import (
    reject_private_data,
    require_current_schema,
    require_exact_keys,
    require_mapping,
)

FIXTURE = ROOT / "tests/golden/fixtures/new_job_state_v1.json"


def _timestamp(second):
    return f"2026-09-05T00:00:{second:02d}.000000Z"


def _roundtrip(task):
    restored = RoundTranslationTask.from_dict(json.loads(json.dumps(task.to_dict())))
    if restored != task or restored.content_fingerprint() != task.content_fingerprint():
        raise ValueError("Round trip mismatch")
    return restored


def replay_story(payload):
    require_mapping(payload, "fixture")
    require_current_schema(payload, "fixture")
    require_exact_keys(
        payload,
        {"schema_version", "fixture_id", "rounds", "expected"},
        set(),
        "fixture",
    )
    reject_private_data(payload, "fixture")
    if payload["fixture_id"] != "new-job-state-v1":
        raise ValueError("Fixture identity mismatch")
    rounds = payload["rounds"]
    if not isinstance(rounds, list) or len(rounds) != 3:
        raise ValueError("Three rounds required")
    tasks, results = {}, {}
    for row in rounds:
        require_mapping(row, "round")
        require_exact_keys(
            row, {"round_id", "input_fingerprint", "result_fingerprint"}, set(), "round"
        )
        identity = row["round_id"]
        if identity in tasks:
            raise ValueError("Duplicate round")
        tasks[identity] = _roundtrip(
            RoundTranslationTask.pending(
                task_id=identity,
                round_id=identity,
                input_fingerprint=row["input_fingerprint"],
                configuration_snapshot_id="snapshot-balanced",
                updated_at=_timestamp(0),
            )
        )
        results[identity] = row["result_fingerprint"]
    canonical_order = list(tasks)
    if canonical_order != ["round-001", "round-002", "round-003"]:
        raise ValueError("Round order mismatch")
    fingerprints = {}

    def update(identity, task):
        tasks[identity] = _roundtrip(task)
        fingerprints[f"{identity}:{task.updated_at}"] = task.content_fingerprint()

    for identity, task in tuple(tasks.items()):
        update(
            identity, start_task(task, attempt_id=f"{identity}-try-1", at=_timestamp(1))
        )
    update(
        "round-002",
        succeed_task(
            tasks["round-002"],
            at=_timestamp(2),
            result_fingerprint=results["round-002"],
        ),
    )
    update(
        "round-001",
        retry_task(
            tasks["round-001"],
            at=_timestamp(3),
            error=RoundTaskError(
                "provider_busy",
                "服务繁忙。",
                "本回合未完成。",
                "请稍后重试。",
                True,
                2_000_000,
            ),
            policy=RetryPolicy(3, 1_000_000, 8_000_000),
        ),
    )
    retry_at = tasks["round-001"].next_retry_at
    update("round-003", cancel_task(tasks["round-003"], at=_timestamp(4)))
    update(
        "round-001",
        start_task(tasks["round-001"], attempt_id="round-001-try-2", at=retry_at),
    )
    update(
        "round-001",
        succeed_task(
            tasks["round-001"],
            at=_timestamp(6),
            result_fingerprint=results["round-001"],
        ),
    )
    update("round-003", reset_task(tasks["round-003"], at=_timestamp(7)))
    update(
        "round-003",
        start_task(tasks["round-003"], attempt_id="round-003-try-2", at=_timestamp(8)),
    )
    update(
        "round-003",
        succeed_task(
            tasks["round-003"],
            at=_timestamp(9),
            result_fingerprint=results["round-003"],
        ),
    )
    progress = derive_round_progress(tasks.values())
    # Simulated completion delivery differs from authoritative round order.
    completion_order = ["round-002", "round-001", "round-003"]
    delivered = {identity: tasks[identity] for identity in completion_order}
    if derive_round_progress(delivered.values()) != progress:
        raise ValueError("Completion-order dependent progress")
    manifest = JobManifest(
        "job-state-replay",
        "回合状态回放",
        _timestamp(0),
        _timestamp(0),
        "a" * 64,
        "synthetic.dem",
        None,
        None,
        P.CREATED,
        JobRunStatus.PENDING,
        RoundProgressSummary(3, 0, 0, 0),
        ("snapshot-balanced",),
        None,
        (),
    )
    for index, phase in enumerate(
        [
            P.TIMELINE_READY,
            P.VOICE_READY,
            P.TRANSCRIBED,
            P.CONTEXT_READY,
            P.UNDERSTANDING_TRANSLATING,
            P.UNDERSTOOD_TRANSLATED,
            P.DRAFT_TIMELINE_READY,
        ],
        10,
    ):
        manifest = advance_job_phase(manifest, phase, at=_timestamp(index))
    manifest = replace(manifest, round_progress=progress)
    draft = advance_job_phase(manifest, P.COMPLETED_DRAFT, at=_timestamp(17))
    review_pending = advance_job_phase(manifest, P.REVIEW_PENDING, at=_timestamp(17))
    try:
        advance_job_phase(review_pending, P.REVIEWED, at=_timestamp(18))
    except DomainSchemaError:
        review_gate_rejected = True
    else:
        raise ValueError("Missing review gate")
    reviewed = advance_job_phase(
        replace(review_pending, active_review_id="review-001"),
        P.REVIEWED,
        at=_timestamp(18),
    )
    final = advance_job_phase(reviewed, P.FINAL_TIMELINE_READY, at=_timestamp(19))
    completed = final
    for index, phase in enumerate(
        [
            P.SUBTITLES_EXPORTED,
            P.GREEN_SCREEN_RENDERED,
            P.READY_FOR_RENDER,
            P.RENDERING,
            P.VIDEO_READY,
            P.COMPLETED_WITH_VIDEO,
        ],
        20,
    ):
        completed = advance_job_phase(completed, phase, at=_timestamp(index))
    completed = replace(
        completed,
        final_artifacts=(
            FinalArtifactEntry(
                "timeline-reviewed-001",
                FinalArtifactKind.TIMELINE,
                "final/timelines/reviewed.json",
                "a" * 64,
                None,
                FinalArtifactTimebase.DEMO_GLOBAL,
            ),
            FinalArtifactEntry(
                "subtitle-final-001",
                FinalArtifactKind.SUBTITLE,
                "final/subtitles/bilingual.srt",
                "b" * 64,
                None,
                FinalArtifactTimebase.DEMO_GLOBAL,
            ),
            FinalArtifactEntry(
                "green-screen-final-001",
                FinalArtifactKind.GREEN_SCREEN,
                "final/green_screen/overlay.mov",
                "c" * 64,
                None,
                FinalArtifactTimebase.DEMO_GLOBAL,
            ),
            FinalArtifactEntry(
                "video-final-001",
                FinalArtifactKind.VIDEO,
                "final/video/complete.mp4",
                "d" * 64,
                None,
                FinalArtifactTimebase.DEMO_GLOBAL,
            ),
        ),
    )
    plan = plan_invalidation(
        InvalidationRequest(
            JobInputChange.TRANSLATION_CONFIGURATION,
            ("round-002",),
        )
    )
    render_only = rewind_job_phase_for_invalidation(
        completed,
        plan_invalidation(InvalidationRequest(JobInputChange.RENDER_CONFIGURATION)),
        at=_timestamp(26),
    )
    if render_only.phase is not P.GREEN_SCREEN_RENDERED:
        raise ValueError("Render-only invalidation phase mismatch")
    if render_only.active_review_id != "review-001":
        raise ValueError("Render-only invalidation cleared review")
    if tuple(artifact.kind for artifact in render_only.final_artifacts) != (
        FinalArtifactKind.TIMELINE,
        FinalArtifactKind.SUBTITLE,
        FinalArtifactKind.GREEN_SCREEN,
    ):
        raise ValueError("Render-only invalidation artifact cleanup mismatch")
    rewound = rewind_job_phase_for_invalidation(completed, plan, at=_timestamp(27))
    if rewound.phase is not P.CONTEXT_READY:
        raise ValueError("Rewind phase mismatch")
    if rewound.active_review_id is not None:
        raise ValueError("Rewind retained active review")
    if rewound.final_artifacts:
        raise ValueError("Rewind artifact cleanup mismatch")
    unaffected = {key: value for key, value in tasks.items() if key != "round-002"}
    update(
        "round-002",
        supersede_task(
            tasks["round-002"],
            spec=RoundTaskSpec("round-002", "round-002", "e" * 64, "snapshot-new"),
            at=_timestamp(21),
        ),
    )
    if any(tasks[key] != value for key, value in unaffected.items()):
        raise ValueError("Unrelated task invalidated")
    return {
        "completion_order": completion_order,
        "aggregate_order": [
            delivered[identity].round_id for identity in canonical_order
        ],
        "progress_before_invalidation": progress.to_dict(),
        "progress_after_invalidation": derive_round_progress(tasks.values()).to_dict(),
        "run_status_after_invalidation": derive_translation_run_status(
            tasks.values()
        ).value,
        "retry_at": retry_at,
        "draft_phase": draft.phase.value,
        "review_gate_rejected": review_gate_rejected,
        "reviewed_phase": final.phase.value,
        "completed_branch_phase": completed.phase.value,
        "rewound_phase": rewound.phase.value,
        "rewound_active_review": rewound.active_review_id,
        "rewound_artifact_kinds": [
            artifact.kind.value for artifact in rewound.final_artifacts
        ],
        "render_only_rewound_phase": render_only.phase.value,
        "render_only_active_review": render_only.active_review_id,
        "render_only_artifact_kinds": [
            artifact.kind.value for artifact in render_only.final_artifacts
        ],
        "transition_fingerprints": fingerprints,
        "final_tasks": [tasks[identity].to_dict() for identity in canonical_order],
    }


def _unique_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON key")
        result[key] = value
    return result


def validate_contract(path=FIXTURE):
    payload = json.loads(
        Path(path).read_text(encoding="utf-8"), object_pairs_hook=_unique_pairs
    )
    actual = replay_story(payload)
    if actual != payload["expected"]:
        raise ValueError("Replay expectation mismatch")


def main():
    try:
        if len(sys.argv) > 2:
            raise ValueError("Unexpected arguments")
        validate_contract(Path(sys.argv[1]) if len(sys.argv) == 2 else FIXTURE)
    except (ValueError, TypeError, KeyError, OSError):
        print("new job state replay failed", file=sys.stderr)
        return 1
    print("new job state replay passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
