from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Callable, TypeVar


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from cs2pov.domain.invocation import ModelConfigurationSnapshot, ModelInvocationRecord
from cs2pov.domain.review import (
    DraftCommsTimeline,
    ReviewDecision,
    ReviewedCommsTimeline,
    compose_reviewed_timeline,
)
from cs2pov.domain.schema import reject_private_data
from cs2pov.domain.timebase import TimeAnchor
from cs2pov.domain.timeline import DemoDescriptor, DemoTimeline, RoundCollection
from cs2pov.domain.transcript import TranscriptCue
from cs2pov.domain.understanding import RoundUnderstandingDocument
from cs2pov.domain.validation import (
    compose_draft_timeline,
    validate_draft_timeline_graph,
    validate_reviewed_timeline_graph,
    validate_transcript_against_timeline,
    validate_understanding_document_graph,
    validate_voice_activity_against_timeline,
)
from cs2pov.domain.voice import VoiceActivityCue


FIXTURE = ROOT / "tests" / "golden" / "fixtures" / "new_domain_contract_v1.json"
TRANSPORT_KEYS = frozenset(
    {
        "schema_version",
        "fixture_id",
        "demo",
        "rounds",
        "time_anchors",
        "model_configurations",
        "model_invocations",
        "voice_activities",
        "transcript_cues",
        "round_understanding",
        "review_decisions",
        "draft_timeline",
        "reviewed_timeline",
        "round_completion_order",
        "expected",
    }
)
EXPECTED_KEYS = frozenset(
    {
        "round_ids",
        "b_callout_cue_id",
        "asr_original",
        "interpreted_source",
        "final_translated_zh",
        "reviewed_cue_order",
        "speechless_round_id",
        "unassigned_cue_id",
    }
)


class ContractValidationError(ValueError):
    """Stable public error for all contract validation failures."""


class _DuplicateJSONKey(ValueError):
    pass


def _object_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicateJSONKey(key)
        result[key] = value
    return result


def _load_payload(path: Path) -> dict[str, Any]:
    raw = path.read_text(encoding="utf-8")
    payload = json.loads(raw, object_pairs_hook=_object_pairs)
    if not isinstance(payload, dict):
        raise ValueError("payload root must be an object")
    if set(payload) != TRANSPORT_KEYS:
        raise ValueError("transport keys are not exact")
    if type(payload["schema_version"]) is not int or payload["schema_version"] != 1:
        raise ValueError("unsupported transport schema")
    if not isinstance(payload["fixture_id"], str) or not payload["fixture_id"]:
        raise ValueError("fixture ID is invalid")
    return payload


T = TypeVar("T")


def _unique(
    values: object,
    path: str,
    factory: Callable[[Any], T],
    attr: str,
) -> tuple[T, ...]:
    if not isinstance(values, list):
        raise ValueError(f"{path} must be a list")
    parsed = tuple(factory(item) for item in values)
    identifiers = [getattr(item, attr) for item in parsed]
    if len(identifiers) != len(set(identifiers)):
        raise ValueError(f"duplicate identifiers in {path}")
    return parsed


def _require_mapping(value: object, path: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{path} must be an object")
    return value


def _validate_payload(payload: dict[str, Any]) -> None:
    reject_private_data(payload, "contract")

    descriptor = DemoDescriptor.from_dict(payload["demo"])
    rounds = RoundCollection.from_dict(payload["rounds"])
    anchors = _unique(
        payload["time_anchors"], "time_anchors", TimeAnchor.from_dict, "anchor_id"
    )
    timeline = DemoTimeline(descriptor, rounds, anchors)

    configurations = _unique(
        payload["model_configurations"],
        "model_configurations",
        ModelConfigurationSnapshot.from_dict,
        "snapshot_id",
    )
    invocations = _unique(
        payload["model_invocations"],
        "model_invocations",
        ModelInvocationRecord.from_dict,
        "invocation_id",
    )
    configuration_ids = {item.snapshot_id for item in configurations}
    if any(
        item.configuration_snapshot_id not in configuration_ids
        for item in invocations
    ):
        raise ValueError("invocation configuration reference is dangling")

    activities = _unique(
        payload["voice_activities"],
        "voice_activities",
        VoiceActivityCue.from_dict,
        "activity_id",
    )
    transcripts = _unique(
        payload["transcript_cues"],
        "transcript_cues",
        TranscriptCue.from_dict,
        "cue_id",
    )
    for activity in activities:
        validate_voice_activity_against_timeline(activity, timeline)
    for transcript in transcripts:
        validate_transcript_against_timeline(
            transcript, timeline, activities, configurations, invocations
        )

    documents = _unique(
        payload["round_understanding"],
        "round_understanding",
        RoundUnderstandingDocument.from_dict,
        "round_id",
    )
    round_ids = tuple(item.round_id for item in rounds.rounds)
    if set(item.round_id for item in documents) != set(round_ids) or len(
        documents
    ) != len(round_ids):
        raise ValueError("understanding documents do not cover every round")
    document_by_round = {item.round_id: item for item in documents}
    for document in documents:
        validate_understanding_document_graph(
            document, transcripts, configurations, invocations
        )

    expected = _require_mapping(payload["expected"], "expected")
    if set(expected) != EXPECTED_KEYS:
        raise ValueError("expected assertions are not exact")
    if expected.get("round_ids") != list(round_ids):
        raise ValueError("expected round IDs do not match timeline")
    speechless_round_id = expected.get("speechless_round_id")
    speechless = document_by_round.get(speechless_round_id)
    if (
        speechless is None
        or speechless.results
        or speechless.invocation_record_id is not None
    ):
        raise ValueError(
            "speechless round is not represented as a successful empty document"
        )
    unassigned_cue_id = expected.get("unassigned_cue_id")
    transcript_by_id = {item.cue_id: item for item in transcripts}
    unassigned = transcript_by_id.get(unassigned_cue_id)
    if unassigned is None or unassigned.round_id is not None:
        raise ValueError("unassigned cue has round membership")
    if any(
        result.cue_id == unassigned_cue_id
        for document in documents
        for result in document.results
    ):
        raise ValueError("unassigned cue appears in a round document")

    stored_draft = DraftCommsTimeline.from_dict(payload["draft_timeline"])
    validate_draft_timeline_graph(
        stored_draft, timeline, transcripts, documents, configurations, invocations
    )
    decisions = _unique(
        payload["review_decisions"],
        "review_decisions",
        ReviewDecision.from_dict,
        "decision_id",
    )
    reviewed = compose_reviewed_timeline(stored_draft, decisions)
    stored_reviewed = ReviewedCommsTimeline.from_dict(payload["reviewed_timeline"])
    if reviewed != stored_reviewed:
        raise ValueError("reviewed timeline recomposition mismatch")
    validate_reviewed_timeline_graph(stored_reviewed, stored_draft, timeline)

    b_callout_id = expected.get("b_callout_cue_id")
    b_result = next(
        (
            result
            for document in documents
            for result in document.results
            if result.cue_id == b_callout_id
        ),
        None,
    )
    b_reviewed = next(
        (cue for cue in stored_reviewed.cues if cue.cue_id == b_callout_id), None
    )
    if (
        b_result is None
        or b_reviewed is None
        or b_result.asr_original != expected.get("asr_original")
        or b_result.interpreted_source != expected.get("interpreted_source")
        or b_reviewed.final_translated_zh != expected.get("final_translated_zh")
    ):
        raise ValueError("B callout semantic assertions failed")
    if [cue.cue_id for cue in stored_reviewed.cues] != expected.get(
        "reviewed_cue_order"
    ):
        raise ValueError("reviewed cue order is not deterministic demo-time order")

    completion_order = payload["round_completion_order"]
    if (
        not isinstance(completion_order, list)
        or len(completion_order) != len(round_ids)
        or len(set(completion_order)) != len(completion_order)
        or set(completion_order) != set(round_ids)
    ):
        raise ValueError("round completion order is not a permutation")


def validate_contract(path: Path) -> None:
    """Validate one current-version contract without exposing input details."""
    try:
        payload = _load_payload(path)
        _validate_payload(payload)
    except ContractValidationError:
        raise
    except Exception as exc:
        raise ContractValidationError("new domain contract is invalid") from exc


def main() -> int:
    if len(sys.argv) > 2:
        print("new domain contract replay failed", file=sys.stderr)
        return 1
    fixture = Path(sys.argv[1]).resolve() if len(sys.argv) == 2 else FIXTURE
    try:
        validate_contract(fixture)
    except ContractValidationError:
        print("new domain contract replay failed", file=sys.stderr)
        return 1
    print("new domain contract replay passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
