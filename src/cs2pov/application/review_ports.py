"""Application services for claim-fenced current Job review writes."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from typing import Callable, Mapping
from uuid import uuid4

from cs2pov.domain.errors import DomainSchemaError
from cs2pov.domain.invalidation import (
    InvalidationRequest,
    JobInputChange,
    plan_invalidation,
    rewind_job_phase_for_invalidation,
)
from cs2pov.domain.job import JobPhase
from cs2pov.domain.job_state import advance_job_phase
from cs2pov.domain.review import (
    ReviewAction,
    ReviewDecision,
    ReviewRevisionManifest,
    RoundReviewDocument,
    compose_reviewed_timeline,
)
from cs2pov.domain.schema import require_path_identifier
from cs2pov.domain.timebase import TimeRange


_TIMESTAMP_FORMAT = "%Y-%m-%dT%H:%M:%S.%fZ"
_LATE_REVIEW_PHASES = frozenset(
    {
        JobPhase.COMPLETED_DRAFT,
        JobPhase.REVIEWED,
        JobPhase.FINAL_TIMELINE_READY,
        JobPhase.SUBTITLES_EXPORTED,
        JobPhase.GREEN_SCREEN_RENDERED,
        JobPhase.COMPLETED_WITHOUT_VIDEO,
        JobPhase.READY_FOR_RENDER,
        JobPhase.RENDERING,
        JobPhase.VIDEO_READY,
        JobPhase.COMPLETED_WITH_VIDEO,
    }
)


class ReviewPortError(RuntimeError):
    """Stable application error for the current Job review write surface."""

    def __init__(
        self,
        code: str,
        message_zh: str,
        suggestion_zh: str,
        path: str | None = None,
        *,
        status: int = 409,
    ) -> None:
        self.code = code
        self.message_zh = message_zh
        self.suggestion_zh = suggestion_zh
        self.path = path
        self.status = status
        super().__init__(message_zh)


@dataclass(frozen=True, slots=True)
class ReviewWriteReport:
    job_id: str
    review_id: str
    source_draft_fingerprint: str
    decision_count: int
    pending_count: int
    complete: bool
    phase: JobPhase
    manifest_fingerprint: str

    def to_dict(self) -> dict[str, object]:
        return {
            "job_id": self.job_id,
            "review_id": self.review_id,
            "source_draft_fingerprint": self.source_draft_fingerprint,
            "decision_count": self.decision_count,
            "pending_count": self.pending_count,
            "complete": self.complete,
            "phase": self.phase.value,
            "manifest_fingerprint": self.manifest_fingerprint,
        }


def _parse_timestamp(value: str) -> datetime:
    try:
        return datetime.strptime(value, _TIMESTAMP_FORMAT).replace(tzinfo=timezone.utc)
    except (TypeError, ValueError) as exc:
        raise ReviewPortError(
            "job_timestamp_invalid",
            "Job 时间无效。",
            "请刷新当前 Job 后重试。",
            "job.updated_at",
        ) from exc


def _next_timestamp(clock: Callable[[], datetime], *latest: str) -> str:
    now = clock()
    if not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None:
        raise ReviewPortError(
            "review_clock_invalid",
            "复核服务时钟无效。",
            "请检查本地系统时间后重试。",
            "reviewed_at",
        )
    current = now.astimezone(timezone.utc)
    for value in latest:
        parsed = _parse_timestamp(value)
        if current <= parsed:
            current = parsed + timedelta(microseconds=1)
    return current.strftime(_TIMESTAMP_FORMAT)


def _action(value: ReviewAction | str) -> ReviewAction:
    if isinstance(value, ReviewAction):
        return value
    if isinstance(value, str):
        try:
            return ReviewAction(value.strip().lower())
        except ValueError as exc:
            raise ReviewPortError(
                "review_decision_invalid",
                "复核动作无效。",
                "请使用 accept、edit 或 exclude。",
                "action",
                status=400,
            ) from exc
    raise ReviewPortError(
        "review_decision_invalid",
        "复核动作无效。",
        "请使用 accept、edit 或 exclude。",
        "action",
        status=400,
    )


class CurrentJobReviewApplicationService:
    """Persist single, round, or whole-job review decisions.

    The service treats each write as a new immutable review revision. Partial
    revisions are useful while a user works through a page; a Reviewed
    timeline is published only after every Draft cue has a decision.
    """

    def __init__(
        self,
        repository: object,
        *,
        claim_lease_us: int = 60_000_000,
        clock: Callable[[], datetime] | None = None,
        review_id_factory: Callable[[], str] | None = None,
        decision_id_factory: Callable[[str], str] | None = None,
    ) -> None:
        required_methods = (
            "load_job",
            "load_draft_timeline",
            "load_review_revision",
            "register_review_revision",
            "save_reviewed_timeline",
            "acquire_write",
            "replace_manifest",
        )
        if any(not callable(getattr(repository, name, None)) for name in required_methods):
            raise TypeError("repository 不符合当前复核 Job 接口。")
        resolved_clock = clock or getattr(repository, "clock", None)
        if not callable(resolved_clock):
            raise TypeError("repository 必须提供可调用的 clock。")
        if type(claim_lease_us) is not int or claim_lease_us <= 0:
            raise ValueError("claim_lease_us 必须是正整数。")
        if review_id_factory is not None and not callable(review_id_factory):
            raise TypeError("review_id_factory 必须可调用。")
        if decision_id_factory is not None and not callable(decision_id_factory):
            raise TypeError("decision_id_factory 必须可调用。")
        self.repository = repository
        self.claim_lease_us = claim_lease_us
        self.clock = resolved_clock
        self.review_id_factory = review_id_factory or (
            lambda: f"review-{uuid4().hex}"
        )
        self.decision_id_factory = decision_id_factory or (
            lambda cue_id: f"decision-{cue_id}-{uuid4().hex[:16]}"
        )

    def submit_decision(
        self,
        job_id: str,
        decision: ReviewDecision,
        *,
        expected_manifest_fingerprint: str | None = None,
    ) -> ReviewWriteReport:
        if type(decision) is not ReviewDecision:
            raise TypeError("decision 必须是 ReviewDecision。")
        return self._with_claim(
            job_id,
            lambda current, draft, existing, claim: self._commit(
                job_id,
                current,
                draft,
                existing,
                (decision,),
                claim,
                expected_manifest_fingerprint=expected_manifest_fingerprint,
            ),
        )

    def submit_decision_values(
        self,
        job_id: str,
        *,
        cue_id: str,
        round_id: str | None = None,
        action: ReviewAction | str,
        reviewer_label: str = "local-user",
        reason: str | None = None,
        reviewed_at: str | None = None,
        decision_id: str | None = None,
        revised_start_us: int | None = None,
        revised_end_us: int | None = None,
        revised_interpreted_source: str | None = None,
        revised_translated_zh: str | None = None,
        expected_manifest_fingerprint: str | None = None,
    ) -> ReviewWriteReport:
        def build(current, draft, _existing, claim):
            cue = self._cue(draft, cue_id)
            if round_id is not None and cue.round_id != round_id:
                raise ReviewPortError(
                    "cue_not_found",
                    "当前回合找不到该 Cue。",
                    "请刷新当前回合后重新选择。",
                    "cue_id",
                    status=404,
                )
            value = ReviewDecision(
                decision_id or self.decision_id_factory(cue.cue_id),
                cue.cue_id,
                cue.understanding_result_fingerprint,
                _action(action),
                reviewed_at
                or _next_timestamp(self.clock, current.manifest.updated_at),
                reviewer_label,
                reason,
                self._time_range(revised_start_us, revised_end_us),
                revised_interpreted_source,
                revised_translated_zh,
            )
            return self._commit(
                job_id,
                current,
                draft,
                _existing,
                (value,),
                claim,
                expected_manifest_fingerprint=expected_manifest_fingerprint,
            )

        return self._with_claim(job_id, build)

    def confirm_round(
        self,
        job_id: str,
        round_id: str,
        *,
        reviewer_label: str = "local-user",
        reason: str | None = None,
        reviewed_at: str | None = None,
        expected_manifest_fingerprint: str | None = None,
    ) -> ReviewWriteReport:
        def build(current, draft, existing, claim):
            cues = tuple(cue for cue in draft.cues if cue.round_id == round_id)
            if not cues and round_id not in self._authoritative_round_ids(job_id, draft):
                raise ReviewPortError(
                    "round_not_found",
                    "找不到当前版本回合。",
                    "请从当前 Job 的回合列表重新选择。",
                    "round_id",
                    status=404,
                )
            pending = [cue for cue in cues if cue.cue_id not in existing]
            stamp = reviewed_at or _next_timestamp(self.clock, current.manifest.updated_at)
            decisions = tuple(
                ReviewDecision(
                    self.decision_id_factory(cue.cue_id),
                    cue.cue_id,
                    cue.understanding_result_fingerprint,
                    ReviewAction.ACCEPT,
                    stamp,
                    reviewer_label,
                    reason,
                    None,
                    None,
                    None,
                )
                for cue in pending
            )
            return self._commit(
                job_id,
                current,
                draft,
                existing,
                decisions,
                claim,
                expected_manifest_fingerprint=expected_manifest_fingerprint,
            )

        return self._with_claim(job_id, build)

    def confirm_all(
        self,
        job_id: str,
        *,
        reviewer_label: str = "local-user",
        reason: str | None = None,
        reviewed_at: str | None = None,
        expected_manifest_fingerprint: str | None = None,
    ) -> ReviewWriteReport:
        def build(current, draft, existing, claim):
            pending = [cue for cue in draft.cues if cue.cue_id not in existing]
            stamp = reviewed_at or _next_timestamp(self.clock, current.manifest.updated_at)
            decisions = tuple(
                ReviewDecision(
                    self.decision_id_factory(cue.cue_id),
                    cue.cue_id,
                    cue.understanding_result_fingerprint,
                    ReviewAction.ACCEPT,
                    stamp,
                    reviewer_label,
                    reason,
                    None,
                    None,
                    None,
                )
                for cue in pending
            )
            return self._commit(
                job_id,
                current,
                draft,
                existing,
                decisions,
                claim,
                expected_manifest_fingerprint=expected_manifest_fingerprint,
            )

        return self._with_claim(job_id, build)

    def _with_claim(self, job_id: str, operation: Callable) -> ReviewWriteReport:
        with self.repository.acquire_write(job_id, lease_us=self.claim_lease_us) as session:
            current = self.repository.load_job(job_id)
            draft = self.repository.load_draft_timeline(job_id)
            existing = self._load_existing_decisions(job_id, current)
            return operation(current, draft, existing, session.claim)

    def _commit(
        self,
        job_id: str,
        current,
        draft,
        existing: Mapping[str, ReviewDecision],
        supplied: tuple[ReviewDecision, ...],
        claim,
        *,
        expected_manifest_fingerprint: str | None,
    ) -> ReviewWriteReport:
        if expected_manifest_fingerprint is not None and (
            current.manifest.content_fingerprint() != expected_manifest_fingerprint
        ):
            raise ReviewPortError(
                "job_manifest_conflict",
                "Job 清单已经被其他操作更新。",
                "请重新读取 Job 后基于最新状态重试。",
                "job.json",
            )
        draft_by_id = {cue.cue_id: cue for cue in draft.cues}
        merged = dict(existing)
        for decision in supplied:
            if type(decision) is not ReviewDecision:
                raise TypeError("supplied decisions 必须是 ReviewDecision。")
            cue = draft_by_id.get(decision.cue_id)
            if cue is None:
                raise ReviewPortError(
                    "review_decision_invalid",
                    "复核决策引用了不存在的 Cue。",
                    "请刷新当前 Job 后重新选择 Cue。",
                    "cue_id",
                    status=400,
                )
            if decision.source_result_fingerprint != cue.understanding_result_fingerprint:
                raise ReviewPortError(
                    "domain_fingerprint_mismatch",
                    "复核决策引用了不同版本的理解结果。",
                    "请刷新当前 Job 后基于最新 Draft 重新提交。",
                    "source_result_fingerprint",
                )
            merged[decision.cue_id] = decision
        decision_ids = [decision.decision_id.casefold() for decision in merged.values()]
        if len(decision_ids) != len(set(decision_ids)):
            raise ReviewPortError(
                "review_decision_invalid",
                "复核决策标识重复。",
                "请重新提交当前 Cue 的复核操作。",
                "decision_id",
                status=400,
            )

        if current.manifest.phase in _LATE_REVIEW_PHASES:
            current = self._rewind_for_review(job_id, current, draft, claim)
        elif current.manifest.phase not in {
            JobPhase.DRAFT_TIMELINE_READY,
            JobPhase.REVIEW_PENDING,
        }:
            raise ReviewPortError(
                "review_phase_invalid",
                "当前 Job 阶段不允许写入复核。",
                "请先完成理解翻译并生成 Draft 时间线。",
                "job.phase",
            )

        ordered_decisions = tuple(
            merged[cue.cue_id] for cue in draft.cues if cue.cue_id in merged
        )
        complete = len(ordered_decisions) == len(draft.cues)
        timeline_round_ids = self._authoritative_round_ids(job_id, draft)
        by_round: dict[str, list[ReviewDecision]] = {}
        for decision in ordered_decisions:
            by_round.setdefault(draft_by_id[decision.cue_id].round_id, []).append(decision)
        document_round_ids = timeline_round_ids if complete else tuple(
            round_id for round_id in timeline_round_ids if round_id in by_round
        )
        review_id = self._new_review_id()
        source_fingerprint = draft.content_fingerprint()
        revision = ReviewRevisionManifest(
            review_id,
            source_fingerprint,
            _next_timestamp(self.clock, current.manifest.updated_at),
            document_round_ids,
        )
        documents = tuple(
            RoundReviewDocument(
                review_id,
                round_id,
                source_fingerprint,
                tuple(by_round.get(round_id, ())),
            )
            for round_id in document_round_ids
        )
        registered = self.repository.register_review_revision(
            job_id,
            revision,
            documents,
            current.manifest.content_fingerprint(),
            False,
            claim,
        )
        activated = replace(
            current.manifest,
            updated_at=_next_timestamp(self.clock, current.manifest.updated_at),
            active_review_id=review_id,
        )
        current = self.repository.replace_manifest(
            job_id,
            current.manifest.content_fingerprint(),
            activated,
            claim,
        )
        if complete:
            reviewed = compose_reviewed_timeline(draft, ordered_decisions)
            self.repository.save_reviewed_timeline(job_id, reviewed, claim)
            current = self._advance_review_phases(job_id, current, claim)
        elif current.manifest.phase is JobPhase.DRAFT_TIMELINE_READY:
            current = self._advance(job_id, current, JobPhase.REVIEW_PENDING, claim)
        return ReviewWriteReport(
            job_id,
            registered.revision.review_id,
            source_fingerprint,
            len(ordered_decisions),
            len(draft.cues) - len(ordered_decisions),
            complete,
            current.manifest.phase,
            current.manifest.content_fingerprint(),
        )

    def _rewind_for_review(self, job_id: str, current, draft, claim):
        try:
            round_ids = tuple(dict.fromkeys(cue.round_id for cue in draft.cues))
            if not round_ids:
                round_ids = self._authoritative_round_ids(job_id, draft)
            plan = plan_invalidation(
                InvalidationRequest(JobInputChange.REVIEW_DECISION, round_ids)
            )
            rewound = rewind_job_phase_for_invalidation(
                current.manifest,
                plan,
                at=_next_timestamp(self.clock, current.manifest.updated_at),
            )
            return self.repository.replace_manifest(
                job_id,
                current.manifest.content_fingerprint(),
                rewound,
                claim,
            )
        except (DomainSchemaError, TypeError, ValueError) as exc:
            raise ReviewPortError(
                "review_phase_invalid",
                "当前 Job 无法重新打开复核阶段。",
                "请检查 Job 阶段和回合数据后重试。",
                "job.phase",
            ) from exc

    def _advance_review_phases(self, job_id: str, current, claim):
        for target in (JobPhase.REVIEW_PENDING, JobPhase.REVIEWED, JobPhase.FINAL_TIMELINE_READY):
            if current.manifest.phase is target:
                continue
            if current.manifest.phase not in {
                JobPhase.DRAFT_TIMELINE_READY,
                JobPhase.REVIEW_PENDING,
                JobPhase.REVIEWED,
            }:
                break
            current = self._advance(job_id, current, target, claim)
        return current

    def _advance(self, job_id: str, current, target: JobPhase, claim):
        try:
            candidate = advance_job_phase(
                current.manifest,
                target,
                at=_next_timestamp(self.clock, current.manifest.updated_at),
            )
        except (DomainSchemaError, TypeError, ValueError) as exc:
            raise ReviewPortError(
                "review_phase_invalid",
                "复核阶段无法推进。",
                "请重新读取 Job 并检查当前复核数据。",
                "job.phase",
            ) from exc
        return self.repository.replace_manifest(
            job_id,
            current.manifest.content_fingerprint(),
            candidate,
            claim,
        )

    def _load_existing_decisions(self, job_id: str, current) -> dict[str, ReviewDecision]:
        review_id = current.manifest.active_review_id
        if review_id is None:
            return {}
        bundle = self.repository.load_review_revision(job_id, review_id)
        return {
            decision.cue_id: decision
            for document in bundle.round_documents
            for decision in document.decisions
        }

    def _new_review_id(self) -> str:
        try:
            return require_path_identifier(self.review_id_factory(), "review_id")
        except (DomainSchemaError, TypeError, ValueError) as exc:
            raise ReviewPortError(
                "review_id_invalid",
                "无法生成复核版本标识。",
                "请重试写入复核；如持续失败请检查本地配置。",
                "review_id",
                status=500,
            ) from exc

    @staticmethod
    def _cue(draft, cue_id: str):
        if not isinstance(cue_id, str):
            raise ReviewPortError(
                "review_decision_invalid",
                "Cue 标识无效。",
                "请从当前页面选择有效 Cue。",
                "cue_id",
                status=400,
            )
        for cue in draft.cues:
            if cue.cue_id == cue_id:
                return cue
        raise ReviewPortError(
            "cue_not_found",
            "找不到当前版本 Cue。",
            "请刷新当前回合后重新选择。",
            "cue_id",
            status=404,
        )

    @staticmethod
    def _round_ids(draft) -> tuple[str, ...]:
        return tuple(dict.fromkeys(cue.round_id for cue in draft.cues))

    def _authoritative_round_ids(self, job_id: str, draft) -> tuple[str, ...]:
        fallback = self._round_ids(draft)
        loader = getattr(self.repository, "load_demo_timeline", None)
        if not callable(loader):
            return fallback
        timeline = loader(job_id)
        rounds = getattr(getattr(timeline, "rounds", None), "rounds", ())
        values = tuple(value.round_id for value in rounds)
        return values or fallback

    @staticmethod
    def _time_range(start: int | None, end: int | None) -> TimeRange | None:
        if (start is None) != (end is None):
            raise ReviewPortError(
                "review_decision_invalid",
                "修订时间范围必须同时提供开始和结束值。",
                "请完整填写修订时间范围，或同时留空。",
                "revised_time_range",
                status=400,
            )
        if start is None:
            return None
        try:
            return TimeRange(start, end)
        except (DomainSchemaError, TypeError, ValueError) as exc:
            raise ReviewPortError(
                "review_decision_invalid",
                "修订时间范围无效。",
                "请填写有效的 Demo 微秒区间。",
                "revised_time_range",
                status=400,
            ) from exc
