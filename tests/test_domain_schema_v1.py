from __future__ import annotations
import pytest
from cs2pov.domain.errors import DomainSchemaError
from cs2pov.domain.fingerprint import canonical_json_bytes, content_fingerprint
from cs2pov.domain.schema import CURRENT_DOMAIN_SCHEMA_VERSION, MAX_DEMO_TIME_US, reject_private_data, reject_secret_keys, require_current_schema, require_identifier, require_int, require_probability

def test_domain_schema_error_exposes_stable_diagnostic_fields():
    error=DomainSchemaError("time_range_invalid","时间范围无效。","请修正后重试。","cue.start_us")
    assert str(error)=="时间范围无效。" and error.code=="time_range_invalid" and error.message=="时间范围无效。" and error.action=="请修正后重试。" and error.path=="cue.start_us"
def test_current_schema_accepts_only_exact_integer_one():
    assert CURRENT_DOMAIN_SCHEMA_VERSION==1 and require_current_schema({"schema_version":1},"document")==1
    for value in (True,0,2,"1",1.0,None):
        with pytest.raises(DomainSchemaError) as e: require_current_schema({"schema_version":value},"document")
        assert e.value.code=="domain_schema_unsupported"
def test_integer_validator_rejects_bool_and_negative_values():
    assert require_int(0,"value",minimum=0)==0
    for value in (True,-1,1.5,"1"):
        with pytest.raises(DomainSchemaError) as e: require_int(value,"value",minimum=0)
        assert e.value.code=="domain_field_invalid"
def test_identifier_is_safe_as_one_cross_platform_path_segment():
    assert require_identifier("round-001","round_id")=="round-001"
    for value in ("",".","..","CON","nul.txt","COM1","round/1",r"round\1","B 点","x"*129):
        with pytest.raises(DomainSchemaError) as e: require_identifier(value,"round_id")
        assert e.value.code=="domain_identifier_invalid"
def test_probability_is_finite_and_between_zero_and_one():
    assert require_probability(0,"confidence")==0.0 and require_probability(.86,"confidence")==.86 and require_probability(1,"confidence")==1.0
    for value in (True,-.1,1.1,float("inf"),float("nan"),"0.5"):
        with pytest.raises(DomainSchemaError) as e: require_probability(value,"confidence")
        assert e.value.code=="domain_field_invalid"
def test_secret_key_scan_rejects_nested_credentials_but_not_max_tokens():
    reject_secret_keys({"temperature":.2,"max_tokens":512},"parameters")
    for payload in ({"api_key":"secret"},{"x-api-key":"secret"},{"headers":{"authorization":"x"}},{"headers":{"proxy-authorization":"x"}},{"credentials":[{"access_token":"x"}]},{"refresh_token":"x"},{"client_secret":"x"},{"password":"x"}):
        with pytest.raises(DomainSchemaError) as e: reject_secret_keys(payload,"parameters")
        assert e.value.code=="domain_secret_forbidden"
def test_durable_privacy_scan_rejects_absolute_locations_and_urls():
    reject_private_data({"text":"B","model":"org/model"},"document")
    for value in (r"C:\Users\private\demo.dem","/home/private/demo.dem",r"\\server\share\demo.dem","https://private.example/api","~/private/demo.dem"):
        with pytest.raises(DomainSchemaError) as e: reject_private_data({"value":value},"document")
        assert e.value.code=="domain_private_data_forbidden"
def test_demo_time_has_a_bounded_current_version_range():
    assert require_int(MAX_DEMO_TIME_US,"demo_time_us",minimum=0,maximum=MAX_DEMO_TIME_US)==MAX_DEMO_TIME_US
    with pytest.raises(DomainSchemaError) as e: require_int(MAX_DEMO_TIME_US+1,"demo_time_us",minimum=0,maximum=MAX_DEMO_TIME_US)
    assert e.value.code=="domain_field_invalid"
def test_canonical_json_fingerprint_is_derived_and_order_independent():
    left={"translated_zh":"B点","confidence":.86,"warnings":[]}; right={"warnings":[],"confidence":.86,"translated_zh":"B点"}
    assert canonical_json_bytes(left)==canonical_json_bytes(right) and content_fingerprint(left)==content_fingerprint(right) and len(content_fingerprint(left))==64
    with pytest.raises(DomainSchemaError) as e: canonical_json_bytes({"confidence":float("nan")})
    assert e.value.code=="domain_field_invalid"
