# Round Orchestration Runtime Implementation Plan

> **Execution protocol:** Implement each task with failing behavioral tests, focused changes, verification and independent review under `docs/DEVELOPMENT_WORKFLOW.zh.md`. Independent modules may be delegated with disjoint write scopes. Optional agent skills are not runtime or workflow dependencies.

**Status (2026-09-05):** Planned; implementation starts after 02C-A is merged. Provider-specific integration belongs to task 5.3 of the overall plan.

**Goal:** Persist round tasks and run them with bounded parallelism, deterministic retries, cancellation, crash recovery, immediate successful checkpoints, and stable aggregation without requiring a real model API.

**Architecture:** `FileSystemJobRepository` remains the only filesystem authority and claim fence, but task codecs live in a focused storage module. A new application coordinator owns Job manifest/events and serializes durable completions; async workers only compute typed outcomes. `asyncio` provides bounded concurrency while injected clock/sleep/worker ports make retry, cancellation, recovery, and completion order fully deterministic in tests.

**Tech Stack:** Python 3.11+ `asyncio`, existing file repository/atomic codec/write claim, frozen domain values from Plan 02C-A, pytest and real spawned processes.

**Spec:** `docs/superpowers/specs/2026-08-31-new-job-domain-and-timeline-design.md` sections 5.2–5.3, 6, 7, 8, 9, and 10; prerequisite plan `docs/superpowers/plans/2026-09-03-round-task-state-core.md`.

## Global Constraints

- Start only after Plan 02C-A is merged into `master`; do not copy its types into this plan.
- Current-version historical Job means a Job made by this same new schema and reopened later. Do not add v0.x import or cross-version migration.
- Only the coordinator writes Job manifest/events. Worker coroutines never receive paths, claims, repository objects, secrets, or permission to write arbitrary shards.
- Every successful round is atomically checkpointed before it counts as succeeded; completion/aggregation order never depends on API response order.
- One Job has one write claim. Every task/result/manifest mutation verifies the same live claim under `events/.write.lock`.
- Filesystem task truth may lead the cached manifest summary after a crash. Explicit resume reconciles it; list/inspect/load remain read-only.
- No real provider, endpoint, API key, CS2, GPU, Web UI, knowledge database, subtitle renderer, or POV recorder is introduced here.
- Use the configured `ModelConfigurationSnapshot`; failures must not silently switch model, service, prompt, or knowledge revision.
- Use TDD, focused commits, full real-process replay, independent review, GitHub CI, and post-merge CI. Prefer Luna for implementation, testing, documentation and routine review; reserve the coordinating model for material unresolved risks.

---

## File Structure

- Create `src/cs2pov/storage/job_task_documents.py`: strict task parser, canonical ordering, task/result/history closure checks.
- Modify `src/cs2pov/storage/job_repository.py`: small claim-fenced task methods and task inspection hooks only.
- Modify `src/cs2pov/storage/job_paths.py`: retain/verify `tasks/round_<round_id>.json` and add the canonical archived Understanding result path.
- Create `src/cs2pov/application/round_worker.py`: narrow async worker request/result/failure protocol.
- Create `src/cs2pov/application/job_coordinator.py`: task preparation, durable state commits, manifest/event reconciliation, invalidation application.
- Create `src/cs2pov/application/round_scheduler.py`: bounded async execution, retry/cancel/heartbeat, stable result reporting.
- Create focused tests per unit plus one real-process replay.

### Task 1: Strict claim-fenced round task persistence

**Files:**
- Create: `src/cs2pov/storage/job_task_documents.py`
- Modify: `src/cs2pov/storage/job_repository.py`
- Modify: `src/cs2pov/storage/job_paths.py`
- Create: `tests/test_job_repository_round_tasks_v1.py`

**Interfaces:**
- Consumes: `RoundTranslationTask`, `JobWriteClaim`, existing `atomic_write_json`, `read_strict_json`, path/claim/lock validation.
- Produces repository methods:

```python
def initialize_round_tasks(
    self,
    job_id: str,
    tasks: tuple[RoundTranslationTask, ...],
    claim: JobWriteClaim,
) -> tuple[RoundTranslationTask, ...]: ...

def load_round_tasks(self, job_id: str) -> tuple[RoundTranslationTask, ...]: ...

def replace_round_task(
    self,
    job_id: str,
    expected_fingerprint: str,
    task: RoundTranslationTask,
    claim: JobWriteClaim,
) -> RoundTranslationTask: ...

def merge_task_invocations(
    self,
    job_id: str,
    task_id: str,
    records: tuple[ModelInvocationRecord, ...],
    claim: JobWriteClaim,
) -> tuple[ModelInvocationRecord, ...]: ...

def archive_round_understanding(
    self,
    job_id: str,
    round_id: str,
    expected_fingerprint: str,
    claim: JobWriteClaim,
) -> None: ...
```

- [ ] **Step 1: Write failing repository tests**

Cover exact path/content identity, canonical timeline order, idempotent partial initialization, CAS replacement, invocation merging, Understanding history archival, stale/foreign claim fencing, safe read-only loads, schema/JSON corruption isolation, symlink/junction rejection, and concurrent process writers. Representative test:

```python
with repository.acquire_write("job-rounds", lease_us=30_000_000) as session:
    persisted = repository.initialize_round_tasks(
        "job-rounds", (task_002, task_001), session.claim
    )
assert [task.round_id for task in persisted] == ["round-001", "round-002"]
assert json.loads(
    (workspace.jobs_dir / "job-rounds/tasks/round_round-001.json").read_text("utf-8")
) == task_001.to_dict()
```

Require `initialize_round_tasks` to load the persisted Demo timeline and reject missing/extra/duplicate round IDs. `load_round_tasks` is read-only and rejects a task whose filename, `round_id`, `task_id`, configuration reference, or input fingerprint closure is invalid.

Inject a crash after publishing the first task, rerun initialization, and prove the identical first task is reused while missing tasks are created. Existing different content must fail closed. Prove `merge_task_invocations` atomically reads/merges/rewrites the canonical JSONL set under one lock, is idempotent for identical invocation IDs, and rejects a duplicate ID with different content.

Before a succeeded task is superseded, `archive_round_understanding` copies its validated current document to `understanding/history/round_<round_id>/result_<result_fingerprint>.json`. An existing identical archive is reused; different bytes/content at that logical identity fail. No invalidation deletes the archive.

- [ ] **Step 2: Run and verify red**

```powershell
py -3.12 -m pytest tests/test_job_repository_round_tasks_v1.py -q
```

Expected: missing repository methods/module.

- [ ] **Step 3: Implement focused task codecs**

`job_task_documents.py` owns:

```python
ROUND_TASK_PARSER = schema_aware_parser(
    RoundTranslationTask.from_dict,
    expectations=("",),
)

def canonical_round_tasks(
    timeline: DemoTimeline,
    tasks: Iterable[RoundTranslationTask],
) -> tuple[RoundTranslationTask, ...]: ...

def validate_succeeded_task_result(
    task: RoundTranslationTask,
    document: RoundUnderstandingDocument,
) -> None: ...
```

Canonical order is timeline round order, never filename or completion order. A succeeded task must reference the production `RoundUnderstandingDocument.content_fingerprint()` for the same round; non-succeeded tasks must not claim a current result. Add `JobPaths.round_understanding_history(round_id, result_fingerprint)` for `understanding/history/round_<round_id>/result_<sha256>.json`; historical succeeded attempts must close over a matching archived or current result.

- [ ] **Step 4: Implement claim-fenced repository methods**

Follow existing shard patterns exactly:

- validate all domain inputs before acquiring the lock;
- open the existing `.write.lock`, verify the same claim, reload current Job/timeline under that lock;
- initialize absent task files with `atomic_write_json`, accept existing identical files, and recover safely from a partially initialized batch;
- CAS replacement compares the persisted task content fingerprint and raises `job_task_conflict` on mismatch;
- merge invocation records and archive a superseded Understanding document while holding the same short OS-lock/claim critical section used by other shard writes;
- round/task filename/content mismatch maps to `job_shard_invalid` with a logical `tasks/round_<id>.json` path;
- never create a lock, claim, task, or directory from a read method.

`load_round_tasks` opens the already existing Job write lock and reads the manifest, timeline, task filenames, and task contents inside that one read snapshot; it does not return a mixture from two cooperating writer states. Add task files and `understanding/history` files/directories to deep inspection. One corrupt task/history document marks only its Job unhealthy; sibling Jobs remain listable. Do not make task files mandatory for phases earlier than `CONTEXT_READY`.

- [ ] **Step 5: Run task persistence and existing repository gates**

```powershell
py -3.12 -m pytest tests/test_job_repository_round_tasks_v1.py tests/test_job_repository_catalog_v1.py tests/test_job_write_claim_v1.py tests/test_new_job_repository_replay.py -q
```

Expected: all pass.

- [ ] **Step 6: Commit Task 1**

```powershell
git add src/cs2pov/storage/job_task_documents.py src/cs2pov/storage/job_repository.py src/cs2pov/storage/job_paths.py tests/test_job_repository_round_tasks_v1.py
git commit -m "feat: persist round translation tasks"
```

### Task 2: Typed worker port with privacy-minimal requests

**Files:**
- Create: `src/cs2pov/application/round_worker.py`
- Create: `tests/test_round_worker_contract_v1.py`

**Interfaces:**
- Consumes: `ModelConfigurationSnapshot`, `ModelInvocationRecord`, `Round`, `TranscriptCue`, `RoundUnderstandingDocument`.
- Produces: `RoundWorkCue`, `RoundWorkRequest`, `RoundWorkResult`, `RoundWorkFailure`, `RoundTranslationWorker`, plus the validation factories below.

```python
@dataclass(frozen=True, slots=True)
class RoundWorkCue:
    cue_id: str
    speaker_token: str
    start_us: int
    end_us: int
    asr_original: str
    language: str
    confidence: float | None

@dataclass(frozen=True, slots=True)
class RoundWorkRequest:
    task_id: str
    round_id: str
    round_number: int
    configuration: ModelConfigurationSnapshot
    cues: tuple[RoundWorkCue, ...]
    document_input_fingerprint: str
    task_input_fingerprint: str

@dataclass(frozen=True, slots=True)
class RoundWorkResult:
    document: RoundUnderstandingDocument
    invocations: tuple[ModelInvocationRecord, ...]

class RoundWorkFailure(RuntimeError):
    error: RoundTaskError
    invocations: tuple[ModelInvocationRecord, ...]

class RoundTranslationWorker(Protocol):
    async def translate(self, request: RoundWorkRequest) -> RoundWorkResult: ...
```

- [ ] **Step 1: Write failing request/result closure tests**

Prove the request contains only the selected round's privacy-minimal cues and non-secret configuration snapshot. `RoundWorkCue` carries no `player_id`, source stream/clock/range, anchor/voice IDs, ASR invocation ID, Steam identity, path, endpoint, or secret. Map speakers to deterministic Job-local tokens (`speaker-001`, `speaker-002`, …) by first appearance within the round. Current schema v1 requires `task_id == round_id` to match the existing production invocation/Understanding validator. Reject mismatched IDs, incorrect document/task fingerprints, absolute paths, secret-shaped keys, and a result whose round/input/invocation/configuration closure fails production validators.

Prove an empty target-team round may return a valid empty `RoundUnderstandingDocument` with `invocations=()`.

For a non-empty result, require exactly one successful invocation referenced by the document and every `UnderstandingResult`; its `task_id` equals the round/task ID and its configuration/request/response fingerprints pass the existing production graph validator. Retry/failure invocation history may contain additional records, but they are not allowed to masquerade as the successful document invocation.

- [ ] **Step 2: Run and verify red**

```powershell
py -3.12 -m pytest tests/test_round_worker_contract_v1.py -q
```

Expected: import failure for `round_worker`.

- [ ] **Step 3: Implement the narrow protocol and validation factories**

Construct requests/results only through factories:

```python
def build_round_work_request(
    *, task: RoundTranslationTask, round: Round,
    configuration: ModelConfigurationSnapshot,
    transcripts: tuple[TranscriptCue, ...],
) -> RoundWorkRequest: ...

def validate_round_work_result(
    request: RoundWorkRequest,
    result: RoundWorkResult,
) -> None: ...

def validate_round_work_failure(
    request: RoundWorkRequest,
    failure: RoundWorkFailure,
) -> None: ...
```

Recompute two distinct fingerprints; do not accept either from the caller without verification:

```python
document_input_fingerprint = content_fingerprint({
    "round_id": round.round_id,
    "transcript_cues": [cue.to_dict() for cue in canonical_full_transcripts],
})
task_input_fingerprint = content_fingerprint({
    "document_input_fingerprint": document_input_fingerprint,
    "configuration_fingerprint": configuration.configuration_fingerprint,
})
```

`RoundUnderstandingDocument.input_fingerprint` and the successful invocation request fingerprint continue to use `document_input_fingerprint`, preserving the existing production graph contract. `RoundTranslationTask.input_fingerprint` uses `task_input_fingerprint`, so model/prompt/knowledge changes invalidate the task even when transcripts are unchanged. The worker receives only the hashes and privacy-minimal cues, not the full transcript source evidence. `RoundWorkFailure` exposes only a typed safe error; raw exception details stay in `__cause__`, not durable payloads.

Implement `RoundWorkFailure.__init__(error, invocations=(), *, cause=None)` explicitly. The constructor validates its own types, uses only `error.message_zh` as the exception string, and attaches the optional raw cause through exception chaining rather than a serializable field. `validate_round_work_failure(request, failure)` is the request-dependent boundary: every invocation must match the request round/task ID, configuration snapshot, and `document_input_fingerprint`; duplicates or mismatches are rejected before any invocation is persisted.

- [ ] **Step 4: Run tests and commit**

```powershell
py -3.12 -m pytest tests/test_round_worker_contract_v1.py tests/test_domain_invocation_v1.py tests/test_domain_validation_v1.py -q
git add src/cs2pov/application/round_worker.py tests/test_round_worker_contract_v1.py
git commit -m "feat: define round translation worker port"
```

### Task 3: Job coordinator preparation, checkpoint, and reconciliation

**Files:**
- Create: `src/cs2pov/application/job_coordinator.py`
- Create: `tests/test_job_round_coordinator_v1.py`

**Interfaces:**
- Consumes: task repository methods, task/Job state functions, `plan_invalidation`, language graph validators, Job events.
- Produces: `PreparedRoundBatch`, `JobRoundCoordinator`, and private canonical-time allocation helpers exercised through coordinator tests.

```python
@dataclass(frozen=True, slots=True)
class PreparedRoundBatch:
    job_id: str
    configuration_snapshot_id: str
    tasks: tuple[RoundTranslationTask, ...]
    requests: tuple[RoundWorkRequest, ...]

class JobRoundCoordinator:
    def __init__(self, repository: FileSystemJobRepository, *, clock,
                 event_id_factory) -> None: ...
    def prepare_translation(self, job_id: str, *, configuration_snapshot_id: str,
                            claim: JobWriteClaim) -> PreparedRoundBatch: ...
    def mark_running(self, task: RoundTranslationTask, *, attempt_id: str,
                     claim: JobWriteClaim) -> RoundTranslationTask: ...
    def checkpoint_success(self, task: RoundTranslationTask, result: RoundWorkResult,
                           *, claim: JobWriteClaim) -> RoundTranslationTask: ...
    def checkpoint_failure(self, task: RoundTranslationTask, failure: RoundWorkFailure,
                           *, policy: RetryPolicy,
                           claim: JobWriteClaim) -> RoundTranslationTask: ...
    def checkpoint_cancellation(self, task: RoundTranslationTask, *,
                                claim: JobWriteClaim) -> RoundTranslationTask: ...
    def reconcile_for_resume(self, job_id: str, *, claim: JobWriteClaim,
                             retry_round_ids: tuple[str, ...] = ()) -> PreparedRoundBatch: ...
```

- [ ] **Step 1: Write failing preparation/checkpoint tests**

Cover:

- all target rounds share the exact requested snapshot while each request gets its own input fingerprint;
- unchanged, validated succeeded tasks are reused and omitted from runnable requests;
- changed translation input archives prior result history, removes manifest authority before task replacement, supersedes only affected tasks, and applies the translation invalidation plan;
- checkpoint success writes invocations, then Understanding, then succeeded task; it updates progress/phase/event only after all three validate;
- crashes injected after history archive, after manifest invalidation, and after each affected task replacement always leave a conservative recoverable state with no stale review/artifact authority;
- old/foreign claims cannot checkpoint;
- coordinator event IDs and timestamps are injected and deterministic;
- a frozen clock still permits immediate `PENDING -> RUNNING -> SUCCEEDED`, with each persisted task/manifest timestamp strictly increasing by one microsecond when necessary;
- two completions that obtain the same clock tick, including reverse worker completion order, both checkpoint without manifest/task timestamp conflicts;
- cancellation checkpoint is idempotent: it leaves `PENDING` and already terminal tasks unchanged without an event, but changes `RUNNING`/`RETRY_WAIT` exactly once to `CANCELLED`, refreshes manifest progress/run status, and appends one cancellation event;
- manifest active review/current artifacts are cleared only when the invalidation plan requires it; old files remain on disk.

- [ ] **Step 2: Run and verify red**

```powershell
py -3.12 -m pytest tests/test_job_round_coordinator_v1.py -q
```

Expected: missing `JobRoundCoordinator`.

- [ ] **Step 3: Implement preparation without starting work**

`prepare_translation` performs, under the caller's claim:

1. load Job, timeline, transcripts, and the named configuration snapshot;
2. build one canonical `RoundTaskSpec`/request per target round;
3. initialize missing tasks and idempotently recover a partially initialized batch;
4. reuse succeeded tasks only when input/config/result/invocation closure validates;
5. if any desired spec changed, execute the safe invalidation protocol below before treating a replacement task as current;
6. derive progress and keep the manifest at `CONTEXT_READY/SUCCEEDED` until execution starts.

If every task is a validated reusable success, preparation keeps an already `UNDERSTOOD_TRANSLATED` manifest or reconciles a stale `UNDERSTANDING_TRANSLATING` summary through its one legal edge; it never skips the Task 3 phase graph. Otherwise it never calls the worker and never changes the selected snapshot mid-batch. The first `mark_running` advances `CONTEXT_READY` to `UNDERSTANDING_TRANSLATING/RUNNING`. Each later checkpoint derives fresh progress/run status from all persisted tasks; the final success advances to `UNDERSTOOD_TRANSLATED/SUCCEEDED`, while partial failure/cancellation/interruption keeps the translation phase and exposes the matching run status.

The safe invalidation protocol is intentionally conservative and idempotent:

1. compute every affected task and one combined production `InvalidationPlan` before writing;
2. archive each currently authoritative succeeded Understanding result; this only adds diagnostic history;
3. CAS the manifest through `rewind_job_phase_for_invalidation`, clearing active review/current artifacts **before** changing any task input;
4. CAS each affected task through `supersede_task`, retaining closed attempts/invocation IDs and clearing its current result;
5. append the invalidation event last.

A crash after step 2 changes no authority. A crash after step 3 is safely over-invalidated; the next explicit preparation recomputes desired specs and idempotently finishes step 4. Once any task is superseded, the old review/artifacts are already non-current. Add an injected crash test at every numbered boundary and assert list/open never reports the old review or export as current after step 3.

- [ ] **Step 4: Implement ordered durable checkpoints**

For success, publish in this recoverable order while verifying the same claim at each repository mutation:

1. merge invocation records into the task's canonical JSONL history (zero new records only for a valid empty result);
2. save the round Understanding document;
3. CAS the round task to `SUCCEEDED` with the actual result fingerprint;
4. derive and CAS the manifest summary/phase;
5. append a safe `round_task_succeeded` event.

For failure/retry, merge any real invocation records before CASing the task; cancellation/interruption creates none. `checkpoint_cancellation` reloads the task under the current claim, returns unchanged for `PENDING`/terminal states, or applies `cancel_task` for `RUNNING`/`RETRY_WAIT`; only an actual transition updates the manifest and appends `round_task_cancelled`. Then derive/CAS the manifest and append the matching event. Events are audit history, not the source of truth. Reconciliation repairs a stale manifest summary from task shards without rewriting anything during list/inspect/load.

Every coordinator mutation reloads the current task and manifest first, then allocates its durable transition time inside the scheduler's `claim_gate`:

```python
def parse_canonical_utc(value: str) -> datetime:
    return datetime.strptime(value, "%Y-%m-%dT%H:%M:%S.%fZ").replace(
        tzinfo=timezone.utc
    )

def next_persisted_timestamp(now: datetime, *latest_values: str) -> str:
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("clock must return an aware datetime")
    latest = max(parse_canonical_utc(value) for value in latest_values)
    candidate = now.astimezone(timezone.utc)
    if candidate <= latest:
        candidate = latest + timedelta(microseconds=1)
    return candidate.strftime("%Y-%m-%dT%H:%M:%S.%fZ")
```

Use the maximum relevant persisted timestamp: task transitions include current task and manifest `updated_at`; manifest-only invalidation includes the current manifest and every task it summarizes. Never compute `at` before entering `claim_gate`, and never reuse an earlier coroutine's captured timestamp. Reject naive clocks and overflow as stable `job_timestamp_invalid` without writing.

- [ ] **Step 5: Implement explicit resume reconciliation**

`reconcile_for_resume` is a write operation under a newly acquired claim. It:

- maps durable `RUNNING` tasks left by an earlier expired run to `INTERRUPTED`, then resets them to `PENDING` while preserving attempts;
- resets `FAILED`/`CANCELLED` only when their round IDs are explicitly present in `retry_round_ids`;
- preserves validated successes;
- treats a missing/corrupt claimed result as a stable repository error, never silent rerun;
- reconstructs manifest progress/run status from task truth and emits one reconciliation event.

- [ ] **Step 6: Run tests and commit**

```powershell
py -3.12 -m pytest tests/test_job_round_coordinator_v1.py tests/test_job_repository_round_tasks_v1.py tests/test_job_write_claim_v1.py -q
git add src/cs2pov/application/job_coordinator.py tests/test_job_round_coordinator_v1.py
git commit -m "feat: coordinate durable round checkpoints"
```

### Task 4: Bounded parallel scheduler with completion-order independence

**Files:**
- Create: `src/cs2pov/application/round_scheduler.py`
- Create: `tests/test_round_scheduler_parallel_v1.py`

**Interfaces:**
- Consumes: `PreparedRoundBatch`, `JobRoundCoordinator`, `RoundTranslationWorker`, `RetryPolicy`, `JobWriteSession`.
- Produces:

```python
@dataclass(frozen=True, slots=True)
class RoundSchedulerSettings:
    max_concurrency: int
    claim_lease_us: int
    heartbeat_interval_us: int
    retry_policy: RetryPolicy

@dataclass(frozen=True, slots=True)
class RoundBatchReport:
    tasks: tuple[RoundTranslationTask, ...]
    completion_order: tuple[str, ...]
    cancelled: bool

class RoundScheduler:
    async def run(self, job_id: str, *, configuration_snapshot_id: str,
                  settings: RoundSchedulerSettings,
                  cancel_event: asyncio.Event | None = None,
                  retry_round_ids: tuple[str, ...] = ()) -> RoundBatchReport: ...
```

- [ ] **Step 1: Write failing concurrency and ordering tests**

Use an async fake worker with per-round gates/counters. Prove:

- `max_concurrency=2` never observes three workers inside `translate`;
- rounds 003, 001, 002 may finish in that order while `report.tasks` and durable aggregation remain timeline order 001, 002, 003;
- success for round 003 is visible on disk before round 001 is released;
- one failed round does not cancel or erase unrelated successes;
- a malformed success result maps only that round to non-retryable `round_task_output_mismatch`, persists no malformed invocation/result shard, and does not cancel siblings;
- a `RoundWorkFailure` with mismatched/duplicate invocation records is mapped through the same safe error without persisting those records or cancelling siblings;
- an unexpected worker `Exception` maps only that round to non-retryable `round_task_worker_error`; its persisted error contains the stable safe Chinese fields but no raw exception text, and sibling rounds still complete;
- invalid settings reject bools, zero, heartbeat not less than lease, and unreasonable limits;
- every request uses the one selected configuration snapshot.

- [ ] **Step 2: Run and verify red**

```powershell
py -3.12 -m pytest tests/test_round_scheduler_parallel_v1.py -q
```

Expected: missing scheduler module.

- [ ] **Step 3: Implement structured bounded concurrency**

Use `asyncio.TaskGroup` and `asyncio.Semaphore(settings.max_concurrency)`. The scheduler acquires one `JobWriteSession`, calls coordinator preparation, and starts one coroutine per runnable request. Each coroutine:

1. waits for the semaphore;
2. checks cancellation;
3. persists `RUNNING` before invoking the worker;
4. validates and immediately checkpoints its typed result/failure;
5. records completion order only for diagnostics.

Do not hold `events/.write.lock` across network/worker await points; the long-lived writer claim provides ownership, and each short repository mutation reopens/verifies the OS lock and claim. Create one scheduler-local `asyncio.Lock` named `claim_gate`. Heartbeats and every coordinator mutation run inside `claim_gate`, read `session.claim` only after entering it, and complete before releasing it. This prevents a heartbeat from replacing `claim.json` after a worker captured the previous claim value while still allowing all model work to run concurrently. Each manifest update reloads the latest manifest inside this gate before CAS.

Contain worker-boundary exceptions inside each round coroutine so `TaskGroup` does not cancel healthy siblings:

```python
try:
    result = await worker.translate(request)
    validate_round_work_result(request, result)
except RoundWorkFailure as failure:
    try:
        validate_round_work_failure(request, failure)
    except (DomainSchemaError, TypeError, ValueError) as cause:
        failure = output_mismatch_failure(cause)
    await checkpoint_failure_inside_claim_gate(failure)
except (DomainSchemaError, TypeError, ValueError) as cause:
    await checkpoint_failure_inside_claim_gate(output_mismatch_failure(cause))
except Exception as cause:
    await checkpoint_failure_inside_claim_gate(worker_error_failure(cause))
else:
    await checkpoint_success_inside_claim_gate(result)
```

`output_mismatch_failure` creates a non-retryable `RoundTaskError` with code `round_task_output_mismatch`, safe Chinese message/impact/suggestion, and no invocation records. `worker_error_failure` uses stable code `round_task_worker_error`, is non-retryable in this phase, and retains the raw cause only in memory. Repository/claim/heartbeat errors raised by checkpointing are global integrity failures and may still escape the child to stop the batch; adapter output errors may not.

Use a nested structured-concurrency protocol for active cancellation. Store the `asyncio.Task` returned for every round coroutine. An outer `TaskGroup` owns heartbeat and a cancel watcher; an inner `TaskGroup` owns round tasks. The watcher waits for the first of `cancel_event.wait()` and an internal `batch_done.wait()`. If user cancellation wins, it calls `.cancel()` on every unfinished round task. When the inner group settles, set `batch_done` so watcher/heartbeat exit normally before releasing the write session. Cancel and await the watcher's two temporary wait tasks in its `finally` block so no task leaks.

Each round coroutine tracks whether `mark_running` completed. Cancellation before that point leaves durable `PENDING` untouched. Cancellation while awaiting the worker or a retry sleep enters `finally`, acquires `claim_gate`, rereads `session.claim`, and calls `checkpoint_cancellation`. If success and cancellation race, `claim_gate` plus the coordinator's terminal-state no-op guarantees exactly one durable terminal transition/event. Heartbeat/claim failure takes precedence: when claim health is lost, do not attempt a cancellation write using the old claim.

- [ ] **Step 4: Return canonical reports and aggregation inputs**

Load final tasks through the repository after all child coroutines settle and return them in Demo timeline order. `completion_order` is explicitly non-authoritative diagnostics. The scheduler does not build Draft/Reviewed timelines; it only makes deterministic inputs available to the existing production aggregator.

- [ ] **Step 5: Run tests and commit**

```powershell
py -3.12 -m pytest tests/test_round_scheduler_parallel_v1.py tests/test_job_round_coordinator_v1.py -q
git add src/cs2pov/application/round_scheduler.py tests/test_round_scheduler_parallel_v1.py
git commit -m "feat: schedule bounded parallel round work"
```

### Task 5: Retry waits, cancellation, and claim heartbeats

**Files:**
- Modify: `src/cs2pov/application/round_scheduler.py`
- Create: `tests/test_round_scheduler_recovery_v1.py`

**Interfaces:**
- Adds injected dependencies to `RoundScheduler.__init__`: `clock`, `sleep`, `attempt_id_factory`.
- Preserves Task 4 public `run` signature.

- [ ] **Step 1: Write deterministic retry/heartbeat/cancel tests**

Use a fake clock and awaitable sleeper; do not sleep wall-clock time. Prove:

- retryable failures persist `RETRY_WAIT`, honor the greater of exponential delay and `retry_after_us`, then start the next numbered attempt;
- exhaustion becomes task `FAILED` with final attempt `EXHAUSTED` and does not call the worker again;
- a non-retryable failure never sleeps;
- the background heartbeat runs before half the lease expires during a blocked worker;
- a completion racing a heartbeat is serialized by `claim_gate` and is not rejected as the scheduler's own stale claim;
- heartbeat failure cancels unfinished work, preserves successes, and reports `job_write_interrupted`;
- setting `cancel_event` prevents queued `PENDING` tasks from starting and leaves them `PENDING`, cancels in-flight `RUNNING` tasks to `CANCELLED`, cancels `RETRY_WAIT` without rewriting its closed failed attempt, and leaves successes untouched;
- no retry path changes configuration snapshot/model/provider.

- [ ] **Step 2: Run and verify red**

```powershell
py -3.12 -m pytest tests/test_round_scheduler_recovery_v1.py -q
```

Expected: retry/cancel/heartbeat assertions fail.

- [ ] **Step 3: Implement injected time and retries**

`clock()` returns an aware UTC datetime; `sleep(delay_seconds)` is awaitable. On a `RoundWorkFailure`, checkpoint through the coordinator. If the new task is `RETRY_WAIT`, await exactly until `next_retry_at`, then restart that same task after checking cancellation and claim health.

Do not catch `BaseException`. Preserve `asyncio.CancelledError`, but use a `finally` path to call `checkpoint_cancellation` for an actually started task while the claim is still healthy. A coroutine cancelled before `mark_running` performs no task write, so its durable state remains `PENDING` for an explicit later resume.

- [ ] **Step 4: Implement one heartbeat coroutine per run**

Run a sibling heartbeat loop in the outer `TaskGroup`. Until `batch_done` is set, it waits for the first of the heartbeat interval and `batch_done`; on each interval it enters `claim_gate`, calls `session.heartbeat()`, and publishes failure to the scheduler. Validate `heartbeat_interval_us * 2 < claim_lease_us` so one delayed tick does not immediately expire ownership.

Stop the heartbeat before releasing the write session. If claim health is lost, no later completion may be checkpointed with the old claim.

- [ ] **Step 5: Run scheduler tests and commit**

```powershell
py -3.12 -m pytest tests/test_round_scheduler_parallel_v1.py tests/test_round_scheduler_recovery_v1.py tests/test_job_write_claim_v1.py -q
git add src/cs2pov/application/round_scheduler.py tests/test_round_scheduler_recovery_v1.py
git commit -m "feat: recover retries cancellations and writer leases"
```

### Task 6: Same-version process restart and deterministic aggregation gate

**Files:**
- Create: `tests/golden/fixtures/new_round_orchestration_v1.json`
- Create: `scripts/check_round_orchestration.py`
- Create: `tests/test_round_orchestration_replay.py`

**Interfaces:**
- Consumes: production repository, coordinator, scheduler, worker port, and existing Understanding/Draft validators.
- Produces exact stdout `round orchestration replay passed`.

- [ ] **Step 1: Write the failing real-process replay test**

The checker creates one temporary workspace and runs these separate spawned Python processes:

1. producer imports a synthetic three-round current-version Job, checkpoints round 002, persists 001 as `RUNNING`, leaves 003 pending, then calls `os._exit(73)` while the `JobWriteSession` is still open so no release path removes `claim.json`;
2. a consumer with an injected time before lease expiry opens/lists/inspects the Job read-only, observes the active durable run without mutating byte/hash/mtime snapshots, and proves an explicit write acquisition returns `job_write_busy`;
3. a consumer with fixture time after lease expiry observes the in-memory interrupted projection, acquires a new claim, reconciles 001, reuses 002, and runs only 001/003 with completion deliberately reversed;
4. final consumer validates all task/result/invocation closures, builds the Draft input with production validators, and proves canonical round/cue ordering;
5. cancellation variant preserves already successful task/result files, automatically runs still-pending queued rounds, and resets only explicitly selected cancelled/failed rounds;
6. sibling corrupt Job and unsupported-schema Job remain isolated in catalog output.

No process receives a real API key, endpoint, Demo, audio, video, CS2, or GPU.

Assert the producer's exact exit code, the continued presence and original run ID of the stale claim, pre-expiry refusal, post-expiry takeover with a different run ID, archival/removal of the old active claim, and absence of a claim after the resumed session releases normally. Use injected repository clocks rather than wall-clock sleeps.

- [ ] **Step 2: Run and verify red**

```powershell
py -3.12 -m pytest tests/test_round_orchestration_replay.py -q
```

Expected: missing checker.

- [ ] **Step 3: Implement the fixture and checker**

Store only anonymous IDs, relative logical paths, canonical timestamps, deterministic fake delays/errors, and exact expected fingerprints. Use production codecs/validators/state transitions; the checker must not recreate their algorithms.

- [ ] **Step 4: Run the replay repeatedly**

```powershell
1..5 | ForEach-Object { py -3.12 scripts/check_round_orchestration.py }
```

Expected: five identical success lines, no flakes or leftover writer claim.

- [ ] **Step 5: Commit Task 6**

```powershell
git add tests/golden/fixtures/new_round_orchestration_v1.json scripts/check_round_orchestration.py tests/test_round_orchestration_replay.py
git commit -m "test: gate round orchestration recovery"
```

### Task 7: Documentation, complete verification, independent review, and GitHub merge

**Files:**
- Modify: `docs/ARCHITECTURE.zh.md`
- Modify: `docs/TESTING_GUIDE.zh.md`
- Modify: `tests/golden/README.zh.md`

- [ ] **Step 1: Document the operational boundary for non-programmers**

Explain in plain Chinese:

- different rounds run concurrently up to a configured limit;
- completion order does not change subtitle order;
- success is saved immediately and survives cancellation/crash;
- reopening an earlier Job means the same current version, not v0.x/cross-version migration;
- list/view/inspect are read-only, while resume/retry/cancel are explicit writes;
- provider-specific rate limits/default “stable/balanced/fast” presets, API switching UI, Playwright UI E2E, knowledge approval, and real POV recording are later modules.

- [ ] **Step 2: Run focused and full local verification**

```powershell
py -3.12 -m compileall -q src scripts tests
py -3.12 -m pytest tests/test_domain_job_tasks_v1.py tests/test_domain_job_task_state_v1.py tests/test_domain_job_state_v1.py tests/test_domain_invalidation_v1.py tests/test_job_repository_round_tasks_v1.py tests/test_round_worker_contract_v1.py tests/test_job_round_coordinator_v1.py tests/test_round_scheduler_parallel_v1.py tests/test_round_scheduler_recovery_v1.py tests/test_round_orchestration_replay.py -q
py -3.12 -m pytest -q
py -3.12 scripts/check_golden_baseline.py --replay
py -3.12 scripts/check_new_domain_contract.py
py -3.12 scripts/check_new_job_repository.py
py -3.12 scripts/check_new_job_state.py
py -3.12 scripts/check_round_orchestration.py
py -3.12 scripts/check_repository_hygiene.py
git diff --check origin/master...HEAD
```

Run Ruff on every changed Python file:

```powershell
$changedPython = @(git diff --name-only origin/master...HEAD | Where-Object { $_ -like '*.py' })
py -3.12 -m ruff check $changedPython
```

Privacy/timing scan must produce no output:

```powershell
rg -n "start_time|end_time|api_key|authorization|access_token|password|https?://|steamid|steam_id" src/cs2pov/domain/job_tasks.py src/cs2pov/application/round_worker.py src/cs2pov/application/job_coordinator.py src/cs2pov/application/round_scheduler.py tests/golden/fixtures/new_round_orchestration_v1.json
```

- [ ] **Step 3: Commit documentation**

```powershell
git add docs/ARCHITECTURE.zh.md docs/TESTING_GUIDE.zh.md tests/golden/README.zh.md
git commit -m "docs: explain round orchestration recovery"
```

- [ ] **Step 4: Independent review**

Ask an independent reviewer, normally Luna under the user's resource allocation, to review state legality, claim fencing, cross-file crash points, task/result closure, async cancellation, retry timing, no-write reads, Windows junction behavior, and test realism. Escalate material unresolved risks to the coordinating model. Resolve every accepted finding with a red regression first and rerun the complete gate.

- [ ] **Step 5: GitHub handoff and post-merge proof**

Push the feature branch, create a PR against `master`, and list the deliberate non-scope in the PR body. Wait for all Ubuntu 3.11/3.12/3.13 and Windows 3.12 checks. Merge only when green, fetch `origin/master`, verify the reviewed head is an ancestor, then wait for the merge commit's own CI to pass.

## Definition of Done

- Round tasks persist independently, are claim-fenced, and reopen safely in the same current version.
- Bounded concurrency is measured by tests, not inferred from creating coroutines.
- Out-of-order worker completion never changes canonical timeline/aggregation order.
- Success checkpoints survive partial failure, cancellation, process exit, and next-day resume.
- Retry-After, exponential waits, exhaustion, heartbeat loss, and cancellation are deterministic and observable.
- No worker can write paths/manifest/events or silently change model configuration.
- No read-only historical operation mutates bytes, timestamps, locks, claims, tasks, or manifests.
- Full local gates, real-process replay, independent review, PR CI, and post-merge CI pass.
