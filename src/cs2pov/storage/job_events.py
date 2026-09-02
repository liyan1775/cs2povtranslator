from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from cs2pov.domain.job import JobEvent, JobIssue

from .atomic_documents import read_strict_jsonl, schema_aware_parser
from .job_errors import JobRepositoryError


EVENT_LOGICAL_PATH = "events/job_events.jsonl"
JOB_EVENT_PARSER = schema_aware_parser(
    JobEvent.from_dict,
    expectations=("",),
)


@dataclass(frozen=True, slots=True)
class EventJournalRead:
    events: tuple[JobEvent, ...]
    incomplete_tail: bool
    issues: tuple[JobIssue, ...]


def _invalid(message_zh: str, record_number: int | None = None) -> JobRepositoryError:
    logical_path = EVENT_LOGICAL_PATH
    if record_number is not None:
        logical_path = f"{logical_path}#{record_number}"
    return JobRepositoryError(
        "job_shard_invalid",
        message_zh,
        "请检查事件日志；读取操作不会自动修复或截断它。",
        logical_path,
    )


def read_event_journal(path: Path, *, expected_job_id: str) -> EventJournalRead:
    result = read_strict_jsonl(
        path,
        logical_path=EVENT_LOGICAL_PATH,
        parser=JOB_EVENT_PARSER,
        allow_incomplete_tail=True,
    )
    events = tuple(result.records)
    seen: set[str] = set()
    for record_number, event in enumerate(events, 1):
        if event.job_id != expected_job_id:
            raise _invalid("事件日志包含其他 Job 的事件。", record_number)
        if event.event_id in seen:
            raise _invalid("事件日志中的事件 ID 重复。", record_number)
        seen.add(event.event_id)
    issues = (
        (
            JobIssue(
                "job_event_tail_incomplete",
                "warning",
                "事件日志末行不完整；已保留此前完整事件。",
                "请不要继续追加；后续使用显式修复功能处理该日志。",
                EVENT_LOGICAL_PATH,
            ),
        )
        if result.incomplete_tail
        else ()
    )
    return EventJournalRead(events, result.incomplete_tail, issues)
