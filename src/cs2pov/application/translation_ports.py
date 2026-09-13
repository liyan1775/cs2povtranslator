"""Current Job translation ports and the legacy LLM adapter boundary.

The worker receives only the privacy-minimal round projection.  The
coordinator remains responsible for rebuilding the full transcript graph and
publishing a result through the claim-fenced repository.
"""

from __future__ import annotations

import asyncio
import json
import re
import uuid
from collections.abc import Callable, Mapping
from typing import Protocol

from cs2pov.adapters.llm_adapter import LLMAdapterError, OpenAICompatibleLLM
from cs2pov.domain.errors import DomainSchemaError
from cs2pov.domain.fingerprint import content_fingerprint
from cs2pov.domain.invocation import (
    ModelConfigurationSnapshot,
    ModelInvocationRecord,
)
from cs2pov.domain.job import JobPhase
from cs2pov.domain.job_tasks import RoundTaskError
from cs2pov.domain.understanding import (
    RoundUnderstandingDocument,
    UnderstandingResult,
)
from cs2pov.storage.job_errors import JobRepositoryError

from .job_coordinator import JobRoundCoordinator
from .round_scheduler import RoundBatchReport, RoundScheduler, RoundSchedulerSettings
from .round_worker import (
    RoundTranslationWorker,
    RoundWorkFailure,
    RoundWorkRequest,
    RoundWorkResult,
)


try:
    from cs2pov.services.translation_service import SYSTEM_PROMPT as _LEGACY_SYSTEM_PROMPT
except ImportError:  # pragma: no cover - defensive for isolated packaging
    _LEGACY_SYSTEM_PROMPT = "你是一个熟悉 CS2 队内语音的翻译助手。"


UNDERSTANDING_TRANSLATION_SYSTEM_PROMPT = (
    _LEGACY_SYSTEM_PROMPT
    + "\n"
    + "当前接口还需要为每条输入返回 interpreted_source、translated_text、"
    + "confidence、evidence 和 warnings；JSON 顶层键使用 results，条目 id 必须对应输入。"
)


class TranslationPortError(RuntimeError):
    """Stable application error before a round task is started."""

    def __init__(self, code: str, message_zh: str, suggestion_zh: str, path: str):
        self.code = code
        self.message_zh = message_zh
        self.suggestion_zh = suggestion_zh
        self.path = path
        super().__init__(message_zh)


class TranslationProviderError(RuntimeError):
    """Provider boundary error with a curated durable classification."""

    def __init__(self, code: str, *, retryable: bool, retry_after_us: int | None = None):
        self.code = code
        self.retryable = retryable
        self.retry_after_us = retry_after_us
        super().__init__(code)


class TranslationProviderPort(Protocol):
    def chat_json(
        self,
        configuration: ModelConfigurationSnapshot,
        system_prompt: str,
        user_prompt: str,
    ) -> object: ...


class OpenAICompatibleTranslationProvider:
    """Resolve secrets outside the worker and use the Job snapshot for model settings."""

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        default_timeout_seconds: int = 60,
    ) -> None:
        if not isinstance(base_url, str) or not base_url.strip():
            raise ValueError("base_url 必须是非空字符串。")
        if not isinstance(api_key, str) or not api_key.strip():
            raise ValueError("api_key 必须是非空字符串。")
        if (
            type(default_timeout_seconds) is not int
            or not 1 <= default_timeout_seconds <= 600
        ):
            raise ValueError("default_timeout_seconds 必须在 1 到 600 之间。")
        self._base_url = base_url
        self._api_key = api_key
        self._default_timeout_seconds = default_timeout_seconds

    def chat_json(
        self,
        configuration: ModelConfigurationSnapshot,
        system_prompt: str,
        user_prompt: str,
    ) -> object:
        parameters = _configuration_parameters(configuration)
        timeout = parameters.get(
            "timeout_seconds", self._default_timeout_seconds
        )
        if type(timeout) is not int or not 1 <= timeout <= 600:
            raise TranslationProviderError(
                "provider_configuration_invalid", retryable=False
            )
        client = OpenAICompatibleLLM(
            base_url=self._base_url,
            api_key=self._api_key,
            model=configuration.model_name,
            timeout_seconds=timeout,
        )
        return client.chat_json(system_prompt, user_prompt)


def _configuration_parameters(
    configuration: ModelConfigurationSnapshot,
) -> dict[str, object]:
    value = configuration.to_dict(include_fingerprint=False).get("parameters")
    return dict(value) if isinstance(value, Mapping) else {}


def _translation_mode(configuration: ModelConfigurationSnapshot) -> str:
    parameters = _configuration_parameters(configuration)
    mode = parameters.get("translation_mode", parameters.get("mode", "provider"))
    if parameters.get("skip_translation") is True or mode in {
        "skip",
        "skipped",
        "skip_translation",
    }:
        return "skip"
    if parameters.get("dry_run") is True or mode == "dry_run":
        return "dry_run"
    return "provider"


def _safe_invocation_id(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise DomainSchemaError(
            "domain_field_invalid", "调用记录标识无效。", "请修正后重试。", "invocation_id"
        )
    # ModelInvocationRecord performs the complete identifier validation; this
    # early check keeps a malformed injected factory inside the controlled
    # worker error mapping.
    if re.search(r"[^A-Za-z0-9_.-]", value):
        raise DomainSchemaError(
            "domain_field_invalid", "调用记录标识无效。", "请修正后重试。", "invocation_id"
        )
    return value


def _default_invocation_id() -> str:
    return f"invoke-translation-{uuid.uuid4().hex}"


def _provider_request(request: RoundWorkRequest) -> dict[str, object]:
    return {
        "round_id": request.round_id,
        "round_number": request.round_number,
        "segments": [
            {
                "id": cue.cue_id,
                "speaker": cue.speaker_token,
                "start_us": cue.start_us,
                "end_us": cue.end_us,
                "language": cue.language,
                "text": cue.asr_original,
            }
            for cue in request.cues
        ],
    }


def _user_prompt(request: RoundWorkRequest) -> str:
    parameters = _configuration_parameters(request.configuration)
    payload = _provider_request(request)
    payload["map_name"] = parameters.get("map_name")
    payload["glossary"] = parameters.get("glossary", [])
    payload["output_contract"] = {
        "results": [
            {
                "id": "input segment id",
                "interpreted_source": "normalized source meaning",
                "translated_text": "natural Chinese subtitle",
                "confidence": "number from 0 to 1",
                "evidence": ["short reason"],
                "warnings": [],
            }
        ]
    }
    return "请按 output_contract 返回本回合的理解和翻译结果。\n" + json.dumps(
        payload, ensure_ascii=False, sort_keys=True
    )


def _as_text(value: object, *, fallback: str | None = None) -> str:
    if value is None and fallback is not None:
        return fallback
    if not isinstance(value, str) or not value.strip():
        raise ValueError("text is empty")
    return value.strip()


def _as_string_tuple(value: object, *, default: tuple[str, ...]) -> tuple[str, ...]:
    if value is None:
        return default
    if isinstance(value, str):
        value = (value,)
    if not isinstance(value, (tuple, list)):
        raise ValueError("string list is invalid")
    result = tuple(item.strip() for item in value if isinstance(item, str) and item.strip())
    return result or default


def _as_confidence(value: object) -> float:
    if value is None:
        return 0.8
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("confidence is invalid")
    confidence = float(value)
    if confidence != confidence or confidence in {float("inf"), float("-inf")}:
        raise ValueError("confidence is invalid")
    if not 0.0 <= confidence <= 1.0:
        raise ValueError("confidence is invalid")
    return confidence


def _response_rows(payload: object) -> tuple[object, ...]:
    if not isinstance(payload, Mapping):
        raise ValueError("provider response is not an object")
    rows = payload.get("results", payload.get("translations"))
    if not isinstance(rows, (tuple, list)):
        raise ValueError("provider response results are invalid")
    return tuple(rows)


def _provider_results(
    request: RoundWorkRequest, payload: object
) -> tuple[UnderstandingResult, ...]:
    rows = _response_rows(payload)
    by_id: dict[str, Mapping[str, object]] = {}
    for row in rows:
        if not isinstance(row, Mapping):
            raise ValueError("provider response item is invalid")
        cue_id = row.get("id", row.get("cue_id"))
        if not isinstance(cue_id, str) or cue_id in by_id:
            raise ValueError("provider response id is invalid")
        by_id[cue_id] = row
    expected = {cue.cue_id for cue in request.cues}
    if set(by_id) != expected:
        raise ValueError("provider response does not cover the input")

    results = []
    for cue in request.cues:
        row = by_id[cue.cue_id]
        translated = row.get("translated_zh", row.get("translated_text"))
        interpreted = row.get("interpreted_source", row.get("source"))
        evidence = _as_string_tuple(
            row.get("evidence"), default=("provider_translation",)
        )
        warnings = _as_string_tuple(row.get("warnings"), default=())
        results.append(
            UnderstandingResult(
                cue.cue_id,
                request.round_id,
                cue.asr_original,
                _as_text(interpreted, fallback=cue.asr_original),
                _as_text(translated),
                _as_confidence(row.get("confidence")),
                evidence,
                warnings,
                "pending-invocation",
            )
        )
    return tuple(results)


def _response_payload(
    round_id: str, results: tuple[UnderstandingResult, ...]
) -> dict[str, object]:
    return {
        "round_id": round_id,
        "results": [result.to_dict() for result in results],
    }


def _replace_invocation_id(
    results: tuple[UnderstandingResult, ...], invocation_id: str
) -> tuple[UnderstandingResult, ...]:
    return tuple(
        UnderstandingResult(
            result.cue_id,
            result.round_id,
            result.asr_original,
            result.interpreted_source,
            result.translated_zh,
            result.confidence,
            result.evidence,
            result.warnings,
            invocation_id,
        )
        for result in results
    )


class LegacyRoundTranslationWorker:
    """Adapt the existing OpenAI-compatible response to the current worker contract."""

    def __init__(
        self,
        provider: TranslationProviderPort | None = None,
        *,
        invocation_id_factory: Callable[[], str] | None = None,
    ) -> None:
        if provider is not None and not callable(getattr(provider, "chat_json", None)):
            raise TypeError("provider 必须实现 chat_json。")
        if invocation_id_factory is not None and not callable(invocation_id_factory):
            raise TypeError("invocation_id_factory 必须可调用。")
        self.provider = provider
        self.invocation_id_factory = invocation_id_factory or _default_invocation_id

    def _new_invocation(
        self, request: RoundWorkRequest, response_payload: object
    ) -> ModelInvocationRecord:
        invocation_id = _safe_invocation_id(self.invocation_id_factory())
        return ModelInvocationRecord(
            invocation_id,
            request.configuration.snapshot_id,
            request.task_id,
            request.document_input_fingerprint,
            content_fingerprint(response_payload),
        )

    def _failure(
        self,
        request: RoundWorkRequest,
        *,
        code: str,
        message_zh: str,
        impact_zh: str,
        suggestion_zh: str,
        retryable: bool,
        retry_after_us: int | None = None,
        cause: BaseException | None = None,
    ) -> RoundWorkFailure:
        error = RoundTaskError(
            code,
            message_zh,
            impact_zh,
            suggestion_zh,
            retryable,
            retry_after_us,
        )
        invocations = ()
        if request.cues:
            invocations = (
                self._new_invocation(
                    request, {"status": "failed", "error_code": code}
                ),
            )
        return RoundWorkFailure(error, invocations, cause=cause)

    def _mode_result(self, request: RoundWorkRequest, mode: str) -> RoundWorkResult:
        results = tuple(
            UnderstandingResult(
                cue.cue_id,
                request.round_id,
                cue.asr_original,
                cue.asr_original,
                (
                    f"[演示翻译] {cue.asr_original}"
                    if mode == "dry_run"
                    else "[未翻译：已跳过翻译]"
                ),
                0.0,
                ("dry_run",) if mode == "dry_run" else ("translation_skipped",),
                ("translation_dry_run",)
                if mode == "dry_run"
                else ("translation_skipped",),
                "pending-invocation",
            )
            for cue in request.cues
        )
        invocation_id = _safe_invocation_id(self.invocation_id_factory())
        results = _replace_invocation_id(results, invocation_id)
        invocation = ModelInvocationRecord(
            invocation_id,
            request.configuration.snapshot_id,
            request.task_id,
            request.document_input_fingerprint,
            content_fingerprint(_response_payload(request.round_id, results)),
        )
        document = RoundUnderstandingDocument(
            request.round_id,
            request.document_input_fingerprint,
            request.configuration.snapshot_id,
            invocation.invocation_id,
            results,
        )
        return RoundWorkResult(document, (invocation,))

    def _provider_failure(
        self, request: RoundWorkRequest, exc: BaseException
    ) -> RoundWorkFailure:
        if isinstance(exc, TranslationProviderError):
            code = exc.code
            retryable = exc.retryable
            retry_after_us = exc.retry_after_us
        elif isinstance(exc, LLMAdapterError):
            text = str(exc).lower()
            if "未返回合法 json" in text or "invalid json" in text:
                code, retryable, retry_after_us = "provider_invalid_response", False, None
            elif any(token in text for token in ("http 401", "http 403", "http 404")):
                code, retryable, retry_after_us = "provider_configuration_invalid", False, None
            elif "http 429" in text or re.search(r"http 5[0-9]{2}", text):
                code, retryable, retry_after_us = "provider_busy", True, 5_000_000
            else:
                code, retryable, retry_after_us = "provider_unavailable", True, 5_000_000
        else:
            code, retryable, retry_after_us = "provider_unavailable", True, 5_000_000

        messages = {
            "provider_invalid_response": (
                "翻译服务返回的数据格式无效。",
                "本回合未保存。",
                "请检查模型输出格式后重试。",
            ),
            "provider_configuration_invalid": (
                "翻译服务配置无效。",
                "本回合未保存。",
                "请检查服务地址、模型和访问权限。",
            ),
            "provider_busy": (
                "翻译服务暂时繁忙。",
                "本回合未完成。",
                "系统会按重试策略稍后重试。",
            ),
            "provider_unavailable": (
                "翻译服务暂时不可用。",
                "本回合未完成。",
                "请检查网络或服务状态，系统会按重试策略处理。",
            ),
        }
        message_zh, impact_zh, suggestion_zh = messages.get(
            code,
            (
                "翻译服务调用失败。",
                "本回合未完成。",
                "请检查翻译服务后重试。",
            ),
        )
        return self._failure(
            request,
            code=code,
            message_zh=message_zh,
            impact_zh=impact_zh,
            suggestion_zh=suggestion_zh,
            retryable=retryable,
            retry_after_us=retry_after_us,
            cause=exc,
        )

    async def translate(self, request: RoundWorkRequest) -> RoundWorkResult:
        mode = _translation_mode(request.configuration)
        if not request.cues:
            document = RoundUnderstandingDocument(
                request.round_id,
                request.document_input_fingerprint,
                request.configuration.snapshot_id,
                None,
                (),
            )
            return RoundWorkResult(document, ())
        if mode in {"dry_run", "skip"}:
            return self._mode_result(request, mode)
        if self.provider is None:
            raise self._failure(
                request,
                code="translation_provider_unavailable",
                message_zh="尚未配置翻译服务。",
                impact_zh="本回合未保存。",
                suggestion_zh="请配置翻译服务，或选择 dry-run 或跳过翻译。",
                retryable=False,
            )

        try:
            payload = await asyncio.to_thread(
                self.provider.chat_json,
                request.configuration,
                UNDERSTANDING_TRANSLATION_SYSTEM_PROMPT,
                _user_prompt(request),
            )
            parsed = _provider_results(request, payload)
            invocation_id = _safe_invocation_id(self.invocation_id_factory())
            parsed = _replace_invocation_id(parsed, invocation_id)
            response = _response_payload(request.round_id, parsed)
            invocation = ModelInvocationRecord(
                invocation_id,
                request.configuration.snapshot_id,
                request.task_id,
                request.document_input_fingerprint,
                content_fingerprint(response),
            )
            document = RoundUnderstandingDocument(
                request.round_id,
                request.document_input_fingerprint,
                request.configuration.snapshot_id,
                invocation_id,
                parsed,
            )
            return RoundWorkResult(document, (invocation,))
        except (TranslationProviderError, LLMAdapterError) as exc:
            raise self._provider_failure(request, exc) from exc
        except (DomainSchemaError, TypeError, ValueError) as exc:
            raise self._failure(
                request,
                code="provider_invalid_response",
                message_zh="翻译结果未通过格式校验。",
                impact_zh="本回合未保存。",
                suggestion_zh="请检查模型输出格式后重试。",
                retryable=False,
                cause=exc,
            ) from exc
        except Exception as exc:
            raise self._provider_failure(request, exc) from exc


class CurrentJobTranslationApplicationService:
    """Start the current Job round scheduler from a registered configuration snapshot."""

    def __init__(
        self,
        repository: object,
        worker: RoundTranslationWorker,
        *,
        settings: RoundSchedulerSettings,
        clock: Callable | None = None,
        event_id_factory: Callable[[], str] | None = None,
        sleep: Callable | None = None,
        attempt_id_factory: Callable[[], str] | None = None,
    ) -> None:
        required_methods = (
            "load_job",
            "load_model_configuration",
            "acquire_write",
            "load_round_tasks",
        )
        if any(not callable(getattr(repository, name, None)) for name in required_methods):
            raise TypeError("repository 不符合当前翻译 Job 接口。")
        if not hasattr(worker, "translate") or not callable(worker.translate):
            raise TypeError("worker 必须实现 translate。")
        if not isinstance(settings, RoundSchedulerSettings):
            raise TypeError("settings 必须是 RoundSchedulerSettings。")
        resolved_clock = clock or getattr(repository, "clock", None)
        if not callable(resolved_clock):
            raise TypeError("repository 必须提供可调用的 clock。")
        self.repository = repository
        self.worker = worker
        self.settings = settings
        self.clock = resolved_clock
        self.event_id_factory = event_id_factory or (
            lambda: f"event-translation-{uuid.uuid4().hex}"
        )
        self.sleep = sleep
        self.attempt_id_factory = attempt_id_factory

    async def run_async(
        self,
        job_id: str,
        *,
        configuration_snapshot_id: str,
        cancel_event: asyncio.Event | None = None,
        retry_round_ids: tuple[str, ...] = (),
    ) -> RoundBatchReport:
        opened = self.repository.load_job(job_id)
        if opened.manifest.phase not in {
            JobPhase.CONTEXT_READY,
            JobPhase.UNDERSTANDING_TRANSLATING,
        }:
            raise TranslationPortError(
                "pipeline_phase_invalid",
                "当前 Job 不允许执行理解翻译。",
                "请从上下文就绪或理解翻译中的阶段继续。",
                "job.phase",
            )
        try:
            configuration = self.repository.load_model_configuration(
                job_id, configuration_snapshot_id
            )
        except JobRepositoryError:
            raise
        if configuration.snapshot_id != configuration_snapshot_id:
            raise TranslationPortError(
                "pipeline_configuration_invalid",
                "模型配置快照与请求不一致。",
                "请重新选择当前 Job 已登记的理解翻译配置。",
                "models/snapshots",
            )
        coordinator = JobRoundCoordinator(
            self.repository,
            clock=self.clock,
            event_id_factory=self.event_id_factory,
        )
        scheduler = RoundScheduler(
            coordinator,
            self.worker,
            clock=self.clock,
            **({"sleep": self.sleep} if self.sleep is not None else {}),
            **(
                {"attempt_id_factory": self.attempt_id_factory}
                if self.attempt_id_factory is not None
                else {}
            ),
        )
        return await scheduler.run(
            job_id,
            configuration_snapshot_id=configuration.snapshot_id,
            settings=self.settings,
            cancel_event=cancel_event,
            retry_round_ids=retry_round_ids,
        )

    def run(
        self,
        job_id: str,
        *,
        configuration_snapshot_id: str,
        cancel_event: asyncio.Event | None = None,
        retry_round_ids: tuple[str, ...] = (),
    ) -> RoundBatchReport:
        return asyncio.run(
            self.run_async(
                job_id,
                configuration_snapshot_id=configuration_snapshot_id,
                cancel_event=cancel_event,
                retry_round_ids=retry_round_ids,
            )
        )
