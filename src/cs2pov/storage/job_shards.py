from __future__ import annotations

from cs2pov.domain.errors import DomainSchemaError
from cs2pov.domain.invocation import (
    ModelConfigurationSnapshot,
    ModelInvocationRecord,
)
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
