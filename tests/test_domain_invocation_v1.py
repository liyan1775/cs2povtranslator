import pytest
from cs2pov.domain.errors import DomainSchemaError
from cs2pov.domain.invocation import ModelCapability, ModelConfigurationSnapshot, ModelInvocationRecord
def cfg(p=None): return ModelConfigurationSnapshot("llm-config-001",ModelCapability.UNDERSTANDING_TRANSLATION,"openai-compatible","provider-local-profile","fixture-model","understanding-v1",p or {"temperature":.2,"max_tokens":512},("knowledge-global-001",),"adapter-v1")
def test_configuration_round_trip_and_derived_fingerprint():
    c=cfg(); p=c.to_dict(); assert p["schema_version"]==1 and len(p["configuration_fingerprint"])==64 and ModelConfigurationSnapshot.from_dict(p)==c
def test_configuration_defensively_copies_parameters_and_rejects_secrets():
    source={"response_format":{"type":"json_object"}}; c=cfg(source); source["response_format"]["type"]="text"; assert c.to_dict()["parameters"]["response_format"]["type"]=="json_object"
    with pytest.raises(DomainSchemaError): cfg({"headers":{"authorization":"x"}})
def test_invocation_hashes_payloads_and_allows_retry_task_identity():
    c=cfg(); a=ModelInvocationRecord.from_payloads("invoke-1",c.snapshot_id,"round-001",{"x":1},{"y":2}); b=ModelInvocationRecord.from_payloads("invoke-2",c.snapshot_id,"round-001",{"x":2},{"y":3}); assert a.task_id==b.task_id and a.request_content_fingerprint!=b.request_content_fingerprint and ModelInvocationRecord.from_dict(a.to_dict())==a
