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


def test_atomic_write_handles_short_and_zero_progress_without_publishing(tmp_path, monkeypatch):
    p = tmp_path / "doc.json"
    p.write_bytes(b'{"schema_version":1,"old":true}\n')
    original = __import__("cs2pov.storage.atomic_documents", fromlist=["os"]).os.write
    calls = {"n": 0}

    def short_write(fd, data):
        calls["n"] += 1
        if calls["n"] == 1:
            return original(fd, data[:2])
        if calls["n"] == 2:
            return 0
        return original(fd, data)

    monkeypatch.setattr("cs2pov.storage.atomic_documents.os.write", short_write)
    with pytest.raises(JobRepositoryError) as exc:
        atomic_write_json(p, {"schema_version": 1, "new": True}, logical_path="doc.json", serializer=lambda x: x, parser=parser)
    assert exc.value.code == "job_write_failed"
    assert p.read_bytes() == b'{"schema_version":1,"old":true}\n'
    assert not list(tmp_path.glob("*.tmp"))


def test_atomic_json_rejects_parent_symlink_and_read_uses_regular_target(tmp_path):
    outside = tmp_path.parent / "atomic-outside"
    outside.mkdir()
    link = tmp_path / "link"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("symlink privileges unavailable")
    with pytest.raises(JobRepositoryError) as exc:
        atomic_write_json(link / "doc.json", {"schema_version": 1}, logical_path="doc.json", serializer=lambda x: x, parser=parser)
    assert exc.value.code == "job_path_escape"


def test_atomic_write_parent_fsync_failure_leaves_new_target_visible(tmp_path, monkeypatch):
    import os
    if os.name == "nt":
        pytest.skip("POSIX directory fsync semantics")
    p = tmp_path / "doc.json"
    p.write_bytes(b'{"schema_version":1,"old":true}\n')
    real_fsync = os.fsync
    calls = {"n": 0}

    def fail_parent(fd):
        calls["n"] += 1
        if calls["n"] == 2:
            raise OSError("injected parent fsync")
        return real_fsync(fd)

    monkeypatch.setattr("cs2pov.storage.atomic_documents.os.fsync", fail_parent)
    with pytest.raises(JobRepositoryError) as exc:
        atomic_write_json(p, {"schema_version": 1, "new": True}, logical_path="doc.json", serializer=lambda x: x, parser=parser)
    assert exc.value.code == "job_write_durability_uncertain"
    assert json.loads(p.read_text(encoding="utf-8"))["new"] is True
    assert not list(tmp_path.glob("*.tmp"))


def test_append_jsonl_short_write_is_completed(tmp_path, monkeypatch):
    from cs2pov.storage.atomic_documents import append_jsonl_record
    import cs2pov.storage.atomic_documents as module
    p = tmp_path / "events.jsonl"
    real_write = module.os.write
    calls = {"n": 0}

    def short(fd, data):
        calls["n"] += 1
        if len(data) > 2:
            return real_write(fd, data[:2])
        return real_write(fd, data)

    monkeypatch.setattr(module.os, "write", short)
    append_jsonl_record(p, {"schema_version": 1, "event": "x"}, logical_path="events.jsonl", serializer=lambda x: x, parser=lambda x: x)
    assert p.read_text(encoding="utf-8").endswith("\n")


def test_atomic_replace_failure_preserves_old_target_and_cleans_stage(tmp_path, monkeypatch):
    p = tmp_path / "doc.json"
    old = b'{"schema_version":1,"old":true}\n'
    p.write_bytes(old)
    def fail_replace(src, dst):
        raise OSError("injected replace failure")
    monkeypatch.setattr("cs2pov.storage.atomic_documents.os.replace", fail_replace)
    with pytest.raises(JobRepositoryError) as exc:
        atomic_write_json(p, {"schema_version": 1, "new": True}, logical_path="doc.json", serializer=lambda x: x, parser=parser)
    assert exc.value.code == "job_write_failed"
    assert p.read_bytes() == old
    assert not list(tmp_path.glob("*.tmp"))


def test_schema_empty_wildcard_is_current_but_missing_container_is_malformed():
    assert classify_schema_versions({"schema_version": 1, "results": []}, ("", "/results/*")) is SchemaClassification.CURRENT
    assert classify_schema_versions({"schema_version": 1}, ("", "/results/*")) is SchemaClassification.MALFORMED
