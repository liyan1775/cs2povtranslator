from __future__ import annotations

import copy
import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable

import pytest

from scripts.check_new_domain_contract import ContractValidationError, validate_contract


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "golden" / "fixtures" / "new_domain_contract_v1.json"


def test_new_domain_contract_replays_in_a_fresh_python_process() -> None:
    result = subprocess.run(
        [sys.executable, "scripts/check_new_domain_contract.py"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.strip() == "new domain contract replay passed"
    assert result.stderr == ""


def _secret(payload: dict[str, Any]) -> None:
    payload["model_configurations"][0]["api_key"] = "private"


def _windows_path(payload: dict[str, Any]) -> None:
    payload["demo"]["server_name"] = r"C:\private\demo.dem"


def _unix_path(payload: dict[str, Any]) -> None:
    payload["demo"]["server_name"] = "/home/private/demo.dem"


def _unc_path(payload: dict[str, Any]) -> None:
    payload["demo"]["server_name"] = r"\\server\share\demo.dem"


def _unknown_player(payload: dict[str, Any]) -> None:
    payload["transcript_cues"][0]["player_id"] = "player-missing"


def _dangling_invocation(payload: dict[str, Any]) -> None:
    payload["transcript_cues"][0]["asr_invocation_record_id"] = "asr-call-missing"


def _changed_asr(payload: dict[str, Any]) -> None:
    payload["round_understanding"][1]["results"][0]["asr_original"] = "B B B"


def _stale_review_fingerprint(payload: dict[str, Any]) -> None:
    payload["review_decisions"][0]["source_result_fingerprint"] = "0" * 64


def _stale_draft_input_fingerprint(payload: dict[str, Any]) -> None:
    payload["draft_timeline"]["input_fingerprint"] = "0" * 64


def _stale_configuration_fingerprint(payload: dict[str, Any]) -> None:
    payload["model_configurations"][1]["model_name"] = "tampered-model"


def _unsupported_schema(payload: dict[str, Any]) -> None:
    payload["schema_version"] = 2


def _reversed_cues(payload: dict[str, Any]) -> None:
    payload["draft_timeline"]["cues"].reverse()


def _overlapping_anchor_sources(payload: dict[str, Any]) -> None:
    payload["time_anchors"][2]["source_start"] = 12_000


TAMPERS: tuple[Callable[[dict[str, Any]], None], ...] = (
    _secret,
    _windows_path,
    _unix_path,
    _unc_path,
    _unknown_player,
    _dangling_invocation,
    _changed_asr,
    _stale_review_fingerprint,
    _stale_draft_input_fingerprint,
    _stale_configuration_fingerprint,
    _unsupported_schema,
    _reversed_cues,
    _overlapping_anchor_sources,
)


@pytest.mark.parametrize("mutate", TAMPERS, ids=lambda item: item.__name__)
def test_contract_tampering_is_rejected(
    tmp_path: Path,
    mutate: Callable[[dict[str, Any]], None],
) -> None:
    payload = copy.deepcopy(json.loads(FIXTURE.read_text(encoding="utf-8")))
    mutate(payload)
    tampered = tmp_path / "tampered.json"
    tampered.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    with pytest.raises(ContractValidationError):
        validate_contract(tampered)


def test_contract_rejects_duplicate_json_keys(tmp_path: Path) -> None:
    duplicate = tmp_path / "duplicate.json"
    duplicate.write_text('{"schema_version": 1, "schema_version": 1}\n', encoding="utf-8")

    with pytest.raises(ContractValidationError):
        validate_contract(duplicate)


def test_contract_rejects_malformed_json(tmp_path: Path) -> None:
    malformed = tmp_path / "malformed.json"
    malformed.write_text('{"schema_version": 1,\n', encoding="utf-8")

    with pytest.raises(ContractValidationError):
        validate_contract(malformed)


def test_completion_order_is_metadata_only(tmp_path: Path) -> None:
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    payload["round_completion_order"] = ["round-002", "round-003", "round-001"]
    reordered = tmp_path / "reordered.json"
    reordered.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    validate_contract(reordered)


def test_cli_normalizes_contract_errors_without_traceback(tmp_path: Path) -> None:
    malformed = tmp_path / "malformed.json"
    malformed.write_text('{"schema_version": 1,\n', encoding="utf-8")
    result = subprocess.run(
        [sys.executable, "scripts/check_new_domain_contract.py", str(malformed)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 1
    assert result.stdout == ""
    assert result.stderr == "new domain contract replay failed\n"
