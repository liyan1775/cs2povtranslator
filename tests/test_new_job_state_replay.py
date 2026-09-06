import json
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

import pytest

import scripts.check_new_job_state as replay

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "check_new_job_state.py"
FIXTURE = ROOT / "tests" / "golden" / "fixtures" / "new_job_state_v1.json"


def run_replay(path=FIXTURE):
    return subprocess.run(
        [sys.executable, str(SCRIPT), str(path)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=30,
    )


def test_new_job_state_replays_in_fresh_process():
    result = run_replay()
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout == "new job state replay passed\n"
    assert result.stderr == ""


def test_static_expected_story_matches_approved_semantics():
    expected = json.loads(FIXTURE.read_text(encoding="utf-8"))["expected"]
    assert expected["aggregate_order"] == ["round-001", "round-002", "round-003"]
    assert expected["completion_order"] == ["round-002", "round-001", "round-003"]
    assert expected["progress_before_invalidation"] == dict(
        total=3, succeeded=3, failed=0, review_pending=0
    )
    assert expected["progress_after_invalidation"] == dict(
        total=3, succeeded=2, failed=0, review_pending=0
    )
    assert expected["rewound_phase"] == "context_ready"
    assert expected["rewound_active_review"] is None
    assert expected["run_status_after_invalidation"] == "pending"
    assert expected["draft_phase"] == "completed_draft"
    assert expected["reviewed_phase"] == "final_timeline_ready"
    assert expected["completed_branch_phase"] == "completed_with_video"
    assert expected["review_gate_rejected"]
    assert expected["retry_at"] == "2026-09-05T00:00:05.000000Z"
    assert expected["rewound_artifact_kinds"] == []
    assert expected["render_only_rewound_phase"] == "green_screen_rendered"
    assert expected["render_only_active_review"] == "review-001"
    assert expected["render_only_artifact_kinds"] == [
        "timeline",
        "subtitle",
        "green_screen",
    ]
    assert [
        [attempt["status"] for attempt in task["attempts"]]
        for task in expected["final_tasks"]
    ] == [
        ["retryable_failed", "succeeded"],
        ["succeeded"],
        ["cancelled", "succeeded"],
    ]
    assert [task["status"] for task in expected["final_tasks"]] == [
        "succeeded",
        "pending",
        "succeeded",
    ]


@pytest.mark.parametrize(
    "mutation", ["unknown", "tampered_result", "duplicate_round", "wrong_order"]
)
def test_replay_rejects_contract_changes(tmp_path, mutation):
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    if mutation == "unknown":
        data["unknown"] = True
    elif mutation == "tampered_result":
        data["rounds"][1]["result_fingerprint"] = "0" * 64
    elif mutation == "duplicate_round":
        data["rounds"][1]["round_id"] = data["rounds"][0]["round_id"]
    else:
        data["expected"]["aggregate_order"].reverse()
    path = tmp_path / "broken.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    result = run_replay(path)
    assert result.returncode == 1
    assert result.stdout == ""
    assert result.stderr == "new job state replay failed\n"


def test_replay_rejects_duplicate_json_keys(tmp_path):
    path = tmp_path / "duplicate.json"
    raw = FIXTURE.read_text(encoding="utf-8").replace(
        '"schema_version": 1', '"schema_version": 1, "schema_version": 1', 1
    )
    path.write_text(raw, encoding="utf-8")
    result = run_replay(path)
    assert result.returncode == 1
    assert result.stderr == "new job state replay failed\n"


def test_replay_rejects_rewind_that_retains_stale_artifacts(monkeypatch):
    original_rewind = replay.rewind_job_phase_for_invalidation

    def retain_stale_artifacts(manifest, plan, *, at):
        rewound = original_rewind(manifest, plan, at=at)
        return replace(rewound, final_artifacts=manifest.final_artifacts)

    monkeypatch.setattr(
        replay, "rewind_job_phase_for_invalidation", retain_stale_artifacts
    )

    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    with pytest.raises(ValueError, match="artifact cleanup mismatch"):
        replay.replay_story(payload)
