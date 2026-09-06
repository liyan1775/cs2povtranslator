from __future__ import annotations

import json
import os
import subprocess
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

import pytest

from cs2pov.application.job_runtime import JobRuntime, JobRuntimeError
from cs2pov.application.workspace import WorkspaceSelection
from cs2pov.application.workspace_runtime import WorkspaceRuntimeResolver
from cs2pov.domain.models import PipelineConfig
from cs2pov.pipeline.manifest import PipelineManifest
from cs2pov.storage.artifact_store import ArtifactStore, safe_name
from cs2pov.storage.workspace_selection_store import JsonWorkspaceSelectionStore
from cs2pov.workspace.paths import WorkspacePaths
from cs2pov.workspace.service import WorkspaceService


def _runtime(tmp_path: Path):
    root = tmp_path / "工作区"
    WorkspaceService(WorkspacePaths(root), minimum_free_bytes=0).initialize()
    selection = JsonWorkspaceSelectionStore(tmp_path / "state.json")
    selection.save(WorkspaceSelection(1, str(root)))
    return WorkspaceRuntimeResolver(selection).resolve_for_write()


def _create_windows_junction_or_skip(link: Path, target: Path) -> None:
    result = subprocess.run(
        ["cmd.exe", "/d", "/c", "mklink", "/J", str(link), str(target)],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        pytest.skip(f"无法创建 Windows junction：{result.stderr or result.stdout}")


def test_default_job_store_is_claimed_under_runtime_jobs_dir(tmp_path: Path):
    runtime = _runtime(tmp_path)

    policy = JobRuntime.from_config(runtime, PipelineConfig(map_name="de_mirage"))
    store = policy.create_store()

    assert store.job_dir.parent == runtime.paths.jobs_dir.resolve()
    assert store.job_dir.is_dir()
    assert store.job_dir.is_relative_to(runtime.paths.jobs_dir.resolve())


def test_explicit_output_is_the_single_legacy_branch_and_keeps_workspace_cache(tmp_path: Path):
    runtime = _runtime(tmp_path)
    external = tmp_path / "legacy-output"
    original = PipelineConfig(output_root="old-output", whisper_cache_dir="old-cache")

    policy = JobRuntime.from_config(runtime, original, output_root=external)
    adapted = policy.adapt_config()
    store = policy.create_store()

    assert policy.legacy_external_output is True
    assert store.job_dir.parent == external.resolve()
    assert adapted.whisper_cache_dir == str(runtime.paths.whisper_cache_dir)
    assert adapted.output_root == str(external.resolve())
    assert original.output_root == "old-output"
    assert original.whisper_cache_dir == "old-cache"


def test_old_config_paths_do_not_change_default_job_location(tmp_path: Path):
    runtime = _runtime(tmp_path)
    config = PipelineConfig(output_root=str(tmp_path / "old-output"), whisper_cache_dir=str(tmp_path / "old-cache"))

    policy = JobRuntime.from_config(runtime, config)
    store = policy.create_store()

    assert store.job_dir.parent == runtime.paths.jobs_dir.resolve()
    assert not (tmp_path / "old-output").exists()
    assert not (tmp_path / "old-cache").exists()


@pytest.mark.parametrize(
    "job_id",
    [
        "",
        " ",
        " job",
        "job ",
        ".",
        "..",
        "nested/job",
        "nested\\job",
        "/absolute",
        "\\absolute",
        "C:\\absolute",
        "CON",
        "PRN.txt",
        "AUX.",
        "NUL ",
        "COM1",
        "LPT9.log",
        "hello.",
        "hello ",
        "..\\escape",
    ],
)
def test_job_id_rejects_cross_platform_path_escape_and_reserved_names(tmp_path: Path, job_id: str):
    output_root = tmp_path / "must-not-be-created"
    with pytest.raises(JobRuntimeError) as caught:
        ArtifactStore.create(output_root, job_id=job_id)

    assert caught.value.code == "job_id_invalid"
    assert not output_root.exists()


@pytest.mark.parametrize("job_id", ["中文 Job", "de-mirage_01", "回放-01_测试"])
def test_job_id_allows_safe_unicode_hyphen_and_underscore_names(tmp_path: Path, job_id: str):
    store = ArtifactStore.create(tmp_path, job_id=job_id)

    assert store.job_dir.name == job_id
    assert store.job_dir.is_dir()


def test_explicit_and_automatic_collisions_use_observable_suffixes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    class FixedDatetime(datetime):
        @classmethod
        def now(cls):
            return cls(2026, 9, 5, 12, 0, 0)

    # Keep automatic IDs in the same second to exercise a real directory collision.
    monkeypatch.setattr("cs2pov.storage.artifact_store.datetime", FixedDatetime)

    first = ArtifactStore.create(tmp_path, job_id="same-job")
    second = ArtifactStore.create(tmp_path, job_id="same-job")
    auto_one = ArtifactStore.create(tmp_path, map_name="de_mirage")
    auto_two = ArtifactStore.create(tmp_path, map_name="de_mirage")

    assert first.job_dir.name == "same-job"
    assert second.job_dir.name == "same-job_2"
    assert auto_two.job_dir.name == f"{auto_one.job_dir.name}_2"
    assert first.job_dir != second.job_dir
    assert all(store.job_dir.is_dir() for store in (first, second, auto_one, auto_two))


def test_creation_retries_when_competing_claim_disappears_before_stat(tmp_path, monkeypatch):
    claim = tmp_path / ".released.job.claim"
    claim.mkdir()
    original_stat = Path.stat
    released = False

    def release_before_stat(path, *args, **kwargs):
        nonlocal released
        if path == claim and not released:
            released = True
            claim.rmdir()
        return original_stat(path, *args, **kwargs)

    monkeypatch.setattr(Path, "stat", release_before_stat)
    store = ArtifactStore.create(tmp_path, job_id="released")
    assert released
    assert store.job_dir.is_dir()
    assert not claim.exists()


def test_disappearing_claim_race_still_respects_deadline(tmp_path, monkeypatch):
    from types import SimpleNamespace
    import cs2pov.storage.artifact_store as module

    claim = tmp_path / ".churn.job.claim"
    original_mkdir = Path.mkdir
    ticks = iter((0.0, 11.0))

    def contested_mkdir(path, *args, **kwargs):
        if path == claim:
            raise FileExistsError()
        return original_mkdir(path, *args, **kwargs)

    monkeypatch.setattr(Path, "mkdir", contested_mkdir)
    monkeypatch.setattr(module, "time", SimpleNamespace(
        monotonic=lambda: next(ticks), time=module.time.time, sleep=module.time.sleep,
    ))
    with pytest.raises(JobRuntimeError) as caught:
        with module._rename_claim(tmp_path, "churn"):
            pytest.fail("Expired claim deadline entered critical section")
    assert caught.value.code == "job_path_claim_busy"
    assert next(ticks, None) is None


def test_claim_stat_permission_error_is_not_retried_as_release(tmp_path, monkeypatch):
    import cs2pov.storage.artifact_store as module

    claim = tmp_path / ".occupied.job.claim"
    claim.mkdir()
    original_stat = Path.stat

    def blocked_stat(path, *args, **kwargs):
        if path == claim:
            raise PermissionError()
        return original_stat(path, *args, **kwargs)

    monkeypatch.setattr(Path, "stat", blocked_stat)
    with pytest.raises(JobRuntimeError) as caught:
        with module._rename_claim(tmp_path, "occupied"):
            pytest.fail("Unreadable claim entered critical section")
    assert caught.value.code == "job_path_claim_busy"


def test_concurrent_creators_claim_distinct_real_directories(tmp_path: Path):
    def create() -> Path:
        return ArtifactStore.create(tmp_path, job_id="parallel").job_dir


    with ThreadPoolExecutor(max_workers=2) as pool:
        paths = list(pool.map(lambda _: create(), range(2)))

    assert len({path.name for path in paths}) == 2
    assert all(path.is_dir() for path in paths)
    assert sorted(path.name for path in paths) == ["parallel", "parallel_2"]


def test_job_creation_rejects_symlinked_candidate_outside_root(tmp_path: Path):
    root = tmp_path / "jobs"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    try:
        (root / "linked").symlink_to(outside, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"symlink creation is unavailable: {exc}")

    with pytest.raises(JobRuntimeError) as caught:
        ArtifactStore.create(root, job_id="linked")

    assert caught.value.code == "job_path_escape"
    assert not (outside / "input").exists()


@pytest.mark.skipif(os.name != "nt", reason="Windows junction containment check")
def test_job_creation_rejects_windows_junction_candidate_outside_root(tmp_path: Path):
    root = tmp_path / "jobs"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    junction = root / "linked"
    _create_windows_junction_or_skip(junction, outside)

    with pytest.raises(JobRuntimeError) as caught:
        ArtifactStore.create(root, job_id="linked")

    assert caught.value.code == "job_path_escape"
    assert not (outside / "input").exists()


def test_rename_suffix_avoids_race_and_preserves_job_contents(tmp_path: Path):
    store = ArtifactStore.create(tmp_path, map_name=None)
    (store.input_dir / "demo.dem").write_bytes(b"demo")
    occupied = store.job_dir.with_name(store.job_dir.name.replace("unknown_map", "de_mirage"))
    occupied.mkdir()
    (occupied / "must-survive.txt").write_text("old", encoding="utf-8")

    renamed = store.rename_suffix("de_mirage")

    assert renamed.job_dir.name.endswith("_de_mirage_2")
    assert (renamed.input_dir / "demo.dem").read_bytes() == b"demo"
    assert (occupied / "must-survive.txt").read_text(encoding="utf-8") == "old"


def test_rename_suffix_preserves_existing_empty_directory(tmp_path: Path):
    store = ArtifactStore.create(tmp_path, map_name=None)
    occupied = store.job_dir.with_name(store.job_dir.name.replace("unknown_map", "de_mirage"))
    occupied.mkdir()

    renamed = store.rename_suffix("de_mirage")

    assert renamed.job_dir.name.endswith("_de_mirage_2")
    assert occupied.is_dir()


def test_concurrent_rename_claims_never_replace_existing_target(tmp_path: Path):
    source = ArtifactStore.create(tmp_path, job_id="same_unknown_map")
    competing_view = ArtifactStore(source.job_dir)
    occupied = source.job_dir.with_name("same_de_mirage")
    occupied.mkdir()
    (occupied / "old.txt").write_text("old", encoding="utf-8")

    def rename(store: ArtifactStore):
        try:
            return store.rename_suffix("de_mirage").job_dir
        except Exception as exc:  # the losing view has no source after claim
            return exc

    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(rename, [source, competing_view]))

    assert sum(isinstance(outcome, Path) for outcome in outcomes) == 1
    assert any(isinstance(outcome, FileNotFoundError) for outcome in outcomes)
    assert (occupied / "old.txt").read_text(encoding="utf-8") == "old"
    assert (tmp_path / "same_de_mirage_2").is_dir()


def test_resolve_job_dir_breaks_equal_mtime_by_canonical_name(tmp_path: Path):
    from cs2pov.cli.job_ops import resolve_job_dir

    root = tmp_path / "jobs"
    root.mkdir()
    for name in ["20260101_b", "20260101_a"]:
        job = root / name
        job.mkdir()
        (job / "manifest.json").write_text("{}", encoding="utf-8")
    timestamp = 1_700_000_000
    for job in root.iterdir():
        os.utime(job, (timestamp, timestamp))

    assert resolve_job_dir(root) == (root / "20260101_b").resolve()


def test_manifest_records_path_policy_and_legacy_flag(tmp_path: Path):
    runtime = _runtime(tmp_path)
    config = PipelineConfig()
    policy = JobRuntime.from_config(runtime, config)
    manifest = policy.create_manifest("job-1")
    raw = manifest.to_public_dict()

    assert raw["path_policy_version"] == runtime.path_policy_version
    assert raw["legacy_external_output"] is False

    external = JobRuntime.from_config(runtime, config, output_root=tmp_path / "external")
    assert external.create_manifest("job-2").to_public_dict()["legacy_external_output"] is True


def test_old_manifest_without_new_fields_loads_with_compatible_defaults(tmp_path: Path):
    path = tmp_path / "manifest.json"
    data = PipelineManifest.create("old-job", PipelineConfig()).to_public_dict()
    data.pop("path_policy_version", None)
    data.pop("legacy_external_output", None)
    path.write_text(json.dumps(data), encoding="utf-8")

    loaded = PipelineManifest.load(path)

    assert loaded.path_policy_version is None
    assert loaded.legacy_external_output is None
    loaded.save(path)
    round_tripped = json.loads(path.read_text(encoding="utf-8"))
    assert "path_policy_version" not in round_tripped
    assert "legacy_external_output" not in round_tripped
    assert round_tripped["config"]["output_root"] == "[legacy-unmanaged]"


def test_public_manifest_hides_runtime_and_external_absolute_paths(tmp_path: Path):
    runtime = _runtime(tmp_path)
    external = (tmp_path / "external").resolve()
    policy = JobRuntime.from_config(runtime, PipelineConfig(), output_root=external)
    config = policy.adapt_config()
    manifest = policy.create_manifest("job-1")
    manifest.config = config
    manifest.set_artifact("artifact", external / "job-1" / "final" / "out.srt")
    manifest.set_artifact("unknown_absolute", external / "some-other-file.srt")

    text = json.dumps(manifest.to_public_dict(), ensure_ascii=False)

    assert str(runtime.root) not in text
    assert str(external) not in text
    assert "[workspace-managed]" in text
    assert "[legacy-external-output]" in text
    assert "[artifact-path]" in text


def test_failed_runtime_adaptation_creates_no_output_directories(tmp_path: Path):
    runtime = _runtime(tmp_path)
    config = PipelineConfig()
    with pytest.raises(JobRuntimeError):
        JobRuntime.from_config(runtime, config, output_root=Path("bad\x00root"))

    assert not (tmp_path / "badroot").exists()


@pytest.mark.parametrize("map_name, expected", [("de_mirage.", "de_mirage"), (".", "unnamed"), ("   .  ", "unnamed")])
def test_automatic_job_names_are_safe_windows_components(tmp_path: Path, map_name: str, expected: str):
    store = ArtifactStore.create(tmp_path, map_name=map_name)

    assert store.job_dir.name.endswith(f"_{expected}")
    assert not store.job_dir.name.endswith((".", " "))


def test_explicit_job_id_has_stable_component_length_error(tmp_path: Path):
    with pytest.raises(JobRuntimeError) as caught:
        ArtifactStore.create(tmp_path, job_id="x" * 256)

    assert caught.value.code == "job_id_invalid"


def test_safe_name_strips_dot_reintroduced_by_max_length_truncation():
    value = safe_name("a" * 79 + ".suffix")

    assert value == "a" * 79
    assert len(value) <= 80
    assert not value.endswith((".", " "))


@pytest.mark.parametrize("output_root", ["", "   "])
def test_empty_explicit_output_root_is_rejected_without_cwd_assets(tmp_path: Path, monkeypatch, output_root: str):
    runtime = _runtime(tmp_path)
    config = PipelineConfig()
    cwd = tmp_path / "cwd"
    cwd.mkdir()
    monkeypatch.chdir(cwd)
    before = sorted(path.name for path in cwd.iterdir())

    with pytest.raises(JobRuntimeError) as caught:
        JobRuntime.from_config(runtime, config, output_root=output_root)

    assert caught.value.code == "job_path_escape"
    assert sorted(path.name for path in cwd.iterdir()) == before
