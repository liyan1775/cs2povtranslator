from __future__ import annotations
from dataclasses import dataclass
from enum import Enum
import math
from .errors import DomainSchemaError
from .schema import (
    require_identifier,
    require_mapping,
    require_current_schema,
    require_exact_keys,
    require_str,
    require_sha256,
    reject_private_data,
)
from .fingerprint import content_fingerprint


class ModelCapability(Enum):
    ASR = "asr"
    UNDERSTANDING_TRANSLATION = "understanding_translation"


def _freeze(v):
    if isinstance(v, dict):
        if any(not isinstance(k, str) for k in v):
            raise DomainSchemaError(
                "domain_field_invalid", "参数无效。", "请修正后重试。"
            )
        return ("__dict__", tuple(sorted((k, _freeze(x)) for k, x in v.items())))
    if isinstance(v, list):
        return ("__list__", tuple(_freeze(x) for x in v))
    if isinstance(v, float) and not math.isfinite(v):
        raise DomainSchemaError("domain_field_invalid", "参数无效。", "请修正后重试。")
    if isinstance(v, (str, int, float, bool)) or v is None:
        return v
    raise DomainSchemaError("domain_field_invalid", "参数无效。", "请修正后重试。")


def _thaw(v):
    if isinstance(v, tuple):
        if len(v) == 2 and v[0] == "__dict__":
            return {k: _thaw(x) for k, x in v[1]}
        if len(v) == 2 and v[0] == "__list__":
            return [_thaw(x) for x in v[1]]
    return v


@dataclass(frozen=True, slots=True)
class ModelConfigurationSnapshot:
    snapshot_id: str
    capability: ModelCapability
    provider_kind: str
    endpoint_profile_id: str | None
    model_name: str
    prompt_template_version: str | None
    parameters: object
    knowledge_revision_ids: tuple[str, ...]
    adapter_version: str

    def __post_init__(self):
        require_identifier(self.snapshot_id, "snapshot_id")
        if not isinstance(self.capability, ModelCapability):
            raise DomainSchemaError(
                "domain_field_invalid", "配置无效。", "请修正后重试。"
            )
        for v, p in (
            (self.provider_kind, "provider_kind"),
            (self.model_name, "model_name"),
            (self.adapter_version, "adapter_version"),
        ):
            require_str(v, p)
        if self.endpoint_profile_id is not None:
            require_identifier(self.endpoint_profile_id, "endpoint_profile_id")
        if self.prompt_template_version is not None:
            require_identifier(self.prompt_template_version, "prompt_template_version")
        object.__setattr__(self, "parameters", _freeze(self.parameters))
        if not isinstance(self.knowledge_revision_ids, (tuple, list)):
            raise DomainSchemaError(
                "domain_field_invalid", "配置无效。", "请修正后重试。"
            )
        object.__setattr__(
            self,
            "knowledge_revision_ids",
            tuple(
                require_identifier(x, "knowledge_revision_id")
                for x in self.knowledge_revision_ids
            ),
        )
        reject_private_data(self.to_dict(include_fingerprint=False), "configuration")

    def _payload(self):
        return {
            "snapshot_id": self.snapshot_id,
            "capability": self.capability.value,
            "provider_kind": self.provider_kind,
            "endpoint_profile_id": self.endpoint_profile_id,
            "model_name": self.model_name,
            "prompt_template_version": self.prompt_template_version,
            "parameters": _thaw(self.parameters),
            "knowledge_revision_ids": list(self.knowledge_revision_ids),
            "adapter_version": self.adapter_version,
        }

    @property
    def configuration_fingerprint(self):
        return content_fingerprint(self._payload())

    def to_dict(self, include_fingerprint=True):
        p = {"schema_version": 1, **self._payload()}
        if include_fingerprint:
            p["configuration_fingerprint"] = self.configuration_fingerprint
        return p

    @classmethod
    def from_dict(cls, d):
        d = require_mapping(d, "configuration")
        reject_private_data(d, "configuration")
        require_current_schema(d, "configuration")
        require_exact_keys(
            d,
            {
                "schema_version",
                "snapshot_id",
                "capability",
                "provider_kind",
                "endpoint_profile_id",
                "model_name",
                "prompt_template_version",
                "parameters",
                "knowledge_revision_ids",
                "adapter_version",
                "configuration_fingerprint",
            },
            set(),
            "configuration",
        )
        try:
            cap = ModelCapability(d["capability"])
        except ValueError:
            raise DomainSchemaError(
                "domain_field_invalid", "配置无效。", "请修正后重试。"
            )
        if not isinstance(d["knowledge_revision_ids"], (list, tuple)):
            raise DomainSchemaError(
                "domain_field_invalid", "配置无效。", "请修正后重试。"
            )
        c = cls(
            require_identifier(d["snapshot_id"], "snapshot_id"),
            cap,
            require_str(d["provider_kind"], "provider_kind"),
            d["endpoint_profile_id"],
            require_str(d["model_name"], "model_name"),
            d["prompt_template_version"],
            d["parameters"],
            tuple(d["knowledge_revision_ids"]),
            require_str(d["adapter_version"], "adapter_version"),
        )
        if c.configuration_fingerprint != d["configuration_fingerprint"]:
            raise DomainSchemaError(
                "domain_fingerprint_mismatch", "指纹不匹配。", "请重新生成。"
            )
        return c


@dataclass(frozen=True, slots=True)
class ModelInvocationRecord:
    invocation_id: str
    configuration_snapshot_id: str
    task_id: str
    request_content_fingerprint: str
    response_content_fingerprint: str

    def __post_init__(self):
        for v, p in (
            (self.invocation_id, "invocation_id"),
            (self.configuration_snapshot_id, "configuration_snapshot_id"),
            (self.task_id, "task_id"),
        ):
            require_identifier(v, p)
        require_sha256(self.request_content_fingerprint, "request_content_fingerprint")
        require_sha256(
            self.response_content_fingerprint, "response_content_fingerprint"
        )

    @classmethod
    def from_payloads(
        cls,
        invocation_id,
        configuration_snapshot_id,
        task_id,
        request_payload,
        response_payload,
    ):
        return cls(
            invocation_id,
            configuration_snapshot_id,
            task_id,
            content_fingerprint(request_payload),
            content_fingerprint(response_payload),
        )

    def to_dict(self):
        return {
            "schema_version": 1,
            "invocation_id": self.invocation_id,
            "configuration_snapshot_id": self.configuration_snapshot_id,
            "task_id": self.task_id,
            "request_content_fingerprint": self.request_content_fingerprint,
            "response_content_fingerprint": self.response_content_fingerprint,
        }

    @classmethod
    def from_dict(cls, d):
        d = require_mapping(d, "invocation")
        reject_private_data(d, "invocation")
        require_current_schema(d, "invocation")
        require_exact_keys(
            d,
            {
                "schema_version",
                "invocation_id",
                "configuration_snapshot_id",
                "task_id",
                "request_content_fingerprint",
                "response_content_fingerprint",
            },
            set(),
            "invocation",
        )
        return cls(
            d["invocation_id"],
            d["configuration_snapshot_id"],
            d["task_id"],
            d["request_content_fingerprint"],
            d["response_content_fingerprint"],
        )
