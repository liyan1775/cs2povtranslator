from __future__ import annotations

# The standalone script adds the repository's source tree before production imports.
# ruff: noqa: E402

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable
from uuid import UUID


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

import scripts.check_new_domain_contract as domain_replay
from cs2pov.domain.errors import DomainSchemaError
from cs2pov.domain.invocation import ModelConfigurationSnapshot, ModelInvocationRecord
from cs2pov.domain.job import (
    CreateJobRequest,
    JobDemoSource,
    JobEvent,
    JobManifest,
    JobPhase,
    JobRepositoryMarker,
    JobRunStatus,
    JobWriteClaim,
    RoundProgressSummary,
)
from cs2pov.domain.review import (
    ReviewDecision,
    ReviewRevisionManifest,
    RoundReviewDocument,
    compose_reviewed_timeline,
)
from cs2pov.domain.schema import reject_private_data
from cs2pov.domain.timebase import TimeAnchor
from cs2pov.domain.timeline import DemoDescriptor, DemoTimeline, RoundCollection
from cs2pov.domain.transcript import TranscriptCue
from cs2pov.domain.understanding import RoundUnderstandingDocument
from cs2pov.domain.validation import compose_draft_timeline
from cs2pov.domain.voice import VoiceActivityCue
from cs2pov.storage.atomic_documents import atomic_write_bytes
from cs2pov.storage.demo_asset_repository import (
    DemoAssetRepositoryError,
    FileSystemDemoAssetRepository,
)
from cs2pov.storage.job_errors import JobRepositoryError
from cs2pov.storage.job_repository import FileSystemJobRepository
from cs2pov.workspace.paths import WorkspacePaths


FIXTURE = ROOT / "tests/golden/fixtures/new_job_repository_v1.json"
PRIMARY_RUN_UUID = UUID("11111111-1111-4111-8111-111111111111")
TRANSPORT_KEYS = frozenset(
    {
        "schema_version",
        "fixture_id",
        "domain_contract",
        "source",
        "clock",
        "claims",
        "job",
        "siblings",
        "expected",
    }
)
REQUIRED_PRIMARY_FILES = frozenset(
    {
        "repository.json",
        "job.json",
        "source/demo_ref.json",
        "timeline/demo.json",
        "timeline/rounds.json",
        "timeline/time_anchors.jsonl",
        "voice/activities.jsonl",
        "models/snapshots/snapshot_asr-config-001.json",
        "models/snapshots/snapshot_llm-config-001.json",
        "models/invocations/task_asr-batch-001.jsonl",
        "models/invocations/task_round-001.jsonl",
        "models/invocations/task_round-002.jsonl",
        "transcript/round_round-001.jsonl",
        "transcript/round_round-002.jsonl",
        "transcript/round_round-003.jsonl",
        "transcript/unassigned.jsonl",
        "understanding/round_round-001.json",
        "understanding/round_round-002.json",
        "understanding/round_round-003.json",
        "review/revisions/review_review-001/revision.json",
        "review/revisions/review_review-001/round_round-001.json",
        "review/revisions/review_review-001/round_round-002.json",
        "review/revisions/review_review-001/round_round-003.json",
        "final/timelines/draft.json",
        "final/timelines/reviewed.json",
        "final/subtitles/bilingual.srt",
        "events/.write.lock",
        "events/job_events.jsonl",
    }
)


class ContractValidationError(ValueError):
    """Stable public error for expected fixture and replay failures."""


class _DuplicateJSONKey(ValueError):
    pass


class _MutableClock:
    def __init__(self, value: str) -> None:
        self.set(value)

    def set(self, value: str) -> None:
        self.value = _parse_timestamp(value)

    def __call__(self) -> datetime:
        return self.value


@dataclass(frozen=True, slots=True)
class _DomainValues:
    timeline: DemoTimeline
    activities: tuple[VoiceActivityCue, ...]
    configurations: tuple[ModelConfigurationSnapshot, ...]
    invocations: tuple[ModelInvocationRecord, ...]
    transcripts: tuple[TranscriptCue, ...]
    understanding: tuple[RoundUnderstandingDocument, ...]
    draft: object
    decisions: tuple[ReviewDecision, ...]
    reviewed: object
    revision: ReviewRevisionManifest
    review_documents: tuple[RoundReviewDocument, ...]


def _object_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicateJSONKey(key)
        result[key] = value
    return result


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_object_pairs)
    if not isinstance(value, dict):
        raise ValueError("JSON root must be an object")
    return value


def _exact(value: object, keys: set[str] | frozenset[str], path: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != set(keys):
        raise ValueError(f"{path} keys are not exact")
    return value


def _sequence(value: object, path: str) -> list[Any]:
    if not isinstance(value, list):
        raise ValueError(f"{path} must be a list")
    return value


def _parse_timestamp(value: object) -> datetime:
    if not isinstance(value, str):
        raise ValueError("timestamp must be a string")
    parsed = datetime.strptime(value, "%Y-%m-%dT%H:%M:%S.%fZ")
    return parsed.replace(tzinfo=timezone.utc)


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _json_bytes(value: object) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")


def _jsonl_bytes(values: tuple[object, ...]) -> bytes:
    return b"".join(_json_bytes(value.to_dict()) for value in values)


def _domain_payload(payload: dict[str, Any], fixture: Path) -> dict[str, Any]:
    declaration = _exact(
        payload["domain_contract"], {"relative_path", "sha256"}, "domain_contract"
    )
    relative = declaration["relative_path"]
    if relative != "new_domain_contract_v1.json":
        raise ValueError("domain fixture path is not canonical")
    domain_path = fixture.parent / relative
    raw = domain_path.read_bytes()
    if _sha256(raw) != declaration["sha256"]:
        raise ValueError("domain fixture hash mismatch")
    domain_replay.validate_contract(domain_path)
    return _load_json(domain_path)


def _unique(values: list[Any], factory: Callable[[object], Any], attr: str) -> tuple[Any, ...]:
    parsed = tuple(factory(value) for value in values)
    identifiers = [getattr(value, attr) for value in parsed]
    if len(identifiers) != len(set(identifiers)):
        raise ValueError(f"duplicate {attr}")
    return parsed


def _build_domain(
    raw: dict[str, Any], asset_id: str, review: dict[str, Any]
) -> _DomainValues:
    descriptor = replace(DemoDescriptor.from_dict(raw["demo"]), demo_asset_id=asset_id)
    timeline = DemoTimeline(
        descriptor,
        RoundCollection.from_dict(raw["rounds"]),
        _unique(raw["time_anchors"], TimeAnchor.from_dict, "anchor_id"),
    )
    activities = _unique(
        raw["voice_activities"], VoiceActivityCue.from_dict, "activity_id"
    )
    configurations = _unique(
        raw["model_configurations"],
        ModelConfigurationSnapshot.from_dict,
        "snapshot_id",
    )
    invocations = _unique(
        raw["model_invocations"], ModelInvocationRecord.from_dict, "invocation_id"
    )
    transcripts = _unique(raw["transcript_cues"], TranscriptCue.from_dict, "cue_id")
    understanding = _unique(
        raw["round_understanding"],
        RoundUnderstandingDocument.from_dict,
        "round_id",
    )
    draft = compose_draft_timeline(
        timeline, transcripts, understanding, configurations, invocations
    )
    decisions = _unique(
        raw["review_decisions"], ReviewDecision.from_dict, "decision_id"
    )
    reviewed = compose_reviewed_timeline(draft, decisions)
    round_ids = tuple(value.round_id for value in timeline.rounds.rounds)
    revision = ReviewRevisionManifest(
        review["review_id"],
        draft.content_fingerprint(),
        review["created_at"],
        round_ids,
    )
    cue_round = {cue.cue_id: cue.round_id for cue in draft.cues}
    documents = tuple(
        RoundReviewDocument(
            revision.review_id,
            round_id,
            revision.source_draft_fingerprint,
            tuple(
                decision
                for decision in decisions
                if cue_round.get(decision.cue_id) == round_id
            ),
        )
        for round_id in round_ids
    )
    return _DomainValues(
        timeline,
        activities,
        configurations,
        invocations,
        transcripts,
        understanding,
        draft,
        decisions,
        reviewed,
        revision,
        documents,
    )


def _expected_durable_bytes(
    marker: JobRepositoryMarker,
    manifest: JobManifest,
    source: JobDemoSource,
    event: JobEvent,
    domain: _DomainValues,
    artifact: bytes,
) -> dict[str, bytes]:
    values: dict[str, bytes] = {
        "repository.json": _json_bytes(marker.to_dict()),
        "job.json": _json_bytes(manifest.to_dict()),
        "source/demo_ref.json": _json_bytes(source.to_dict()),
        "timeline/demo.json": _json_bytes(domain.timeline.descriptor.to_dict()),
        "timeline/rounds.json": _json_bytes(domain.timeline.rounds.to_dict()),
        "timeline/time_anchors.jsonl": _jsonl_bytes(domain.timeline.anchors),
        "voice/activities.jsonl": _jsonl_bytes(
            tuple(
                sorted(
                    domain.activities,
                    key=lambda item: (
                        item.time_range.start_us,
                        item.time_range.end_us,
                        item.activity_id,
                    ),
                )
            )
        ),
        "final/timelines/draft.json": _json_bytes(domain.draft.to_dict()),
        "final/timelines/reviewed.json": _json_bytes(domain.reviewed.to_dict()),
        "events/.write.lock": b"0",
        "events/job_events.jsonl": _json_bytes(event.to_dict()),
        manifest.final_artifacts[0].relative_path: artifact,
        f"review/revisions/review_{domain.revision.review_id}/revision.json": _json_bytes(
            domain.revision.to_dict()
        ),
    }
    for configuration in domain.configurations:
        values[f"models/snapshots/snapshot_{configuration.snapshot_id}.json"] = (
            _json_bytes(configuration.to_dict())
        )
    task_ids = sorted({invocation.task_id for invocation in domain.invocations})
    for task_id in task_ids:
        records = tuple(
            sorted(
                (
                    value
                    for value in domain.invocations
                    if value.task_id == task_id
                ),
                key=lambda value: value.invocation_id,
            )
        )
        values[f"models/invocations/task_{task_id}.jsonl"] = _jsonl_bytes(records)
    round_ids = tuple(value.round_id for value in domain.timeline.rounds.rounds)
    for round_id in round_ids:
        records = tuple(
            sorted(
                (value for value in domain.transcripts if value.round_id == round_id),
                key=lambda item: (
                    item.time_range.start_us,
                    item.time_range.end_us,
                    item.cue_id,
                ),
            )
        )
        values[f"transcript/round_{round_id}.jsonl"] = _jsonl_bytes(records)
    unassigned = tuple(
        sorted(
            (value for value in domain.transcripts if value.round_id is None),
            key=lambda item: (
                item.time_range.start_us,
                item.time_range.end_us,
                item.cue_id,
            ),
        )
    )
    values["transcript/unassigned.jsonl"] = _jsonl_bytes(unassigned)
    for document in domain.understanding:
        values[f"understanding/round_{document.round_id}.json"] = _json_bytes(
            document.to_dict()
        )
    for document in domain.review_documents:
        values[
            f"review/revisions/review_{domain.revision.review_id}/round_{document.round_id}.json"
        ] = _json_bytes(document.to_dict())
    if set(values) != REQUIRED_PRIMARY_FILES:
        raise ValueError("reconstructed durable file closure is incomplete")
    return values


def _declared_file_hashes(expected: dict[str, Any]) -> dict[str, str]:
    declarations = _sequence(expected["durable_files"], "expected.durable_files")
    result: dict[str, str] = {}
    for index, value in enumerate(declarations):
        item = _exact(
            value, {"logical_path", "sha256"}, f"durable_files[{index}]"
        )
        path = item["logical_path"]
        digest = item["sha256"]
        if (
            not isinstance(path, str)
            or path.startswith(("/", "\\"))
            or "\\" in path
            or ":" in path
            or any(part in {"", ".", ".."} for part in path.split("/"))
        ):
            raise ValueError("durable path is unsafe")
        if (
            not isinstance(digest, str)
            or len(digest) != 64
            or any(char not in "0123456789abcdef" for char in digest)
        ):
            raise ValueError("durable hash is invalid")
        if path in result:
            raise ValueError("duplicate durable path")
        result[path] = digest
    return result


def _validate_payload(payload: dict[str, Any], fixture: Path) -> None:
    if set(payload) != TRANSPORT_KEYS:
        raise ValueError("transport keys are not exact")
    if type(payload["schema_version"]) is not int or payload["schema_version"] != 1:
        raise ValueError("unsupported transport schema")
    if payload["fixture_id"] != "new-job-repository-v1":
        raise ValueError("fixture ID is invalid")
    reject_private_data(payload, "job_repository_contract")

    source_value = _exact(
        payload["source"], {"file_name", "content_text", "sha256"}, "source"
    )
    source_bytes = source_value["content_text"].encode("utf-8")
    if source_value["file_name"] != "fixture.dem" or _sha256(source_bytes) != source_value["sha256"]:
        raise ValueError("source declaration mismatch")

    clock = _exact(
        payload["clock"],
        {"day_1", "configuration_1", "configuration_2", "review", "final", "day_2"},
        "clock",
    )
    clock_values = [_parse_timestamp(clock[key]) for key in clock]
    if clock_values != sorted(clock_values) or len(set(clock_values)) != len(clock_values):
        raise ValueError("clock sequence is not strictly increasing")

    claims = _exact(
        payload["claims"],
        {"primary_run_id", "lease_us", "race_successes", "race_busy", "old_owner_result"},
        "claims",
    )
    if (
        claims["primary_run_id"] != f"run-{PRIMARY_RUN_UUID.hex}"
        or type(claims["lease_us"]) is not int
        or claims["lease_us"] <= 0
        or claims["race_successes"] != 1
        or claims["race_busy"] != 1
        or claims["old_owner_result"] != "job_write_interrupted"
    ):
        raise ValueError("claim expectations are invalid")

    job = _exact(
        payload["job"],
        {"job_id", "display_name", "repository", "source", "manifest", "review", "event", "final_artifact"},
        "job",
    )
    marker = JobRepositoryMarker.from_dict(job["repository"])
    source = JobDemoSource.from_dict(job["source"])
    manifest = JobManifest.from_dict(job["manifest"])
    event = JobEvent.from_dict(job["event"])
    review = _exact(job["review"], {"review_id", "created_at"}, "job.review")
    artifact_value = _exact(
        job["final_artifact"], {"relative_path", "content_text", "sha256"}, "job.final_artifact"
    )
    artifact_bytes = artifact_value["content_text"].encode("utf-8")
    if _sha256(artifact_bytes) != artifact_value["sha256"]:
        raise ValueError("artifact hash mismatch")
    if (
        marker.job_id != job["job_id"]
        or manifest.job_id != job["job_id"]
        or source.asset_id != source_value["sha256"]
        or manifest.demo_asset_id != source.asset_id
        or manifest.demo_display_name != source.display_name
        or manifest.display_name != job["display_name"]
        or event.job_id != job["job_id"]
        or event.run_id != claims["primary_run_id"]
    ):
        raise ValueError("Job identity closure mismatch")
    if (
        manifest.created_at != clock["day_1"]
        or manifest.updated_at != clock["final"]
        or manifest.phase is not JobPhase.COMPLETED_WITHOUT_VIDEO
        or manifest.run_status is not JobRunStatus.SUCCEEDED
        or manifest.round_progress != RoundProgressSummary(3, 3, 0, 0)
        or len(manifest.final_artifacts) != 1
        or manifest.final_artifacts[0].relative_path != artifact_value["relative_path"]
        or manifest.final_artifacts[0].content_sha256 != artifact_value["sha256"]
        or event.occurred_at != clock["final"]
    ):
        raise ValueError("manifest or event expectations mismatch")

    raw_domain = _domain_payload(payload, fixture)
    domain = _build_domain(raw_domain, source.asset_id, review)
    expected = _exact(
        payload["expected"],
        {
            "healthy_job_id",
            "round_ids",
            "configuration_snapshot_ids",
            "invocation_ids",
            "active_review_id",
            "event_ids",
            "event_incomplete_tail",
            "asr_original",
            "interpreted_source",
            "final_translated_zh",
            "durable_files",
        },
        "expected",
    )
    round_ids = [value.round_id for value in domain.timeline.rounds.rounds]
    configuration_ids = [value.snapshot_id for value in domain.configurations]
    invocation_ids = [value.invocation_id for value in domain.invocations]
    b_result = next(
        result
        for document in domain.understanding
        for result in document.results
        if result.cue_id == "cue-b-callout"
    )
    b_reviewed = next(
        value for value in domain.reviewed.cues if value.cue_id == "cue-b-callout"
    )
    if (
        expected["healthy_job_id"] != job["job_id"]
        or expected["round_ids"] != round_ids
        or expected["configuration_snapshot_ids"] != configuration_ids
        or expected["invocation_ids"] != invocation_ids
        or expected["active_review_id"] != domain.revision.review_id
        or expected["event_ids"] != [event.event_id]
        or expected["event_incomplete_tail"] is not False
        or expected["asr_original"] != b_result.asr_original
        or expected["interpreted_source"] != b_result.interpreted_source
        or expected["final_translated_zh"] != b_reviewed.final_translated_zh
        or tuple(manifest.configuration_snapshot_ids) != tuple(configuration_ids)
        or manifest.active_review_id != domain.revision.review_id
    ):
        raise ValueError("domain graph expectation mismatch")

    siblings = _exact(
        payload["siblings"], {"corrupt", "unsupported", "legacy"}, "siblings"
    )
    corrupt = _exact(siblings["corrupt"], {"job_id", "marker_present", "issue_code"}, "siblings.corrupt")
    unsupported = _exact(siblings["unsupported"], {"job_id", "marker_present", "issue_code"}, "siblings.unsupported")
    legacy = _exact(siblings["legacy"], {"job_id", "marker_present", "listed"}, "siblings.legacy")
    if (
        corrupt != {"job_id": "job-corrupt", "marker_present": True, "issue_code": "job_shard_invalid"}
        or unsupported != {"job_id": "job-unsupported", "marker_present": True, "issue_code": "job_schema_unsupported"}
        or legacy != {"job_id": "legacy-output", "marker_present": False, "listed": False}
    ):
        raise ValueError("sibling isolation semantics mismatch")

    reconstructed = _expected_durable_bytes(
        marker, manifest, source, event, domain, artifact_bytes
    )
    declared = _declared_file_hashes(expected)
    actual_hashes = {path: _sha256(value) for path, value in reconstructed.items()}
    if declared != actual_hashes:
        raise ValueError("durable file hash closure mismatch")

    _run_replay(payload, fixture, raw_domain, domain, reconstructed)


def _repository(
    root: Path,
    clock_value: str,
    *,
    run_id_factory: Callable[[], UUID] | None = None,
) -> tuple[WorkspacePaths, FileSystemDemoAssetRepository, FileSystemJobRepository]:
    paths = WorkspacePaths(root)
    clock = _MutableClock(clock_value)
    assets = FileSystemDemoAssetRepository(paths, clock=clock)
    repository = FileSystemJobRepository(
        paths,
        assets,
        clock=clock,
        **({"run_id_factory": run_id_factory} if run_id_factory is not None else {}),
    )
    return paths, assets, repository


def _materialize_primary(
    workspace_root: Path,
    input_root: Path,
    payload: dict[str, Any],
    domain: _DomainValues,
) -> tuple[WorkspacePaths, FileSystemDemoAssetRepository, FileSystemJobRepository]:
    clock_values = payload["clock"]
    paths = WorkspacePaths(workspace_root)
    clock = _MutableClock(clock_values["day_1"])
    assets = FileSystemDemoAssetRepository(paths, clock=clock)
    input_root.mkdir(parents=True, exist_ok=True)
    source_path = input_root / payload["source"]["file_name"]
    source_path.write_bytes(payload["source"]["content_text"].encode("utf-8"))
    imported = assets.import_source(source_path).asset
    source = JobDemoSource(
        imported.asset_id,
        f"library/demos/{imported.asset_id}/asset.json",
        imported.display_name,
    )
    repository = FileSystemJobRepository(
        paths,
        assets,
        clock=clock,
        run_id_factory=lambda: PRIMARY_RUN_UUID,
        process_id_supplier=lambda: 4101,
    )
    job = payload["job"]
    opened = repository.create_job(
        CreateJobRequest(job["job_id"], job["display_name"], source)
    )
    if opened.marker != JobRepositoryMarker.from_dict(job["repository"]):
        raise ValueError("created marker mismatch")
    session = repository.acquire_write(job["job_id"], lease_us=payload["claims"]["lease_us"])
    acquired = _parse_timestamp(clock_values["day_1"])
    expected_claim = JobWriteClaim(
        job["job_id"],
        payload["claims"]["primary_run_id"],
        4101,
        clock_values["day_1"],
        clock_values["day_1"],
        (acquired + timedelta(microseconds=payload["claims"]["lease_us"])).strftime(
            "%Y-%m-%dT%H:%M:%S.%fZ"
        ),
    )
    if session.claim != expected_claim:
        raise ValueError("primary claim mismatch")

    repository.save_demo_timeline(job["job_id"], domain.timeline, session.claim)
    repository.save_voice_activities(job["job_id"], domain.activities, session.claim)
    for index, configuration in enumerate(domain.configurations, 1):
        clock.set(clock_values[f"configuration_{index}"])
        current = repository.load_job(job["job_id"])
        repository.register_model_configuration(
            job["job_id"],
            configuration,
            current.manifest.content_fingerprint(),
            session.claim,
        )
    for task_id in sorted({value.task_id for value in domain.invocations}):
        repository.save_task_invocations(
            job["job_id"],
            task_id,
            tuple(value for value in domain.invocations if value.task_id == task_id),
            session.claim,
        )
    for round_value in domain.timeline.rounds.rounds:
        repository.save_transcript_round(
            job["job_id"],
            round_value.round_id,
            tuple(
                value
                for value in domain.transcripts
                if value.round_id == round_value.round_id
            ),
            session.claim,
        )
    repository.save_unassigned_transcript(
        job["job_id"],
        tuple(value for value in domain.transcripts if value.round_id is None),
        session.claim,
    )
    for document in domain.understanding:
        repository.save_round_understanding(job["job_id"], document, session.claim)
    repository.save_draft_timeline(job["job_id"], domain.draft, session.claim)
    clock.set(clock_values["review"])
    current = repository.load_job(job["job_id"])
    repository.register_review_revision(
        job["job_id"],
        domain.revision,
        domain.review_documents,
        current.manifest.content_fingerprint(),
        True,
        session.claim,
    )
    repository.save_reviewed_timeline(job["job_id"], domain.reviewed, session.claim)
    artifact = job["final_artifact"]
    artifact_path = paths.jobs_dir / job["job_id"] / Path(artifact["relative_path"])
    atomic_write_bytes(
        artifact_path,
        artifact["content_text"].encode("utf-8"),
        logical_path=artifact["relative_path"],
    )
    clock.set(clock_values["final"])
    repository.append_event(
        job["job_id"], JobEvent.from_dict(job["event"]), session.claim
    )
    current = repository.load_job(job["job_id"])
    final_manifest = JobManifest.from_dict(job["manifest"])
    repository.replace_manifest(
        job["job_id"],
        current.manifest.content_fingerprint(),
        final_manifest,
        session.claim,
    )
    session.release()
    if repository.load_job(job["job_id"]).manifest != final_manifest:
        raise ValueError("final manifest mismatch")
    return paths, assets, repository


def _create_siblings(
    payload: dict[str, Any],
    repository: FileSystemJobRepository,
    source: JobDemoSource,
) -> None:
    siblings = payload["siblings"]
    for key in ("corrupt", "unsupported"):
        job_id = siblings[key]["job_id"]
        repository.create_job(CreateJobRequest(job_id, f"Fixture {key}", source))
    corrupt = repository.load_job(siblings["corrupt"]["job_id"])
    corrupt.paths.demo_timeline.write_bytes(b"{malformed")
    unsupported = repository.load_job(siblings["unsupported"]["job_id"])
    raw = json.loads(unsupported.paths.manifest.read_text(encoding="utf-8"))
    raw["schema_version"] = 2
    unsupported.paths.manifest.write_bytes(_json_bytes(raw))
    legacy = repository.paths.jobs_dir / siblings["legacy"]["job_id"]
    legacy.mkdir()
    (legacy / "manifest.json").write_bytes(_json_bytes({"legacy": True}))


def _snapshot_tree(root: Path) -> tuple[tuple[object, ...], ...]:
    rows: list[tuple[object, ...]] = []
    for path in sorted((root, *root.rglob("*")), key=lambda value: value.as_posix()):
        state = path.lstat()
        rows.append(
            (
                path.relative_to(root).as_posix(),
                state.st_mode,
                state.st_size,
                state.st_mtime_ns,
                path.read_bytes() if path.is_file() else None,
            )
        )
    return tuple(rows)


def _primary_file_bytes(root: Path, job_id: str) -> dict[str, bytes]:
    job_root = root / "jobs" / job_id
    return {
        path.relative_to(job_root).as_posix(): path.read_bytes()
        for path in job_root.rglob("*")
        if path.is_file()
    }


def _worker_environment() -> dict[str, str]:
    environment = os.environ.copy()
    source_root = str(ROOT / "src")
    environment["PYTHONPATH"] = os.pathsep.join(
        part for part in (str(ROOT), source_root, environment.get("PYTHONPATH", "")) if part
    )
    return environment


def _worker_command(mode: str, *arguments: object) -> list[str]:
    return [sys.executable, str(Path(__file__).resolve()), "--worker", mode, *(str(value) for value in arguments)]


def _run_worker(mode: str, *arguments: object, timeout: float = 30) -> dict[str, Any]:
    result = subprocess.run(
        _worker_command(mode, *arguments),
        cwd=ROOT,
        env=_worker_environment(),
        text=True,
        capture_output=True,
        check=False,
        timeout=timeout,
    )
    if result.returncode != 0 or result.stderr or not result.stdout.strip():
        raise ValueError(f"worker {mode} failed")
    value = json.loads(result.stdout)
    if not isinstance(value, dict):
        raise ValueError("worker result is not an object")
    return value


def _start_worker(mode: str, *arguments: object) -> subprocess.Popen[str]:
    return subprocess.Popen(
        _worker_command(mode, *arguments),
        cwd=ROOT,
        env=_worker_environment(),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


def _finish_worker(child: subprocess.Popen[str], timeout: float = 30) -> dict[str, Any]:
    stdout, stderr = child.communicate(timeout=timeout)
    if child.returncode != 0 or stderr or not stdout.strip():
        raise ValueError("concurrent worker failed")
    value = json.loads(stdout)
    if not isinstance(value, dict):
        raise ValueError("concurrent worker result is not an object")
    return value


def _wait_for(path: Path, children: tuple[subprocess.Popen[str], ...], timeout: float = 10) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if path.exists():
            return
        for child in children:
            if child.poll() is not None:
                raise ValueError("barrier worker exited early")
        time.sleep(0.01)
    raise ValueError("barrier timed out")


def _exercise_create_race(
    scenario: Path, payload: dict[str, Any], source_file: Path
) -> None:
    workspace = scenario / "workspace"
    paths, assets, _ = _repository(workspace, payload["clock"]["day_1"])
    imported = assets.import_source(source_file).asset
    barrier = scenario / "create-go"
    job_id = "job-create-race"
    command_args = (
        workspace,
        job_id,
        imported.asset_id,
        imported.display_name,
        barrier,
        payload["clock"]["day_1"],
    )
    children = tuple(_start_worker("create", *command_args) for _ in range(2))
    barrier.write_text("go", encoding="ascii")
    results = [_finish_worker(child) for child in children]
    statuses = sorted(value["status"] for value in results)
    if statuses != ["created", "job_already_exists"]:
        raise ValueError("create race did not have one winner")

    protected_id = "job-empty-target"
    protected = paths.jobs_dir / protected_id
    protected.mkdir()
    before = protected.stat()
    result = _run_worker(
        "create",
        workspace,
        protected_id,
        imported.asset_id,
        imported.display_name,
        barrier,
        payload["clock"]["day_1"],
    )
    after = protected.stat()
    if result["status"] != "job_already_exists" or (before.st_dev, before.st_ino) != (after.st_dev, after.st_ino) or tuple(protected.iterdir()):
        raise ValueError("pre-existing empty target was replaced")


def _exercise_claim_race(
    scenario: Path, payload: dict[str, Any], source_file: Path
) -> None:
    workspace = scenario / "workspace"
    _, assets, repository = _repository(workspace, payload["clock"]["day_1"])
    imported = assets.import_source(source_file).asset
    source = JobDemoSource(imported.asset_id, f"library/demos/{imported.asset_id}/asset.json", imported.display_name)
    repository.create_job(CreateJobRequest("job-claim-race", "Claim Race", source))
    barrier = scenario / "claim-go"
    args = (workspace, "job-claim-race", barrier, payload["clock"]["day_1"])
    children = tuple(_start_worker("claim", *args) for _ in range(2))
    barrier.write_text("go", encoding="ascii")
    results = [_finish_worker(child) for child in children]
    statuses = sorted(value["status"] for value in results)
    if statuses != ["job_write_busy", "owner"]:
        raise ValueError("claim race did not have one owner")


def _exercise_old_owner_fencing(
    scenario: Path, payload: dict[str, Any], source_file: Path
) -> None:
    workspace = scenario / "workspace"
    paths, assets, repository = _repository(
        workspace,
        payload["clock"]["day_1"],
        run_id_factory=lambda: UUID("22222222-2222-4222-8222-222222222222"),
    )
    imported = assets.import_source(source_file).asset
    source = JobDemoSource(imported.asset_id, f"library/demos/{imported.asset_id}/asset.json", imported.display_name)
    repository.create_job(CreateJobRequest("job-fence", "Fence", source))
    old = repository.acquire_write("job-fence", lease_us=5)
    control = scenario / "old-claim.json"
    control.write_bytes(_json_bytes(old.claim.to_dict()))
    ready = scenario / "old-ready"
    go = scenario / "old-go"
    child = _start_worker(
        "old-publish",
        workspace,
        "job-fence",
        control,
        ready,
        go,
        "2026-09-01T08:00:00.000020Z",
    )
    _wait_for(ready, (child,))
    _, _, contender = _repository(
        workspace,
        "2026-09-01T08:00:00.000010Z",
        run_id_factory=lambda: UUID("33333333-3333-4333-8333-333333333333"),
    )
    contender.acquire_write("job-fence", lease_us=60_000_000)
    before = _snapshot_tree(paths.jobs_dir / "job-fence")
    go.write_text("go", encoding="ascii")
    result = _finish_worker(child)
    after = _snapshot_tree(paths.jobs_dir / "job-fence")
    if result["status"] != payload["claims"]["old_owner_result"] or before != after:
        raise ValueError("old writer changed bytes after takeover")


def _exercise_locked_publication(
    scenario: Path, payload: dict[str, Any], source_file: Path
) -> None:
    workspace = scenario / "workspace"
    _, assets, repository = _repository(
        workspace,
        payload["clock"]["day_1"],
        run_id_factory=lambda: UUID("44444444-4444-4444-8444-444444444444"),
    )
    imported = assets.import_source(source_file).asset
    source = JobDemoSource(imported.asset_id, f"library/demos/{imported.asset_id}/asset.json", imported.display_name)
    repository.create_job(CreateJobRequest("job-lock-barrier", "Lock Barrier", source))
    owner = repository.acquire_write("job-lock-barrier", lease_us=5)
    control = scenario / "holder-claim.json"
    control.write_bytes(_json_bytes(owner.claim.to_dict()))
    ready = scenario / "holder-ready"
    release = scenario / "holder-release"
    holder = _start_worker(
        "locked-publish",
        workspace,
        "job-lock-barrier",
        control,
        ready,
        release,
        "2026-09-01T08:00:00.000001Z",
    )
    _wait_for(ready, (holder,))
    contender = _start_worker(
        "claim",
        workspace,
        "job-lock-barrier",
        scenario / "already-go",
        "2026-09-01T08:00:00.000010Z",
    )
    (scenario / "already-go").write_text("go", encoding="ascii")
    time.sleep(0.2)
    if contender.poll() is not None:
        raise ValueError("takeover entered during locked publication")
    release.write_text("go", encoding="ascii")
    holder_result = _finish_worker(holder)
    contender_result = _finish_worker(contender)
    if holder_result["status"] != "published" or contender_result["status"] != "owner":
        raise ValueError("lock barrier publication result mismatch")


def _scan_durable_json(job_root: Path, temp_root: Path) -> None:
    forbidden_fragments = {temp_root.name.casefold()}
    username = os.environ.get("USERNAME") or os.environ.get("USER")
    if username:
        forbidden_fragments.add(username.casefold())
    for path in job_root.rglob("*"):
        if not path.is_file() or path.suffix not in {".json", ".jsonl"}:
            continue
        text = path.read_text(encoding="utf-8")
        for fragment in forbidden_fragments:
            if fragment and fragment in text.casefold():
                raise ValueError("durable JSON contains machine-specific text")
        lines = text.splitlines() if path.suffix == ".jsonl" else [text]
        for line in lines:
            if not line:
                continue
            reject_private_data(
                json.loads(line, object_pairs_hook=_object_pairs),
                path.relative_to(job_root).as_posix(),
            )


def _run_replay(
    payload: dict[str, Any],
    fixture: Path,
    raw_domain: dict[str, Any],
    domain: _DomainValues,
    expected_files: dict[str, bytes],
) -> None:
    del fixture, raw_domain
    with tempfile.TemporaryDirectory(prefix="cs2pov-job-replay-") as temporary:
        temp_root = Path(temporary)
        workspace = temp_root / "primary-workspace"
        input_root = temp_root / "anonymous-input"
        paths, assets, repository = _materialize_primary(
            workspace, input_root, payload, domain
        )
        job_id = payload["job"]["job_id"]
        actual_files = _primary_file_bytes(workspace, job_id)
        if actual_files != expected_files:
            raise ValueError("production durable bytes differ from fixture")
        source = JobDemoSource.from_dict(payload["job"]["source"])
        _create_siblings(payload, repository, source)
        before = _snapshot_tree(paths.jobs_dir)
        day2 = _run_worker(
            "day2",
            workspace,
            job_id,
            payload["job"]["final_artifact"]["relative_path"],
            payload["clock"]["day_2"],
        )
        after = _snapshot_tree(paths.jobs_dir)
        if before != after:
            raise ValueError("day-2 read mutated the Job tree")
        expected = payload["expected"]
        siblings = payload["siblings"]
        catalog = {value["discovery_id"]: value for value in day2["catalog"]}
        if (
            set(catalog) != {job_id, siblings["corrupt"]["job_id"], siblings["unsupported"]["job_id"]}
            or not catalog[job_id]["healthy"]
            or siblings["corrupt"]["issue_code"] not in catalog[siblings["corrupt"]["job_id"]]["issue_codes"]
            or siblings["unsupported"]["issue_code"] not in catalog[siblings["unsupported"]["job_id"]]["issue_codes"]
            or day2["unsupported_open"]["code"] != "job_schema_unsupported"
            or day2["unsupported_open"]["cause"] != "DomainSchemaError"
            or day2["round_ids"] != expected["round_ids"]
            or day2["configuration_snapshot_ids"] != expected["configuration_snapshot_ids"]
            or day2["invocation_ids"] != expected["invocation_ids"]
            or day2["active_review_id"] != expected["active_review_id"]
            or day2["event_ids"] != expected["event_ids"]
            or day2["event_incomplete_tail"] is not expected["event_incomplete_tail"]
            or day2["asr_original"] != expected["asr_original"]
            or day2["interpreted_source"] != expected["interpreted_source"]
            or day2["final_translated_zh"] != expected["final_translated_zh"]
            or day2["artifact_sha256"] != payload["job"]["final_artifact"]["sha256"]
        ):
            raise ValueError("day-2 repository result mismatch")

        primary_root = paths.jobs_dir / job_id
        before_unavailable = _snapshot_tree(primary_root)
        assets.resolve_asset(source.to_ref()).unlink()
        inspection = repository.inspect_job(job_id)
        artifact_path = primary_root / Path(payload["job"]["final_artifact"]["relative_path"])
        if (
            "job_source_unavailable" not in {issue.code for issue in inspection.entry.issues}
            or _sha256(artifact_path.read_bytes()) != payload["job"]["final_artifact"]["sha256"]
        ):
            raise ValueError("source unavailability damaged final artifact semantics")
        after_unavailable = _snapshot_tree(primary_root)
        if before_unavailable != after_unavailable:
            raise ValueError("source inspection mutated the Job tree")
        _scan_durable_json(primary_root, temp_root)

        source_file = input_root / payload["source"]["file_name"]
        _exercise_create_race(temp_root / "create-race", payload, source_file)
        _exercise_claim_race(temp_root / "claim-race", payload, source_file)
        _exercise_old_owner_fencing(temp_root / "fencing", payload, source_file)
        _exercise_locked_publication(temp_root / "lock-barrier", payload, source_file)


def validate_contract(path: Path) -> None:
    """Validate and replay one current-version Job repository contract."""
    try:
        fixture = Path(path)
        payload = _load_json(fixture)
        _validate_payload(payload, fixture)
    except ContractValidationError:
        raise
    except (
        OSError,
        UnicodeError,
        json.JSONDecodeError,
        DomainSchemaError,
        JobRepositoryError,
        DemoAssetRepositoryError,
        subprocess.TimeoutExpired,
        ValueError,
        TypeError,
        KeyError,
        IndexError,
        StopIteration,
    ) as exc:
        raise ContractValidationError("new job repository contract is invalid") from exc


def _wait_worker_barrier(path: Path, timeout: float = 20) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if path.exists():
            return
        time.sleep(0.01)
    raise ValueError("worker barrier timed out")


def _worker_day2(arguments: list[str]) -> dict[str, Any]:
    workspace, job_id, artifact_relative, clock_value = arguments
    paths, _, repository = _repository(Path(workspace), clock_value)
    catalog = [
        {
            "discovery_id": value.discovery_id,
            "healthy": value.healthy,
            "effective_run_status": None if value.effective_run_status is None else value.effective_run_status.value,
            "issue_codes": [issue.code for issue in value.issues],
        }
        for value in repository.list_jobs()
    ]
    opened = repository.load_job(job_id)
    graph = repository.load_complete_domain_graph(job_id)
    events = repository.read_events(job_id)
    b_result = next(
        result
        for document in graph.language.understanding_documents
        for result in document.results
        if result.cue_id == "cue-b-callout"
    )
    b_reviewed = next(
        cue for cue in graph.reviewed.cues if cue.cue_id == "cue-b-callout"
    )
    unsupported = next(value["discovery_id"] for value in catalog if "job_schema_unsupported" in value["issue_codes"])
    try:
        repository.load_job(unsupported)
    except JobRepositoryError as exc:
        unsupported_open = {
            "code": exc.code,
            "cause": None if exc.__cause__ is None else type(exc.__cause__).__name__,
        }
    else:
        raise ValueError("unsupported sibling unexpectedly opened")
    artifact_path = opened.paths.final_artifact_path(artifact_relative)
    return {
        "catalog": catalog,
        "round_ids": [value.round_id for value in graph.language.timeline.rounds.rounds],
        "configuration_snapshot_ids": [value.snapshot_id for value in graph.language.configurations],
        "invocation_ids": [value.invocation_id for value in graph.language.invocations],
        "active_review_id": graph.active_review.revision.review_id,
        "event_ids": [value.event_id for value in events.events],
        "event_incomplete_tail": events.incomplete_tail,
        "asr_original": b_result.asr_original,
        "interpreted_source": b_result.interpreted_source,
        "final_translated_zh": b_reviewed.final_translated_zh,
        "artifact_sha256": _sha256(artifact_path.read_bytes()),
        "unsupported_open": unsupported_open,
        "effective_run_status": opened.effective_run_status.value,
        "workspace_name": paths.root.name,
    }


def _worker_create(arguments: list[str]) -> dict[str, Any]:
    workspace, job_id, asset_id, display_name, barrier, clock_value = arguments
    _wait_worker_barrier(Path(barrier))
    _, _, repository = _repository(Path(workspace), clock_value)
    source = JobDemoSource(asset_id, f"library/demos/{asset_id}/asset.json", display_name)
    try:
        repository.create_job(CreateJobRequest(job_id, "Create Race", source))
    except JobRepositoryError as exc:
        return {"status": exc.code}
    return {"status": "created"}


def _worker_claim(arguments: list[str]) -> dict[str, Any]:
    workspace, job_id, barrier, clock_value = arguments
    _wait_worker_barrier(Path(barrier))
    _, _, repository = _repository(Path(workspace), clock_value)
    try:
        session = repository.acquire_write(job_id, lease_us=60_000_000)
    except JobRepositoryError as exc:
        return {"status": exc.code}
    return {"status": "owner", "run_id": session.claim.run_id}


def _worker_old_publish(arguments: list[str]) -> dict[str, Any]:
    workspace, job_id, claim_path, ready, go, clock_value = arguments
    _, _, repository = _repository(Path(workspace), clock_value)
    claim = JobWriteClaim.from_dict(_load_json(Path(claim_path)))
    opened = repository.load_job(job_id)
    candidate = replace(
        opened.manifest,
        updated_at=clock_value,
        phase=JobPhase.TIMELINE_READY,
    )
    Path(ready).write_text("ready", encoding="ascii")
    _wait_worker_barrier(Path(go))
    try:
        repository.replace_manifest(
            job_id, opened.manifest.content_fingerprint(), candidate, claim
        )
    except JobRepositoryError as exc:
        return {"status": exc.code}
    return {"status": "published"}


def _worker_locked_publish(arguments: list[str]) -> dict[str, Any]:
    workspace, job_id, claim_path, ready, release, clock_value = arguments
    import cs2pov.storage.job_repository as repository_module

    _, _, repository = _repository(Path(workspace), clock_value)
    claim = JobWriteClaim.from_dict(_load_json(Path(claim_path)))
    opened = repository.load_job(job_id)
    candidate = replace(
        opened.manifest,
        updated_at=clock_value,
        phase=JobPhase.TIMELINE_READY,
    )
    real_write = repository_module.atomic_write_json

    def delayed_write(path, value, *, logical_path, serializer, parser):
        if logical_path == "job.json":
            Path(ready).write_text("ready", encoding="ascii")
            _wait_worker_barrier(Path(release))
        return real_write(
            path,
            value,
            logical_path=logical_path,
            serializer=serializer,
            parser=parser,
        )

    repository_module.atomic_write_json = delayed_write
    repository.replace_manifest(
        job_id, opened.manifest.content_fingerprint(), candidate, claim
    )
    return {"status": "published"}


WORKERS: dict[str, Callable[[list[str]], dict[str, Any]]] = {
    "day2": _worker_day2,
    "create": _worker_create,
    "claim": _worker_claim,
    "old-publish": _worker_old_publish,
    "locked-publish": _worker_locked_publish,
}


def _worker_main(arguments: list[str]) -> int:
    if not arguments or arguments[0] not in WORKERS:
        return 2
    try:
        result = WORKERS[arguments[0]](arguments[1:])
    except Exception as exc:
        print(json.dumps({"worker_error": type(exc).__name__}), file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


def main() -> int:
    if len(sys.argv) >= 2 and sys.argv[1] == "--worker":
        return _worker_main(sys.argv[2:])
    if len(sys.argv) > 2:
        print("new job repository replay failed", file=sys.stderr)
        return 1
    fixture = Path(sys.argv[1]).resolve() if len(sys.argv) == 2 else FIXTURE
    try:
        validate_contract(fixture)
    except ContractValidationError:
        print("new job repository replay failed", file=sys.stderr)
        return 1
    print("new job repository replay passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
