# Luna-01E-A DemoAsset 素材库实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans` to implement this plan task-by-task. Every production change follows `superpowers:test-driven-development`; stop at every commit/review checkpoint.

**Goal:** 建立按解压后 Demo 内容 SHA-256 寻址的工作区素材库，交付原子导入、去重、完整性检查、缓存解析以及非程序员可用的 `demos import/list/inspect` 命令，但不改变现有 Pipeline。

**Architecture:** 版本化领域对象不依赖文件系统；zstandard 适配器只负责流式解压；文件系统仓储负责工作区路径、staging、原子提交、完整性和缓存；应用服务解析当前不可变 `WorkspaceRuntime` 并把稳定结果提供给 CLI。01E-A 完成后现有 `run`、向导、Job 和 `DemoService` 行为必须保持不变，01E-B 才接入自动导入。

**Tech Stack:** Python 3.11+、标准库 `dataclasses/hashlib/json/pathlib/tempfile/shutil/os`、`zstandard>=0.23`、pytest、argparse、现有 `WorkspaceRuntime`/`WorkspacePaths`。

**Spec:** `docs/plans/2026-08-31-demo-asset-library-design.zh.md`

## Global Constraints

- 只实施 Luna-01E-A；严禁修改 `src/cs2pov/pipeline/engine.py`、`src/cs2pov/services/demo_service.py`、`src/cs2pov/pipeline/manifest.py`、向导或 `run` 数据流。
- `asset_id` 必须等于解压后 `.dem` 完整字节的 64 位小写 SHA-256；文件名和压缩字节不得参与逻辑身份。
- 每个资产只允许 `asset.json` 加一个 `source.dem` 或 `source.dem.zst`；首次成功提交的格式不被后续导入替换。
- 外部 Demo 只读；不得移动、改名、删除或原地解压用户文件。
- staging 只位于当前工作区 `cache/tmp/demo_imports/`；持久资产只位于 `library/demos/<asset_id>/`；解压缓存只位于 `cache/decompressed_demos/<asset_id>.dem`。
- 原子提交使用同文件系统重命名；不得用“先创建最终目录再逐个复制文件”产生半资产。
- 并发正确性不得只依赖线程锁；真实多进程导入必须得到一个完整资产。
- `demos list` 和 `demos inspect` 只读；只有 `demos import` 和内部 `resolve_asset()` 可以创建或重建缓存。
- 已有资产损坏时拒绝复用和覆盖；缓存损坏可以通过受控安全替换重建，但不得影响持久源。
- JSON stdout 只能包含一个 JSON 文档；警告、进度和诊断文字进入 stderr。
- manifest、CLI JSON、错误和日志不得包含外部绝对路径、用户目录、staging 路径、SteamID、API Key 或模型配置。
- `zstandard>=0.23` 成为基础运行依赖；`demoparser2`、PyOgg、Whisper、GPU 和渲染依赖仍保持可选。
- 所有测试只用匿名合成字节和临时工作区，不读取真实 Demo、用户工作区、模型或秘密。
- 不实现 delete/repair、旧 Job 导入、数据库、Web/API、理解翻译、录制或跨工作区扫描。
- 每个任务必须先提交失败测试，确认 RED，再写最小实现，确认 GREEN 后单独提交；不得把所有任务压成一次提交。

---

## 1. 文件结构和接口总图

01E-A 最终新增或修改：

```text
pyproject.toml
src/cs2pov/domain/assets.py
src/cs2pov/adapters/zstandard_adapter.py
src/cs2pov/storage/demo_asset_repository.py
src/cs2pov/application/demo_assets.py
src/cs2pov/application/__init__.py
src/cs2pov/cli/demo_commands.py
src/cs2pov/cli/commands.py
tests/test_demo_asset_models.py
tests/test_zstandard_adapter.py
tests/test_demo_asset_repository.py
tests/test_demo_asset_application.py
tests/test_demo_asset_cli.py
scripts/check_workspace_demo_asset_e2e.py
.github/workflows/ci.yml
README.md
README.zh.md
docs/ARCHITECTURE.zh.md
docs/FAQ.zh.md
docs/OUTPUT_FILES.zh.md
docs/RELEASE_CHECKLIST.zh.md
docs/TESTING_GUIDE.zh.md
```

核心接口固定为：

```python
# cs2pov.domain.assets
DEMO_ASSET_SCHEMA_VERSION = 1

@dataclass(frozen=True, slots=True)
class DemoAsset:
    schema_version: int
    asset_id: str
    logical_sha256: str
    logical_size_bytes: int
    source_sha256: str
    source_size_bytes: int
    source_format: str
    source_relative_path: str
    display_name: str
    imported_at: str
    def to_dict(self) -> dict[str, object]: ...
    @classmethod
    def from_dict(cls, value: object) -> "DemoAsset": ...
    def to_ref(self) -> "DemoAssetRef": ...

@dataclass(frozen=True, slots=True)
class DemoAssetRef:
    asset_id: str
    asset_manifest_relative_path: str
    def to_dict(self) -> dict[str, str]: ...

@dataclass(frozen=True, slots=True)
class DemoImportResult:
    asset: DemoAsset
    disposition: str  # imported | reused
    persistent_bytes_added: int
    def to_dict(self) -> dict[str, object]: ...

@dataclass(frozen=True, slots=True)
class DemoAssetSummary:
    asset_id: str
    display_name: str | None
    source_format: str | None
    source_size_bytes: int | None
    logical_size_bytes: int | None
    imported_at: str | None
    healthy: bool
    issue_code: str | None
    def to_dict(self) -> dict[str, object]: ...

@dataclass(frozen=True, slots=True)
class DemoAssetInspection:
    asset: DemoAsset
    source_ok: bool
    cache_status: str  # not_applicable | missing | valid | corrupt
    issues: tuple[str, ...]
    @property
    def ok(self) -> bool: ...
    def to_dict(self) -> dict[str, object]: ...
```

```python
# cs2pov.adapters.zstandard_adapter
class DemoCompressionError(RuntimeError): ...

class ZstandardDemoAdapter:
    def iter_decompressed(
        self, source: BinaryIO, *, chunk_size: int = 1024 * 1024
    ) -> Iterator[bytes]: ...
```

```python
# cs2pov.storage.demo_asset_repository
class DemoAssetRepositoryError(RuntimeError):
    code: str
    message_zh: str
    suggestion_zh: str

class FileSystemDemoAssetRepository:
    def __init__(
        self,
        paths: WorkspacePaths,
        *,
        decompressor: ZstandardDemoAdapter | None = None,
        clock: Callable[[], datetime] = utc_now,
        id_factory: Callable[[], UUID] = uuid4,
        chunk_size: int = 1024 * 1024,
    ) -> None: ...
    def import_source(self, source: Path) -> DemoImportResult: ...
    def list_assets(self) -> tuple[DemoAssetSummary, ...]: ...
    def inspect_asset(self, asset_id: str) -> DemoAssetInspection: ...
    def resolve_asset(self, ref: DemoAssetRef) -> Path: ...
```

```python
# cs2pov.application.demo_assets
class DemoAssetUseCaseError(RuntimeError):
    code: str
    message_zh: str
    suggestion_zh: str

class DemoAssetApplicationService:
    def __init__(
        self,
        runtime_resolver: WorkspaceRuntimeResolver,
        *,
        repository_factory: Callable[[WorkspacePaths], FileSystemDemoAssetRepository]
            = FileSystemDemoAssetRepository,
    ) -> None: ...
    def import_demo(self, source: str | Path) -> DemoImportResult: ...
    def list_assets(self) -> tuple[DemoAssetSummary, ...]: ...
    def inspect_asset(self, asset_id: str) -> DemoAssetInspection: ...
    def resolve_asset(self, ref: DemoAssetRef) -> Path: ...
```

任务实现中如发现签名无法成立，立即停止并报告；不得让相邻任务各自发明不同名称。

仓储与应用层使用以下精确稳定错误码，CLI 不得重新命名：

```text
demo_source_required
demo_source_not_found
demo_source_not_file
demo_source_format_unsupported
demo_source_empty
demo_source_unreadable
demo_source_changed
demo_decompression_failed
demo_import_space_insufficient
demo_asset_id_invalid
demo_asset_not_found
demo_asset_manifest_invalid
demo_asset_path_escape
demo_asset_integrity_failed
demo_asset_commit_failed
demo_cache_rebuild_failed
```

只有设计内的已知用户/文件系统错误映射到这些 code；`AssertionError`、`TypeError` 等未知程序缺陷必须继续暴露给测试和开发日志，不能伪装成可恢复用户错误。

---

### Task 1: 版本化 DemoAsset 领域契约

**Files:**
- Create: `src/cs2pov/domain/assets.py`
- Create: `tests/test_demo_asset_models.py`

**Interfaces:**
- Consumes: Python 标准库；不消费工作区、存储、zstandard 或 CLI。
- Produces: `DemoAsset`、`DemoAssetRef`、`DemoImportResult`、`DemoAssetSummary`、`DemoAssetInspection` 及其稳定 `to_dict/from_dict` 契约。

- [ ] **Step 1: 为精确 schema 和序列化写失败测试**

测试至少包含以下断言，使用固定 UTC 时间和匿名哈希：

```python
def valid_asset() -> DemoAsset:
    asset_id = hashlib.sha256(b"anonymous-demo").hexdigest()
    return DemoAsset(
        schema_version=1,
        asset_id=asset_id,
        logical_sha256=asset_id,
        logical_size_bytes=14,
        source_sha256=asset_id,
        source_size_bytes=14,
        source_format="dem",
        source_relative_path=f"library/demos/{asset_id}/source.dem",
        display_name="match.dem",
        imported_at="2026-08-31T00:00:00.000000Z",
    )

def test_demo_asset_round_trips_exact_schema():
    asset = valid_asset()
    assert DemoAsset.from_dict(asset.to_dict()) == asset
    assert set(asset.to_dict()) == {
        "schema_version", "asset_id", "logical_sha256",
        "logical_size_bytes", "source_sha256", "source_size_bytes",
        "source_format", "source_relative_path", "display_name", "imported_at",
    }
```

覆盖 `DemoAssetRef.to_dict()` 的精确两个键、五种 DTO 的 JSON 可序列化结果、`DemoAssetInspection.ok` 只取决于持久源/manifest 而不是缓存缺失。

- [ ] **Step 2: 运行领域测试并确认 RED**

Run: `py -3.12 -m pytest -q tests/test_demo_asset_models.py`

Expected: collection/import 失败，明确显示 `cs2pov.domain.assets` 或类型尚不存在；不能因为测试没有执行而“通过”。

- [ ] **Step 3: 写非法输入矩阵测试**

参数化拒绝：

- schema 不是整数 1；
- `asset_id`/哈希不是 64 位小写十六进制；
- `asset_id != logical_sha256`；
- bool 冒充整数大小、负数大小；
- `source_format` 不是 `dem`/`dem.zst`；
- 源格式和文件名后缀不匹配；
- 路径包含反斜杠、盘符、绝对路径、空段、`.`、`..`；
- 路径不是精确的 `library/demos/<asset_id>/source.dem[.zst]`；
- display name 为空、带 `/`、`\`、控制字符或超过 255 字符；
- 时间不是带 6 位微秒的 UTC `...Z`；
- `from_dict()` 缺键、多键或接收非 dict；
- DTO disposition 不是 `imported/reused`、cache status 不在固定集合。

- [ ] **Step 4: 实现最小不可变领域模型**

实现时使用 frozen/slots dataclass。验证函数保持纯函数，例如：

```python
_HASH_RE = re.compile(r"^[0-9a-f]{64}$")
_ASSET_KEYS = frozenset({...精确十个 manifest 键...})

def _validate_hash(value: object, field: str) -> str:
    if not isinstance(value, str) or _HASH_RE.fullmatch(value) is None:
        raise ValueError(f"{field} 必须是 64 位小写 SHA-256。")
    return value
```

`to_dict()` 必须手写稳定字段，不使用 `asdict()` 自动暴露未来字段。`from_dict()` 先验证精确 key set，再调用构造器。领域异常消息不得包含路径实值。

- [ ] **Step 5: 运行领域测试并确认 GREEN**

Run: `py -3.12 -m pytest -q tests/test_demo_asset_models.py`

Expected: 全部通过，无 skip。

- [ ] **Step 6: 提交 Task 1**

```powershell
git add src/cs2pov/domain/assets.py tests/test_demo_asset_models.py
git commit -m "feat: define versioned DemoAsset contracts"
```

Review checkpoint: 检查领域文件没有导入 `workspace`、`storage`、`zstandard`、`argparse`、Pipeline 或第三方库。

---

### Task 2: zstandard 流式适配器与基础依赖

**Files:**
- Modify: `pyproject.toml`
- Create: `src/cs2pov/adapters/zstandard_adapter.py`
- Create: `tests/test_zstandard_adapter.py`
- Modify: `src/cs2pov/adapters/demoparser_adapter.py`（仅复用新适配器消除重复解压逻辑；不得修改 inspect/voice/round 行为）

**Interfaces:**
- Consumes: `zstandard>=0.23`。
- Produces: `ZstandardDemoAdapter.iter_decompressed()`，供 Task 3 仓储以固定大小块流式写入并计算哈希。

- [ ] **Step 1: 写流式解压失败测试**

```python
def test_iter_decompressed_yields_original_bytes_in_bounded_chunks():
    original = (b"anonymous-cs2-demo" * 8192) + b"end"
    compressed = zstandard.ZstdCompressor(level=3).compress(original)
    chunks = list(ZstandardDemoAdapter().iter_decompressed(io.BytesIO(compressed), chunk_size=4096))
    assert b"".join(chunks) == original
    assert chunks
    assert all(0 < len(chunk) <= 4096 for chunk in chunks)
```

另测有效的空压缩流、截断/随机字节、`chunk_size` 为 bool/0/负数、source 没有 `read()`。适配器允许有效空帧产生零个 chunk，由 repository 映射为 `demo_source_empty`；损坏输入统一抛 `DemoCompressionError`，消息不包含源路径。

- [ ] **Step 2: 运行适配器测试并确认 RED**

Run: `py -3.12 -m pytest -q tests/test_zstandard_adapter.py`

Expected: 新模块不存在或接口缺失。

- [ ] **Step 3: 把 zstandard 提升为基础依赖**

`pyproject.toml` 必须变为：

```toml
dependencies = ["zstandard>=0.23"]
cs2 = ["demoparser2>=0.41", "pyogg>=0.6.1a1"]
all = ["demoparser2>=0.41", "pyogg>=0.6.1a1", "faster-whisper>=1.1", "Pillow>=10.0", "PyYAML>=6.0", "pytest>=8.0"]
```

不要在 `cs2` 或 `all` 重复声明基础依赖。更新现有安装文档留到 Task 6。

- [ ] **Step 4: 实现 bounded streaming adapter**

使用 `ZstdDecompressor().stream_reader(source)`，只按 `chunk_size` 读取；不得调用 `source.read()` 无长度版本，不得一次加载整个 Demo。捕获 zstandard/IO 解压异常并以 `DemoCompressionError` 链接原异常。

然后让 `DemoparserAdapter.decompress_if_needed()` 的 `.zst` 分支消费同一迭代器并写目标文件；非 `.zst` 的 `shutil.copy2` 行为不变。

- [ ] **Step 5: 运行适配器与既有 Demo 服务测试**

Run:

```powershell
py -3.12 -m pytest -q tests/test_zstandard_adapter.py tests/test_workspace_job_pipeline_batch_b.py tests/test_artifact_store.py
```

Expected: 全部通过；不存在新增 skip。

- [ ] **Step 6: 提交 Task 2**

```powershell
git add pyproject.toml src/cs2pov/adapters/zstandard_adapter.py src/cs2pov/adapters/demoparser_adapter.py tests/test_zstandard_adapter.py
git commit -m "feat: add streaming zstandard demo adapter"
```

Review checkpoint: 搜索 `read_bytes()`、无参数 `read()` 和一次性 `decompress()`，确认生产解压路径没有整文件加载。

---

### Task 3: `.dem` 原子导入、manifest 和只读查询

**Files:**
- Create: `src/cs2pov/storage/demo_asset_repository.py`
- Create: `tests/test_demo_asset_repository.py`

**Interfaces:**
- Consumes: Task 1 领域类型、`WorkspacePaths`、Task 2 解压适配器接口。
- Produces: `DemoAssetRepositoryError`、`FileSystemDemoAssetRepository.import_source/list_assets/inspect_asset/resolve_asset`；Task 3 先让 `.dem` 路径 GREEN，`.dem.zst` 在 Task 4 完成。

- [ ] **Step 1: 写 `.dem` 导入和精确落盘测试**

```python
def test_import_dem_commits_one_content_addressed_asset(runtime, tmp_path):
    source = tmp_path / "中文 比赛.dem"
    source.write_bytes(b"anonymous-demo-v1")
    repo = FileSystemDemoAssetRepository(runtime.paths, clock=fixed_clock, id_factory=fixed_uuid)

    result = repo.import_source(source)

    expected = hashlib.sha256(b"anonymous-demo-v1").hexdigest()
    assert result.disposition == "imported"
    assert result.asset.asset_id == expected
    asset_dir = runtime.paths.demo_library_dir / expected
    assert (asset_dir / "source.dem").read_bytes() == b"anonymous-demo-v1"
    assert DemoAsset.from_dict(json.loads((asset_dir / "asset.json").read_text("utf-8"))) == result.asset
    assert not list((runtime.paths.temp_dir / "demo_imports").glob("*/asset"))
```

断言 manifest 没有外部绝对路径，`persistent_bytes_added` 等于持久 source 加 manifest 的实际文件大小总和，不估算。

- [ ] **Step 2: 运行单测并确认 RED**

Run: `py -3.12 -m pytest -q tests/test_demo_asset_repository.py -k "import_dem"`

Expected: repository 模块或方法不存在。

- [ ] **Step 3: 写复用、源变化和写前失败测试**

覆盖：

- 相同字节、不同 basename 第二次返回 `reused`，目录数仍为 1，首个 display name/源不变，新增字节为 0；
- 不同内容生成不同 ID；
- `None`、空字符串、缺失路径、目录、`.txt`、`.zst` 非复合后缀；
- bool/非法 chunk size、非法 clock/id factory；
- 外部 source 在复制期间 size/mtime/file identity 改变返回 `demo_source_changed`；
- `WorkspacePaths` 的 demo library 或 temp 通过 symlink/junction 越界时，在创建 staging 前返回 `demo_asset_path_escape`；
- 模拟 `errno.ENOSPC` 映射为 `demo_import_space_insufficient`；
- 模拟重命名失败映射为 `demo_asset_commit_failed`，最终目录不可见。

测试 source 变化时使用可注入的分块流或 monkeypatch 文件状态，不使用不稳定 sleep。

- [ ] **Step 4: 实现 `.dem` staging 和原子目录提交**

实现要点：

```python
imports_root = paths.temp_dir / "demo_imports"
staging_root = imports_root / str(id_factory())
staging_asset = staging_root / "asset"
final_asset = paths.demo_library_dir / asset_id
```

- 在打开和复制前后比较 `stat().st_size`、`st_mtime_ns`，并在平台提供时比较 `st_dev/st_ino`；
- 用固定 1 MiB 块复制到 `staging_asset/source.dem`，同步更新 hashlib 和 logical size；
- 用严格 UTC clock 创建 `DemoAsset`；
- 通过临时 manifest + `os.replace` 在 staging 内完成 `asset.json`，再把整个非空 `asset/` 目录 `rename` 到 final；
- 目标已存在时不覆盖，验证既有资产自身完整且逻辑 ID 相同，然后返回 `reused`；
- `finally` 只清理当前随机 staging，不清理其他进程目录；
- 异常清理不得递归作用于 `cache/tmp/demo_imports` 根或 `library/demos` 根。

禁止 `shutil.copytree(..., dirs_exist_ok=True)`、`os.replace(staging_asset, existing_asset)` 或先 mkdir final 再填文件。

- [ ] **Step 5: 写 list/inspect 只读测试**

覆盖：

- list 忽略 `_` 开头目录、随机 staging、非 64 位目录和链接目录；合法 64 位资产目录缺 manifest 时保留为 `healthy=false` 的损坏摘要；
- list 对完整资产按 `(imported_at, asset_id)` 确定性排序；
- list 遇到损坏资产返回 `healthy=False` summary，而不是 traceback 或静默消失；
- inspect 对健康 `.dem` 返回 `source_ok=True/cache_status=not_applicable/ok=True`；
- inspect 不创建、修改、删除任何文件；用递归路径+hash 快照证明；
- 非法 ID 返回 `demo_asset_id_invalid`，不存在返回 `demo_asset_not_found`；
- manifest 多键/缺键、路径逃逸返回对应稳定错误；manifest 可解析但 source size/hash 不匹配时返回 `source_ok=False`、`issues=("demo_asset_integrity_failed",)` 的 inspection。

- [ ] **Step 6: 实现 manifest 加载、完整性检查和查询**

所有读取先 `lstat`/containment，拒绝 asset dir、manifest 或 source 为链接。哈希使用 `_hash_stream(path, chunk_size) -> tuple[str, int]`，不使用 `read_bytes()`。

`list_assets()` 对每个候选单独捕获已知完整性错误并生成不健康 summary；无法解析 manifest 时仅保留目录中的合法 `asset_id`，其余展示字段为 `None`，`issue_code` 为稳定错误码。不得因为一个坏资产阻止用户看到其他资产。`inspect_asset()` 对目标执行严格验证并返回结构化 inspection；manifest 可解析但持久源错误使 `inspection.ok=False`，缓存缺失不使 `.zst` 持久资产失败。manifest 本身无法解析时才抛 `demo_asset_manifest_invalid`。

- [ ] **Step 7: 运行 Task 3 测试和相关回归**

Run:

```powershell
py -3.12 -m pytest -q tests/test_demo_asset_models.py tests/test_zstandard_adapter.py tests/test_demo_asset_repository.py
py -3.12 -m pytest -q tests/test_workspace_paths.py tests/test_workspace_runtime.py tests/test_job_runtime.py
```

Expected: 全部通过；Windows junction 用例若系统允许创建必须实际通过，不能用平台 skip 掩盖。

- [ ] **Step 8: 提交 Task 3**

```powershell
git add src/cs2pov/storage/demo_asset_repository.py tests/test_demo_asset_repository.py
git commit -m "feat: import content-addressed demo assets"
```

Review checkpoint: 人工检查每个 recursive cleanup 的解析后绝对目标都严格位于当前 staging；检查任何错误路径都不会删除既有 asset。

---

### Task 4: `.dem.zst`、缓存重建和多进程一致性

**Files:**
- Modify: `src/cs2pov/storage/demo_asset_repository.py`
- Modify: `tests/test_demo_asset_repository.py`
- Create: `tests/test_demo_asset_concurrency.py`

**Interfaces:**
- Consumes: Task 2 `ZstandardDemoAdapter.iter_decompressed()`、Task 3 仓储。
- Produces: 两种输入格式共享逻辑 ID；`resolve_asset()` 为 `.zst` 安全复用或重建缓存；真实进程级提交语义。

- [ ] **Step 1: 写跨格式去重失败测试**

用 zstandard level 1 与 level 9 生成字节不同但解压内容相同的两个 `.dem.zst`：

```python
logical = b"anonymous-logical-demo" * 4096
zst_a = ZstdCompressor(level=1).compress(logical)
zst_b = ZstdCompressor(level=9).compress(logical)
assert zst_a != zst_b

first = repo.import_source(path_a)
second = repo.import_source(path_b)
third = repo.import_source(plain_dem)
assert {first.asset.asset_id, second.asset.asset_id, third.asset.asset_id} == {
    hashlib.sha256(logical).hexdigest()
}
assert first.asset.source_format == "dem.zst"
assert (asset_dir / "source.dem.zst").read_bytes() == zst_a
assert not (asset_dir / "source.dem").exists()
```

再反向测试 `.dem` 首先提交时后续 `.dem.zst` 不替换 source。

- [ ] **Step 2: 运行跨格式测试并确认 RED**

Run: `py -3.12 -m pytest -q tests/test_demo_asset_repository.py -k "zst or cross_format"`

Expected: `.dem.zst` 尚不支持或 identity 不正确。

- [ ] **Step 3: 实现压缩源 staging 与逻辑哈希**

- 压缩源流式复制到 `staging/asset/source.dem.zst` 并计算 source hash/size；
- 同一 staging 根写 `logical.dem`，消费解压 chunks 时同步计算 logical hash/size；
- 只提交 `asset/` 子目录，绝不把 `logical.dem` 放入 `library/demos`；
- 资产提交后把 `logical.dem` 提交到 `cache/decompressed_demos/<asset_id>.dem`；
- 如果并发胜出的既有资产 source 格式不同，只验证它自身和 candidate logical ID，不要求两个 source hash 相同；
- 无效/截断 zstd 返回 `demo_decompression_failed`，不产生 asset；
- asset 已完整提交但 cache 提交失败时，持久资产保持完整，并返回 `demo_cache_rebuild_failed` 或在同次操作成功重建后返回；不得回滚删除资产。

- [ ] **Step 4: 写 cache 只读检查与 resolve 重建测试**

覆盖：

- import `.zst` 后 cache 内容与逻辑内容一致；
- inspect 报告 valid/missing/corrupt，但路径和内容快照证明它从不写；
- 删除 cache 后 `resolve_asset(ref)` 原子重建并返回 cache 路径；
- 篡改为相同大小的 cache 也必须用 SHA-256 检出并安全替换；
- 多线程同时 resolve 最终只有一个正确文件；
- 持久压缩 source hash 错误时 resolve 返回 `demo_asset_integrity_failed`，不使用已有 cache 掩盖源损坏；
- cache target 是 symlink/junction 时返回 `demo_asset_path_escape`，不跟随写出工作区；
- cache rename 失败不破坏已有有效 cache 或持久资产。

- [ ] **Step 5: 实现安全 cache commit**

缓存候选始终在 `cache/decompressed_demos` 或工作区同盘 staging。提交前验证逻辑大小/hash。若目标存在：

- 有效：删除当前候选并复用；
- 无效普通文件：使用同文件系统 `os.replace` 把已验证候选原子替换为正式缓存；替换失败时旧缓存必须保持原样；
- 链接、目录或越界：拒绝，不删除；
- 并发冲突：首次缺失提交使用硬链接的 no-clobber 语义；重新验证胜出目标，有效才复用，损坏普通文件才允许由已验证候选安全替换。

所有 destructive 操作必须先以 `WorkspacePaths._inside()` 验证精确文件，不接受 glob、环境变量或宽目录。

- [ ] **Step 6: 写进程级并发与中断状态测试**

`tests/test_demo_asset_concurrency.py` 使用 `multiprocessing` 的 spawn context 或真实 `subprocess`，不得只用 `ThreadPoolExecutor`：

- 6 个进程同时导入同一 `.dem`；
- 6 个进程同时导入不同压缩字节但相同逻辑内容；
- 断言全部成功返回同一 ID、一个 asset 目录、一个 source、一个 manifest；
- 预置其他随机 staging 和完整 staging/asset，正常导入不得把它当正式资产或误删；
- 预置已损坏 final asset，所有进程稳定失败且 final 字节保持不变；
- Windows 下真实创建 directory junction 指向外部临时目录，验证没有外部写入。

子进程函数必须位于模块顶层，兼容 Windows spawn。每个进程只接收临时路径和匿名字节，不继承真实 workspace selection。

- [ ] **Step 7: 运行 Task 4 和完整仓储测试**

Run:

```powershell
py -3.12 -m pytest -q tests/test_demo_asset_repository.py tests/test_demo_asset_concurrency.py
py -3.12 -m pytest -q tests/test_demo_asset_models.py tests/test_zstandard_adapter.py tests/test_workspace_paths.py tests/test_workspace_runtime.py
```

Expected: 全部通过；无竞态重跑才能过的 flaky 测试。

- [ ] **Step 8: 提交 Task 4**

```powershell
git add src/cs2pov/storage/demo_asset_repository.py tests/test_demo_asset_repository.py tests/test_demo_asset_concurrency.py
git commit -m "feat: verify and resolve compressed demo assets"
```

Review checkpoint: 运行 `rg -n "read_bytes|copytree|rmtree|unlink|replace|rename" src/cs2pov/storage/demo_asset_repository.py`，逐处审查内存、覆盖和删除边界。

---

### Task 5: 应用服务与非程序员 CLI

**Files:**
- Create: `src/cs2pov/application/demo_assets.py`
- Modify: `src/cs2pov/application/__init__.py`
- Create: `src/cs2pov/cli/demo_commands.py`
- Modify: `src/cs2pov/cli/commands.py`
- Create: `tests/test_demo_asset_application.py`
- Create: `tests/test_demo_asset_cli.py`

**Interfaces:**
- Consumes: `WorkspaceRuntimeResolver`、Task 3/4 仓储。
- Produces: `DemoAssetApplicationService`、`DemoAssetUseCaseError`、三个 CLI 子命令及稳定文本/JSON envelope；01E-B 直接复用 `import_demo/resolve_asset`。

- [ ] **Step 1: 写应用服务 runtime 和错误映射测试**

使用 fake runtime resolver 与 fake repository，精确断言：

```python
def test_import_resolves_write_runtime_before_repository_call():
    result = app.import_demo("match.dem")
    assert resolver.calls == ["write"]
    assert factory.paths == runtime.paths
    assert repository.imported == Path("match.dem")

def test_list_and_inspect_are_read_only_runtime_calls():
    app.list_assets()
    app.inspect_asset("a" * 64)
    assert resolver.calls == ["read", "read"]
```

`resolve_asset()` 使用 write runtime，因为它可能重建 cache。映射 Task 3 稳定 error code，不把底层 OSError、路径或 traceback塞入 message。未知异常不得被误标成“用户错误”。

- [ ] **Step 2: 运行应用测试并确认 RED**

Run: `py -3.12 -m pytest -q tests/test_demo_asset_application.py`

Expected: application 模块不存在。

- [ ] **Step 3: 实现应用服务和导出**

`DemoAssetUseCaseError` 与现有 `WorkspaceRuntimeError` 一样保存 `code/message_zh/suggestion_zh`。服务每次调用只解析一次 runtime，并把同一 `runtime.paths` 交给 repository。不得读取 cwd、环境变量、默认 output 或旧 config。

在 `application/__init__.py` 导出新服务和错误；不得把具体 repository 加入 public application API。

- [ ] **Step 4: 写 CLI parser、文本与 JSON 测试**

命令固定为：

```text
cs2pov demos import <path> [--json]
cs2pov demos list [--json]
cs2pov demos inspect <asset-id> [--json]
```

成功 JSON 固定：

```json
{"ok": true, "command": "demos.import", "result": {}}
{"ok": true, "command": "demos.list", "count": 1, "assets": []}
{"ok": true, "command": "demos.inspect", "inspection": {}}
```

失败 JSON 固定：

```json
{
  "ok": false,
  "command": "demos.import",
  "error": {
    "code": "demo_source_not_found",
    "message_zh": "...",
    "suggestion_zh": "..."
  }
}
```

inspect 的顶层 `ok` 必须等于 `inspection.ok`；持久源损坏时返回 code 1 和 inspection，而不是丢失细节改成通用 error envelope。测试必须执行 `json.loads(stdout)`，断言 stderr 只含允许的人类进度，stdout 无前后杂字。文本模式断言：

- imported：包含“已导入到当前工作区素材库”和长期新增空间；
- reused：包含“工作区已有相同 Demo，本次直接复用”；
- list 空库：说明可运行 `cs2pov demos import`；
- inspect cache missing：说明源安全、需要时可重建，不声称损坏；
- persistent source 损坏：返回 1、中文建议、无 traceback；
- 未选择/损坏 workspace：稳定返回 workspace error，且无素材/staging 写入。

- [ ] **Step 5: 实现独立 demo_commands 模块并接线**

仿照 `workspace_commands.py`，在 `demo_commands.py` 提供：

```python
def add_demos_parser(subparsers) -> None: ...
def run_demos(args: argparse.Namespace) -> int: ...
```

`commands.main()` 只增加 parser 注册；`dispatch()` 在其他资源命令前路由 `args.cmd == "demos"`。已知 DemoAsset 错误由 `run_demos()` 生成 envelope，不落到 `commands.py` 的通用异常/feedback 文案。

普通文本不打印工作区绝对 root 或 asset source 绝对路径；可显示用户传入的 basename、完整 asset ID、大小和工作区相对路径。

- [ ] **Step 6: 运行 CLI/应用与现有入口回归**

Run:

```powershell
py -3.12 -m pytest -q tests/test_demo_asset_application.py tests/test_demo_asset_cli.py
py -3.12 -m pytest -q tests/test_workspace_cli.py tests/test_cli_encoding.py tests/test_launcher_navigation.py tests/test_release_entry_v096.py
py -3.12 scripts/launch_sanity_check.py
```

Expected: 全部通过；无现有帮助/启动器行为变化。

- [ ] **Step 7: 提交 Task 5**

```powershell
git add src/cs2pov/application/demo_assets.py src/cs2pov/application/__init__.py src/cs2pov/cli/demo_commands.py src/cs2pov/cli/commands.py tests/test_demo_asset_application.py tests/test_demo_asset_cli.py
git commit -m "feat: manage DemoAssets through workspace CLI"
```

Review checkpoint: `cs2pov run --help`、`cs2pov-wizard` 和 Pipeline 文件必须没有功能性变化；`demos --help` 不出现 delete/repair/migrate。

---

### Task 6: 真实子进程 E2E、CI 与当前文档

**Files:**
- Create: `scripts/check_workspace_demo_asset_e2e.py`
- Modify: `.github/workflows/ci.yml`
- Modify: `README.md`
- Modify: `README.zh.md`
- Modify: `docs/ARCHITECTURE.zh.md`
- Modify: `docs/FAQ.zh.md`
- Modify: `docs/OUTPUT_FILES.zh.md`
- Modify: `docs/RELEASE_CHECKLIST.zh.md`
- Modify: `docs/TESTING_GUIDE.zh.md`
- Modify: `docs/INDEX.zh.md`（加入本设计和任务书入口）

**Interfaces:**
- Consumes: 完整 01E-A CLI 和仓储。
- Produces: CI 每个 OS/Python 矩阵都执行的真实文件系统 E2E，以及诚实描述 01E-A/01E-B 边界的用户文档。

- [ ] **Step 1: 先写 E2E 脚本并确认旧 HEAD 失败**

脚本必须真实运行 `sys.executable -m cs2pov`，不得导入 `run_demos()`、monkeypatch 或调用 repository。隔离：

```python
env.update({
    "PYTHONUTF8": "1",
    "PYTHONDONTWRITEBYTECODE": "1",
    "PYTHONPATH": str(source_root / "src"),
    "CS2POV_STATE_FILE": str(base / "state" / "workspace.json"),
    "HOME": str(base / "HOME"),
    "USERPROFILE": str(base / "HOME"),
    "LOCALAPPDATA": str(base / "LOCALAPPDATA"),
    "APPDATA": str(base / "APPDATA"),
    "XDG_STATE_HOME": str(base / "XDG_STATE"),
    "XDG_CONFIG_HOME": str(base / "XDG_CONFIG"),
})
```

首次运行脚本应在未实现/未接 CI 的旧提交上失败；记录失败原因后继续。

- [ ] **Step 2: 实现基础导入和跨格式 E2E**

在临时目录生成匿名 logical bytes、plain `.dem`、level 1 和 level 9 的 `.dem.zst`。先导入 zst-A，再导入不同名 `.dem` 和 zst-B：

- 三次 stdout 都可 `json.loads`；
- disposition 依次为 imported/reused/reused；
- asset ID 相同；
- `library/demos` 只有一个 64 位目录；
- 目录只有 `asset.json` 与首个 `source.dem.zst`；
- manifest key set 精确、无任一隔离 root 字符串；
- list/inspect JSON 可解析且不回显外部路径。

- [ ] **Step 3: 实现 cache、中断和真实并发 E2E**

- 删除解压 cache；`demos inspect --json` 只报告 missing 且快照无写入；再次 `demos import zst-A --json` 后 cache 被重建；
- 在 `cache/tmp/demo_imports/orphan/asset` 放不完整文件；list 不显示，后续导入成功且不删除非本进程 orphan；
- 使用 `subprocess.Popen` 同时启动至少 6 个 import，等待全部退出；全部 code 0、同 ID、仍只有一个资产；
- 篡改持久 source 的一个字节，再执行 inspect/import，二者稳定失败且坏 source/manifest 不被覆盖；
- Windows 与 Ubuntu 都执行相同逻辑，不以 `os.name` 跳过整个并发或完整性部分。

- [ ] **Step 4: 实现旁路写入和写前失败断言**

递归快照文件名、大小和 SHA-256：源码树、cwd、隔离 HOME、USERPROFILE、LOCALAPPDATA、APPDATA、XDG、工作区外 sentinel。验证：

- workspace init 前的 `demos import` 稳定失败且所有快照不变；
- 损坏 `workspace.json` 后 import 稳定失败且 library/cache 不变；
- 正常命令只改变 state 文件和当前 workspace；
- 源外部文件 hash/mtime 不变；
- 无 `__pycache__`、默认 `output/`、`jobs/`、HF/Whisper cache 或临时文件旁路。

E2E 最后打印唯一成功行：

```text
workspace DemoAsset E2E passed: content dedupe, atomic concurrency, integrity, and path isolation
```

- [ ] **Step 5: 串行运行新旧真实 E2E**

Run:

```powershell
py -3.12 scripts/check_workspace_cli_e2e.py
py -3.12 scripts/check_workspace_model_runtime_e2e.py
py -3.12 scripts/check_workspace_job_runtime_e2e.py
py -3.12 scripts/check_workspace_demo_asset_e2e.py
```

Expected: 四个脚本全部通过。不要与 compileall 并行，因为源码快照会把编译产生的 `__pycache__` 视为污染。

- [ ] **Step 6: 把新 E2E 接入所有 CI 矩阵**

在 workspace Job E2E 后加入：

```yaml
- name: Exercise workspace DemoAsset library end to end
  run: python scripts/check_workspace_demo_asset_e2e.py
```

不得创建只覆盖 Ubuntu 的新 job；当前 Ubuntu 3.11/3.12/3.13 和 Windows 3.12 的每个矩阵项都必须运行它。

- [ ] **Step 7: 更新当前文档，禁止过度声明**

文档必须说明：

- `library/demos/<asset_id>` 是持久素材，`cache/decompressed_demos` 可清理；
- 显式 `demos import/list/inspect` 可用，普通用户暂时仍可以按现有 run/向导处理；
- 01E-A **尚未**让 Pipeline/Job 自动引用资产，当前 Job 输入副本会在 01E-B 才移除；
- `demos inspect` 只读，缓存重建由 import 或未来 resolve 触发；
- 不要提交 Demo、素材库、缓存或真实哈希数据；
- 未实现 delete、旧 Job 迁移、Web、理解翻译或录制。

不得修改 archive 历史文档。`docs/INDEX.zh.md` 加入设计和任务书链接。

- [ ] **Step 8: 运行完整本地门禁**

严格串行执行：

```powershell
py -3.12 -m pytest -q
py -3.12 scripts/check_workspace_cli_e2e.py
py -3.12 scripts/check_workspace_model_runtime_e2e.py
py -3.12 scripts/check_workspace_job_runtime_e2e.py
py -3.12 scripts/check_workspace_demo_asset_e2e.py
py -3.12 scripts/check_golden_baseline.py --replay
py -3.12 scripts/check_repository_hygiene.py --root .
py -3.12 -m compileall -q src tests scripts
py -3.12 scripts/launch_sanity_check.py
git diff --check
git status --short
```

Expected: 所有命令 exit 0；pytest 只允许既有平台/可选依赖 skip，新 DemoAsset 核心测试不得 skip；工作树只包含计划内修改。

- [ ] **Step 9: 提交 Task 6**

```powershell
git add scripts/check_workspace_demo_asset_e2e.py .github/workflows/ci.yml README.md README.zh.md docs/ARCHITECTURE.zh.md docs/FAQ.zh.md docs/OUTPUT_FILES.zh.md docs/RELEASE_CHECKLIST.zh.md docs/TESTING_GUIDE.zh.md docs/INDEX.zh.md
git commit -m "test: gate workspace DemoAsset library behavior"
```

Review checkpoint: `rg -n "01E|DemoAsset|Pipeline|自动导入|input/" README.md README.zh.md docs/*.zh.md`，确认当前文档明确 01E-A 已完成但 01E-B 尚未完成。

---

## 2. Luna 执行与审查协议

### 2.1 执行批次

Luna 按以下检查点执行，不得跨批隐藏中间失败：

1. Batch A：Task 1–2，领域契约和 zstd 适配器；
2. Batch B：Task 3，`.dem` 仓储、原子导入和只读查询；
3. Batch C：Task 4，`.dem.zst`、缓存和多进程；
4. Batch D：Task 5，应用服务和 CLI；
5. Batch E：Task 6，真实 E2E、CI 和文档。

每批结束必须回报：提交号、RED/GREEN 证据、实际运行命令、skip 数、已知风险和 `git status --short`。未经主审确认不得进入下一批。

### 2.2 必须停止并上报的情况

- 现有设计要求无法用固定接口实现；
- 需要修改 Pipeline、Job manifest、wizard 或 run 才能让 01E-A 通过；
- 需要数据库、文件锁第三方库、Web 框架或新增删除功能；
- 需要覆盖/删除损坏的持久资产；
- Windows 与 POSIX 无法共享原子提交语义；
- CI 需要跳过 Windows 并发/junction 核心测试；
- zstandard 基础依赖与当前打包发生不可兼容冲突；
- 发现真实秘密、Demo、模型或用户产物已进入 git 状态。

遇到这些情况只报告证据和最小选项，不自行扩张范围。

### 2.3 主审与合并门禁

实现完成后：

1. 主模型审查每批 diff 和测试设计；
2. 完整本地门禁在最终 HEAD 新鲜运行；
3. 独立强模型只读审查完整 `master..HEAD`，重点检查原子性、并发、链接逃逸、损坏覆盖、JSON 和虚假 E2E；
4. Critical/Important 必须修复并重新复审；
5. 推送功能分支并创建 PR；
6. GitHub 全矩阵 CI 全绿后才允许自动 merge；
7. 合并后 fetch 并 fast-forward 本地 master；
8. 仅在工作树干净、PR 已合并后清理功能工作树和分支。

## 3. 01E-A 完成定义

只有以下条件全部成立才完成：

- `.dem` 与 `.dem.zst` 都能导入；
- 相同解压内容跨文件名、跨压缩字节、跨格式只产生一个资产；
- 首个持久源不被后续复用替换；
- manifest schema 精确、路径相对、无外部路径；
- 多进程并发最终只有一个完整资产；
- 中断 staging 不可见且不会阻塞重试；
- 损坏持久资产拒绝复用和覆盖；
- 缓存可检查、可通过 import/resolve 重建，inspect 保持只读；
- CLI 文本适合非程序员，JSON stdout 可直接解析；
- 未初始化/损坏 workspace 在资产写入前失败；
- 工作区外和源码树无旁路写入；
- Pipeline、run、wizard、Job 输入副本行为完全未改变；
- 完整测试、四个真实 E2E、独立审查和 GitHub CI 全绿；
- 文档诚实说明 01E-B 尚未完成；
- GitHub 与本地 master 同步。
