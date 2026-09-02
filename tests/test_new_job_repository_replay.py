from __future__ import annotations

import copy
import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable

import pytest

import scripts.check_new_job_repository as replay
from scripts.check_new_job_repository import ContractValidationError, validate_contract


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests/golden/fixtures/new_job_repository_v1.json"


def test_new_job_repository_replays_in_fresh_day_one_and_day_two_processes() -> None:
    result = subprocess.run(
        [sys.executable, "scripts/check_new_job_repository.py"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
        timeout=60,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.strip() == "new job repository replay passed"
    assert result.stderr == ""


def _manifest_identity(payload: dict[str, Any]) -> None:
    payload["job"]["manifest"]["job_id"] = "job-other"


def _source_identity(payload: dict[str, Any]) -> None:
    payload["job"]["source"]["asset_id"] = "0" * 64


def _unsupported_schema(payload: dict[str, Any]) -> None:
    payload["schema_version"] = 2


def _backwards_timestamp(payload: dict[str, Any]) -> None:
    payload["job"]["manifest"]["updated_at"] = "2026-08-31T00:00:00.000000Z"


def _wrong_phase(payload: dict[str, Any]) -> None:
    payload["job"]["manifest"]["phase"] = "created"


def _wrong_status(payload: dict[str, Any]) -> None:
    payload["job"]["manifest"]["run_status"] = "pending"


def _wrong_progress(payload: dict[str, Any]) -> None:
    payload["job"]["manifest"]["round_progress"]["succeeded"] = 2


def _wrong_artifact_path(payload: dict[str, Any]) -> None:
    payload["job"]["manifest"]["final_artifacts"][0]["relative_path"] = (
        "final/subtitles/other.srt"
    )


def _wrong_artifact_hash(payload: dict[str, Any]) -> None:
    payload["job"]["manifest"]["final_artifacts"][0]["content_sha256"] = "0" * 64


def _directory_manifest_mismatch(payload: dict[str, Any]) -> None:
    payload["expected"]["healthy_job_id"] = "job-other"


def _round_filename_mismatch(payload: dict[str, Any]) -> None:
    files = payload["expected"]["durable_files"]
    item = next(
        value
        for value in files
        if value["logical_path"] == "transcript/round_round-001.jsonl"
    )
    item["logical_path"] = "transcript/round_round-002.jsonl"


def _missing_shard(payload: dict[str, Any]) -> None:
    payload["expected"]["durable_files"] = [
        value
        for value in payload["expected"]["durable_files"]
        if value["logical_path"] != "understanding/round_round-003.json"
    ]


def _malformed_shard_hash(payload: dict[str, Any]) -> None:
    item = payload["expected"]["durable_files"][0]
    item["sha256"] = "f" * 64


def _tail_classification(payload: dict[str, Any]) -> None:
    payload["expected"]["event_incomplete_tail"] = True


def _claim_owner(payload: dict[str, Any]) -> None:
    payload["claims"]["primary_run_id"] = "run-not-primary"


def _claim_expiry(payload: dict[str, Any]) -> None:
    payload["claims"]["lease_us"] = 0


def _model_closure(payload: dict[str, Any]) -> None:
    payload["expected"]["invocation_ids"].append("invoke-missing")


def _review_closure(payload: dict[str, Any]) -> None:
    payload["expected"]["active_review_id"] = "review-missing"


def _domain_closure(payload: dict[str, Any]) -> None:
    payload["expected"]["round_ids"].reverse()


def _current_damage_semantics(payload: dict[str, Any]) -> None:
    payload["siblings"]["corrupt"]["marker_present"] = False


def _legacy_ignore_semantics(payload: dict[str, Any]) -> None:
    payload["siblings"]["legacy"]["marker_present"] = True


def _private_value(payload: dict[str, Any]) -> None:
    payload["job"]["display_name"] = r"C:\private\history.dem"


TAMPERS: tuple[Callable[[dict[str, Any]], None], ...] = (
    _manifest_identity,
    _source_identity,
    _unsupported_schema,
    _backwards_timestamp,
    _wrong_phase,
    _wrong_status,
    _wrong_progress,
    _wrong_artifact_path,
    _wrong_artifact_hash,
    _directory_manifest_mismatch,
    _round_filename_mismatch,
    _missing_shard,
    _malformed_shard_hash,
    _tail_classification,
    _claim_owner,
    _claim_expiry,
    _model_closure,
    _review_closure,
    _domain_closure,
    _current_damage_semantics,
    _legacy_ignore_semantics,
    _private_value,
)


@pytest.mark.parametrize("mutate", TAMPERS, ids=lambda item: item.__name__)
def test_repository_contract_tampering_is_rejected(
    tmp_path: Path,
    mutate: Callable[[dict[str, Any]], None],
) -> None:
    payload = copy.deepcopy(json.loads(FIXTURE.read_text(encoding="utf-8")))
    mutate(payload)
    tampered = tmp_path / "tampered.json"
    tampered.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(ContractValidationError):
        validate_contract(tampered)


def test_repository_contract_rejects_duplicate_json_keys(tmp_path: Path) -> None:
    duplicate = tmp_path / "duplicate.json"
    duplicate.write_text(
        '{"schema_version": 1, "schema_version": 1}\n', encoding="utf-8"
    )

    with pytest.raises(ContractValidationError):
        validate_contract(duplicate)


def test_repository_contract_rejects_malformed_json(tmp_path: Path) -> None:
    malformed = tmp_path / "malformed.json"
    malformed.write_text('{"schema_version": 1,\n', encoding="utf-8")

    with pytest.raises(ContractValidationError):
        validate_contract(malformed)


def test_contract_validation_normalizes_expected_value_errors(monkeypatch) -> None:
    def raise_expected_error(payload: dict[str, Any], fixture: Path) -> None:
        raise ValueError("malformed input")

    monkeypatch.setattr(replay, "_validate_payload", raise_expected_error)

    with pytest.raises(ContractValidationError):
        validate_contract(FIXTURE)


def test_contract_validation_does_not_swallow_unexpected_runtime_errors(
    monkeypatch,
) -> None:
    def raise_programming_error(payload: dict[str, Any], fixture: Path) -> None:
        raise RuntimeError("programming defect")

    monkeypatch.setattr(replay, "_validate_payload", raise_programming_error)

    with pytest.raises(RuntimeError, match="programming defect"):
        validate_contract(FIXTURE)


def test_cli_normalizes_contract_errors_without_traceback(tmp_path: Path) -> None:
    malformed = tmp_path / "malformed.json"
    malformed.write_text('{"schema_version": 1,\n', encoding="utf-8")
    result = subprocess.run(
        [sys.executable, "scripts/check_new_job_repository.py", str(malformed)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
        timeout=30,
    )

    assert result.returncode == 1
    assert result.stdout == ""
    assert result.stderr == "new job repository replay failed\n"
