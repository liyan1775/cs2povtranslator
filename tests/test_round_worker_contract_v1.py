"""Worker projections preserve the existing full-evidence domain contract."""

import asyncio
from dataclasses import FrozenInstanceError, asdict, fields, replace

import pytest

from cs2pov.application.round_worker import (
    RoundWorkFailure,
    RoundWorkResult,
    build_round_work_request,
    validate_round_work_failure,
    validate_round_work_result,
)
from cs2pov.domain.errors import DomainSchemaError
from cs2pov.domain.fingerprint import content_fingerprint
from cs2pov.domain.invocation import ModelCapability
from cs2pov.domain.job_tasks import RoundTaskError, RoundTranslationTask
from cs2pov.domain.understanding import RoundUnderstandingDocument
from cs2pov.domain.validation import validate_understanding_document_graph
from test_domain_validation_v1 import _understanding_graph


def inputs(cues=None):
    timeline, _, cue, _, _, config, invocation, document = _understanding_graph()
    if cues is None:
        cues = (cue,)
    selected = sorted(
        (c for c in cues if c.round_id == "round-001"),
        key=lambda c: (c.time_range.start_us, c.time_range.end_us, c.cue_id),
    )
    digest = content_fingerprint(
        {
            "round_id": "round-001",
            "transcript_cues": [c.to_dict() for c in selected],
        }
    )
    task = RoundTranslationTask.pending(
        task_id="round-001",
        round_id="round-001",
        input_fingerprint=content_fingerprint(
            {
                "document_input_fingerprint": digest,
                "configuration_fingerprint": config.configuration_fingerprint,
            }
        ),
        configuration_snapshot_id=config.snapshot_id,
        updated_at="2026-09-06T00:00:00.000000Z",
    )
    return (
        dict(
            task=task,
            round=timeline.rounds.rounds[0],
            configuration=config,
            transcripts=cues,
        ),
        invocation,
        document,
    )


def test_builder_retains_only_projected_fields_and_two_verified_hashes():
    args, _, document = inputs()
    cue = args["transcripts"][0]
    others = (
        replace(cue, cue_id="cue-b", player_id="player-beta"),
        replace(cue, cue_id="cue-c"),
        replace(cue, cue_id="cue-other", round_id="round-002"),
    )
    args, _, _ = inputs((others[2], others[1], others[0], cue))
    request = build_round_work_request(**args)
    assert [c.cue_id for c in request.cues] == [cue.cue_id, "cue-b", "cue-c"]
    assert [c.speaker_token for c in request.cues] == [
        "speaker-001",
        "speaker-002",
        "speaker-001",
    ]
    assert {f.name for f in fields(request)} == {
        "task_id",
        "round_id",
        "round_number",
        "configuration",
        "cues",
        "document_input_fingerprint",
        "task_input_fingerprint",
    }
    assert {f.name for f in fields(request.cues[0])} == {
        "cue_id",
        "speaker_token",
        "start_us",
        "end_us",
        "asr_original",
        "language",
        "confidence",
    }
    assert not hasattr(request, "__dict__")
    assert not hasattr(request.cues[0], "__dict__")
    assert request.cues[0].start_us == cue.time_range.start_us
    assert request.task_input_fingerprint == args["task"].input_fingerprint
    assert request.document_input_fingerprint != document.input_fingerprint
    assert "player-beta" not in repr(asdict(request))
    assert cue.source_stream_id not in repr(asdict(request))
    with pytest.raises(FrozenInstanceError):
        request.round_id = "round-002"
    assert (
        build_round_work_request(**inputs()[0]).cues[0].speaker_token == "speaker-001"
    )


@pytest.mark.parametrize(
    "mutation",
    [
        "task_hash",
        "snapshot",
        "round",
        "duplicate",
        "bad_type",
        "capability",
    ],
)
def test_builder_rejects_invalid_inputs(mutation):
    args, _, _ = inputs()
    if mutation == "task_hash":
        args["task"] = replace(args["task"], input_fingerprint="0" * 64)
    elif mutation == "snapshot":
        args["task"] = replace(args["task"], configuration_snapshot_id="other")
    elif mutation == "round":
        args["round"] = replace(args["round"], round_id="round-002")
    elif mutation == "duplicate":
        args["transcripts"] *= 2
    elif mutation == "bad_type":
        args["transcripts"] = ({},)
    else:
        args["configuration"] = replace(
            args["configuration"], capability=ModelCapability.ASR, parameters={}
        )
    with pytest.raises(DomainSchemaError):
        build_round_work_request(**args)


def test_result_validates_projection_and_unchanged_production_wire():
    args, invocation, document = inputs()
    request = build_round_work_request(**args)
    diagnostic = replace(
        invocation,
        invocation_id="diagnostic-001",
        response_content_fingerprint="f" * 64,
    )
    result = RoundWorkResult(document, (diagnostic, invocation))
    validate_round_work_result(request, result)
    validate_understanding_document_graph(
        document,
        args["transcripts"],
        (args["configuration"],),
        result.invocations,
    )
    assert RoundUnderstandingDocument.from_dict(document.to_dict()) == document

    class Worker:
        async def translate(self, request):
            return result

    assert asyncio.run(Worker().translate(request)) == result


@pytest.mark.parametrize(
    "mutation",
    [
        "input",
        "round",
        "snapshot",
        "missing_cue",
        "extra_cue",
        "asr",
        "missing_invocation",
        "duplicate_invocation",
        "call_task",
        "call_config",
        "call_request",
        "call_response",
        "diagnostic_wrong_request",
    ],
)
def test_result_rejects_mismatched_projection_and_authoritative_invocation(mutation):
    args, invocation, document = inputs()
    request = build_round_work_request(**args)
    invocations = (invocation,)
    if mutation in {"input", "snapshot"}:
        document = replace(
            document,
            **{
                "input_fingerprint"
                if mutation == "input"
                else "model_configuration_snapshot_id": "0" * 64
                if mutation == "input"
                else "other",
            },
        )
    elif mutation == "round":
        document = replace(
            document,
            round_id="round-002",
            results=(replace(document.results[0], round_id="round-002"),),
        )
    elif mutation == "missing_cue":
        document = replace(document, results=(), invocation_record_id=None)
    elif mutation == "extra_cue":
        document = replace(
            document,
            results=(*document.results, replace(document.results[0], cue_id="extra")),
        )
    elif mutation == "asr":
        document = replace(
            document, results=(replace(document.results[0], asr_original="changed"),)
        )
    elif mutation == "missing_invocation":
        invocations = ()
    elif mutation == "duplicate_invocation":
        invocations *= 2
    elif mutation == "diagnostic_wrong_request":
        invocations += (
            replace(
                invocation, invocation_id="extra", request_content_fingerprint="0" * 64
            ),
        )
    else:
        field = {
            "call_task": "task_id",
            "call_config": "configuration_snapshot_id",
            "call_request": "request_content_fingerprint",
            "call_response": "response_content_fingerprint",
        }[mutation]
        invocations = (replace(invocation, **{field: "0" * 64}),)
    with pytest.raises(DomainSchemaError):
        validate_round_work_result(request, RoundWorkResult(document, invocations))


def test_empty_success_requires_empty_complete_round_and_no_new_calls():
    args, invocation, document = inputs(())
    request = build_round_work_request(**args)
    empty = replace(
        document,
        input_fingerprint=request.document_input_fingerprint,
        invocation_record_id=None,
        results=(),
    )
    validate_round_work_result(request, RoundWorkResult(empty, ()))
    validate_understanding_document_graph(empty, (), (args["configuration"],), ())
    with pytest.raises(DomainSchemaError):
        validate_round_work_result(request, RoundWorkResult(empty, (invocation,)))


def test_same_projection_cannot_prove_full_evidence_hash_at_worker_boundary():
    args, invocation, document = inputs()
    request = build_round_work_request(**args)
    changed = replace(args["transcripts"][0], asr_invocation_record_id="asr-other")
    changed_args, _, _ = inputs((changed,))
    rebuilt = build_round_work_request(**changed_args)
    assert request.cues == rebuilt.cues
    assert request.document_input_fingerprint != rebuilt.document_input_fingerprint
    assert request.task_input_fingerprint != rebuilt.task_input_fingerprint
    result = RoundWorkResult(document, (invocation,))
    validate_round_work_result(request, result)
    with pytest.raises(DomainSchemaError):
        validate_round_work_result(rebuilt, result)
    with pytest.raises(DomainSchemaError):
        validate_understanding_document_graph(
            document, (changed,), (args["configuration"],), (invocation,)
        )


def test_valid_digest_with_digit_run_is_not_misclassified_as_private_identity():
    args, invocation, document = inputs()
    request = build_round_work_request(**args)
    diagnostic = replace(
        invocation,
        invocation_id="diagnostic-digest",
        response_content_fingerprint="1" * 17 + "a" * 47,
    )
    validate_round_work_result(
        request, RoundWorkResult(document, (invocation, diagnostic))
    )


def test_relative_model_name_and_normal_slash_text_remain_valid():
    args, invocation, document = inputs()
    request = build_round_work_request(**args)
    config = replace(args["configuration"], model_name="org/model", parameters={})
    request = replace(
        request,
        configuration=config,
        task_input_fingerprint=content_fingerprint(
            {
                "document_input_fingerprint": request.document_input_fingerprint,
                "configuration_fingerprint": config.configuration_fingerprint,
            }
        ),
    )
    assert replace(request.cues[0], asr_original="A/B").asr_original == "A/B"
    document = replace(
        document, results=(replace(document.results[0], translated_zh="A/B方向"),)
    )
    invocation = replace(
        invocation,
        response_content_fingerprint=content_fingerprint(
            {
                "round_id": document.round_id,
                "results": [r.to_dict() for r in document.results],
            }
        ),
    )
    validate_round_work_result(request, RoundWorkResult(document, (invocation,)))


def test_failure_keeps_raw_cause_out_of_message_and_validates_call_ownership():
    args, invocation, _ = inputs()
    request = build_round_work_request(**args)
    error = RoundTaskError(
        "provider_busy", "服务繁忙。", "本回合未完成。", "稍后重试。", True, None
    )
    cause = RuntimeError("raw details")
    failure = RoundWorkFailure(error, (invocation,), cause=cause)
    assert str(failure) == error.message_zh
    assert failure.args == (error.message_zh,)
    assert failure.__cause__ is cause
    validate_round_work_failure(request, failure)
    validate_round_work_failure(request, RoundWorkFailure(error))
    with pytest.raises(DomainSchemaError):
        validate_round_work_failure(
            request,
            RoundWorkFailure(error, (replace(invocation, task_id="round-other"),)),
        )
    with pytest.raises(DomainSchemaError):
        RoundWorkFailure(error, (invocation, invocation))
    with pytest.raises(DomainSchemaError):
        RoundWorkFailure("raw exception")
    with pytest.raises(DomainSchemaError):
        RoundWorkFailure(error, cause="raw exception")


@pytest.mark.parametrize(
    "value",
    [
        "C:/private/file",
        "请检查C:/private/file",
        "https://private.example",
        "编号12345678901234567",
    ],
)
def test_request_boundary_rejects_private_cue_text(value):
    args, _, _ = inputs()
    with pytest.raises(DomainSchemaError):
        cue = replace(args["transcripts"][0], asr_original=value)
        build_round_work_request(**inputs((cue,))[0])


def test_direct_request_cannot_bypass_hash_order_or_type_checks():
    request = build_round_work_request(**inputs()[0])
    for changes in [
        dict(task_input_fingerprint="0" * 64),
        dict(task_id="other"),
        dict(round_number=True),
        dict(cues=(request.cues[0], request.cues[0])),
        dict(cues=({},)),
    ]:
        with pytest.raises(DomainSchemaError):
            replace(request, **changes)
    for changes in [
        dict(start_us=True),
        dict(end_us=0),
        dict(confidence=float("nan")),
        dict(speaker_token="player-alpha"),
    ]:
        with pytest.raises(DomainSchemaError):
            replace(request.cues[0], **changes)


def test_result_rejects_noncanonical_order_even_with_matching_response_hash():
    args, invocation, document = inputs()
    cue = args["transcripts"][0]
    args, _, _ = inputs((cue, replace(cue, cue_id="cue-z")))
    request = build_round_work_request(**args)
    results = (replace(document.results[0], cue_id="cue-z"), document.results[0])
    document = replace(
        document, input_fingerprint=request.document_input_fingerprint, results=results
    )
    invocation = replace(
        invocation,
        request_content_fingerprint=request.document_input_fingerprint,
        response_content_fingerprint=content_fingerprint(
            {"round_id": document.round_id, "results": [r.to_dict() for r in results]}
        ),
    )
    with pytest.raises(DomainSchemaError):
        validate_round_work_result(request, RoundWorkResult(document, (invocation,)))
