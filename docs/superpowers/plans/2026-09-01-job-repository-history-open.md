# Current-Version Job Repository and Historical Reopen Implementation Plan

> **For the implementing agent:** Use the `superpowers:executing-plans` skill and complete this plan task by task. Use `superpowers:test-driven-development` for every production change. Stop at each review checkpoint. Do not widen this batch into scheduling, UI, legacy migration, or pipeline porting.

**Goal:** Build the current-version filesystem Job repository that creates the approved Job layout, publishes every individual file atomically, lists and inspects same-version historical Jobs without side effects, isolates damaged siblings, and enforces one write coordinator through an expiring claim.

**Architecture:** Add a new, strict v1 Job contract beside the already merged v1 domain core. A dedicated `FileSystemJobRepository` owns `workspace/jobs/<job_id>` and never reuses the legacy `ArtifactStore`, legacy `PipelineManifest`, or `manifest.json`. Durable documents contain only resource IDs and normalized workspace-relative paths. Read APIs never create, repair, claim, touch, or rewrite files. Write APIs require an explicit owner claim after creation and use same-directory staging, validation, flush/fsync, and atomic replace.

**Tech Stack:** Python 3.11+, frozen dataclasses and enums, `pathlib`, stdlib `json`, `os`, `tempfile`, `datetime`, `uuid`, `pytest`, subprocess-based contract replay, GitHub Actions on Ubuntu and Windows.

---

## Batch boundary

This plan is phase **02B** from `docs/superpowers/specs/2026-08-31-new-job-domain-and-timeline-design.md`.

It implements:

- the new `jobs/<job_id>/...` layout and safe path generation;
- a strict current-version `job.json` and `source/demo_ref.json`;
- atomic JSON/JSONL publication and strict reads;
- typed persistence for the complete 02A reference graph: timeline, voice activity, model configuration snapshots, invocation records, transcript, understanding, review, and final timelines;
- Job catalog listing, deep inspection, and same-version reopen;
- corrupt-Job isolation and current-version rejection;
- a cross-process single-writer claim with heartbeat and expiry;
- an append-only Job event journal whose incomplete final line is reported but does not invalidate earlier complete events;
- real-process replay proving that a Job created yesterday can be reopened today by the same version.

It does **not** implement:

- v0.x Job discovery, import, conversion, migration, or fallback parsing;
- cross-version schema migration;
- round task state machines, retry policy, rate limiting, parallel scheduling, invalidation, or resume orchestration (phase 02C);
- calls to Demo parsers, voice extraction, ASR, model APIs, subtitle export, overlay rendering, or POV recording;
- a Web/desktop management UI;
- SQLite or the global understanding-translation knowledge base;
- deletion, cleanup, backup import, or automatic repair of damaged Jobs.

The word **historical Job** in every test and document in this batch means: a Job written by this same current-version repository in an earlier process or session. It never means an old v0.x Job.

## Non-negotiable invariants

1. `job.json` is the only Job identity and summary manifest. The old `manifest.json` is neither read nor written by this repository.
2. Only direct children of the selected workspace `jobs/` directory are discovered. Never scan another workspace, the user profile, a drive root, or the legacy output directory.
3. All IDs that become path segments pass a new stricter `require_path_identifier`: lower-case ASCII letters/digits plus internal `-`/`_`, 1..64 characters, no dots, no trailing space/dot, and no Windows device stem. Existing `require_identifier` is not sufficient for filesystem paths. User-visible names never become filenames.
4. Durable JSON contains no absolute path, URL, Steam ID, API key, bearer token, user profile, drive letter, or system temp path. Reuse `reject_private_data` at every document boundary.
5. Every top-level JSON document and every JSONL record has exact `schema_version: 1`. Boolean `True` is not version `1`.
6. Repository schema classification is based on raw exact-version fields before/alongside domain parsing: an exact integer version other than 1 is `job_schema_unsupported`; a missing, boolean, string, null, or otherwise malformed version is manifest/shard invalid. When a domain parser raises `domain_schema_unsupported`, preserve it as `__cause__` and use the raw recursive version classification to choose the stable repository code.
7. Read-only list, inspect, open, and event-read operations are byte-for-byte side-effect free, including for damaged Jobs and stale `RUNNING` state.
8. A single damaged Job never stops catalog listing. It appears as unhealthy with a stable issue code and actionable Chinese text.
9. Replace-style JSON/JSONL documents are visible only after their complete payload has passed validation and been flushed. Validation, staging-file fsync, or `os.replace` failure preserves the previous target and removes staging. If replacement succeeds but the later POSIX parent-directory fsync fails, the new target is already visible and must not be rolled back; return `job_write_durability_uncertain` and require inspection/retry. The append-only event journal is the sole crash-tail exception.
10. Under the cooperative repository protocol, creation never overwrites an existing directory. The entire initial Job is prepared under a hidden same-parent staging directory; repository processes serialize the final `lstat`/existence check and rename under a workspace Job-repository OS lock. Pre-existing targets are rejected. Hostile filesystem mutation racing after the final check is outside this guarantee and must be detected by post-publish no-follow validation, not claimed impossible.
11. Mutable writes after creation require the matching live claim `run_id`. PID alone is never ownership proof. Claim validation and the resulting file publication occur inside one cross-process OS-lock critical section, so an expired claim cannot be taken over between check and publish.
12. An expired or missing claim can make a durable `RUNNING` status appear as `INTERRUPTED` in memory, but read-only opening never writes that projection back.
13. A complete, closed review revision may remain inactive and is valid history. Only hidden staging, missing declared files, identity/fingerprint mismatch, invalid round order, or another incomplete revision closure is damaged; absence from `active_review_id` alone is never an orphan error.
14. Typed shard methods enforce their filename/content relationship: a round transcript contains only that round; `unassigned.jsonl` contains only `round_id=None`; a round understanding document and review document match the requested round.
15. Aggregation order is not introduced here. Repository reads preserve canonical durable order and invoke the 02A validators; the 02C scheduler will decide completion and aggregation.
16. No test in this batch requires CS2, a Demo, GPU, network access, or a real model API.

## Stable repository diagnostics

The repository error type exposes `code`, `message_zh`, `suggestion_zh`, and optional `path` without including an absolute filesystem path in any durable or serialized diagnostic.

Required codes:

- `job_not_found`
- `job_already_exists`
- `job_path_escape`
- `job_source_unavailable`
- `job_schema_unsupported`
- `job_manifest_invalid`
- `job_manifest_conflict`
- `job_shard_missing`
- `job_shard_invalid`
- `job_write_failed`
- `job_write_durability_uncertain`
- `job_write_busy`
- `job_write_interrupted`
- `job_claim_invalid`
- `job_event_tail_incomplete`

`job_event_tail_incomplete` is an inspection issue, not a fatal exception when all preceding event records are valid. A malformed complete line or malformed non-final line is `job_shard_invalid`.

## Exact public interfaces

Do not leave constructor/API choices to the implementing agent.

`src/cs2pov/storage/job_errors.py` owns:

```python
class JobRepositoryError(RuntimeError):
    code: str
    message_zh: str
    suggestion_zh: str
    logical_path: str | None
```

It never serializes an absolute path. `DomainSchemaError`, `OSError`, and JSON exceptions are retained as `__cause__` when mapped. Task 1 creates this shared type so Task 2 path/codec code does not invent another error boundary.

`CreateJobRequest` is a frozen domain value with exact fields:

```python
job_id: str
display_name: str
source: JobDemoSource
```

The repository clock supplies timestamps; creation always starts with `created/pending`, zero progress, empty configuration IDs, null active review, and no final artifacts.

`JobIssue` exact fields:

```python
code: str
severity: str              # "warning" or "error"
message_zh: str
suggestion_zh: str
logical_path: str | None   # Job-relative POSIX path only
```

`JobCatalogEntry` exact fields:

```python
discovery_id: str
job_id: str | None
display_name: str | None
created_at: str | None
updated_at: str | None
demo_asset_id: str | None
demo_display_name: str | None
map_name: str | None
target_player_id: str | None
phase: JobPhase | None
durable_run_status: JobRunStatus | None
effective_run_status: JobRunStatus | None
round_progress: RoundProgressSummary | None
final_artifact_kinds: tuple[FinalArtifactKind, ...]
healthy: bool
issues: tuple[JobIssue, ...]
```

`JobInspection` exact fields:

```python
entry: JobCatalogEntry
marker: JobRepositoryMarker | None
manifest: JobManifest | None
source: JobDemoSource | None
events: tuple[JobEvent, ...]
event_tail_incomplete: bool
```

`OpenedJob` is a frozen runtime value in `storage/job_repository.py`:

```python
marker: JobRepositoryMarker
manifest: JobManifest
source: JobDemoSource
paths: JobPaths
effective_run_status: JobRunStatus
```

`JobWriteSession` in `storage/job_claim.py` holds `repository`, `job_id`, and immutable `JobWriteClaim`; it implements `heartbeat()`, `release()`, and context-manager close. Closing is idempotent only for the same still-owned claim; it never releases another run ID.

`FileSystemJobRepository` exact initial public surface by the end of 02B:

```python
FileSystemJobRepository(paths: WorkspacePaths,
                        demo_assets: FileSystemDemoAssetRepository,
                        *, clock=utc_now,
                        staging_id_factory=uuid4,
                        run_id_factory=uuid4,
                        process_id_supplier=os.getpid,
                        lock_factory=CrossProcessFileLock)
create_job(request: CreateJobRequest) -> OpenedJob
list_jobs() -> tuple[JobCatalogEntry, ...]
inspect_job(job_id: str) -> JobInspection
load_job(job_id: str) -> OpenedJob
acquire_write(job_id: str, *, lease_us: int) -> JobWriteSession
replace_manifest(job_id: str, expected_fingerprint: str,
                 new_manifest: JobManifest, claim: JobWriteClaim) -> OpenedJob
```

The lock adapter's exact non-reentrant API is:

```python
CrossProcessFileLock.open_existing(path: Path, *, timeout_ms: int) -> ContextManager[LockedFile]
CrossProcessFileLock.bootstrap_for_write(path: Path, *, timeout_ms: int) -> ContextManager[LockedFile]
```

`LockedFile` keeps the verified descriptor open until context exit. Nested acquisition of the same lock by one process is unsupported and tested to fail fast rather than hang.

Typed graph return values are frozen runtime DTOs:

```python
class LanguageGraph:
    timeline: DemoTimeline
    activities: tuple[VoiceActivityCue, ...]
    configurations: tuple[ModelConfigurationSnapshot, ...]
    invocations: tuple[ModelInvocationRecord, ...]
    transcripts: tuple[TranscriptCue, ...]
    understanding_documents: tuple[RoundUnderstandingDocument, ...]

class ReviewRevisionBundle:
    revision: ReviewRevisionManifest
    round_documents: tuple[RoundReviewDocument, ...]

class CompleteDomainGraph:
    language: LanguageGraph
    draft: DraftCommsTimeline
    active_review: ReviewRevisionBundle
    reviewed: ReviewedCommsTimeline

class EventJournalRead:
    events: tuple[JobEvent, ...]
    incomplete_tail: bool
    issues: tuple[JobIssue, ...]
```

Exact shard/event signatures added in Tasks 6–9 are:

```python
save_voice_activities(job_id: str, activities: tuple[VoiceActivityCue, ...], claim: JobWriteClaim) -> None
load_voice_activities(job_id: str) -> tuple[VoiceActivityCue, ...]
register_model_configuration(job_id: str, snapshot: ModelConfigurationSnapshot,
                             expected_manifest_fingerprint: str,
                             claim: JobWriteClaim) -> OpenedJob
load_model_configuration(job_id: str, snapshot_id: str) -> ModelConfigurationSnapshot
load_model_configurations(job_id: str) -> tuple[ModelConfigurationSnapshot, ...]
save_task_invocations(job_id: str, task_id: str,
                      records: tuple[ModelInvocationRecord, ...], claim: JobWriteClaim) -> None
load_task_invocations(job_id: str, task_id: str) -> tuple[ModelInvocationRecord, ...]
load_all_invocations(job_id: str) -> tuple[ModelInvocationRecord, ...]
save_demo_timeline(job_id: str, timeline: DemoTimeline, claim: JobWriteClaim) -> None
load_demo_timeline(job_id: str) -> DemoTimeline
save_transcript_round(job_id: str, round_id: str,
                      cues: tuple[TranscriptCue, ...], claim: JobWriteClaim) -> None
load_transcript_round(job_id: str, round_id: str) -> tuple[TranscriptCue, ...]
save_unassigned_transcript(job_id: str, cues: tuple[TranscriptCue, ...], claim: JobWriteClaim) -> None
load_unassigned_transcript(job_id: str) -> tuple[TranscriptCue, ...]
save_round_understanding(job_id: str, document: RoundUnderstandingDocument,
                         claim: JobWriteClaim) -> None
load_round_understanding(job_id: str, round_id: str) -> RoundUnderstandingDocument
load_language_graph(job_id: str) -> LanguageGraph
register_review_revision(job_id: str, revision: ReviewRevisionManifest,
                         round_documents: tuple[RoundReviewDocument, ...],
                         expected_manifest_fingerprint: str, activate: bool,
                         claim: JobWriteClaim) -> ReviewRevisionBundle
load_review_revision(job_id: str, review_id: str) -> ReviewRevisionBundle
save_draft_timeline(job_id: str, timeline: DraftCommsTimeline, claim: JobWriteClaim) -> None
load_draft_timeline(job_id: str) -> DraftCommsTimeline
save_reviewed_timeline(job_id: str, timeline: ReviewedCommsTimeline,
                       claim: JobWriteClaim) -> None
load_reviewed_timeline(job_id: str) -> ReviewedCommsTimeline
load_complete_domain_graph(job_id: str) -> CompleteDomainGraph
append_event(job_id: str, event: JobEvent, claim: JobWriteClaim) -> None
read_events(job_id: str) -> EventJournalRead
```

No method accepts an arbitrary dict, free-form output root, or `legacy=True` switch.

`demo_assets` is used only through `inspect_asset` in this batch. `create_job` refuses an unavailable/mismatched source; later inspection reports source loss without blocking existing final artifacts. Never call `resolve_asset`, because it may rebuild cache and would violate read-only inspection.

## Exact durable layout

```text
jobs/<job_id>/
  repository.json              # immutable marker for this new repository family
  job.json
  source/
    demo_ref.json
  timeline/
    demo.json
    rounds.json
    time_anchors.jsonl
  voice/
    activities.jsonl
  models/
    snapshots/
      snapshot_<snapshot_id>.json
    invocations/
      task_<task_id>.jsonl
  transcript/
    round_<round_id>.jsonl
    unassigned.jsonl
  understanding/
    round_<round_id>.json
  review/
    revisions/
      review_<review_id>/
        revision.json
        round_<round_id>.json
  tasks/
    round_<round_id>.json        # reserved for 02C; no task codec in 02B
  events/
    job_events.jsonl
    .write.lock                 # OS advisory-lock target; never catalog data
    .writer_claim/              # absent until an explicit write claim exists
      claim.json                 # ephemeral coordination state, never catalog data
  final/
    timelines/
      draft.json
      reviewed.json
    subtitles/
    green_screen/
    video/
```

The `jobs/.repository.lock` file serializes initial creation across cooperating processes and is ignored by discovery. Because an existing workspace may not contain it, only the write path may bootstrap it by opening with create-without-truncate, first verifying the opened descriptor and path still identify the same regular file, then ensuring byte 0 exists and is flushed, seeking to byte 0, and locking it; simultaneous bootstrappers converge on the same file and OS lock. A zero-length file left by a crashed bootstrap may be restored to the same constant byte by a later write path after the same descriptor/path checks. Read paths never bootstrap or repair it. `repository.json` is an immutable exact document `{schema_version, repository_kind, job_id}` with `repository_kind="cs2pov-current-job"`. Catalog discovery requires this marker: a legacy directory containing only `manifest.json` is ignored without parsing; if a marked new Job later loses `job.json`, it remains visible as damaged. A new pending Job contains the stable one-byte `.write.lock` and an empty `job_events.jsonl`, but no `.writer_claim` directory. Empty stage directories may exist after creation. Their presence does not claim that a stage completed. A shard is present only when its final file exists and validates.

## Durable contract shapes

Keep exact-key validation. Do not accept aliases, defaults for missing keys, or extra fields.

### `job.json`

```json
{
  "schema_version": 1,
  "job_id": "job-001",
  "display_name": "Mirage POV 双语字幕",
  "created_at": "2026-08-31T16:00:00.000000Z",
  "updated_at": "2026-08-31T16:00:00.000000Z",
  "demo_asset_id": "<64 lowercase hex>",
  "demo_display_name": "match.dem",
  "map_name": null,
  "target_player_id": null,
  "phase": "created",
  "run_status": "pending",
  "round_progress": {
    "total": 0,
    "succeeded": 0,
    "failed": 0,
    "review_pending": 0
  },
  "configuration_snapshot_ids": [],
  "active_review_id": null,
  "final_artifacts": []
}
```

Rules:

- timestamps are canonical UTC with exactly six fractional digits and `Z`; `updated_at >= created_at`;
- `display_name` and `demo_display_name` are trimmed, 1..255 characters, and reject control characters and path separators;
- `map_name`, when known, is a safe identifier;
- `target_player_id`, snapshot IDs, and review ID are safe identifiers;
- `phase` contains the complete phase enum from section 8.1 of the approved design, but 02B only creates `created` and does not implement transitions;
- `run_status` is one of `pending`, `running`, `succeeded`, `failed`, `cancelled`, `interrupted`;
- progress fields are exact non-negative integers, never booleans; each component is `<= total`; `succeeded + failed + review_pending <= total`;
- snapshot IDs are unique under exact and Unicode-casefold comparison and retain input order;
- final artifacts are exact objects `{artifact_id, kind, relative_path, content_sha256, round_id, timebase}`. `kind` is one of `timeline`, `subtitle`, `green_screen`, `video`; `relative_path` must be normalized POSIX beneath the matching `final/` subtree; every segment rejects Windows-invalid characters/device stems/trailing space or dot, and artifact paths are casefold-unique; `round_id` and `timebase` may be null. No existence check occurs in the dataclass; repository inspection checks it.

### `source/demo_ref.json`

```json
{
  "schema_version": 1,
  "asset_id": "<64 lowercase hex>",
  "asset_manifest_relative_path": "library/demos/<asset_id>/asset.json",
  "display_name": "match.dem"
}
```

The `asset_id` and display name must exactly equal the corresponding `job.json` fields.

### Review revision documents

`review/revisions/review_<review_id>/revision.json` is:

```json
{
  "schema_version": 1,
  "review_id": "review-001",
  "source_draft_fingerprint": "<64 lowercase hex>",
  "created_at": "2026-08-31T16:05:00.000000Z",
  "round_ids": ["round-001", "round-002"]
}
```

Add `ReviewRevisionManifest` to `domain/review.py`. Round IDs are path-safe, unique under exact/casefold comparison, and in canonical round order supplied by the caller. The manifest names every round document belonging to that revision.

`review/revisions/review_<review_id>/round_<round_id>.json` is a `RoundReviewDocument`:

Add a `RoundReviewDocument` to `domain/review.py`:

```json
{
  "schema_version": 1,
  "review_id": "review-001",
  "round_id": "round-001",
  "source_draft_fingerprint": "<64 lowercase hex>",
  "decisions": ["<ReviewDecision.to_dict() objects>"]
}
```

This storage contract enforces its own `review_id`/`round_id`, unique decision IDs, unique cue IDs, and exact schema. `ReviewDecision` intentionally has no `round_id`, so cue membership against a round must not be guessed from an ID prefix or duplicated here. The existing review graph validates cue membership against the Draft timeline when composing. `job.json.active_review_id`, when non-null, must resolve to one complete revision manifest and all of its declared round documents.

### `events/job_events.jsonl`

Each line is:

```json
{
  "schema_version": 1,
  "event_id": "event-001",
  "job_id": "job-001",
  "run_id": "run-001",
  "occurred_at": "2026-08-31T16:00:00.000000Z",
  "event_type": "job_created",
  "payload": {}
}
```

`payload` is JSON-only, finite, secret-free, and private-data-free. It is frozen on construction in the same spirit as model configuration parameters.

### `events/.writer_claim/claim.json`

```json
{
  "schema_version": 1,
  "job_id": "job-001",
  "run_id": "run-001",
  "process_id": 1234,
  "acquired_at": "2026-08-31T16:00:00.000000Z",
  "heartbeat_at": "2026-08-31T16:00:00.000000Z",
  "lease_expires_at": "2026-08-31T16:00:30.000000Z"
}
```

Do not store hostnames, usernames, executables, command lines, current directories, or absolute paths.

---

### Task 1: Current-version Job manifest, catalog, event, claim, and round-review contracts

**Files:**

- Create: `src/cs2pov/domain/job.py`
- Modify: `src/cs2pov/domain/schema.py`
- Modify: `src/cs2pov/domain/review.py`
- Create: `src/cs2pov/storage/job_errors.py`
- Test: `tests/test_domain_job_v1.py`
- Modify test: `tests/test_domain_review_v1.py`
- Test: `tests/test_job_errors_v1.py`

**Step 1: Write failing manifest and nested-value tests**

Cover:

- exact `job.json` round trip;
- deterministic `JobManifest.content_fingerprint()` derived from canonical payload and unaffected by mapping insertion order;
- every enum value and rejection of unknown/case variants;
- exact integer validation rejecting booleans;
- canonical timestamp parsing, impossible dates, non-UTC offsets, variable fractions, and `updated_at < created_at`;
- safe names, identifiers, SHA-256 values, uniqueness, progress arithmetic, and artifact subtree matching;
- direct-constructor and `from_dict` privacy/secret scanning across every durable string and event payload;
- path-bearing IDs reject upper-case/casefold aliases, dots, trailing spaces/dots, reserved devices, and lengths above 64 even though the older generic `require_identifier` accepts some of them;
- event payload rejects non-JSON objects, non-string mapping keys, NaN, and Infinity;
- a returned `to_dict()` cannot mutate the frozen object;
- exact-key rejection at every nested level.

Use helpers and fixture factories in the test module; do not couple tests to field order.

**Step 2: Run the tests and prove RED**

Run:

```powershell
py -3.12 -m pytest tests/test_domain_job_v1.py -q
```

Expected: import or missing-contract failures.

**Step 3: Implement the strict contracts**

Implement in `domain/job.py`:

- `CURRENT_JOB_SCHEMA_VERSION = 1`
- `require_path_identifier` in `domain/schema.py`, used only where an ID becomes a durable path segment; do not silently change unrelated legacy IDs
- `JobPhase`
- `JobRunStatus`
- `FinalArtifactKind`
- `FinalArtifactTimebase` with `demo_global` and `round_local`
- `RoundProgressSummary`
- `FinalArtifactEntry`
- `CreateJobRequest`
- `JobManifest`
- `JobRepositoryMarker`
- `JobDemoSource`
- `JobEvent`
- `JobWriteClaim`
- `JobIssue`
- `JobCatalogEntry`
- `JobInspection`

Implement `JobRepositoryError` in `storage/job_errors.py` exactly as specified in the public-interface section, including safe `to_issue()` mapping where appropriate. This is a boundary type only; do not implement filesystem operations in Task 1.

Reuse schema validators and `DemoAssetRef`. Keep UI/runtime projections such as effective interrupted status out of the durable manifest. `JobCatalogEntry` and `JobInspection` may contain optional fields when a corrupt manifest cannot be parsed, but they must always contain a safe discovery ID and one or more `JobIssue` values when unhealthy.

Add `ReviewRevisionManifest` and `RoundReviewDocument` in `domain/review.py` with exact schemas, path-safe revision/round IDs, tuple normalization, casefold uniqueness, unique decision IDs, and unique decision cue IDs. Each round document carries the revision ID and source Draft fingerprint. Do not infer round membership from cue IDs. Do not change the existing `ReviewDecision`, Draft, Reviewed, or composition semantics.

**Step 4: Run focused and existing domain tests**

```powershell
py -3.12 -m pytest tests/test_domain_job_v1.py tests/test_domain_review_v1.py tests/test_domain_schema_v1.py tests/test_job_errors_v1.py -q
```

Expected: PASS.

**Step 5: Commit**

```powershell
git add src/cs2pov/domain/job.py src/cs2pov/domain/schema.py src/cs2pov/domain/review.py src/cs2pov/storage/job_errors.py tests/test_domain_job_v1.py tests/test_domain_review_v1.py tests/test_job_errors_v1.py
git commit -m "feat: add current job repository contracts"
```

### Task 2: Safe Job paths and atomic strict JSON/JSONL codec

**Files:**

- Create: `src/cs2pov/storage/job_paths.py`
- Create: `src/cs2pov/storage/atomic_documents.py`
- Create: `src/cs2pov/storage/cross_process_lock.py`
- Test: `tests/test_job_paths_v1.py`
- Test: `tests/test_atomic_documents_v1.py`
- Test: `tests/test_cross_process_lock_v1.py`

**Step 1: Write failing path tests**

Test `JobPaths` for every exact path in the approved layout, including safe round shard names and final artifact paths. Reject:

- traversal, slashes, backslashes, drive prefixes, reserved Windows names, overlong IDs, and booleans/non-strings;
- upper-case/casefold aliases, tailing dots/spaces, and two IDs or relative artifact paths that would collide on a case-insensitive filesystem;
- a `jobs` root outside the workspace;
- Job directories, parents, or target files that resolve through symlinks or Windows junctions outside the workspace;
- direct use of user text for a shard filename.

`JobPaths` receives `WorkspacePaths` plus a validated `job_id`. It must use `WorkspacePaths._inside`/`resolve_relative` for workspace containment and a repository-local no-link check. Do not make the existing private DemoAsset repository helpers a public dependency.

**Step 2: Write failing atomic codec tests**

Required behavior:

- strict UTF-8 JSON read rejects BOM, malformed JSON, duplicate object keys, NaN/Infinity, non-object top-level payload when an object is required, symlinked files, and directories;
- JSONL read reports 1-based record numbers and rejects blank interior records, duplicate keys, invalid UTF-8, malformed complete lines, and records lacking schema;
- atomic write serializes with `ensure_ascii=False`, `allow_nan=False`, deterministic key ordering, a terminal newline, flush, and `fsync`;
- staging is in the target directory and cannot escape through links;
- validation happens before the first filesystem write;
- validation, staging-file flush/fsync, or `os.replace` failure leaves an old target byte-for-byte unchanged and removes staging;
- an injected POSIX parent-directory fsync failure after successful replacement leaves the new validated target visible, removes staging, and returns `job_write_durability_uncertain`; it never claims the old target survived and never rolls back;
- successful replacement leaves no `.tmp` file;
- POSIX success fsyncs the containing directory after `os.replace`; Windows tests require process-crash atomic visibility but the plan does not claim storage-device power-loss durability beyond available stdlib guarantees;
- JSONL collection replacement is one atomic file write;
- the generic codec never silently treats a missing file as an empty collection.
- raw schema classification distinguishes exact integer non-current versions from malformed/missing/bool/string/null versions at top level and recursively in nested schema-bearing records; tests assert the resulting repository code separately for manifest and shard contexts.

Keep the old `storage/jsonl.py` unchanged; legacy code depends on its permissive behavior.

**Step 3: Write failing cross-process lock tests**

Implement one adapter API backed only by the Python standard library:

- POSIX: `fcntl.flock`;
- Windows: `msvcrt.locking` over byte 0.

Tests must prove:

- the lock target is a stable, regular, pre-existing file containing at least one byte before locking;
- the initial Job layout creates `events/.write.lock` with one fixed byte, while initial repository creation may create `jobs/.repository.lock` only from a write path;
- two child processes starting from an absent global repository lock bootstrap the same lock file and serialize; a write path safely restores a zero-length bootstrap remnant to the constant byte, while a read path leaves it unchanged;
- all read-only APIs treat an absent lock file as “no active operation” and never create it;
- two actual child processes cannot simultaneously enter one exclusive critical section;
- the OS releases the lock after normal close and after a child process exits without cleanup;
- lock timeout/interruption maps to a stable storage error without embedding an absolute path;
- linked, replaced, zero-length, or non-regular lock targets are rejected before use.

The persistent lock file is not an ownership record. Ownership remains in `claim.json`; the OS lock only makes claim checks and publications indivisible among cooperating repository processes.

**Step 4: Prove RED**

```powershell
py -3.12 -m pytest tests/test_job_paths_v1.py tests/test_atomic_documents_v1.py tests/test_cross_process_lock_v1.py -q
```

**Step 5: Implement the minimal codec and lock adapter**

Public functions should be narrow:

```python
read_strict_json(path, *, logical_path, parser)
atomic_write_json(path, value, *, logical_path, serializer, parser)
read_strict_jsonl(path, *, logical_path, parser, allow_incomplete_tail=False)
atomic_write_jsonl(path, values, *, logical_path, serializer, parser)
append_jsonl_record(path, value, *, logical_path, serializer, parser)
classify_schema_versions(raw_value, expectations: tuple[SchemaExpectation, ...]) -> SchemaClassification
```

`SchemaClassification` is the internal enum `current`, `unsupported`, or `malformed`. `SchemaExpectation` is a parser-owned JSON-pointer pattern such as the document root, `/results/*`, or `/decisions/*`. Each typed codec declares its exact schema-bearing locations. Ordinary nested dictionaries (for example model `parameters` or event `payload`) are never assumed to require `schema_version`. An exact integer other than 1 at a declared location is unsupported; absence, `bool`, string, null, or other malformed value is invalid.

The write functions serialize, privacy-scan, then reparse through the production parser before touching disk. `append_jsonl_record` is reserved for the single-writer event log and always appends exactly one compact UTF-8 line plus `\n`, then flushes/fsyncs.

Return a typed JSONL read result containing parsed records and `incomplete_tail: bool`; do not delete or rewrite the tail.

The lock adapter exposes a context manager. It must open and lock the already validated stable file descriptor, confirm the opened descriptor still identifies the expected regular file, and keep that descriptor open for the entire critical section. It must not lock one pathname and then publish through an unrelated unverified root.

**Step 6: Run tests and commit**

```powershell
py -3.12 -m pytest tests/test_job_paths_v1.py tests/test_atomic_documents_v1.py tests/test_cross_process_lock_v1.py -q
git add src/cs2pov/storage/job_paths.py src/cs2pov/storage/atomic_documents.py src/cs2pov/storage/cross_process_lock.py tests/test_job_paths_v1.py tests/test_atomic_documents_v1.py tests/test_cross_process_lock_v1.py
git commit -m "feat: add atomic current job document storage"
```

### Task 3: Atomic Job creation and strict current-version reopen

**Files:**

- Create: `src/cs2pov/storage/job_repository.py`
- Test: `tests/test_job_repository_create_v1.py`

**Step 1: Write failing creation tests**

Construct a repository with injectable UTC clock, staging ID factory, and atomic codec functions. Task 5 adds run-ID/PID injection with write claims. Test:

- creation writes the exact static directory layout, immutable `repository.json`, valid `job.json`, valid `source/demo_ref.json`, stable one-byte `events/.write.lock`, and empty `events/job_events.jsonl`; it does not create `.writer_claim`;
- initial manifest values are `phase=created`, `run_status=pending`, zero progress, empty snapshots/review/artifacts;
- creation calls only `demo_assets.inspect_asset`, verifies the source asset ID/display name and persistent-source health, and returns `job_source_unavailable` without creating staging when unavailable; it never calls `resolve_asset`;
- the final Job directory appears only after every initial document validates;
- an existing Job ID returns `job_already_exists` and is never overwritten, even when corrupt;
- concurrent child-process creators for the same ID produce one success and one stable collision, never a merged directory;
- a pre-existing empty target directory is rejected and remains byte-for-byte/metadata unchanged on POSIX and Windows; do not rely on platform `rename` replacement semantics;
- failed validation creates no directory and no staging files;
- failures before the final directory rename remove only the caller's staging directory and never remove an existing Job;
- final directory rename failure preserves the target and removes staging; POSIX parent-directory fsync failure after a successful rename leaves the newly published valid Job in place and returns `job_write_durability_uncertain` rather than deleting it;
- created durable files contain no workspace absolute path;
- the repository rejects a linked/junction `jobs/` root or linked Job candidate before writing outside the workspace.

The only public creation input is the typed `CreateJobRequest` defined above. Do not add explicit-parameter overloads or accept arbitrary dicts.

**Step 2: Write failing reopen tests**

Test `load_job(job_id)`:

- returns an immutable `OpenedJob` with manifest, source, and `JobPaths`; Task 5 later adds the effective interruption projection once claims exist;
- validates directory name, manifest ID, source ID/display-name equality, exact schema, and safe regular files;
- maps an exact integer `schema_version != 1` anywhere in a required parsed document to `job_schema_unsupported` and preserves the domain parser error as its cause;
- maps missing, boolean, string, null, or malformed schema fields to `job_manifest_invalid`/`job_shard_invalid`, even though the lower-level domain parser uses the broader `domain_schema_unsupported` code;
- missing manifest is `job_manifest_invalid`; missing required source is `job_shard_missing`;
- it never reads `manifest.json`, searches v0.x outputs, or falls back to a legacy parser;
- two repository instances can open the same Job read-only;
- a complete filesystem snapshot before/after load is identical.

**Step 3: Prove RED**

```powershell
py -3.12 -m pytest tests/test_job_repository_create_v1.py -q
```

**Step 4: Implement creation and strict load**

`FileSystemJobRepository` is rooted in `WorkspacePaths`; it must not accept a free-form output root. Add `JobRepositoryError` with the stable fields listed above.

Creation algorithm:

1. validate all objects and final paths in memory;
2. create a uniquely named hidden staging directory directly under `jobs/`;
3. create the approved subdirectories under staging;
4. write and re-read `repository.json`, `source/demo_ref.json`, and `job.json` using the strict codec;
5. prepare the stable one-byte `events/.write.lock` inside staging;
6. acquire the stable one-byte `jobs/.repository.lock` through the cross-process lock adapter (a write operation may create and initialize this lock file; read APIs may not);
7. while holding that descriptor lock, use `lstat` and no-follow checks to reject any pre-existing target, then rename staging to `jobs/<job_id>` and release the lock;
8. on any pre-publication failure, delete only the verified caller-owned staging directory; after a successful final rename, staging no longer exists and later durability-reporting failure must never delete the published Job;
9. return by reopening the published Job through the same production read path.

The OS lock, not a nonexistent portable `RENAME_NOREPLACE`, gives cooperating repositories a single-winner critical section. The final `lstat` immediately before rename protects pre-existing empty directories from POSIX replacement. Externally racing non-repository filesystem tampering is detected on subsequent no-follow validation and is outside the cooperative writer guarantee; never silently repair or overwrite it.

After a successful initial directory rename, fsync the `jobs/` directory on POSIX. On Windows, verify process-crash visibility and do not overstate power-loss durability.

Do not update `updated_at` during a read.

**Step 5: Run tests and commit**

```powershell
py -3.12 -m pytest tests/test_job_repository_create_v1.py tests/test_job_paths_v1.py tests/test_atomic_documents_v1.py -q
git add src/cs2pov/storage/job_repository.py tests/test_job_repository_create_v1.py
git commit -m "feat: create and reopen current version jobs"
```

### Task 4: Catalog listing, deep inspection, and damaged-Job isolation

**Files:**

- Modify: `src/cs2pov/storage/job_repository.py`
- Test: `tests/test_job_repository_catalog_v1.py`

**Step 1: Write failing catalog tests**

Create at least:

- two healthy Jobs with different timestamps;
- one invalid `job.json`;
- one missing manifest;
- one unsupported schema;
- one legacy directory containing `manifest.json` but no `repository.json`;
- one manifest whose `job_id` disagrees with its safe directory;
- one missing source shard;
- one linked/junction Job directory;
- one hidden staging directory;
- one unrelated regular file.

Verify `list_jobs()`:

- scans direct children only;
- returns every safe directory carrying the current-repository marker as one `JobCatalogEntry` and does not follow links;
- ignores a legacy `manifest.json`-only directory without reading or classifying it, while a marked current Job missing `job.json` remains visible as `job_manifest_invalid`;
- ignores hidden repository staging and unrelated non-directories;
- sorts healthy entries by `updated_at` descending then `job_id`, with entries lacking a valid timestamp last and ordered by discovery ID;
- preserves healthy siblings when another entry is corrupt;
- uses `job_schema_unsupported`, `job_manifest_invalid`, `job_shard_missing`, or `job_path_escape` precisely;
- exposes display/demo/map/POV/phase/status/progress/final artifact kinds when manifest data is valid;
- includes Chinese impact and next-action text without absolute paths;
- performs zero writes, mkdirs, claims, replacements, touches, or mtime changes.

**Step 2: Write failing inspection tests**

`inspect_job(job_id)` is a non-throwing diagnostic for an existing safe Job. It returns all discoverable metadata and issues. It verifies:

- required identity/source files;
- immutable marker, directory, manifest, and source identities agree;
- the referenced workspace DemoAsset is checked only through the existing read-only `FileSystemDemoAssetRepository.inspect_asset`, never `resolve_asset`; missing/corrupt source adds `job_source_unavailable` with an actionable suggestion but does not prevent viewing metadata or downloading already valid final artifacts;
- every present path in the approved layout is regular and remains in-Job; Task 6 later adds typed content validation for stage shards;
- final artifact index targets exist, are regular, remain inside the Job, and match the declared content SHA-256;
- unknown extra files do not make the Job invalid; they are ignored for forward-safe workspace tooling within the same schema;
- no automatic repair or rewrite occurs.

`load_job` remains strict and raises the first fatal issue; `inspect_job` captures issues.

**Step 3: Implement, run, and commit**

```powershell
py -3.12 -m pytest tests/test_job_repository_catalog_v1.py tests/test_job_repository_create_v1.py -q
git add src/cs2pov/storage/job_repository.py tests/test_job_repository_catalog_v1.py
git commit -m "feat: list and inspect historical jobs"
```

### Task 5: Cross-process single-writer claim and read-only interruption projection

**Files:**

- Create: `src/cs2pov/storage/job_claim.py`
- Modify: `src/cs2pov/storage/job_repository.py`
- Test: `tests/test_job_write_claim_v1.py`

**Step 1: Write failing claim tests**

Use an injected UTC clock and deterministic factories. Test:

- claim acquisition holds `events/.write.lock` from the absence/expiry check through publication of one complete `.writer_claim/claim.json`;
- two simultaneous contenders yield exactly one owner and one `job_write_busy`;
- a second live claim is rejected even if it has the same PID;
- ownership checks require `job_id` and random `run_id`, not PID;
- heartbeat updates only the owner claim and extends from current clock time;
- release verifies ownership before removing the active claim;
- a non-owner heartbeat/release/write is `job_write_interrupted` and never alters the owner claim;
- expired claims can be atomically displaced by one contender while the old claim directory is renamed to a hidden diagnostic name, not overwritten;
- a malformed/incomplete claim is `job_claim_invalid`; it is not automatically stolen until its directory age exceeds a fixed, tested initialization grace period;
- all claim timestamps and lease durations reject booleans, negative/zero durations, naive clocks, and backwards time;
- claim files contain no hostname, username, command line, executable, cwd, or absolute path;
- a read-only `RUNNING` Job with an expired/missing claim reports effective `INTERRUPTED` without filesystem mutation;
- claim-based effective-status inspection opens the already existing `.write.lock` and reads the claim while holding that lock, so it cannot observe the deliberate gap during stale-claim archive/replacement; it never creates or repairs a lock file and does not change bytes/mtime;
- `PENDING`, `FAILED`, and `SUCCEEDED` are never projected to interrupted;
- a live heartbeat keeps effective `RUNNING` even if the PID is not locally observable.
- an old writer paused before ownership validation cannot publish after another process completes stale takeover; after it acquires `.write.lock`, its re-read sees the new `run_id` and fails;
- a takeover waits while an old writer is inside the single critical section containing ownership validation plus shard publication; it cannot interleave between those two operations;
- claim acquire, takeover, heartbeat, release, manifest update, shard replacement, and event append all use the same stable `events/.write.lock` file and never substitute a per-operation lock pathname.
- `replace_manifest(job_id, expected_fingerprint, new_manifest, claim)` is compare-and-swap: a stale fingerprint returns `job_manifest_conflict`; Job/source identity and `created_at` are immutable; `updated_at` moves forward. Pre-replace failure preserves the old manifest; post-replace parent-fsync failure leaves the new validated manifest visible and reports durability uncertainty.
- repository replacement validates durable references before publication but deliberately does not implement legal phase-transition policy; 02C owns the state machine.
- the OS lock is not assumed reentrant: a deliberate nested acquisition fails fast in tests; compound registration methods acquire once and call a locked helper instead of recursively calling the public `replace_manifest`.

Use a lease duration expressed as integer microseconds or `timedelta`, never float seconds.

**Step 2: Prove RED**

```powershell
py -3.12 -m pytest tests/test_job_write_claim_v1.py -q
```

**Step 3: Implement the claim protocol**

Use the Task 2 OS advisory-lock adapter as the exclusion primitive. `events/.write.lock` already exists as a stable regular one-byte file in every published Job. Hold its same open locked descriptor while reading the current claim, deciding live/expired/invalid state, archiving an expired claim directory, and atomically publishing the replacement claim. Do not use directory rename alone as a mutex and do not release the OS lock between ownership validation and publication.

The returned `JobWriteSession` owns a `JobWriteClaim` token and exposes explicit `heartbeat()` and `release()`; do not start background threads in this batch. Every repository mutable method acquires the same OS lock, re-reads and validates the active claim, performs the complete atomic file publication while still holding the lock, and only then releases it. This critical section is the fencing mechanism for cooperating repository processes.

Add the narrow public compare-and-swap `replace_manifest` needed by future coordinators and by model/artifact registration. It accepts a complete `JobManifest`, never patches arbitrary dicts, verifies the current content fingerprint and immutable identity, checks monotonic `updated_at`, validates referenced durable files, and publishes atomically. It does not decide whether one phase may transition to another.

Factor `_replace_manifest_locked(locked_file, job_id, expected_fingerprint, new_manifest, claim)` as a private helper that requires the already held, identity-verified `.write.lock` descriptor and never acquires it again. Public `replace_manifest` acquires once then calls the helper. `register_model_configuration` and `register_review_revision` also acquire once, publish their immutable first file/directory, and call the same locked helper. Do not rely on `flock` or `msvcrt.locking` reentrancy.

**Step 4: Run and commit**

```powershell
py -3.12 -m pytest tests/test_job_write_claim_v1.py tests/test_job_repository_catalog_v1.py tests/test_job_repository_create_v1.py -q
git add src/cs2pov/storage/job_claim.py src/cs2pov/storage/job_repository.py tests/test_job_write_claim_v1.py
git commit -m "feat: enforce one current job writer"
```

### Task 6: Persist voice activity and model provenance

**Files:**

- Create: `src/cs2pov/storage/job_shards.py`
- Modify: `src/cs2pov/storage/job_repository.py`
- Test: `tests/test_job_repository_provenance_v1.py`

**Step 1: Write failing exact-API tests**

```python
save_voice_activities(job_id, activities, claim)
load_voice_activities(job_id)
register_model_configuration(job_id, snapshot, expected_manifest_fingerprint, claim)
load_model_configuration(job_id, snapshot_id)
load_model_configurations(job_id)
save_task_invocations(job_id, task_id, records, claim)
load_task_invocations(job_id, task_id)
load_all_invocations(job_id)
```

Verify:

- voice records round-trip in canonical `(start_us, end_us, activity_id)` order; Task 6 validates them against an independently reconstructed in-memory `DemoTimeline`, while repository-level reopened timeline/activity graph validation begins in Task 7 after timeline persistence exists;
- snapshot filenames match `snapshot_id`; task invocation filenames match every record's `task_id`; all path IDs use the lower-case path validator;
- snapshot and invocation files are immutable by ID: identical content is idempotent, different content is rejected and never overwrites;
- `configuration_snapshot_ids` exactly equals valid snapshot files, with exact/casefold uniqueness;
- `register_model_configuration` acquires the claim lock, validates the expected manifest fingerprint before any snapshot write, then writes/validates the snapshot and uses the locked manifest helper; stale CAS input creates no orphan;
- an injected crash after snapshot publication but before manifest replacement leaves a diagnosed orphan snapshot, never a manifest reference to a missing snapshot; retry with identical content completes registration;
- invocation configuration IDs resolve and capabilities can be checked by the 02A validators;
- malformed/missing/duplicate-key/version/privacy failures map stably; unexpected programming errors propagate.

**Step 2: Implement thin typed codecs and repository methods**

`job_shards.py` owns serializers/parsers and relationship checks, not roots or locking. Repository methods acquire `.write.lock`, verify the claim, and publish while still locked. Do not add task-state documents; 02C owns them.

**Step 3: Run and commit**

```powershell
py -3.12 -m pytest tests/test_job_repository_provenance_v1.py tests/test_job_write_claim_v1.py tests/test_domain_invocation_v1.py tests/test_domain_validation_v1.py -q
git add src/cs2pov/storage/job_shards.py src/cs2pov/storage/job_repository.py tests/test_job_repository_provenance_v1.py
git commit -m "feat: persist job model provenance"
```

### Task 7: Persist timeline, transcript, and understanding shards

**Files:**

- Modify: `src/cs2pov/storage/job_shards.py`
- Modify: `src/cs2pov/storage/job_repository.py`
- Test: `tests/test_job_repository_language_shards_v1.py`

**Step 1: Write failing exact-API tests**

```python
save_demo_timeline(job_id, timeline, claim)
load_demo_timeline(job_id)
save_transcript_round(job_id, round_id, cues, claim)
load_transcript_round(job_id, round_id)
save_unassigned_transcript(job_id, cues, claim)
load_unassigned_transcript(job_id)
save_round_understanding(job_id, document, claim)
load_round_understanding(job_id, round_id)
load_language_graph(job_id)
```

Verify:

- Demo descriptor, rounds, and anchors reconstruct one valid `DemoTimeline`; partial three-file writes are detected, never filled;
- every replace is atomic under ownership; no float Demo time appears;
- round/path IDs are path-safe and casefold-unique;
- a round transcript contains only that non-null round; `unassigned.jsonl` contains only `round_id=None`;
- understanding document round IDs match filenames;
- reopened voice/config/invocation/transcript/understanding values run through `validate_voice_activity_against_timeline`, `validate_transcript_against_timeline`, and `validate_understanding_document_graph`;
- duplicate cues/results, dangling activity/invocation/snapshot IDs, wrong capability, malformed shards, and unsupported versions are rejected;
- one damaged known shard produces an inspection issue without hiding a healthy sibling;
- read APIs preserve bytes and mtimes; unexpected programming exceptions are not converted into corrupt-input errors.

**Step 2: Implement, run, and commit**

Do not duplicate 02A graph logic. `load_language_graph` returns typed values only after production validators pass.

```powershell
py -3.12 -m pytest tests/test_job_repository_language_shards_v1.py tests/test_job_repository_provenance_v1.py tests/test_domain_validation_v1.py -q
git add src/cs2pov/storage/job_shards.py src/cs2pov/storage/job_repository.py tests/test_job_repository_language_shards_v1.py
git commit -m "feat: persist job language shards"
```

### Task 8: Persist review revisions and final timelines

**Files:**

- Modify: `src/cs2pov/storage/job_shards.py`
- Modify: `src/cs2pov/storage/job_repository.py`
- Test: `tests/test_job_repository_review_v1.py`

**Step 1: Write failing exact-API tests**

```python
register_review_revision(job_id, revision, round_documents,
                         expected_manifest_fingerprint, activate, claim)
load_review_revision(job_id, review_id)
save_draft_timeline(job_id, timeline, claim)
load_draft_timeline(job_id)
save_reviewed_timeline(job_id, timeline, claim)
load_reviewed_timeline(job_id)
load_complete_domain_graph(job_id)
```

Verify:

- revision directory, manifest, and round documents agree on `review_id`, source Draft fingerprint, and exact/casefold-unique round IDs;
- repository registration loads the durable `DemoTimeline` and requires revision `round_ids` to equal the selected IDs in authoritative Demo round order; reordered IDs are rejected even if the same set is present;
- each declared round file exists; undeclared/missing/mismatched files are diagnosed; cue membership is validated only by the existing review graph;
- registration validates the expected manifest fingerprint under the claim lock before writing; a complete closed revision with `activate=False` is legal inactive history and is never diagnosed merely because the manifest does not reference it;
- activation publishes a complete validated revision first; on POSIX it fsyncs `review/revisions/` after the directory rename and only then atomically replaces `job.json`, so a later crash cannot leave a dangling `active_review_id`;
- if the revision parent-directory fsync fails, keep the visible complete revision inactive, return `job_write_durability_uncertain`, and do not update `job.json`; the injected-failure test proves this ordering;
- retry of the same immutable revision is idempotent; conflicting content never overwrites;
- `active_review_id`, when non-null, resolves to the full revision closure;
- Draft/Reviewed timelines round-trip and production draft/review graph validators reject tampered fingerprints, decisions, omitted cues, and forged exclusions;
- `load_complete_domain_graph` reconstructs every 02A object and calls the production validators for configurations, invocations, timeline, activity, transcript, understanding, draft, decisions, and reviewed output;
- `inspect_job` diagnoses unindexed model snapshots plus staged/incomplete/invalid review revisions and all present typed shards without mutating them; a complete inactive review revision is healthy history, not an orphan.

**Step 2: Implement, run, and commit**

Prepare a new review revision in a hidden same-parent staging directory. Hold `.write.lock`, revalidate ownership and collision, publish the revision directory, fsync `review/revisions/` on POSIX, then update `job.json` if activation was requested. Use the cooperative-lock threat model and final `lstat`; never replace a pre-existing revision directory. A parent-fsync failure stops before manifest CAS and returns durability uncertainty with the complete revision left inactive.

```powershell
py -3.12 -m pytest tests/test_job_repository_review_v1.py tests/test_job_repository_language_shards_v1.py tests/test_domain_review_v1.py tests/test_domain_validation_v1.py -q
git add src/cs2pov/storage/job_shards.py src/cs2pov/storage/job_repository.py tests/test_job_repository_review_v1.py
git commit -m "feat: persist job review revisions"
```

### Task 9: Append-only Job event journal with incomplete-tail isolation

**Files:**

- Create: `src/cs2pov/storage/job_events.py`
- Modify: `src/cs2pov/storage/job_repository.py`
- Test: `tests/test_job_events_v1.py`

**Step 1: Write failing event tests**

Test:

- only a live claim can append;
- appended bytes are one canonical compact JSON object plus newline and are fsynced;
- event `job_id` and `run_id` must match the Job and active claim;
- event IDs are unique within all complete existing events;
- a fresh repository instance reads the same event values in append order;
- an invalid UTF-8 or malformed complete line is `job_shard_invalid` with logical record number;
- a missing terminal newline on the final partial record returns all earlier events plus `job_event_tail_incomplete`;
- a valid JSON final record without a newline is still considered incomplete and is not returned;
- an incomplete non-final record is fatal because subsequent bytes prove it is not only a crash tail;
- read-only event inspection never truncates, quarantines, renames, or repairs the file;
- an append after an incomplete tail is rejected until a future explicit repair operation (out of scope);
- concurrent append is not attempted outside the single active claim.

**Step 2: Implement and commit**

Keep tail classification in `job_events.py`; reuse the strict codec and `JobEvent.from_dict`. Surface the incomplete tail as a `JobIssue` in `inspect_job`.

```powershell
py -3.12 -m pytest tests/test_job_events_v1.py tests/test_job_write_claim_v1.py -q
git add src/cs2pov/storage/job_events.py src/cs2pov/storage/job_repository.py tests/test_job_events_v1.py
git commit -m "feat: add crash aware job event journal"
```

### Task 10: Real-process same-version historical Job replay and documentation

**Files:**

- Create: `tests/golden/fixtures/new_job_repository_v1.json`
- Create: `scripts/check_new_job_repository.py`
- Create: `tests/test_new_job_repository_replay.py`
- Modify: `docs/ARCHITECTURE.zh.md`
- Modify: `docs/TESTING_GUIDE.zh.md`
- Modify: `tests/golden/README.zh.md`

**Step 1: Define a deterministic fixture**

The fixture contains only anonymous IDs and relative paths. It declares:

- one healthy Job created on day 1;
- the exact repository marker, manifest, Demo source, voice activity, model snapshots/invocations, and review revision;
- the same three-round Demo timeline and language/final shards already covered by the 02A contract;
- one event journal;
- a day-2 expected catalog/open result;
- one corrupt sibling and one unsupported-schema sibling expected to remain isolated.

No absolute path, URL, API key, Steam ID, external model name requiring network, or machine-specific value may appear.

**Step 2: Write replay tests before the script**

Test that `validate_contract(fixture)` independently reconstructs all expected durable objects and refuses tampering in:

- manifest identity, source identity, schema, timestamps, phase/status, progress, artifact path/hash;
- directory/manifest mismatch;
- round filename/content mismatch;
- missing and malformed shards;
- incomplete event tail classification;
- claim owner/expiry projection;
- model snapshot/invocation closure, active review revision closure, and complete 02A graph validation;
- marker-present current Job damage versus marker-absent legacy-directory ignore semantics;
- fixture privacy and duplicate JSON keys.

Unexpected `RuntimeError` from a monkeypatched production validator must propagate; catch only expected input/domain/repository errors.

**Step 3: Add a real multi-process replay**

`scripts/check_new_job_repository.py` must support an internal worker mode. Use `subprocess.run` for sequential day-1/day-2 workers and `subprocess.Popen` plus explicit pipe/file barriers and bounded timeouts for concurrent workers:

1. parent creates a temporary initialized workspace and the fixture Job through production APIs using the day-1 clock;
2. parent records a recursive byte/hash/mtime snapshot;
3. a fresh Python child process uses the day-2 clock, lists Jobs, strictly opens the healthy Job, loads shards/events, and prints a JSON result to stdout;
4. parent verifies the child result against the fixture and verifies the read-only tree snapshot is unchanged;
5. two barrier-synchronized child processes create the same Job ID; exactly one succeeds and a pre-existing empty target is never replaced;
6. two barrier-synchronized child processes acquire the same claim; exactly one owns it;
7. an expired old owner waits outside the write lock, a new owner takes over, then the old owner attempts publication and receives `job_write_interrupted` without changing bytes;
8. a second barrier case holds `.write.lock` across ownership validation and a delayed atomic publication; takeover cannot enter until publication completes, proving the check/write critical section is indivisible;
9. one marked sibling has a corrupted known typed shard while a healthy sibling still lists and strictly opens; one unmarked `manifest.json`-only legacy directory is ignored;
10. the DemoAsset source is made unavailable after valid final artifact creation; inspection reports `job_source_unavailable` while the existing final artifact remains readable;
11. parent snapshots the tree before every read-only child and proves no new lock/claim/staging file, byte, mtime, or directory appears;
12. parent scans durable JSON values with the production privacy/path classifier for any absolute Windows/POSIX path, URL, username, temp-root fragment, or secret key;
13. script prints exactly `new job repository replay passed` on success.

The child imports installed/source production modules. It must not reconstruct Job results directly from fixture JSON.

**Step 4: Document plain-language semantics**

State explicitly:

- “历史 Job” is an earlier Job from the same new version/session family;
- old v0.x and cross-version loading are deliberately unsupported;
- listing and viewing never mutate files;
- only continue/retry/edit operations acquire a writer claim;
- a stale running claim appears interrupted in memory until a future explicit continue action;
- this batch remains executable without CS2/GPU/API and does not yet schedule round translation.

**Step 5: Run and commit**

```powershell
py -3.12 -m pytest tests/test_new_job_repository_replay.py -q
py -3.12 scripts/check_new_job_repository.py
git add tests/golden/fixtures/new_job_repository_v1.json scripts/check_new_job_repository.py tests/test_new_job_repository_replay.py docs/ARCHITECTURE.zh.md docs/TESTING_GUIDE.zh.md tests/golden/README.zh.md
git commit -m "test: gate current job repository replay"
```

### Task 11: Full verification, independent review, and GitHub handoff

**Files:**

- Modify only if evidence requires a fix.

**Step 1: Focused verification**

```powershell
py -3.12 -m pytest tests/test_domain_job_v1.py tests/test_domain_review_v1.py tests/test_job_errors_v1.py tests/test_job_paths_v1.py tests/test_atomic_documents_v1.py tests/test_cross_process_lock_v1.py tests/test_job_repository_create_v1.py tests/test_job_repository_catalog_v1.py tests/test_job_write_claim_v1.py tests/test_job_repository_provenance_v1.py tests/test_job_repository_language_shards_v1.py tests/test_job_repository_review_v1.py tests/test_job_events_v1.py tests/test_new_job_repository_replay.py -q
```

**Step 2: Full local gates**

```powershell
py -3.12 -m compileall -q src scripts tests
py -3.12 -m pytest -q
py -3.12 scripts/check_golden_baseline.py --replay
py -3.12 scripts/check_new_domain_contract.py
py -3.12 scripts/check_new_job_repository.py
py -3.12 scripts/check_repository_hygiene.py
git diff --check origin/master...HEAD
```

Expected replay messages:

```text
golden baseline check passed
new domain contract replay passed
new job repository replay passed
repository hygiene check passed
```

**Step 3: Scope and privacy audit**

```powershell
rg -n "start_time|end_time" src/cs2pov/domain/job.py src/cs2pov/storage/job_*.py
rg -n "api_key|authorization|access_token|password|https?://|steamid|steam_id" tests/golden/fixtures/new_job_repository_v1.json
git diff --name-only origin/master...HEAD
git status --short
```

The first two searches must return no matches. They are only a quick audit; the contract replay must recursively classify every fixture/durable string and reject any absolute path on either platform rather than relying on `/home/` or drive-letter regexes. The diff must not modify legacy `ArtifactStore`, legacy `PipelineManifest`, CLI, pipeline engine, model adapters, exporters, or existing permissive `storage/jsonl.py`.

**Step 4: Independent strong-model review checkpoint**

The reviewer must read the approved design, this entire plan, and every changed file. It must independently reproduce at least:

- same-version day-1/day-2 reopen with a byte-identical read-only tree;
- corrupt sibling isolation;
- unsupported-schema mapping with preserved cause;
- directory and file atomic failure preservation;
- symlink/junction escape rejection;
- one-winner concurrent create and one-winner concurrent writer claim;
- old-owner/new-owner fencing with both sides of the OS-lock barrier;
- stale claim interruption projection without writes;
- incomplete event-tail isolation;
- typed filename/content relationship rejection;
- complete voice/configuration/invocation/transcript/understanding/review reference closure;
- marker-based legacy ignore and read-only DemoAsset source health reporting;
- fixture privacy scan and both old/new contract replays.

Report findings as Critical, Important, or Minor and state `Ready to merge: Yes/No`. Any Critical or Important finding requires a targeted failing regression test, Luna fix, full rerun, and another independent review.

**Step 5: GitHub integration**

After local verification and independent review are green:

1. push the feature branch;
2. create a PR against `master` summarizing scope and explicit non-scope;
3. wait for Ubuntu Python 3.11/3.12/3.13 and Windows Python 3.12 CI;
4. merge using the already authorized repository merge flow;
5. wait for the post-merge `master` CI and verify the merge commit contains the reviewed head.

Do not delete implementation worktrees until the merged commit and post-merge CI are verified.

---

## Review checkpoints for the primary agent

Pause implementation for strong-model review after:

1. Tasks 1–2: contract and atomic/path boundary;
2. Tasks 3–4: creation, current-version reopen, catalog, and corruption isolation;
3. Task 5: OS-lock-fenced claim protocol and manifest compare-and-swap;
4. Tasks 6–8: provenance, language shards, review revisions, and complete graph reopen;
5. Task 9: event-tail recovery;
6. Task 10: real-process fixture and documentation;
7. Task 11: final branch review before GitHub merge.

At every checkpoint, review against the design and this plan rather than only against tests written by the implementing agent.

## Definition of done for phase 02B

Phase 02B is complete only when all of the following are true:

1. A current-version Job created in one process can be listed, inspected, and strictly reopened in a later process/session.
2. Read-only operations leave every Job byte and mtime unchanged.
3. Marker-less old v0.x `manifest.json` Jobs are ignored; non-current marked schemas are reported unsupported and never imported or rewritten.
4. A corrupt Job remains visible as unhealthy and never hides healthy siblings.
5. Every replace-style document write is validated, same-directory staged, fsynced, and atomically published; the append journal is fsynced and its sole possible crash tail is isolated on read.
6. Initial Job creation never exposes a partial final directory and never overwrites a collision.
7. Typed shards reconstruct the complete 02A graph, including voice/model invocation provenance and review revisions, and reject filename/content/reference mismatches.
8. Only one live write coordinator owns a Job; heartbeat/expiry uses a random run ID and lease, not PID alone.
9. A stale durable running state is projected to interrupted in memory without a read-time write.
10. Earlier complete events survive an incomplete final JSONL record, which is reported without repair.
11. Real-process replay, full pytest, old golden replay, 02A replay, repository hygiene, independent review, PR CI, and post-merge CI all pass.
12. The implementation works on the non-CS2/non-GPU machine and does not call a real model API.
