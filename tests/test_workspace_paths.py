import os
from pathlib import Path, PureWindowsPath

import pytest

from cs2pov.workspace.errors import (
    WorkspaceError,
    WorkspacePathOutsideRootError,
    WorkspaceRootRequiredError,
)
from cs2pov.workspace.paths import WorkspacePaths


def test_missing_blank_and_relative_roots_fail(tmp_path):
    for value in (None, "", "   ", "relative", Path()):
        with pytest.raises(WorkspaceRootRequiredError):
            WorkspacePaths(value)


def test_unicode_spaced_absolute_root_is_normalized(tmp_path):
    root = tmp_path / "中文 工作区"
    paths = WorkspacePaths(root / "sub" / "..")
    assert paths.root == root.resolve()
    assert paths.root.is_absolute()


def test_layout_is_exact_and_inside_root(tmp_path):
    p = WorkspacePaths(tmp_path / "ws")
    assert p.all_directories() == (
        p.models_dir, p.demo_library_dir, p.jobs_dir, p.knowledge_dir,
        p.knowledge_inbox_dir, p.knowledge_exports_dir, p.render_bundles_dir,
        p.cache_dir, p.decompressed_demos_cache_dir, p.audio_cache_dir,
        p.render_cache_dir, p.huggingface_cache_dir,
        p.huggingface_hub_cache_dir, p.whisper_cache_dir, p.temp_dir,
    )
    for path in p.all_directories() + (p.config_file,):
        assert p.root in path.parents


def test_construction_and_reads_have_no_filesystem_side_effect(tmp_path):
    root = tmp_path / "not-created"
    p = WorkspacePaths(root)
    _ = [p.config_file, p.root, *p.all_directories(), p.cache_paths(), p.environment_overrides()]
    assert not root.exists()


def test_relative_conversion_round_trips_and_uses_slashes(tmp_path):
    p = WorkspacePaths(tmp_path / "工作区")
    path = p.root / "library" / "demos" / "match.dem"
    value = p.to_relative(path)
    assert value == "library/demos/match.dem"
    assert p.resolve_relative(value) == path


def test_conversion_rejects_boundaries_and_non_canonical_inputs(tmp_path):
    p = WorkspacePaths(tmp_path / "ws")
    bad_paths = [p.root, tmp_path / "outside.txt", p.root / "link"]
    for path in bad_paths[:2]:
        with pytest.raises(WorkspacePathOutsideRootError):
            p.to_relative(path)
    for value in ("", ".", "..", "../x", "a/../../x", "/tmp/x", "C:/x",
                  "\\\\server\\share", "a\\b", "https://example/x", "a/../b"):
        with pytest.raises(WorkspaceError):
            p.resolve_relative(value)
    with pytest.raises(WorkspaceError):
        p.resolve_relative(str(PureWindowsPath("C:/outside")))


def test_external_symlink_is_rejected_when_supported(tmp_path):
    p = WorkspacePaths(tmp_path / "ws")
    outside = tmp_path / "outside"
    outside.mkdir()
    link = p.root / "link"
    p.root.mkdir()
    try:
        link.symlink_to(outside, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("symbolic links unavailable")
    with pytest.raises(WorkspacePathOutsideRootError):
        p.to_relative(link / "file.txt")
    with pytest.raises(WorkspacePathOutsideRootError):
        p.resolve_relative("link/file.txt")


def test_directory_groups_are_stable_unique_and_disjoint(tmp_path):
    p = WorkspacePaths(tmp_path / "ws")
    assert len(set(p.persistent_directories())) == len(p.persistent_directories())
    assert len(set(p.cache_directories())) == len(p.cache_directories())
    assert set(p.persistent_directories()).isdisjoint(p.cache_directories())
    assert p.persistent_directories() == (
        p.models_dir, p.demo_library_dir, p.jobs_dir, p.knowledge_dir,
        p.knowledge_inbox_dir, p.knowledge_exports_dir, p.render_bundles_dir,
    )
    assert p.cache_directories() == (
        p.cache_dir, p.decompressed_demos_cache_dir, p.audio_cache_dir,
        p.render_cache_dir, p.huggingface_cache_dir,
        p.huggingface_hub_cache_dir, p.whisper_cache_dir, p.temp_dir,
    )


def test_cache_mappings_are_inside_workspace(tmp_path):
    p = WorkspacePaths(tmp_path / "ws")
    assert set(p.cache_paths()) >= {"huggingface", "huggingface_hub", "whisper", "temporary"}
    for path in p.cache_paths().values():
        assert p.root in path.parents


def test_environment_overrides_do_not_mutate_environment(tmp_path):
    p = WorkspacePaths(tmp_path / "ws")
    before = os.environ.copy()
    values = p.environment_overrides()
    assert os.environ.copy() == before
    assert set(values) >= {"HF_HOME", "HF_HUB_CACHE", "HUGGINGFACE_HUB_CACHE", "TMP", "TEMP", "TMPDIR"}
    assert all(p.root in Path(value).parents for value in values.values())
