import json

import pytest

from cs2pov.storage.atomic_documents import (
    SchemaClassification,
    SchemaExpectation,
    SchemaAwareParser,
    atomic_write_bytes,
    atomic_write_json,
    atomic_write_jsonl,
    classify_schema_versions,
    read_strict_json,
    read_strict_jsonl,
    schema_aware_parser,
)
from cs2pov.domain.errors import DomainSchemaError
from cs2pov.domain.schema import require_current_schema
from cs2pov.storage.job_errors import JobRepositoryError


def parser(value):
    assert value["schema_version"] == 1
    return value


def domain_parser(value):
    require_current_schema(value, "test_document")
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


def test_strict_json_rejects_invalid_utf8(tmp_path):
    p = tmp_path / "doc.json"
    p.write_bytes(b'\xff{"schema_version":1}')
    with pytest.raises(JobRepositoryError) as exc:
        read_strict_json(p, logical_path="doc.json", parser=domain_parser)
    assert exc.value.code == "job_shard_invalid"


@pytest.mark.parametrize("raw", [b'{"schema_version":1,"x":Infinity}', b'{"schema_version":1,"x":-Infinity}'])
def test_strict_json_rejects_infinite_numbers(raw, tmp_path):
    p = tmp_path / "doc.json"
    p.write_bytes(raw)
    with pytest.raises(JobRepositoryError) as exc:
        read_strict_json(p, logical_path="doc.json", parser=parser)
    assert exc.value.code == "job_shard_invalid"


def test_strict_json_missing_and_directory_are_stable_errors(tmp_path):
    with pytest.raises(JobRepositoryError) as missing:
        read_strict_json(tmp_path / "missing.json", logical_path="missing.json", parser=parser)
    assert missing.value.code == "job_shard_missing"
    directory = tmp_path / "directory.json"
    directory.mkdir()
    with pytest.raises(JobRepositoryError) as nonregular:
        read_strict_json(directory, logical_path="directory.json", parser=parser)
    assert nonregular.value.code == "job_shard_invalid"


def test_strict_json_rejects_file_symlink(tmp_path):
    target = tmp_path / "target.json"
    target.write_text('{"schema_version":1}', encoding="utf-8")
    link = tmp_path / "link.json"
    try:
        link.symlink_to(target)
    except OSError:
        pytest.skip("symlink privileges unavailable")
    with pytest.raises(JobRepositoryError) as exc:
        read_strict_json(link, logical_path="link.json", parser=parser)
    assert exc.value.code == "job_shard_invalid"


def test_atomic_json_validates_before_write_and_preserves_old_bytes(tmp_path):
    p = tmp_path / "doc.json"
    p.write_bytes(b'{"schema_version":1,"old":true}\n')
    with pytest.raises(JobRepositoryError):
        atomic_write_json(p, {"schema_version": 1, "bad": object()}, logical_path="doc.json", serializer=lambda x: x, parser=parser)
    assert p.read_bytes() == b'{"schema_version":1,"old":true}\n'
    atomic_write_json(p, {"schema_version": 1, "text": "中文"}, logical_path="doc.json", serializer=lambda x: x, parser=parser)
    assert b"\r\n" not in p.read_bytes()
    assert p.read_text(encoding="utf-8").endswith("\n")
    assert "中文" in p.read_text(encoding="utf-8")


def test_atomic_bytes_preserves_lf_bytes_exactly(tmp_path):
    target = tmp_path / "subtitle.srt"
    payload = "one\ntwo 中文\n".encode("utf-8")

    atomic_write_bytes(target, payload, logical_path="final/subtitles/subtitle.srt")

    assert target.read_bytes() == payload


def test_jsonl_incomplete_tail(tmp_path):
    p = tmp_path / "records.jsonl"
    p.write_bytes(b'{"schema_version":1,"n":1}\n{"schema_version":1,"n":2}')
    result = read_strict_jsonl(p, logical_path="records.jsonl", parser=lambda x: x, allow_incomplete_tail=True)
    assert result.records == ({"schema_version": 1, "n": 1},)
    assert result.incomplete_tail is True


@pytest.mark.parametrize("raw", [b"{\"schema_version\":1}\n\n{\"schema_version\":1}\n", b"[]\n", b"{\"schema_version\":1\n", b"\xff\n"])
def test_jsonl_rejects_blank_nonobject_malformed_and_invalid_utf8(raw, tmp_path):
    p = tmp_path / "records.jsonl"
    p.write_bytes(raw)
    with pytest.raises(JobRepositoryError) as exc:
        read_strict_jsonl(p, logical_path="records.jsonl", parser=lambda x: x)
    assert exc.value.code == "job_shard_invalid"


def test_jsonl_parser_schema_error_reports_record_number_and_cause(tmp_path):
    p = tmp_path / "records.jsonl"
    p.write_bytes(b'{"schema_version":1}\n{"schema_version":1}\n')
    def parser(value):
        if value["schema_version"] == 1:
            raise DomainSchemaError("domain_field_invalid", "bad", "fix")
    with pytest.raises(JobRepositoryError) as exc:
        read_strict_jsonl(p, logical_path="records.jsonl", parser=parser)
    assert exc.value.logical_path == "records.jsonl#1"
    assert isinstance(exc.value.__cause__, DomainSchemaError)


def test_jsonl_schema_aware_parser_reports_second_record_and_malformed_version(tmp_path):
    p = tmp_path / "records.jsonl"
    p.write_bytes(b'{"schema_version":1}\n{"schema_version":true}\n')
    def parser(value):
        if value["schema_version"] is True:
            raise DomainSchemaError("domain_schema_unsupported", "bad", "fix")
        return value
    parser = schema_aware_parser(parser, expectations=("",))
    with pytest.raises(JobRepositoryError) as exc:
        read_strict_jsonl(p, logical_path="records.jsonl", parser=parser)
    assert exc.value.code == "job_shard_invalid"
    assert exc.value.logical_path == "records.jsonl#2"


@pytest.mark.parametrize("version, expected", [(None, "job_shard_invalid"), (True, "job_shard_invalid"), ("1", "job_shard_invalid"), (2, "job_schema_unsupported")])
def test_jsonl_schema_aware_parser_classifies_root_version_types(version, expected, tmp_path):
    p = tmp_path / "records.jsonl"
    p.write_text(json.dumps({"schema_version": version}) + "\n", encoding="utf-8")
    parser = schema_aware_parser(lambda value: (_ for _ in ()).throw(DomainSchemaError("domain_schema_unsupported", "bad", "fix")), expectations=[""])
    with pytest.raises(JobRepositoryError) as exc:
        read_strict_jsonl(p, logical_path="records.jsonl", parser=parser)
    assert exc.value.code == expected


def test_jsonl_schema_aware_parser_only_scans_declared_nested_collection(tmp_path):
    p = tmp_path / "records.jsonl"
    p.write_text(json.dumps({"schema_version": 1, "decisions": [], "parameters": {"schema_version": 2}}) + "\n", encoding="utf-8")
    parser = schema_aware_parser(lambda value: (_ for _ in ()).throw(DomainSchemaError("domain_schema_unsupported", "bad", "fix")), expectations=["", "/decisions/*"])
    with pytest.raises(JobRepositoryError) as exc:
        read_strict_jsonl(p, logical_path="records.jsonl", parser=parser)
    assert exc.value.code == "job_shard_invalid"


@pytest.mark.parametrize(
    "raw",
    [
        b'\xef\xbb\xbf{"schema_version":1}\n',
        b'{"schema_version":1,"schema_version":1}\n',
        b'{"value":1}\n',
    ],
)
def test_jsonl_rejects_bom_duplicate_keys_and_missing_schema(raw, tmp_path):
    p = tmp_path / "records.jsonl"
    p.write_bytes(raw)
    aware = schema_aware_parser(domain_parser, expectations=[""])
    with pytest.raises(JobRepositoryError) as exc:
        read_strict_jsonl(p, logical_path="records.jsonl", parser=aware)
    assert exc.value.code == "job_shard_invalid"


def test_jsonl_declared_nested_noncurrent_schema_is_unsupported(tmp_path):
    p = tmp_path / "records.jsonl"
    value = {"schema_version": 1, "decisions": [{"schema_version": 2}]}
    p.write_text(json.dumps(value) + "\n", encoding="utf-8")
    aware = schema_aware_parser(
        lambda raw: (_ for _ in ()).throw(
            DomainSchemaError("domain_schema_unsupported", "bad", "fix")
        ),
        expectations=["", "/decisions/*"],
    )
    with pytest.raises(JobRepositoryError) as exc:
        read_strict_jsonl(p, logical_path="records.jsonl", parser=aware)
    assert exc.value.code == "job_schema_unsupported"


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


def test_atomic_json_rejects_symlink_target_without_modifying_referent(tmp_path):
    target = tmp_path / "target.json"
    original = b'{"schema_version":1,"old":true}\n'
    target.write_bytes(original)
    link = tmp_path / "linked.json"
    try:
        link.symlink_to(target)
    except OSError:
        pytest.skip("symlink privileges unavailable")
    with pytest.raises(JobRepositoryError):
        atomic_write_json(
            link,
            {"schema_version": 1, "new": True},
            logical_path="linked.json",
            serializer=lambda value: value,
            parser=parser,
        )
    assert target.read_bytes() == original


@pytest.mark.skipif(__import__("os").name != "nt", reason="Windows junction semantics")
def test_atomic_json_rejects_junction_parent_without_writing_outside(tmp_path):
    import subprocess

    outside = tmp_path.parent / f"atomic-junction-{tmp_path.name}"
    outside.mkdir()
    junction = tmp_path / "linked-dir"
    result = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(junction), str(outside)],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        pytest.skip(f"mklink /J unavailable: {result.stderr.strip() or result.stdout.strip()}")
    with pytest.raises(JobRepositoryError) as exc:
        atomic_write_json(
            junction / "doc.json",
            {"schema_version": 1},
            logical_path="doc.json",
            serializer=lambda value: value,
            parser=parser,
        )
    assert exc.value.code == "job_path_escape"
    assert not (outside / "doc.json").exists()


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


@pytest.mark.skipif(__import__("os").name == "nt", reason="POSIX directory fsync semantics")
def test_atomic_write_success_fsyncs_parent_directory(tmp_path, monkeypatch):
    import os
    p = tmp_path / "doc.json"
    calls = []
    real_fsync = os.fsync

    def record(fd):
        calls.append(fd)
        return real_fsync(fd)

    monkeypatch.setattr("cs2pov.storage.atomic_documents.os.fsync", record)
    atomic_write_json(p, {"schema_version": 1}, logical_path="doc.json", serializer=lambda x: x, parser=parser)
    assert len(calls) >= 2


def test_append_jsonl_short_write_is_completed(tmp_path, monkeypatch):
    from cs2pov.storage.atomic_documents import append_jsonl_record
    import cs2pov.storage.atomic_documents as module
    p = tmp_path / "events.jsonl"
    p.write_bytes(b"")
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


@pytest.mark.parametrize("version", [None, True, "1"])
def test_reader_maps_malformed_root_schema_to_shard_invalid(version, tmp_path):
    p = tmp_path / "doc.json"
    p.write_text(json.dumps({"schema_version": version}), encoding="utf-8")
    def parser(value):
        raise DomainSchemaError("domain_schema_unsupported", "bad", "fix")
    with pytest.raises(JobRepositoryError) as exc:
        read_strict_json(p, logical_path="doc.json", parser=parser)
    assert exc.value.code == "job_shard_invalid"
    assert isinstance(exc.value.__cause__, DomainSchemaError)


def test_reader_maps_exact_non_current_root_schema_to_unsupported(tmp_path):
    p = tmp_path / "doc.json"
    p.write_text('{"schema_version":2}', encoding="utf-8")
    with pytest.raises(JobRepositoryError) as exc:
        read_strict_json(p, logical_path="doc.json", parser=lambda value: (_ for _ in ()).throw(DomainSchemaError("domain_schema_unsupported", "bad", "fix")))
    assert exc.value.code == "job_schema_unsupported"


@pytest.mark.parametrize("version, expected", [(2, "job_schema_unsupported"), (True, "job_manifest_invalid"), ("1", "job_manifest_invalid"), (None, "job_manifest_invalid")])
def test_schema_aware_parser_maps_root_versions_with_declared_invalid_code(version, expected, tmp_path):
    p = tmp_path / "doc.json"
    p.write_text(json.dumps({"schema_version": version}), encoding="utf-8")
    parser = schema_aware_parser(lambda value: (_ for _ in ()).throw(DomainSchemaError("domain_schema_unsupported", "bad", "fix")), expectations=("",), invalid_code="job_manifest_invalid")
    with pytest.raises(JobRepositoryError) as exc:
        read_strict_json(p, logical_path="job.json", parser=parser)
    assert exc.value.code == expected
    assert exc.value.logical_path == "job.json"
    assert isinstance(exc.value.__cause__, DomainSchemaError)


def test_schema_aware_parser_checks_nested_declared_locations_but_not_payload():
    parser = schema_aware_parser(lambda value: (_ for _ in ()).throw(DomainSchemaError("domain_schema_unsupported", "bad", "fix")), expectations=("", "/decisions/*"))
    with pytest.raises(DomainSchemaError):
        parser({"schema_version": 1, "decisions": [{"schema_version": 2}], "parameters": {"schema_version": 2}})
    assert classify_schema_versions({"schema_version": 1, "decisions": [], "parameters": {"schema_version": 2}}, ("", "/decisions/*")) is SchemaClassification.CURRENT


def test_schema_aware_parser_constructor_validates_and_normalizes_contract():
    parser = schema_aware_parser(lambda value: value, expectations=["", SchemaExpectation("/decisions/*")])
    assert isinstance(parser, SchemaAwareParser)
    assert parser.expectations == ("", "/decisions/*")
    invalid = [
        (lambda: schema_aware_parser(None, expectations=[""]), TypeError),
        (lambda: schema_aware_parser(lambda value: value, expectations=[]), ValueError),
        (lambda: schema_aware_parser(lambda value: value, expectations=["/decisions/*"]), ValueError),
        (lambda: schema_aware_parser(lambda value: value, expectations=["", ""]), ValueError),
        (lambda: schema_aware_parser(lambda value: value, expectations=["", "/decisions"]), ValueError),
        (lambda: schema_aware_parser(lambda value: value, expectations=["", "/a/b/*"]), ValueError),
        (lambda: schema_aware_parser(lambda value: value, expectations=["", "/bad?key/*"]), ValueError),
        (lambda: schema_aware_parser(lambda value: value, expectations=[""], invalid_code="job_schema_unsupported"), ValueError),
        (lambda: SchemaExpectation("/decisions"), ValueError),
        (lambda: SchemaExpectation("/decisions/*/nested"), ValueError),
    ]
    for factory, error in invalid:
        with pytest.raises(error):
            factory()


def test_schema_aware_parser_call_is_transparent_and_does_not_use_fixed_logical_path():
    marker = object()
    parser = schema_aware_parser(lambda value: marker, expectations=[""])
    assert parser({"schema_version": 1}) is marker


def test_atomic_validation_happens_before_first_os_open(tmp_path, monkeypatch):
    p = tmp_path / "doc.json"
    def fail_open(*args, **kwargs):
        raise AssertionError("filesystem write happened before validation")
    monkeypatch.setattr("cs2pov.storage.atomic_documents.os.open", fail_open)
    with pytest.raises(JobRepositoryError) as exc:
        atomic_write_json(p, {"schema_version": 1}, logical_path="doc.json", serializer=lambda x: x, parser=lambda x: (_ for _ in ()).throw(DomainSchemaError("domain_field_invalid", "bad", "fix")))
    assert exc.value.code == "job_shard_invalid"


def test_atomic_staging_fsync_failure_preserves_old_target_and_cleans_stage(tmp_path, monkeypatch):
    p = tmp_path / "doc.json"
    old = b'{"schema_version":1,"old":true}\n'
    p.write_bytes(old)
    monkeypatch.setattr("cs2pov.storage.atomic_documents.os.fsync", lambda fd: (_ for _ in ()).throw(OSError("injected fsync")))
    with pytest.raises(JobRepositoryError) as exc:
        atomic_write_json(p, {"schema_version": 1, "new": True}, logical_path="doc.json", serializer=lambda x: x, parser=parser)
    assert exc.value.code == "job_write_failed"
    assert p.read_bytes() == old
    assert not list(tmp_path.glob("*.tmp"))


def test_missing_jsonl_collection_read_is_stable_error(tmp_path):
    with pytest.raises(JobRepositoryError) as exc:
        read_strict_jsonl(tmp_path / "missing.jsonl", logical_path="missing.jsonl", parser=lambda x: x)
    assert exc.value.code == "job_shard_missing"


@pytest.mark.parametrize(
    "version, expected",
    [(None, "job_shard_invalid"), (True, "job_shard_invalid"), ("1", "job_shard_invalid"), (2, "job_schema_unsupported")],
)
def test_append_schema_aware_parser_classifies_versions_without_writing(version, expected, tmp_path):
    from cs2pov.storage.atomic_documents import append_jsonl_record

    p = tmp_path / "events.jsonl"
    p.write_bytes(b"")
    aware = schema_aware_parser(domain_parser, expectations=[""])
    with pytest.raises(JobRepositoryError) as exc:
        append_jsonl_record(
            p,
            {"schema_version": version},
            logical_path="events.jsonl",
            serializer=lambda value: value,
            parser=aware,
        )
    assert exc.value.code == expected
    assert p.read_bytes() == b""


def test_append_does_not_create_missing_journal(tmp_path):
    from cs2pov.storage.atomic_documents import append_jsonl_record
    p = tmp_path / "missing.jsonl"
    with pytest.raises(JobRepositoryError) as exc:
        append_jsonl_record(p, {"schema_version": 1}, logical_path="missing.jsonl", serializer=lambda x: x, parser=lambda x: x)
    assert exc.value.code == "job_shard_missing"
    assert not p.exists()


def test_staging_cleanup_failure_is_exposed(tmp_path, monkeypatch):
    p = tmp_path / "doc.json"
    def fail_unlink(self, *args, **kwargs):
        raise OSError("cannot remove staging")
    monkeypatch.setattr("pathlib.Path.unlink", fail_unlink)
    with pytest.raises(JobRepositoryError) as exc:
        atomic_write_json(p, {"schema_version": 1}, logical_path="doc.json", serializer=lambda x: x, parser=parser)
    assert exc.value.code == "job_write_failed"
