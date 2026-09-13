"""Translation worker and current Job scheduler integration contracts."""

import asyncio
from dataclasses import replace

import pytest

from cs2pov.application.round_scheduler import RoundSchedulerSettings
from cs2pov.application.round_worker import (
    RoundWorkFailure,
    build_round_work_request,
    validate_round_work_result,
)
from cs2pov.application.translation_ports import (
    CurrentJobTranslationApplicationService,
    LegacyRoundTranslationWorker,
    TranslationProviderError,
)
from cs2pov.domain.fingerprint import content_fingerprint
from cs2pov.domain.invocation import ModelConfigurationSnapshot
from cs2pov.domain.job import JobPhase
from cs2pov.domain.job_tasks import RetryPolicy, RoundTranslationTask
from cs2pov.domain.understanding import RoundUnderstandingDocument
from test_domain_validation_v1 import _understanding_graph
from test_job_round_coordinator_v1 import _coordinator


def _request(configuration: ModelConfigurationSnapshot | None = None):
    timeline, _, cue, _, _, original, _, _ = _understanding_graph()
    configuration = configuration or original
    document_input_fingerprint = content_fingerprint(
        {"round_id": "round-001", "transcript_cues": [cue.to_dict()]}
    )
    task = RoundTranslationTask.pending(
        task_id="round-001",
        round_id="round-001",
        input_fingerprint=content_fingerprint(
            {
                "document_input_fingerprint": document_input_fingerprint,
                "configuration_fingerprint": configuration.configuration_fingerprint,
            }
        ),
        configuration_snapshot_id=configuration.snapshot_id,
        updated_at="2026-09-13T00:00:00.000000Z",
    )
    return build_round_work_request(
        task=task,
        round=timeline.rounds.rounds[0],
        configuration=configuration,
        transcripts=(cue,),
    )


def _settings(max_attempts: int = 1) -> RoundSchedulerSettings:
    return RoundSchedulerSettings(
        2,
        10_000_000,
        1_000_000,
        RetryPolicy(max_attempts, 1, 8_000_000),
    )


@pytest.mark.parametrize(
    ("mode", "expected"),
    [
        ("dry_run", "[演示翻译] one jungle"),
        ("skip", "[未翻译：已跳过翻译]"),
    ],
)
def test_worker_maps_local_translation_modes_to_auditable_results(mode, expected):
    _, _, _, _, _, configuration, _, _ = _understanding_graph()
    configuration = replace(
        configuration,
        snapshot_id=f"llm-{mode}",
        parameters={"mode": mode},
    )
    request = _request(configuration)
    result = asyncio.run(
        LegacyRoundTranslationWorker(
            invocation_id_factory=iter([f"invoke-{mode}"]).__next__
        ).translate(request)
    )

    validate_round_work_result(request, result)
    assert isinstance(result.document, RoundUnderstandingDocument)
    assert result.document.results[0].translated_zh == expected
    assert result.invocations[0].request_content_fingerprint == request.document_input_fingerprint


class _Provider:
    def __init__(self, response=None, error=None):
        self.response = response
        self.error = error
        self.calls = []

    def chat_json(self, configuration, system_prompt, user_prompt):
        self.calls.append((configuration.snapshot_id, configuration.model_name, user_prompt))
        if self.error is not None:
            raise self.error
        return self.response


def test_worker_adapts_legacy_translation_shape_and_uses_snapshot_model():
    request = _request()
    provider = _Provider(
        {"translations": [{"id": "cue-alpha-001", "translated_text": "警家一个"}]}
    )
    result = asyncio.run(
        LegacyRoundTranslationWorker(
            provider,
            invocation_id_factory=iter(["invoke-provider-001"]).__next__,
        ).translate(request)
    )

    validate_round_work_result(request, result)
    assert provider.calls[0][0] == request.configuration.snapshot_id
    assert provider.calls[0][1] == request.configuration.model_name
    assert result.document.results[0].interpreted_source == "one jungle"
    assert result.document.results[0].translated_zh == "警家一个"
    assert result.document.results[0].evidence == ("provider_translation",)


def test_worker_maps_provider_errors_without_persisting_raw_details():
    request = _request()
    provider = _Provider(
        error=RuntimeError("raw provider detail C:/secret and 12345678901234567")
    )
    with pytest.raises(RoundWorkFailure) as caught:
        asyncio.run(
            LegacyRoundTranslationWorker(
                provider,
                invocation_id_factory=iter(["invoke-provider-error"]).__next__,
            ).translate(request)
        )

    failure = caught.value
    assert failure.error.code == "provider_unavailable"
    assert failure.error.retryable is True
    assert "raw provider detail" not in failure.error.message_zh
    assert "C:/secret" not in repr(failure.error)
    assert "12345678901234567" not in repr(failure.error)


def test_worker_rejects_unconfigured_provider_as_non_retryable():
    request = _request()
    with pytest.raises(RoundWorkFailure) as caught:
        asyncio.run(LegacyRoundTranslationWorker().translate(request))
    assert caught.value.error.code == "translation_provider_unavailable"
    assert caught.value.error.retryable is False


def test_current_job_service_persists_translation_and_advances_from_snapshot(tmp_path):
    workspace, repository, _, claim, values, _ = _coordinator(tmp_path)
    repository._release_write("job-language", claim)
    provider = _Provider(
        {"results": [{"id": "cue-alpha-001", "translated_zh": "警家一个", "confidence": 0.93}]}
    )
    worker = LegacyRoundTranslationWorker(
        provider,
        invocation_id_factory=iter(["invoke-service-001"]).__next__,
    )
    service = CurrentJobTranslationApplicationService(
        repository,
        worker,
        settings=_settings(),
        sleep=lambda _: asyncio.sleep(0),
        event_id_factory=iter(["event-service-001", "event-service-002", "event-service-003", "event-service-004", "event-service-005", "event-service-006", "event-service-007", "event-service-008"]).__next__,
        attempt_id_factory=iter(["attempt-service-001"]).__next__,
    )

    report = service.run(
        "job-language",
        configuration_snapshot_id=values[5].snapshot_id,
    )

    assert report.tasks[0].status.value == "succeeded"
    assert repository.load_job("job-language").manifest.phase is JobPhase.UNDERSTOOD_TRANSLATED
    document = repository.load_round_understanding("job-language", "round-001")
    assert document.results[0].translated_zh == "警家一个"
    assert document.invocation_record_id == "invoke-service-001"
    assert provider.calls[0][0] == values[5].snapshot_id
    reopened = type(repository)(workspace, repository.demo_assets, clock=repository.clock)
    assert reopened.load_round_understanding("job-language", "round-001") == document


def test_provider_busy_is_mapped_to_retryable_round_failure():
    request = _request()
    provider = _Provider(
        error=TranslationProviderError(
            "provider_busy", retryable=True, retry_after_us=3_000_000
        )
    )
    with pytest.raises(RoundWorkFailure) as caught:
        asyncio.run(
            LegacyRoundTranslationWorker(
                provider,
                invocation_id_factory=iter(["invoke-provider-busy"]).__next__,
            ).translate(request)
        )
    assert caught.value.error.code == "provider_busy"
    assert caught.value.error.retry_after_us == 3_000_000
