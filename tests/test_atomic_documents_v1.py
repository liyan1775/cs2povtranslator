import json

import pytest

from cs2pov.storage.atomic_documents import (
    SchemaClassification,
    atomic_write_json,
    atomic_write_jsonl,
    classify_schema_versions,
    read_strict_json,
    read_strict_jsonl,
)
from cs2pov.storage.job_errors import JobRepositoryError


def parser(value):
    assert value["schema_version"] == 1
    return value


def test_strict_json_rejects_bom_duplicate_keys_and_nan(tmp_path):
    p = tmp_path / "doc.json"
    p.write_bytes(b"\xef\xbb\xbf{}")
    with pytest.raises(JobRepositoryError):
        read_strict_json(p, logical_path="doc.json", parser=parser)
    p.write_text('{"schema_version":1,"schema_version":1}', encoding="utf-8")
    with pytest.raises(JobRepositoryError):
        read_strict_json(p, logical_path="doc.json", parser=parser)
    p.write_text('{"schema_version":1,"x":NaN}', encoding="utf-8")
    with pytest.raises(JobRepositoryError):
        read_strict_json(p, logical_path="doc.json", parser=parser)


def test_atomic_json_validates_before_write_and_preserves_old_bytes(tmp_path):
    p = tmp_path / "doc.json"
    p.write_bytes(b'{"schema_version":1,"old":true}\n')
    with pytest.raises(JobRepositoryError):
        atomic_write_json(p, {"schema_version": 1, "bad": object()}, logical_path="doc.json", serializer=lambda x: x, parser=parser)
    assert p.read_bytes() == b'{"schema_version":1,"old":true}\n'
    atomic_write_json(p, {"schema_version": 1, "text": "中文"}, logical_path="doc.json", serializer=lambda x: x, parser=parser)
    assert p.read_text(encoding="utf-8").endswith("\n")
    assert "中文" in p.read_text(encoding="utf-8")


def test_jsonl_incomplete_tail(tmp_path):
    p = tmp_path / "records.jsonl"
    p.write_bytes(b'{"schema_version":1,"n":1}\n{"schema_version":1,"n":2}')
    result = read_strict_jsonl(p, logical_path="records.jsonl", parser=lambda x: x, allow_incomplete_tail=True)
    assert result.records == ({"schema_version": 1, "n": 1},)
    assert result.incomplete_tail is True


def test_atomic_jsonl_and_schema_locations(tmp_path):
    p = tmp_path / "records.jsonl"
    atomic_write_jsonl(p, [{"schema_version": 1, "n": 1}], logical_path="records.jsonl", serializer=lambda x: x, parser=lambda x: x)
    assert read_strict_jsonl(p, logical_path="records.jsonl", parser=lambda x: x).records[0]["n"] == 1
    assert classify_schema_versions({"schema_version": 2}, ("",)) is SchemaClassification.UNSUPPORTED
    assert classify_schema_versions({"schema_version": True}, ("",)) is SchemaClassification.MALFORMED
    assert classify_schema_versions({"schema_version": 1, "parameters": {"x": 2}}, ("",)) is SchemaClassification.CURRENT


def test_unexpected_parser_errors_are_not_reclassified(tmp_path):
    p = tmp_path / "doc.json"
    p.write_text('{"schema_version":1}', encoding="utf-8")
    with pytest.raises(RuntimeError, match="programmer"):
        read_strict_json(p, logical_path="doc.json", parser=lambda value: (_ for _ in ()).throw(RuntimeError("programmer")))
