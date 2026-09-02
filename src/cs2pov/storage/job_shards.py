from __future__ import annotations

from cs2pov.domain.errors import DomainSchemaError
from cs2pov.domain.invocation import (
    ModelConfigurationSnapshot,
    ModelInvocationRecord,
)
from cs2pov.domain.review import (
    DraftCommsTimeline,
    ReviewRevisionManifest,
    ReviewedCommsTimeline,
    RoundReviewDocument,
)
from cs2pov.domain.timebase import TimeAnchor
from cs2pov.domain.timeline import DemoDescriptor, RoundCollection
from cs2pov.domain.transcript import TranscriptCue
from cs2pov.domain.understanding import RoundUnderstandingDocument
from cs2pov.domain.voice import VoiceActivityCue

from .atomic_documents import schema_aware_parser


VOICE_ACTIVITY_PARSER = schema_aware_parser(
    VoiceActivityCue.from_dict,
    expectations=("",),
)
MODEL_CONFIGURATION_PARSER = schema_aware_parser(
    ModelConfigurationSnapshot.from_dict,
    expectations=("",),
)
MODEL_INVOCATION_PARSER = schema_aware_parser(
    ModelInvocationRecord.from_dict,
    expectations=("",),
)
DEMO_DESCRIPTOR_PARSER = schema_aware_parser(
    DemoDescriptor.from_dict,
    expectations=("",),
)
ROUND_COLLECTION_PARSER = schema_aware_parser(
    RoundCollection.from_dict,
    expectations=("",),
)
TIME_ANCHOR_PARSER = schema_aware_parser(
    TimeAnchor.from_dict,
    expectations=("",),
)
TRANSCRIPT_CUE_PARSER = schema_aware_parser(
    TranscriptCue.from_dict,
    expectations=("",),
)
ROUND_UNDERSTANDING_PARSER = schema_aware_parser(
    RoundUnderstandingDocument.from_dict,
    expectations=("", "/results/*"),
)
REVIEW_REVISION_PARSER = schema_aware_parser(
    ReviewRevisionManifest.from_dict,
    expectations=("",),
)
ROUND_REVIEW_PARSER = schema_aware_parser(
    RoundReviewDocument.from_dict,
    expectations=("", "/decisions/*"),
)
DRAFT_TIMELINE_PARSER = schema_aware_parser(
    DraftCommsTimeline.from_dict,
    expectations=("",),
)
REVIEWED_TIMELINE_PARSER = schema_aware_parser(
    ReviewedCommsTimeline.from_dict,
    expectations=("",),
)


def _invalid(path: str, message: str) -> DomainSchemaError:
    return DomainSchemaError(
        "domain_reference_invalid",
        message,
        "请修正后重试。",
        path,
    )


def canonical_voice_activities(values: object) -> tuple[VoiceActivityCue, ...]:
    if not isinstance(values, (tuple, list)) or any(
        type(value) is not VoiceActivityCue for value in values
    ):
        raise _invalid("voice/activities.jsonl", "语音活动集合无效。")
    result = tuple(
        sorted(
            values,
            key=lambda value: (
                value.time_range.start_us,
                value.time_range.end_us,
                value.activity_id,
            ),
        )
    )
    if len({value.activity_id for value in result}) != len(result):
        raise _invalid("voice/activities.jsonl", "语音活动 ID 不能重复。")
    return result


def require_canonical_voice_activities(
    values: object,
) -> tuple[VoiceActivityCue, ...]:
    if not isinstance(values, (tuple, list)):
        raise _invalid("voice/activities.jsonl", "语音活动集合无效。")
    original = tuple(values)
    canonical = canonical_voice_activities(original)
    if original != canonical:
        raise _invalid("voice/activities.jsonl", "语音活动顺序不是规范顺序。")
    return canonical


def canonical_task_invocations(
    task_id: str, values: object
) -> tuple[ModelInvocationRecord, ...]:
    if not isinstance(values, (tuple, list)) or any(
        type(value) is not ModelInvocationRecord for value in values
    ):
        raise _invalid("models/invocations", "模型调用集合无效。")
    result = tuple(sorted(values, key=lambda value: value.invocation_id))
    if any(value.task_id != task_id for value in result):
        raise _invalid("models/invocations", "模型调用与任务文件身份不一致。")
    if len({value.invocation_id for value in result}) != len(result):
        raise _invalid("models/invocations", "模型调用 ID 不能重复。")
    return result


def require_canonical_task_invocations(
    task_id: str, values: object
) -> tuple[ModelInvocationRecord, ...]:
    if not isinstance(values, (tuple, list)):
        raise _invalid("models/invocations", "模型调用集合无效。")
    original = tuple(values)
    canonical = canonical_task_invocations(task_id, original)
    if original != canonical:
        raise _invalid("models/invocations", "模型调用顺序不是规范顺序。")
    return canonical


def canonical_transcripts(
    values: object,
    *,
    round_id: str | None,
    logical_path: str,
) -> tuple[TranscriptCue, ...]:
    if not isinstance(values, (tuple, list)) or any(
        type(value) is not TranscriptCue for value in values
    ):
        raise _invalid(logical_path, "转录提示集合无效。")
    result = tuple(
        sorted(
            values,
            key=lambda value: (
                value.time_range.start_us,
                value.time_range.end_us,
                value.cue_id,
            ),
        )
    )
    if len({value.cue_id for value in result}) != len(result):
        raise _invalid(logical_path, "转录提示 ID 不能重复。")
    if any(value.round_id != round_id for value in result):
        raise _invalid(logical_path, "转录提示与回合文件身份不一致。")
    return result


def require_canonical_transcripts(
    values: object,
    *,
    round_id: str | None,
    logical_path: str,
) -> tuple[TranscriptCue, ...]:
    if not isinstance(values, (tuple, list)):
        raise _invalid(logical_path, "转录提示集合无效。")
    original = tuple(values)
    canonical = canonical_transcripts(
        original,
        round_id=round_id,
        logical_path=logical_path,
    )
    if original != canonical:
        raise _invalid(logical_path, "转录提示顺序不是规范顺序。")
    return canonical
