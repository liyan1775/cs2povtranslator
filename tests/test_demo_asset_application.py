from __future__ import annotations

from pathlib import Path

import pytest

from cs2pov.application.demo_assets import DemoAssetApplicationService, DemoAssetUseCaseError
from cs2pov.application.workspace_runtime import WorkspaceRuntime
from cs2pov.domain.assets import DemoAssetRef
from cs2pov.storage.demo_asset_repository import DemoAssetRepositoryError


class FakeResolver:
    def __init__(self, runtime):
        self.runtime = runtime
        self.calls = []

    def resolve_for_write(self):
        self.calls.append("write")
        return self.runtime

    def resolve_for_read(self):
        self.calls.append("read")
        return self.runtime


class FakeRepository:
    def __init__(self):
        self.calls = []
        self.import_result = object()
        self.list_result = (object(),)
        self.inspect_result = object()
        self.resolve_result = Path("resolved.dem")
        self.error = None

    def _record(self, name, value=None):
        self.calls.append((name, value))
        if self.error is not None:
            raise self.error

    def import_source(self, source):
        self._record("import", source)
        return self.import_result

    def list_assets(self):
        self._record("list")
        return self.list_result

    def inspect_asset(self, asset_id):
        self._record("inspect", asset_id)
        return self.inspect_result

    def resolve_asset(self, ref):
        self._record("resolve", ref)
        return self.resolve_result


class RecordingFactory:
    def __init__(self, repository):
        self.repository = repository
        self.paths = []

    def __call__(self, paths):
        self.paths.append(paths)
        return self.repository


def make_app(tmp_path):
    runtime = WorkspaceRuntime(tmp_path / "workspace", "workspace-id", 1, 1)
    resolver = FakeResolver(runtime)
    repository = FakeRepository()
    factory = RecordingFactory(repository)
    return DemoAssetApplicationService(resolver, repository_factory=factory), resolver, repository, factory, runtime


def test_for_runtime_binds_one_immutable_runtime_without_selection_lookup(tmp_path):
    runtime = WorkspaceRuntime(tmp_path / "workspace-a", "workspace-a", 1, 1)
    app = DemoAssetApplicationService.for_runtime(runtime)
    assert app.bound_runtime is runtime
    assert app.bound_runtime.paths.root == runtime.root


def test_bound_runtime_service_uses_bound_paths_even_if_global_selection_changes(tmp_path):
    runtime_a = WorkspaceRuntime(tmp_path / "workspace-a", "workspace-a", 1, 1)
    runtime_b = WorkspaceRuntime(tmp_path / "workspace-b", "workspace-b", 1, 1)
    repository = FakeRepository()
    factory = RecordingFactory(repository)
    resolver = FakeResolver(runtime_b)
    app = DemoAssetApplicationService.for_runtime(runtime_a, repository_factory=factory)

    app.import_demo("match.dem")
    app.inspect_asset("a" * 64)
    app.resolve_asset(DemoAssetRef("a" * 64, f"library/demos/{'a' * 64}/asset.json"))

    assert [paths.root for paths in factory.paths] == [runtime_a.root, runtime_a.root, runtime_a.root]
    assert resolver.calls == []


def test_constructor_requires_exactly_one_of_resolver_or_runtime(tmp_path):
    runtime = WorkspaceRuntime(tmp_path / "workspace", "workspace", 1, 1)
    with pytest.raises(TypeError, match="runtime_resolver 或 runtime"):
        DemoAssetApplicationService()
    with pytest.raises(TypeError, match="runtime_resolver 或 runtime"):
        DemoAssetApplicationService(FakeResolver(runtime), runtime=runtime)


def test_resolver_mode_remains_unbound(tmp_path):
    app, _, _, _, _ = make_app(tmp_path)
    assert app.bound_runtime is None


def test_import_resolves_one_write_runtime_before_repository_call(tmp_path):
    app, resolver, repository, factory, runtime = make_app(tmp_path)

    result = app.import_demo("match.dem")

    assert result is repository.import_result
    assert resolver.calls == ["write"]
    assert [paths.root for paths in factory.paths] == [runtime.root]
    assert repository.calls == [("import", Path("match.dem"))]


def test_list_and_inspect_each_resolve_one_read_runtime(tmp_path):
    app, resolver, repository, factory, runtime = make_app(tmp_path)
    asset_id = "a" * 64

    assert app.list_assets() is repository.list_result
    assert app.inspect_asset(asset_id) is repository.inspect_result

    assert resolver.calls == ["read", "read"]
    assert [paths.root for paths in factory.paths] == [runtime.root, runtime.root]
    assert repository.calls == [("list", None), ("inspect", asset_id)]


def test_resolve_asset_uses_write_runtime_because_cache_may_rebuild(tmp_path):
    app, resolver, repository, factory, runtime = make_app(tmp_path)
    ref = DemoAssetRef("a" * 64, f"library/demos/{'a' * 64}/asset.json")

    assert app.resolve_asset(ref) == Path("resolved.dem")
    assert resolver.calls == ["write"]
    assert [paths.root for paths in factory.paths] == [runtime.root]
    assert repository.calls == [("resolve", ref)]


def test_repository_errors_keep_stable_safe_contract(tmp_path):
    app, _, repository, _, _ = make_app(tmp_path)
    repository.error = DemoAssetRepositoryError(
        "demo_source_not_found",
        "找不到 Demo 源文件。",
        "请确认文件仍存在后重试。",
    )

    with pytest.raises(DemoAssetUseCaseError) as exc_info:
        app.import_demo("C:/private/user/match.dem")

    assert exc_info.value.code == "demo_source_not_found"
    assert exc_info.value.message_zh == "找不到 Demo 源文件。"
    assert exc_info.value.suggestion_zh == "请确认文件仍存在后重试。"
    assert "C:/private" not in str(exc_info.value)


def test_unknown_repository_bug_is_not_disguised_as_user_error(tmp_path):
    app, _, repository, _, _ = make_app(tmp_path)
    repository.error = RuntimeError("programming bug")

    with pytest.raises(RuntimeError, match="programming bug"):
        app.list_assets()
