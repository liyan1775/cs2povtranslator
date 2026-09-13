from __future__ import annotations

import asyncio
from dataclasses import replace

import pytest

from cs2pov.adapters.llm_adapter import LLMAdapterError
from cs2pov.application import translation_ports
from cs2pov.application.translation_ports import (
    LegacyRoundTranslationWorker,
    OpenAICompatibleTranslationProvider,
    TranslationProviderError,
)
from cs2pov.application.round_worker import RoundWorkFailure
from cs2pov.domain.invocation import ModelConfigurationSnapshot
from test_domain_validation_v1 import _understanding_graph
from test_translation_ports_v1 import _request


def _configuration(**parameters: object) -> ModelConfigurationSnapshot:
    configuration = _understanding_graph()[5]
    return replace(configuration, parameters=parameters or {"temperature": 0.2})


def test_real_provider_boundary_uses_snapshot_model_and_timeout_without_persisting_secret(
    monkeypatch,
):
    calls: list[dict[str, object]] = []

    class FakeLLM:
        def __init__(self, **kwargs: object) -> None:
            calls.append(kwargs)

        def chat_json(self, system_prompt: str, user_prompt: str) -> object:
            assert system_prompt and user_prompt
            return {"results": []}

    monkeypatch.setattr(translation_ports, "OpenAICompatibleLLM", FakeLLM)
    configuration = _configuration(timeout_seconds=37)
    provider = OpenAICompatibleTranslationProvider(
        base_url="https://provider.example",
        api_key="secret-token-held-at-boundary",
        default_timeout_seconds=19,
    )

    assert provider.chat_json(configuration, "system", "user") == {"results": []}
    assert calls == [
        {
            "base_url": "https://provider.example",
            "api_key": "secret-token-held-at-boundary",
            "model": configuration.model_name,
            "timeout_seconds": 37,
        }
    ]
    durable = configuration.to_dict()
    assert "api_key" not in durable
    assert "secret-token-held-at-boundary" not in repr(durable)


@pytest.mark.parametrize("timeout", [0, 601, True, "37"])
def test_provider_rejects_invalid_snapshot_timeout_before_network(timeout, monkeypatch):
    called = False

    def fail_if_called(**kwargs: object):
        nonlocal called
        called = True
        raise AssertionError("provider client must not be created")

    monkeypatch.setattr(translation_ports, "OpenAICompatibleLLM", fail_if_called)
    configuration = _configuration(timeout_seconds=timeout)
    provider = OpenAICompatibleTranslationProvider(
        base_url="https://provider.example", api_key="secret"
    )

    with pytest.raises(TranslationProviderError) as caught:
        provider.chat_json(configuration, "system", "user")
    assert caught.value.code == "provider_configuration_invalid"
    assert caught.value.retryable is False
    assert called is False


def test_provider_client_failures_are_classified_by_worker_boundary(monkeypatch):
    class FailingLLM:
        def __init__(self, **kwargs: object) -> None:
            pass

        def chat_json(self, system_prompt: str, user_prompt: str) -> object:
            raise LLMAdapterError("raw provider detail and secret-token")

    monkeypatch.setattr(translation_ports, "OpenAICompatibleLLM", FailingLLM)
    provider = OpenAICompatibleTranslationProvider(
        base_url="https://provider.example", api_key="secret-token"
    )
    with pytest.raises(LLMAdapterError):
        provider.chat_json(_configuration(), "system", "user")

    request = _request(_configuration())
    with pytest.raises(RoundWorkFailure) as caught:
        asyncio.run(
            LegacyRoundTranslationWorker(
                provider,
                invocation_id_factory=iter(["invoke-provider-boundary"]).__next__,
            ).translate(request)
        )
    assert caught.value.error.code == "provider_unavailable"
    assert caught.value.error.retryable is True
    assert "raw provider detail" not in repr(caught.value.error)
    assert "secret-token" not in repr(caught.value.error)
