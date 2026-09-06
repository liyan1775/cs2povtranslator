# Round Task State Core Implementation Plan

> **Execution protocol:** Implement each task with failing behavioral tests, focused changes, verification and independent review under `docs/DEVELOPMENT_WORKFLOW.zh.md`. Independent modules may be delegated with disjoint write scopes. Optional agent skills are not runtime or workflow dependencies.

**Status (2026-09-06):** Tasks 1–5 implemented and implementation commits recorded; all three identified review findings closed. Final local verification passed, including 2233 tests passed and 28 skipped; documentation commit and GitHub integration remain pending, with no GitHub push yet. Completion evidence is recorded below and in the delivery milestone plan. The user has cancelled the stage pause; continue to 02C-B after integration, with Luna handling most implementation, testing and documentation.

**Goal:** Build the pure, current-version domain core for legal Job phase changes, durable round translation task state, retry decisions, progress summaries, and minimal downstream invalidation.

**Architecture:** Add focused immutable domain modules instead of extending the already large `job.py`. All transitions are pure functions over validated value objects; this plan deliberately performs no filesystem writes and starts no workers. A deterministic golden replay locks the contract before the repository and async scheduler consume it in the companion orchestration plan.

**Tech Stack:** Python 3.11+, frozen dataclasses, enums, existing canonical JSON/SHA-256 helpers, pytest.

**Spec:** `docs/superpowers/specs/2026-08-31-new-job-domain-and-timeline-design.md` sections 2, 5.2, 6, 8, and 9.

## Global Constraints

- Implement only the current schema version. Reject other versions; do not add v0.x import or cross-version migration.
- Use non-negative integer microseconds and canonical UTC timestamps; do not introduce floating `start_time` or `end_time` fields.
- Preserve ASR, timeline, Understanding, review, and old artifact files; invalidation removes current authority/references, not diagnostic history.
- Keep secrets, absolute paths, Steam IDs, raw exceptions, endpoints, and API credentials out of every domain object and fixture.
- Use only the standard library and existing project dependencies. No CS2, GPU, model API, Web UI, or video runtime is required.
- Every production change starts from a failing test, uses immutable public values, and ends in a focused commit.
- `job.py` retains Job identity/manifest types. New task, transition, and invalidation logic lives in focused modules.

---

## File Structure

- Create `src/cs2pov/domain/job_tasks.py`: task/attempt/error/retry value objects and strict schema-v1 serialization.
- Create `src/cs2pov/domain/job_task_state.py`: legal immutable task transitions and retry delay calculation.
- Create `src/cs2pov/domain/job_state.py`: Job phase graph, terminal gates, and progress derivation.
- Create `src/cs2pov/domain/invalidation.py`: explicit dependency graph and scoped invalidation plans.
- Modify `src/cs2pov/domain/schema.py`: one public canonical UTC timestamp validator shared by new and existing Job types.
- Modify `src/cs2pov/domain/job.py`: delegate timestamp validation to the shared helper without changing serialized Job v1 behavior.
- Modify `src/cs2pov/domain/understanding.py`: expose the canonical document content fingerprint required by durable task closure.
- Create four focused unit-test files and one golden replay fixture/script.

## Delivery record — 2026-09-06

本节记录当前交付状态；下方 Task 1–5 的步骤保留原施工顺序和命令。勾选实现或测试代码项不表示该批已提交、已通过全部集成门禁；未取得原始执行证据的历史 RED 或整组命令不补记为通过。

### Confirmed implementation and review

- [x] Task 1：严格 schema-v1 任务、尝试、错误及重试契约；共享规范 UTC 校验；Understanding 文档内容指纹。
- [x] Task 2：不可变任务转换、确定性重试及尝试历史保留；结束尝试时合并已有与新增 invocation references。
- [x] Task 3：显式 Job phase 图、草稿与已复核分支门禁、任务派生进度及运行状态。
- [x] Task 4：完整依赖矩阵、严格失效计划、同分支检查点回退及按种类撤销当前产物引用。
- [x] Task 5：生产函数驱动的三回合回放、静态期望、独立进程入口、篡改与 mutation 回归，以及架构/测试/夹具边界说明。
- [x] 审查问题 1（invocation references）：保留已有顺序，追加新引用；重叠引用去重，拒绝本次传入的重复项；不凭空生成调用记录。
- [x] 审查问题 2（诊断隐私）：覆盖紧邻中文的路径及 17 位数字泄露；据主协调器确认，36 个隐私用例先 RED，修正后相关测试 153 passed。此计数是针对性验证结果，不是全量结果。
- [x] 审查问题 3（产物失效回放）：在合法 `COMPLETED_WITH_VIDEO` 分支注入 timeline/subtitle/green_screen/video 合成索引，验证翻译配置变更清除全部四类及 active review，render-only 变更只撤销 video。保留旧产物的 mutation 先暴露 `DID NOT RAISE`，修正后被回放拒绝。
- [x] 独立只读复核：42 项 invocation 合并边界检查、按正向 phase 图独立推导的 190 个 rewind 组合通过，未发现可复现的实质问题；这些是内存检查数量，不计入 pytest 用例总数。

### Confirmed verification and remaining integration

以下定向结果来自主协调器已完成的独立核验；最终全量及完整本地门禁由 Sagan 执行，并由主协调器提供确证。本次文档更新不重复执行这些门禁。

| 验证项 | 已确认结果 |
|---|---|
| `tests/test_new_job_state_replay.py` | 8 passed |
| `scripts/check_new_domain_contract.py` | 通过 |
| `scripts/check_new_job_repository.py` | 通过 |
| `scripts/check_new_job_state.py` | 通过 |
| `scripts/check_golden_baseline.py --replay` | 15 passed |
| `scripts/check_repository_hygiene.py` | 通过 |
| compile 检查 | 通过 |
| 最终全量 `py -3.12 -m pytest -o addopts= -q` | Sagan 执行：2233 passed、28 skipped，95.87 秒，exit 0；跳过项不作为已验收功能 |
| 最终 Ruff | 全部 16 个 changed/untracked Python 文件通过 |
| 最终 `compileall` / `diffcheck` | 均通过 |
| 计划规定的隐私/时间字段扫描 | 无匹配 |

- [x] 接收并登记 Sagan 最终全量结果：2233 passed、28 skipped，95.87 秒，exit 0。
- [x] 登记全部 16 个 changed/untracked Python 文件的 Ruff、compileall、diffcheck 通过及计划扫描无匹配；后续仅在新增改动或未解决问题需要时补验。
- [x] 实现按批次提交，主协调器已确认：legacy `adbc91d`；Task 1 `060ca96`；Task 2–3 `9aed066`；Task 4 `676c42a`；Task 5 脚本/fixture/CI `3c8d25c`。
- [ ] 审核并提交本次交付文档；文档维护者不执行 commit。
- [ ] 推送分支、创建 PR，并等待实际 PR HEAD 的 Ubuntu Python 3.11/3.12/3.13 与 Windows Python 3.12 检查全部通过。
- [ ] 合并 A，核验合并提交的主线 CI，并补记 commit/PR/CI 证据。
- [ ] A 合并后由 Luna 接续 B；B Task 1–7 当前仍未实现，其持久化、并发及恢复验收不能由 A 的合成状态回放替代。

### Task 1: Strict round task, attempt, error, and retry contracts

**Files:**
- Create: `src/cs2pov/domain/job_tasks.py`
- Modify: `src/cs2pov/domain/schema.py`
- Modify: `src/cs2pov/domain/job.py`
- Modify: `src/cs2pov/domain/understanding.py`
- Create: `tests/test_domain_job_tasks_v1.py`
- Modify: `tests/test_domain_understanding_v1.py`

**Interfaces:**
- Produces: `RoundTaskStatus`, `RoundAttemptStatus`, `RoundTaskError`, `RoundTaskAttempt`, `RoundTaskSpec`, `RoundTranslationTask`, `RetryPolicy`.
- Produces: `require_canonical_utc_timestamp(value: object, path: str) -> str` in `domain/schema.py`.
- Consumes: `content_fingerprint`, `require_current_schema`, `require_exact_keys`, `require_int`, `require_mapping`, `require_path_identifier`, `require_sha256`, `reject_private_data`.

- [x] **Step 1: Write failing strict-contract tests**

Create tests proving exact enum values and legal serialized shape:

```python
def test_pending_round_task_round_trips_with_exact_v1_shape():
    task = RoundTranslationTask.pending(
        task_id="round-001",
        round_id="round-001",
        input_fingerprint="1" * 64,
        configuration_snapshot_id="snapshot-balanced",
        updated_at="2026-09-03T01:02:03.000000Z",
    )
    assert task.to_dict() == {
        "schema_version": 1,
        "task_id": "round-001",
        "round_id": "round-001",
        "status": "pending",
        "input_fingerprint": "1" * 64,
        "configuration_snapshot_id": "snapshot-balanced",
        "result_fingerprint": None,
        "attempts": [],
        "next_retry_at": None,
        "updated_at": "2026-09-03T01:02:03.000000Z",
    }
    assert RoundTranslationTask.from_dict(task.to_dict()) == task
    assert task.content_fingerprint() == content_fingerprint(task.to_dict())
```

Add parameterized rejection tests for unknown/missing keys, bool-as-int, non-canonical timestamps, unsafe IDs, invalid SHA-256 values, duplicate/non-contiguous attempt numbers, private-data keys, and non-current `schema_version`.

- [ ] **Step 2: Run the focused test and verify red**

Run:

```powershell
py -3.12 -m pytest tests/test_domain_job_tasks_v1.py -q
```

Expected: collection fails because `cs2pov.domain.job_tasks` does not exist.

- [x] **Step 3: Expose one canonical UTC timestamp validator**

Move the behavior currently implemented by `job._timestamp` into:

```python
def require_canonical_utc_timestamp(value: object, path: str) -> str:
    """Return YYYY-MM-DDTHH:MM:SS.ffffffZ or raise DomainSchemaError."""
```

Keep the exact six-digit UTC format and the existing stable `domain_field_invalid` mapping. Make `job._timestamp` a one-line delegate so all existing Job tests remain byte-for-byte compatible.

- [x] **Step 4: Implement the exact immutable task contracts**

Use these enum values and fields:

```python
class RoundTaskStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    RETRY_WAIT = "retry_wait"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    INTERRUPTED = "interrupted"

class RoundAttemptStatus(str, Enum):
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    RETRYABLE_FAILED = "retryable_failed"
    EXHAUSTED = "exhausted"
    FAILED = "failed"
    CANCELLED = "cancelled"
    INTERRUPTED = "interrupted"

@dataclass(frozen=True, slots=True)
class RoundTaskError:
    code: str
    message_zh: str
    impact_zh: str
    suggestion_zh: str
    retryable: bool
    retry_after_us: int | None

@dataclass(frozen=True, slots=True)
class RoundTaskAttempt:
    attempt_id: str
    attempt_number: int
    input_fingerprint: str
    configuration_snapshot_id: str
    status: RoundAttemptStatus
    started_at: str
    finished_at: str | None
    invocation_record_ids: tuple[str, ...]
    result_fingerprint: str | None
    error: RoundTaskError | None

@dataclass(frozen=True, slots=True)
class RoundTaskSpec:
    task_id: str
    round_id: str
    input_fingerprint: str
    configuration_snapshot_id: str

@dataclass(frozen=True, slots=True)
class RoundTranslationTask:
    task_id: str
    round_id: str
    status: RoundTaskStatus
    input_fingerprint: str
    configuration_snapshot_id: str
    result_fingerprint: str | None
    attempts: tuple[RoundTaskAttempt, ...]
    next_retry_at: str | None
    updated_at: str

@dataclass(frozen=True, slots=True)
class RetryPolicy:
    max_attempts: int
    base_delay_us: int
    max_delay_us: int
```

Enforce these cross-field rules:

- attempts are numbered `1..N` across all input generations, have unique path-safe IDs, preserve the input/configuration actually used, and only the final attempt may be `RUNNING`;
- current schema v1 requires `task_id == round_id`, matching the existing `ModelInvocationRecord.task_id` and production Understanding graph validator;
- `RUNNING` requires a final running attempt; `RETRY_WAIT` requires a final retryable failure plus `next_retry_at` after `updated_at`;
- `SUCCEEDED` requires `result_fingerprint`, no retry time, and a final succeeded attempt with the same result fingerprint;
- `FAILED` requires a final `FAILED` attempt with `error.retryable=False` or `EXHAUSTED` with `error.retryable=True`; exhaustion is therefore independently verifiable after restart without loading a RetryPolicy;
- `CANCELLED` from `RUNNING` closes the active attempt as cancelled; cancellation during `RETRY_WAIT` clears the retry time and retains the already closed retryable-failed attempt; `PENDING` is not converted to cancelled;
- `INTERRUPTED` requires a matching interrupted final attempt when it interrupted active work;
- `PENDING` has no result/retry time but may retain completed historical attempts after explicit reset;
- an empty-communication round may succeed with `invocation_record_ids=()`; no fake invocation is required;
- failed/retry attempts may retain zero or more real invocation IDs, but never invent one;
- every task error has a stable identifier-safe `code`, non-empty safe Chinese `message_zh`, `impact_zh`, and `suggestion_zh`; these fields are the durable UI/API projection and raw exception text is never serialized;
- the task `input_fingerprint` is the orchestration fingerprint over the production transcript/document input fingerprint plus the selected configuration fingerprint; it is deliberately not the same field as `RoundUnderstandingDocument.input_fingerprint`;
- `RoundTaskError.retry_after_us` is either `None` or `0..86_400_000_000`;
- `RetryPolicy` requires `1 <= max_attempts <= 100`, `1 <= base_delay_us <= max_delay_us <= 86_400_000_000`; a retry wait is always at least one microsecond.

Every type uses exact-key `to_dict`/`from_dict`, rejects private data, and `RoundTranslationTask` provides `pending(...)` and `content_fingerprint()`. Add this missing production helper without changing `RoundUnderstandingDocument.to_dict()`:

```python
def content_fingerprint(self) -> str:
    return content_fingerprint(self.to_dict())
```

Extend `tests/test_domain_understanding_v1.py` to assert the helper equals the existing canonical function and survives `to_dict`/`from_dict` round-trip.

- [ ] **Step 5: Run new and existing domain tests**

Run:

```powershell
py -3.12 -m pytest tests/test_domain_job_tasks_v1.py tests/test_domain_job_v1.py tests/test_domain_schema_v1.py tests/test_domain_understanding_v1.py -q
```

Expected: all pass.

- [x] **Step 6: Commit Task 1**

已提交：`060ca96`（主协调器确认）。

```powershell
git add src/cs2pov/domain/schema.py src/cs2pov/domain/job.py src/cs2pov/domain/understanding.py src/cs2pov/domain/job_tasks.py tests/test_domain_job_tasks_v1.py tests/test_domain_understanding_v1.py
git commit -m "feat: add round task domain contracts"
```

### Task 2: Pure task transition and retry policy

**Files:**
- Create: `src/cs2pov/domain/job_task_state.py`
- Create: `tests/test_domain_job_task_state_v1.py`

**Interfaces:**
- Consumes: every Task 1 type.
- Produces: `start_task`, `succeed_task`, `retry_task`, `fail_task`, `cancel_task`, `interrupt_task`, `reset_task`, `supersede_task`, `retry_delay_us`.

- [x] **Step 1: Write the legal-path and illegal-transition tests**

Cover the complete state graph, including this representative sequence:

```python
task = pending_task()
task = start_task(task, attempt_id="attempt-1", at=TS_1)
task = retry_task(
    task,
    at=TS_2,
    error=RoundTaskError(
        "provider_busy",
        "服务繁忙。",
        "本回合暂未完成，其他回合不受影响。",
        "将在服务商建议的等待时间后自动重试。",
        True,
        2_000_000,
    ),
    policy=RetryPolicy(3, 1_000_000, 8_000_000),
)
assert task.status is RoundTaskStatus.RETRY_WAIT
assert task.next_retry_at == "2026-09-03T01:02:05.000000Z"
with pytest.raises(DomainSchemaError):
    start_task(task, attempt_id="attempt-2", at="2026-09-03T01:02:04.999999Z")
task = start_task(task, attempt_id="attempt-2", at=task.next_retry_at)
task = succeed_task(task, at=TS_4, result_fingerprint="9" * 64)
assert task.status is RoundTaskStatus.SUCCEEDED
```

Also prove:

- direct `PENDING -> SUCCEEDED`, `SUCCEEDED -> RUNNING`, and retrying non-retryable errors fail;
- retry exhaustion produces `FAILED`, not a fourth attempt;
- retry exhaustion closes the last attempt as `EXHAUSTED`, while an earlier retryable failure closes it as `RETRYABLE_FAILED`;
- the minimum legal retry policy produces `next_retry_at == updated_at + 1us`;
- `cancel_task` preserves earlier successful task documents elsewhere and closes only the current attempt;
- cancelling `RETRY_WAIT` clears its next retry but does not rewrite the already finished attempt; cancelling `PENDING` is rejected so a scheduler can leave queued work pending;
- `interrupt_task` converts only `RUNNING` to `INTERRUPTED`; it is idempotent for already interrupted tasks;
- `reset_task` accepts only `FAILED`, `CANCELLED`, or `INTERRUPTED` with the same input/config and retains attempts;
- `supersede_task` requires a changed input or configuration, returns `PENDING`, clears the current result, retains closed attempts as diagnostic history, and keeps the same task/round identity;
- timestamp arguments move strictly forward.

- [ ] **Step 2: Run and verify red**

```powershell
py -3.12 -m pytest tests/test_domain_job_task_state_v1.py -q
```

Expected: import failure for `job_task_state`.

- [x] **Step 3: Implement deterministic retry calculation**

Implement:

```python
def retry_delay_us(
    completed_attempt_count: int,
    error: RoundTaskError,
    policy: RetryPolicy,
) -> int:
    exponential = min(
        policy.base_delay_us * (2 ** max(0, completed_attempt_count - 1)),
        policy.max_delay_us,
    )
    return max(exponential, error.retry_after_us or 0)
```

Use checked integer arithmetic and reject a server retry value above the existing one-day contract rather than silently truncating it. Jitter and shared provider throttling remain in the later provider-integration phase.

- [x] **Step 4: Implement immutable transition functions**

Every transition validates the source state, closes/creates the last attempt as required, updates only the legal fields, and returns a new `RoundTranslationTask`. Convert timestamp strings to UTC datetimes for ordering, but serialize the original canonical form. Raise `DomainSchemaError("domain_state_transition_invalid", ...)` with the field path `round_task.status` on illegal transitions.

Use these signatures:

```python
def start_task(task, *, attempt_id: str, at: str) -> RoundTranslationTask: ...
def succeed_task(task, *, at: str, result_fingerprint: str,
                 invocation_record_ids: tuple[str, ...] = ()) -> RoundTranslationTask: ...
def retry_task(task, *, at: str, error: RoundTaskError,
               policy: RetryPolicy,
               invocation_record_ids: tuple[str, ...] = ()) -> RoundTranslationTask: ...
def fail_task(task, *, at: str, error: RoundTaskError,
              invocation_record_ids: tuple[str, ...] = ()) -> RoundTranslationTask: ...
def cancel_task(task, *, at: str) -> RoundTranslationTask: ...
def interrupt_task(task, *, at: str) -> RoundTranslationTask: ...
def reset_task(task, *, at: str) -> RoundTranslationTask: ...
def supersede_task(task, *, spec: RoundTaskSpec, at: str) -> RoundTranslationTask: ...
```

`retry_task` closes the current attempt with `RETRYABLE_FAILED`; if the number of attempts for the current `(input_fingerprint, configuration_snapshot_id)` reaches `max_attempts`, it closes that attempt as `EXHAUSTED`, returns task status `FAILED`, and clears `next_retry_at`. `start_task` permits `RETRY_WAIT` only at or after `next_retry_at`, assigns the next global attempt number, and copies the task's current input/configuration into the attempt.

- [ ] **Step 5: Run Task 1–2 tests**

```powershell
py -3.12 -m pytest tests/test_domain_job_tasks_v1.py tests/test_domain_job_task_state_v1.py -q
```

Expected: all pass.

- [x] **Step 6: Commit Task 2**

已与 Task 3 合批提交：`9aed066`（主协调器确认）。

```powershell
git add src/cs2pov/domain/job_task_state.py tests/test_domain_job_task_state_v1.py
git commit -m "feat: add round task transition policy"
```

### Task 3: Job phase graph and reviewed/draft terminal gates

**Files:**
- Create: `src/cs2pov/domain/job_state.py`
- Create: `tests/test_domain_job_state_v1.py`

**Interfaces:**
- Consumes: `JobManifest`, `JobPhase`, `JobRunStatus`, `RoundProgressSummary`, `RoundTranslationTask`.
- Produces: `advance_job_phase`, `derive_round_progress`, `derive_translation_run_status`, `is_legal_terminal`.

- [x] **Step 1: Write exhaustive phase-edge tests**

Represent the approved forward graph explicitly in the test and assert that every edge succeeds while every unlisted pair fails. Include the branches:

```python
assert is_legal_terminal(JobPhase.COMPLETED_DRAFT)
assert is_legal_terminal(JobPhase.COMPLETED_WITHOUT_VIDEO)
assert is_legal_terminal(JobPhase.COMPLETED_WITH_VIDEO)
assert not is_legal_terminal(JobPhase.READY_FOR_RENDER)
```

Prove `DRAFT_TIMELINE_READY -> COMPLETED_DRAFT` is legal without review, while `DRAFT_TIMELINE_READY -> FINAL_TIMELINE_READY` and any transition into `REVIEWED`/`FINAL_TIMELINE_READY` without `active_review_id` are rejected. Prove `COMPLETED_WITHOUT_VIDEO` does not require CS2/GPU and `READY_FOR_RENDER` is a non-terminal handoff state.

Add progress tests with pending/running/retry/succeeded/failed/cancelled/interrupted tasks and a supplied set of review-pending round IDs. Reject duplicate round/task IDs and review IDs outside the task set.

- [ ] **Step 2: Run and verify red**

```powershell
py -3.12 -m pytest tests/test_domain_job_state_v1.py -q
```

Expected: import failure for `job_state`.

- [x] **Step 3: Implement the explicit forward graph**

Define a module-level immutable mapping with exactly these edges:

```python
CREATED -> TIMELINE_READY -> VOICE_READY -> TRANSCRIBED -> CONTEXT_READY
CONTEXT_READY -> UNDERSTANDING_TRANSLATING -> UNDERSTOOD_TRANSLATED
UNDERSTOOD_TRANSLATED -> DRAFT_TIMELINE_READY
DRAFT_TIMELINE_READY -> COMPLETED_DRAFT
DRAFT_TIMELINE_READY -> REVIEW_PENDING -> REVIEWED -> FINAL_TIMELINE_READY
FINAL_TIMELINE_READY -> SUBTITLES_EXPORTED -> GREEN_SCREEN_RENDERED
GREEN_SCREEN_RENDERED -> COMPLETED_WITHOUT_VIDEO
GREEN_SCREEN_RENDERED -> READY_FOR_RENDER -> RENDERING -> VIDEO_READY
VIDEO_READY -> COMPLETED_WITH_VIDEO
```

`advance_job_phase(manifest, target, *, at)` returns `dataclasses.replace(...)`, advances `updated_at`, and sets the exact default run status below. It never guesses an `active_review_id`.

| Target phase | Default `JobRunStatus` |
|---|---|
| `CREATED` | `PENDING` |
| `TIMELINE_READY` | `SUCCEEDED` |
| `VOICE_READY` | `SUCCEEDED` |
| `TRANSCRIBED` | `SUCCEEDED` |
| `CONTEXT_READY` | `SUCCEEDED` |
| `UNDERSTANDING_TRANSLATING` | `RUNNING` |
| `UNDERSTOOD_TRANSLATED` | `SUCCEEDED` |
| `DRAFT_TIMELINE_READY` | `SUCCEEDED` |
| `COMPLETED_DRAFT` | `SUCCEEDED` |
| `REVIEW_PENDING` | `PENDING` |
| `REVIEWED` | `SUCCEEDED` |
| `FINAL_TIMELINE_READY` | `SUCCEEDED` |
| `SUBTITLES_EXPORTED` | `SUCCEEDED` |
| `GREEN_SCREEN_RENDERED` | `SUCCEEDED` |
| `COMPLETED_WITHOUT_VIDEO` | `SUCCEEDED` |
| `READY_FOR_RENDER` | `PENDING` |
| `RENDERING` | `RUNNING` |
| `VIDEO_READY` | `SUCCEEDED` |
| `COMPLETED_WITH_VIDEO` | `SUCCEEDED` |

Failures, cancellation, and interruption are explicit run outcomes applied by the coordinator while retaining the current phase; they are not alternate phase edges.

- [x] **Step 4: Implement task-derived progress and run status**

`derive_round_progress(tasks, review_pending_round_ids=())` returns the existing four-field `RoundProgressSummary`. Its three result counters are mutually exclusive, matching the existing `succeeded + failed + review_pending <= total` invariant:

- `succeeded`: task status `SUCCEEDED` whose round ID is not review-pending;
- `failed`: `FAILED` only;
- `review_pending`: succeeded tasks whose round ID is explicitly supplied;
- `total`: all canonical tasks.

`derive_translation_run_status(tasks)` returns `RUNNING` if any task runs/retries, `FAILED` if no work remains and any task failed, `CANCELLED` if only cancellation prevents completion, `INTERRUPTED` for interrupted work, `SUCCEEDED` only when all tasks succeeded, otherwise `PENDING`. Use a documented precedence table in the module and test every mixed-status row.

- [ ] **Step 5: Run domain Job state tests**

```powershell
py -3.12 -m pytest tests/test_domain_job_state_v1.py tests/test_domain_job_v1.py -q
```

Expected: all pass.

- [x] **Step 6: Commit Task 3**

已与 Task 2 合批提交：`9aed066`（主协调器确认）。

```powershell
git add src/cs2pov/domain/job_state.py tests/test_domain_job_state_v1.py
git commit -m "feat: enforce job phase transition gates"
```

### Task 4: Explicit minimal invalidation graph

**Files:**
- Create: `src/cs2pov/domain/invalidation.py`
- Create: `tests/test_domain_invalidation_v1.py`

**Interfaces:**
- Produces: `JobInputChange`, `JobStage`, `InvalidationRequest`, `InvalidationPlan`, `plan_invalidation`, `rewind_job_phase_for_invalidation`.
- Consumes: `FinalArtifactKind`, `JobPhase`, strict round IDs.

- [x] **Step 1: Write the full dependency-matrix tests**

Use exact expected results for each change kind. Representative assertions:

```python
plan = plan_invalidation(
    InvalidationRequest(
        JobInputChange.TRANSLATION_CONFIGURATION,
        round_ids=("round-001", "round-002"),
    )
)
assert plan.first_invalid_phase is JobPhase.CONTEXT_READY
assert plan.invalid_stages == (
    JobStage.UNDERSTANDING,
    JobStage.DRAFT_TIMELINE,
    JobStage.REVIEWED_TIMELINE,
    JobStage.SUBTITLES,
    JobStage.GREEN_SCREEN,
    JobStage.VIDEO,
)
assert plan.clear_active_review
assert plan.remove_artifact_kinds == frozenset(FinalArtifactKind)
assert plan.round_ids == ("round-001", "round-002")
```

Test these exact outputs. `ALL` below means `{TIMELINE, SUBTITLE, GREEN_SCREEN, VIDEO}` and `EXPORTS` means `{SUBTITLE, GREEN_SCREEN, VIDEO}`:

| Change | First invalid phase | Invalid stages | Clear active review | Remove artifact kinds | Scope |
|---|---|---|---:|---|---|
| `DISPLAY_METADATA` | `FINAL_TIMELINE_READY` | subtitles, green screen, video | no | `EXPORTS` | global |
| `SUBTITLE_LAYOUT` | `FINAL_TIMELINE_READY` | subtitles, green screen, video | no | `EXPORTS` | global |
| `REVIEW_DECISION` | `DRAFT_TIMELINE_READY` | reviewed timeline and all exports | yes | `ALL` | named rounds |
| `TRANSLATION_CONFIGURATION` | `CONTEXT_READY` | understanding and all downstream stages | yes | `ALL` | named rounds |
| `KNOWLEDGE_REVISION` | `CONTEXT_READY` | understanding and all downstream stages | yes | `ALL` | named rounds |
| `ASR_CONFIGURATION` | `VOICE_READY` | transcript, context, understanding, review, all exports | yes | `ALL` | global |
| `ROUND_BOUNDARY` | `TIMELINE_READY` | affected transcript assignment and all downstream stages | yes | `ALL` | named rounds |
| `DEMO_ASSET_IDENTITY` | `CREATED` | every derived stage | yes | `ALL` | global |
| `RENDER_CONFIGURATION` | `GREEN_SCREEN_RENDERED` | video only | no | `{VIDEO}` | global |
| `POV_ADAPTER_UNAVAILABLE` | `GREEN_SCREEN_RENDERED` | video only; subtitles/green screen remain current | no | `{VIDEO}` | global |

Prove round-scoped changes require non-empty unique canonical round IDs, global changes reject round IDs, and the plan never names source evidence for deletion.

- [ ] **Step 2: Run and verify red**

```powershell
py -3.12 -m pytest tests/test_domain_invalidation_v1.py -q
```

Expected: import failure for `invalidation`.

- [x] **Step 3: Implement typed requests and plans**

Use frozen dataclasses:

```python
@dataclass(frozen=True, slots=True)
class InvalidationRequest:
    change: JobInputChange
    round_ids: tuple[str, ...] = ()

@dataclass(frozen=True, slots=True)
class InvalidationPlan:
    first_invalid_phase: JobPhase
    invalid_stages: tuple[JobStage, ...]
    round_ids: tuple[str, ...]
    clear_active_review: bool
    remove_artifact_kinds: frozenset[FinalArtifactKind]
```

Keep the dependency matrix as a single immutable mapping. `plan_invalidation` canonicalizes round IDs but does not inspect files or mutate a manifest. Old files remain diagnostic history. Add the only manifest rewind API here so callers cannot pass an under-invalidating combination of independent booleans/sets:

```python
def rewind_job_phase_for_invalidation(
    manifest: JobManifest,
    plan: InvalidationPlan,
    *,
    at: str,
) -> JobManifest: ...
```

It rewinds exactly to `plan.first_invalid_phase`, applies `plan.clear_active_review` and `plan.remove_artifact_kinds`, preserves identity/source/configuration snapshot history, and never deletes files. Plan 02C-B invokes it under a write claim before superseding any affected task.

- [ ] **Step 4: Run all new pure-domain tests**

```powershell
py -3.12 -m pytest tests/test_domain_job_tasks_v1.py tests/test_domain_job_task_state_v1.py tests/test_domain_job_state_v1.py tests/test_domain_invalidation_v1.py -q
```

Expected: all pass.

- [x] **Step 5: Commit Task 4**

已提交：`676c42a`（主协调器确认）。

```powershell
git add src/cs2pov/domain/invalidation.py tests/test_domain_invalidation_v1.py
git commit -m "feat: add minimal job invalidation plans"
```

### Task 5: Deterministic state-core replay, documentation, and handoff

**Files:**
- Create: `tests/golden/fixtures/new_job_state_v1.json`
- Create: `scripts/check_new_job_state.py`
- Create: `tests/test_new_job_state_replay.py`
- Modify: `tests/golden/README.zh.md`
- Modify: `docs/ARCHITECTURE.zh.md`
- Modify: `docs/TESTING_GUIDE.zh.md`

**Interfaces:**
- Consumes: all Tasks 1–4 public interfaces.
- Produces: a process-independent fixture and the exact success message `new job state replay passed`.

- [x] **Step 1: Write the failing replay test and fixture contract**

The fixture contains three synthetic rounds and no real names, paths, endpoints, or credentials. Replay this exact story through production functions:

1. create three pending tasks sharing one configuration snapshot;
2. start all three, complete round 002 first, put round 001 into retry wait, and cancel round 003;
3. retry and succeed round 001; reset then succeed round 003;
4. derive stable progress and aggregate order `001, 002, 003`, independent of completion order;
5. advance the Job through `UNDERSTOOD_TRANSLATED`, branch once to `COMPLETED_DRAFT`, and independently prove the reviewed branch gate;
6. change the translation configuration for round 002 and assert only that task is superseded while the invalidation plan removes authority from downstream review/export references;
7. serialize/reload every task and compare exact canonical fingerprints.

审查修正后的第 6 项从合法已复核分支继续到 `COMPLETED_WITH_VIDEO`，在该分支附加四类真实 `FinalArtifactEntry` 合成记录。翻译失效必须清空 artifact index 与 active review；独立 render-only 分支保留 reviewed timeline、subtitle、green screen 及 review，只删除 video。静态期望增加完成分支和两种失效结果字段，原三回合任务历史与转换指纹保留；这是补足原清理断言的覆盖，不是依据执行结果盲目重建期望。

`tests/test_new_job_state_replay.py` runs the checker in a fresh Python process and asserts exit code 0 and exact stdout.

- [ ] **Step 2: Run and verify red**

```powershell
py -3.12 -m pytest tests/test_new_job_state_replay.py -q
```

Expected: failure because the checker is absent.

原始“脚本不存在”RED 的执行证据不在本次交付记录中补认。已直接确认的补充 RED 为：monkeypatch 生产 rewind 调用以保留旧产物时，修正前回放未抛异常；修正后该 mutation 被拒绝。独立回放测试 8 passed 已由主协调器确认。

- [x] **Step 3: Implement the checker using production code only**

The script may parse fixture input and compare expected values, but must not duplicate transition, retry, progress, fingerprint, or invalidation logic. Reject unexpected fixture keys and print only:

```text
new job state replay passed
```

- [x] **Step 4: Document the delivered boundary in plain Chinese**

Document that 02C-A is a pure state core: no workers, no filesystem task persistence, no provider API, no UI, and no video. Explain that `COMPLETED_DRAFT` is legal but cannot masquerade as reviewed, that `COMPLETED_WITHOUT_VIDEO` is a valid eventual terminal state, and that invalidation preserves old files while removing current authority.

- [x] **Step 5: Run focused and full verification**

已完成：定向测试、契约回放、golden、hygiene，以及 Sagan 最终全量 2233 passed、28 skipped 和全部 16 个 Python 文件的 Ruff、compileall、diffcheck、计划扫描均有确证，详见本文件交付记录。GitHub 尚未推送；文档提交及远程集成步骤仍待完成。

```powershell
py -3.12 scripts/check_new_job_state.py
py -3.12 scripts/check_new_domain_contract.py
py -3.12 scripts/check_new_job_repository.py
py -3.12 scripts/check_golden_baseline.py --replay
py -3.12 scripts/check_repository_hygiene.py
py -3.12 -m pytest -q
py -3.12 -m ruff check src/cs2pov/domain/job.py src/cs2pov/domain/schema.py src/cs2pov/domain/understanding.py src/cs2pov/domain/job_tasks.py src/cs2pov/domain/job_task_state.py src/cs2pov/domain/job_state.py src/cs2pov/domain/invalidation.py tests/test_domain_understanding_v1.py tests/test_domain_job_tasks_v1.py tests/test_domain_job_task_state_v1.py tests/test_domain_job_state_v1.py tests/test_domain_invalidation_v1.py tests/test_new_job_state_replay.py scripts/check_new_job_state.py
git diff --check
```

Expected: every command exits 0. Also run privacy/timing scans and expect no matches:

```powershell
rg -n "start_time|end_time|api_key|authorization|access_token|password|https?://|steamid|steam_id" src/cs2pov/domain/job_tasks.py src/cs2pov/domain/job_task_state.py src/cs2pov/domain/job_state.py src/cs2pov/domain/invalidation.py tests/golden/fixtures/new_job_state_v1.json
```

- [ ] **Step 6: Commit Task 5**

- [x] 脚本/fixture/CI 实现批次已提交：`3c8d25c`（主协调器确认）。
- [ ] 本步骤所列交付文档尚待提交，因此整体步骤保持未勾选。

```powershell
git add tests/golden/fixtures/new_job_state_v1.json scripts/check_new_job_state.py tests/test_new_job_state_replay.py tests/golden/README.zh.md docs/ARCHITECTURE.zh.md docs/TESTING_GUIDE.zh.md
git commit -m "test: gate round task state core"
```

- [ ] **Step 7: Independent review and GitHub handoff**

部分完成：三项已接受审查问题全部闭合，独立只读复核未发现实质问题，代码已按批次提交；文档 commit、PR/CI/合并及合并后 CI 尚待完成，因此本项保持未勾选。

Request an independent review of all commits against this plan. In accordance with the user's resource allocation, use Luna for routine review and reserve the coordinating model for material unresolved risks. Resolve findings with a failing regression test first, rerun the full gate, push a feature branch, create a PR against `master`, wait for Ubuntu 3.11/3.12/3.13 and Windows 3.12 CI, merge only when green, then verify the post-merge `master` CI.

## Definition of Done

- All task documents are strict, canonical, current-version-only, and contain no secrets or machine paths.
- The complete task and Job transition graphs are executable production policy, not prose-only conventions.
- Retry/cancel/interruption preserve attempts and never fabricate a model invocation.
- Progress is derived deterministically from round tasks.
- Invalidation is explicitly scoped, preserves old files, and cannot promote draft output to reviewed output.
- Golden replay, old/new contract replays, full pytest, Ruff, repository hygiene, independent review, PR CI, and post-merge CI all pass.
