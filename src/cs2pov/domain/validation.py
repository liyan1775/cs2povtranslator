from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .errors import DomainSchemaError
from .fingerprint import content_fingerprint
from .invocation import ModelCapability
from .review import DraftCommsCue, DraftCommsTimeline, ReviewedCommsTimeline
from .timebase import SourceClock, TimeRange, map_source_range
from .timeline import DemoTimeline
from .transcript import TranscriptCue
from .understanding import (
    RoundUnderstandingDocument,
    UnderstandingResult,
    validate_understanding_against_transcript,
)
from .voice import VoiceActivityCue


def _error(code: str, path: str = "validation") -> None:
    raise DomainSchemaError(code, "领域引用无效。", "请修正后重试。", path)


def _items(value: object, path: str) -> tuple[Any, ...]:
    if not isinstance(value, (tuple, list)):
        _error("domain_field_invalid", path)
    return tuple(value)


def _covers(ranges: object, target: TimeRange) -> bool:
    """Return whether a collection of half-open ranges covers target without gaps."""
    ordered = sorted(
        (item for item in ranges), key=lambda item: (item.start_us, item.end_us)
    )
    cursor = target.start_us
    for item in ordered:
        if item.start_us > cursor:
            return False
        if item.end_us > cursor:
            cursor = item.end_us
        if cursor >= target.end_us:
            return True
    return False


def _index(values: object, path: str, attr: str) -> dict[str, Any]:
    seq = _items(values, path)
    try:
        result = {getattr(item, attr): item for item in seq}
    except (AttributeError, TypeError) as exc:
        raise DomainSchemaError(
            "domain_field_invalid", "领域引用无效。", "请修正后重试。", path
        ) from exc
    if len(result) != len(seq):
        _error("domain_reference_invalid", path)
    return result


def _round_index(timeline: DemoTimeline) -> dict[str, Any]:
    if not isinstance(timeline, DemoTimeline):
        _error("domain_field_invalid", "timeline")
    return _index(timeline.rounds.rounds, "rounds", "round_id")


def validate_voice_activity_against_timeline(
    activity: VoiceActivityCue, timeline: DemoTimeline
) -> None:
    if not isinstance(activity, VoiceActivityCue):
        _error("domain_field_invalid", "activity")
    if not isinstance(timeline, DemoTimeline):
        _error("domain_field_invalid", "timeline")
    players = {player.player_id for player in timeline.descriptor.players}
    if activity.player_id not in players:
        _error("player_reference_invalid", "player_id")
    anchors = _index(timeline.anchors, "anchors", "anchor_id")
    for anchor_id in activity.anchor_ids:
        anchor = anchors.get(anchor_id)
        if anchor is None:
            _error("time_anchor_invalid", "anchor_ids")
        if (
            anchor.source_clock is not SourceClock.COMPACT_AUDIO_SAMPLE
            or anchor.source_stream_id != activity.player_id
        ):
            _error("time_anchor_invalid", "anchor_ids")
    if not _covers(
        (anchors[anchor_id].demo_range for anchor_id in activity.anchor_ids),
        activity.time_range,
    ):
        _error("cue_reference_invalid", "time_range")


def validate_transcript_against_timeline(
    transcript: TranscriptCue,
    timeline: DemoTimeline,
    activities: object = (),
    configurations: object = (),
    invocations: object = (),
) -> None:
    if not isinstance(transcript, TranscriptCue) or not isinstance(
        timeline, DemoTimeline
    ):
        _error("domain_field_invalid", "transcript")
    players = {player.player_id for player in timeline.descriptor.players}
    if transcript.player_id not in players:
        _error("player_reference_invalid", "player_id")
    if transcript.round_id is not None and transcript.round_id not in _round_index(
        timeline
    ):
        _error("cue_reference_invalid", "round_id")
    if transcript.round_id is not None:
        round_value = _round_index(timeline)[transcript.round_id]
        if not (
            round_value.time_range.start_us <= transcript.time_range.start_us
            and transcript.time_range.end_us <= round_value.time_range.end_us
        ):
            _error("cue_reference_invalid", "time_range")
    anchors = _items(timeline.anchors, "anchors")
    if (
        transcript.source_clock is SourceClock.COMPACT_AUDIO_SAMPLE
        and transcript.source_stream_id != transcript.player_id
    ):
        _error("cue_reference_invalid", "source_stream_id")
    try:
        mapped = map_source_range(
            anchors,
            transcript.source_clock,
            transcript.source_stream_id,
            transcript.source_start,
            transcript.source_end,
        )
    except DomainSchemaError as exc:
        raise exc
    if (
        mapped.anchor_ids != transcript.anchor_ids
        or mapped.envelope != transcript.time_range
    ):
        _error("cue_reference_invalid", "source_mapping")
    activity_map = _index(activities, "activities", "activity_id")
    for activity_id in transcript.voice_activity_ids:
        activity = activity_map.get(activity_id)
        if activity is None:
            _error("voice_activity_reference_invalid", "voice_activity_ids")
        validate_voice_activity_against_timeline(activity, timeline)
        if activity.player_id != transcript.player_id:
            _error("cue_reference_invalid", "voice_activity_ids")
    referenced_activities = [
        activity_map[activity_id] for activity_id in transcript.voice_activity_ids
    ]
    if not _covers(
        (activity.time_range for activity in referenced_activities),
        transcript.time_range,
    ):
        _error("cue_reference_invalid", "voice_activity_ids")
    invocation_map = _index(invocations, "invocations", "invocation_id")
    invocation = invocation_map.get(transcript.asr_invocation_record_id)
    if invocation is None:
        _error("invocation_reference_invalid", "asr_invocation_record_id")
    configuration_map = _index(configurations, "configurations", "snapshot_id")
    configuration = configuration_map.get(invocation.configuration_snapshot_id)
    if configuration is None or configuration.capability is not ModelCapability.ASR:
        _error("invocation_reference_invalid", "configuration_snapshot_id")


def validate_understanding_document_graph(
    document: RoundUnderstandingDocument,
    transcripts: object,
    configurations: object,
    invocations: object,
) -> None:
    if not isinstance(document, RoundUnderstandingDocument):
        _error("domain_field_invalid", "document")
    transcript_values = _items(transcripts, "transcripts")
    assigned = [
        cue
        for cue in transcript_values
        if isinstance(cue, TranscriptCue) and cue.round_id == document.round_id
    ]
    if any(not isinstance(cue, TranscriptCue) for cue in transcript_values):
        _error("domain_field_invalid", "transcripts")
    assigned.sort(
        key=lambda cue: (cue.time_range.start_us, cue.time_range.end_us, cue.cue_id)
    )
    request = {
        "round_id": document.round_id,
        "transcript_cues": [cue.to_dict() for cue in assigned],
    }
    if document.input_fingerprint != content_fingerprint(request):
        _error("domain_fingerprint_mismatch", "input_fingerprint")
    config_map = _index(configurations, "configurations", "snapshot_id")
    configuration = config_map.get(document.model_configuration_snapshot_id)
    if (
        configuration is None
        or configuration.capability is not ModelCapability.UNDERSTANDING_TRANSLATION
    ):
        _error("invocation_reference_invalid", "model_configuration_snapshot_id")
    results = _items(document.results, "results")
    if any(not isinstance(result, UnderstandingResult) for result in results):
        _error("domain_field_invalid", "results")
    by_cue = {cue.cue_id: cue for cue in assigned}
    if (
        len(by_cue) != len(assigned)
        or {result.cue_id for result in results} != set(by_cue)
        or len({result.cue_id for result in results}) != len(results)
    ):
        _error("cue_reference_invalid", "results")
    invocation_values = _items(invocations, "invocations")
    invocation_map = _index(invocation_values, "invocations", "invocation_id")
    if not assigned:
        if document.invocation_record_id is not None or results:
            _error("invocation_reference_invalid", "invocation_record_id")
        return
    if document.invocation_record_id is None:
        _error("invocation_reference_invalid", "invocation_record_id")
    invocation = invocation_map.get(document.invocation_record_id)
    if (
        invocation is None
        or invocation.configuration_snapshot_id
        != document.model_configuration_snapshot_id
        or invocation.task_id != document.round_id
    ):
        _error("invocation_reference_invalid", "invocation_record_id")
    ordered_results = sorted(
        results,
        key=lambda result: (
            by_cue[result.cue_id].time_range.start_us,
            by_cue[result.cue_id].time_range.end_us,
            result.cue_id,
        ),
    )
    if tuple(results) != tuple(ordered_results):
        _error("cue_reference_invalid", "results")
    for result in results:
        try:
            validate_understanding_against_transcript(result, by_cue[result.cue_id])
        except DomainSchemaError as exc:
            raise exc
        if result.model_invocation_record_id != invocation.invocation_id:
            _error("invocation_reference_invalid", "model_invocation_record_id")
    response = {
        "round_id": document.round_id,
        "results": [result.to_dict() for result in ordered_results],
    }
    if invocation.request_content_fingerprint != content_fingerprint(
        request
    ) or invocation.response_content_fingerprint != content_fingerprint(response):
        _error("domain_fingerprint_mismatch", "invocation_record_id")


def compose_draft_timeline(
    timeline: DemoTimeline,
    transcripts: object,
    documents: object,
    configurations: object,
    invocations: object,
) -> DraftCommsTimeline:
    if not isinstance(timeline, DemoTimeline):
        _error("domain_field_invalid", "timeline")
    document_values = _items(documents, "documents")
    if any(
        not isinstance(document, RoundUnderstandingDocument)
        for document in document_values
    ):
        _error("domain_field_invalid", "documents")
    expected_round_ids = [
        round_value.round_id for round_value in timeline.rounds.rounds
    ]
    document_map = _index(document_values, "documents", "round_id")
    if set(document_map) != set(expected_round_ids):
        _error("round_reference_invalid", "documents")
    transcript_values = _items(transcripts, "transcripts")
    if any(not isinstance(cue, TranscriptCue) for cue in transcript_values):
        _error("domain_field_invalid", "transcripts")
    for document in document_values:
        validate_understanding_document_graph(
            document, transcript_values, configurations, invocations
        )
    transcript_map = _index(transcript_values, "transcripts", "cue_id")
    cues: list[DraftCommsCue] = []
    ordered_documents = [document_map[round_id] for round_id in expected_round_ids]
    for document in ordered_documents:
        for result in document.results:
            transcript = transcript_map.get(result.cue_id)
            if transcript is None:
                _error("cue_reference_invalid", "cue_id")
            cues.append(
                DraftCommsCue.from_transcript_and_understanding(transcript, result)
            )
    cues.sort(key=lambda cue: (cue.start_us, cue.end_us, cue.cue_id))
    input_fingerprint = content_fingerprint(
        {"round_understanding": [document.to_dict() for document in ordered_documents]}
    )
    return DraftCommsTimeline(
        timeline.descriptor.demo_asset_id,
        "demo-microseconds",
        input_fingerprint,
        tuple(cues),
    )


def validate_draft_timeline_graph(
    draft: DraftCommsTimeline,
    timeline: DemoTimeline,
    transcripts: object,
    documents: object,
    configurations: object,
    invocations: object,
) -> None:
    if not isinstance(draft, DraftCommsTimeline):
        _error("domain_field_invalid", "draft")
    expected = compose_draft_timeline(
        timeline, transcripts, documents, configurations, invocations
    )
    if expected != draft:
        _error("domain_fingerprint_mismatch", "draft_timeline")


def validate_reviewed_timeline_graph(
    reviewed: ReviewedCommsTimeline,
    draft: DraftCommsTimeline,
    timeline: DemoTimeline,
) -> None:
    if (
        not isinstance(reviewed, ReviewedCommsTimeline)
        or not isinstance(draft, DraftCommsTimeline)
        or not isinstance(timeline, DemoTimeline)
    ):
        _error("domain_field_invalid", "reviewed_timeline")
    if reviewed.source_draft_fingerprint != draft.content_fingerprint():
        _error("domain_fingerprint_mismatch", "source_draft_fingerprint")
    if (
        reviewed.demo_asset_id != draft.demo_asset_id
        or reviewed.timebase != "demo-microseconds"
    ):
        _error("timeline_invalid", "reviewed_timeline")
    if reviewed.demo_asset_id != timeline.descriptor.demo_asset_id:
        _error("timeline_invalid", "demo_asset_id")
    draft_map = {cue.cue_id: cue for cue in draft.cues}
    reviewed_ids = {cue.cue_id for cue in reviewed.cues}
    decision_ids = [cue.review_decision_id for cue in reviewed.cues]
    if len(decision_ids) != len(set(decision_ids)):
        _error("review_decision_invalid", "review_decision_id")
    if set(decision_ids) & set(reviewed.excluded_decision_ids):
        _error("review_decision_invalid", "decision_ids")
    if len(reviewed.cues) + len(reviewed.excluded_decision_ids) != len(draft.cues):
        _error("cue_reference_invalid", "cues")
    if not reviewed_ids <= set(draft_map):
        _error("cue_reference_invalid", "cues")
    for cue in reviewed.cues:
        source = draft_map.get(cue.cue_id)
        if (
            source is None
            or cue.round_id != source.round_id
            or cue.player_id != source.player_id
            or cue.asr_original != source.asr_original
            or cue.interpreted_source != source.interpreted_source
            or cue.model_translated_zh != source.translated_zh
            or cue.model_confidence != source.confidence
            or cue.evidence != source.evidence
        ):
            _error("cue_reference_invalid", "cues")
        round_value = _round_index(timeline).get(cue.round_id)
        if round_value is None or not (
            round_value.time_range.start_us <= cue.start_us
            and cue.end_us <= round_value.time_range.end_us
        ):
            _error("cue_reference_invalid", "cues")
