from dataclasses import replace
from datetime import timedelta
import json
import multiprocessing
from pathlib import Path

import pytest

from cs2pov.domain.fingerprint import content_fingerprint
from cs2pov.domain.job_tasks import RoundTranslationTask, RoundTaskSpec
from cs2pov.domain.job_task_state import start_task, succeed_task, supersede_task
from cs2pov.storage.job_errors import JobRepositoryError
from test_job_repository_language_shards_v1 import (
    NOW,
    _persist_closed_language_graph,
    _seed,
    _snapshot_tree,
)

JOB = "job-language"


def ts(n):
    return f"2026-09-01T08:00:{n:02}.000000Z"


def pending(config, document, round_id="round-001"):
    return RoundTranslationTask.pending(
        task_id=round_id,
        round_id=round_id,
        input_fingerprint=content_fingerprint({
            "document_input_fingerprint": document.input_fingerprint,
            "configuration_fingerprint": config.configuration_fingerprint,
        }),
        configuration_snapshot_id=config.snapshot_id,
        updated_at=ts(1),
    )


def seeded(tmp_path):
    workspace, repo, claim, values = _persist_closed_language_graph(tmp_path)
    return workspace, repo, claim, values, pending(values[5], values[7])


def finish(repo, claim, task, values):
    repo.initialize_round_tasks(JOB, (task,), claim)
    running = start_task(task, attempt_id="try-1", at=ts(2))
    repo.replace_round_task(JOB, task.content_fingerprint(), running, claim)
    success = succeed_task(
        running, at=ts(3), result_fingerprint=values[7].content_fingerprint(),
        invocation_record_ids=(values[6].invocation_id,),
    )
    repo.replace_round_task(JOB, running.content_fingerprint(), success, claim)
    return success


def test_empty_tasks_without_timeline_are_read_only_and_compatible(tmp_path):
    workspace, repo, _, _, _ = _seed(tmp_path)
    root = workspace.jobs_dir / JOB
    before = _snapshot_tree(root)
    assert repo.load_round_tasks(JOB) == ()
    assert not any(i.severity == "error" for i in repo.inspect_job(JOB).entry.issues)
    assert _snapshot_tree(root) == before


def test_initialize_canonical_subset_and_crash_recovery(tmp_path, monkeypatch):
    workspace, repo, claim, values, task = seeded(tmp_path)
    second_round = replace(values[0].rounds.rounds[0], round_id="round-002", time_range=type(values[0].rounds.rounds[0].time_range)(8_000_000, 9_000_000))
    # Non-lexical timeline order is intentional.
    timeline = replace(values[0], rounds=replace(values[0].rounds, rounds=(second_round, replace(values[0].rounds.rounds[0], display_number=2))))
    repo.save_demo_timeline(JOB, timeline, claim)
    empty = replace(values[7], round_id="round-002", input_fingerprint=content_fingerprint({"round_id": "round-002", "transcript_cues": []}), invocation_record_id=None, results=())
    second = pending(values[5], empty, "round-002")
    import cs2pov.storage.job_repository as module
    original = module.atomic_write_json

    def crash_after_first(path, *args, **kwargs):
        original(path, *args, **kwargs)
        if path.name == "round_round-002.json" and path.parent.name == "tasks":
            raise RuntimeError("injected crash")

    monkeypatch.setattr(module, "atomic_write_json", crash_after_first)
    with pytest.raises(RuntimeError, match="injected crash"):
        repo.initialize_round_tasks(JOB, (task, second), claim)
    assert repo.load_round_tasks(JOB) == (second,)
    target = workspace.jobs_dir / JOB / "tasks/round_round-002.json"
    before = (target.read_bytes(), target.stat().st_mtime_ns)
    monkeypatch.setattr(module, "atomic_write_json", original)
    assert repo.initialize_round_tasks(JOB, (task, second), claim) == (second, task)
    assert (target.read_bytes(), target.stat().st_mtime_ns) == before
    with pytest.raises(JobRepositoryError):
        repo.initialize_round_tasks(JOB, (task,), claim)
    with pytest.raises(JobRepositoryError):
        repo.initialize_round_tasks(JOB, (task, task), claim)


def test_initialization_rejects_wrong_input_before_any_write(tmp_path):
    workspace, repo, claim, _, task = seeded(tmp_path)
    before = _snapshot_tree(workspace.jobs_dir / JOB)
    with pytest.raises(JobRepositoryError):
        repo.initialize_round_tasks(JOB, (replace(task, input_fingerprint="0" * 64),), claim)
    assert _snapshot_tree(workspace.jobs_dir / JOB) == before


def test_cas_and_claim_fence_preserve_bytes(tmp_path):
    workspace, repo, claim, _, task = seeded(tmp_path)
    repo.initialize_round_tasks(JOB, (task,), claim)
    running = start_task(task, attempt_id="try-1", at=ts(2))
    before = _snapshot_tree(workspace.jobs_dir / JOB)
    for expected, supplied_claim, code in [
        ("0" * 64, claim, "job_task_conflict"),
        (task.content_fingerprint(), replace(claim, run_id="other-run"), "job_write_interrupted"),
        (task.content_fingerprint(), replace(claim, job_id="other-job"), "job_write_interrupted"),
    ]:
        with pytest.raises(JobRepositoryError) as caught:
            repo.replace_round_task(JOB, expected, running, supplied_claim)
        assert caught.value.code == code
    assert _snapshot_tree(workspace.jobs_dir / JOB) == before
    assert repo.replace_round_task(JOB, task.content_fingerprint(), running, claim) == running
    assert repo.load_round_tasks(JOB) == (running,)


def test_merge_retains_calls_and_rejects_collisions(tmp_path):
    _, repo, claim, values, _ = seeded(tmp_path)
    old = values[6]
    new = replace(old, invocation_id="invoke-round-000")
    assert repo.merge_task_invocations(JOB, old.task_id, (new,), claim) == (new, old)
    assert repo.merge_task_invocations(JOB, old.task_id, (old, new), claim) == (new, old)
    with pytest.raises(JobRepositoryError):
        repo.merge_task_invocations(JOB, old.task_id, (replace(old, response_content_fingerprint="0" * 64),), claim)
    with pytest.raises(JobRepositoryError):
        repo.merge_task_invocations(JOB, old.task_id, (new, new), claim)
    with pytest.raises(JobRepositoryError):
        repo.merge_task_invocations(JOB, "other-task", (replace(old, task_id="other-task"),), claim)


def test_success_requires_result_and_real_invocation_closure(tmp_path):
    workspace, repo, claim, values, task = seeded(tmp_path)
    repo.initialize_round_tasks(JOB, (task,), claim)
    running = start_task(task, attempt_id="try-1", at=ts(2))
    repo.replace_round_task(JOB, task.content_fingerprint(), running, claim)
    for digest, refs in [("0" * 64, (values[6].invocation_id,)), (values[7].content_fingerprint(), ()), (values[7].content_fingerprint(), ("absent",))]:
        bad = succeed_task(running, at=ts(3), result_fingerprint=digest, invocation_record_ids=refs)
        with pytest.raises(JobRepositoryError):
            repo.replace_round_task(JOB, running.content_fingerprint(), bad, claim)
    assert repo.load_round_tasks(JOB) == (running,)
    (workspace.jobs_dir / JOB / "understanding/round_round-001.json").unlink()
    with pytest.raises(JobRepositoryError):
        repo.replace_round_task(JOB, running.content_fingerprint(), succeed_task(running, at=ts(3), result_fingerprint=values[7].content_fingerprint(), invocation_record_ids=(values[6].invocation_id,)), claim)


def test_cas_cannot_remove_closed_history_or_running_refs(tmp_path):
    _, repo, claim, values, task = seeded(tmp_path)
    success = finish(repo, claim, task, values)
    with pytest.raises(JobRepositoryError):
        repo.replace_round_task(JOB, success.content_fingerprint(), replace(task, updated_at=ts(4)), claim)


def test_archive_and_supersede_keep_history_across_transcript_change(tmp_path):
    workspace, repo, claim, values, task = seeded(tmp_path)
    success = finish(repo, claim, task, values)
    changed_transcript = replace(values[4], asr_original="new source")
    repo.save_transcript_round(JOB, task.round_id, (changed_transcript,), claim)
    assert repo.load_round_tasks(JOB) == (success,)
    new_document = replace(values[7], input_fingerprint=content_fingerprint({"round_id": task.round_id, "transcript_cues": [changed_transcript.to_dict()]}))
    desired = pending(values[5], new_document)
    next_task = supersede_task(success, spec=RoundTaskSpec(task.task_id, task.round_id, desired.input_fingerprint, desired.configuration_snapshot_id), at=ts(4))
    with pytest.raises(JobRepositoryError):
        repo.replace_round_task(JOB, success.content_fingerprint(), next_task, claim)
    repo.archive_round_understanding(JOB, task.round_id, success.result_fingerprint, claim)
    archive = repo.load_job(JOB).paths.round_understanding_history(task.round_id, success.result_fingerprint)
    before = (archive.read_bytes(), archive.stat().st_mtime_ns)
    repo.archive_round_understanding(JOB, task.round_id, success.result_fingerprint, claim)
    assert (archive.read_bytes(), archive.stat().st_mtime_ns) == before
    repo.replace_round_task(JOB, success.content_fingerprint(), next_task, claim)
    assert repo.load_round_tasks(JOB) == (next_task,)
    assert repo.load_language_graph(JOB).understanding_documents == ()
    assert not any(i.severity == "error" for i in repo.inspect_job(JOB).entry.issues)
    archive.write_text('{"schema_version":true}', encoding="utf-8")
    with pytest.raises(JobRepositoryError):
        repo.load_round_tasks(JOB)
    assert any(i.severity == "error" for i in repo.inspect_job(JOB).entry.issues)


def test_save_understanding_cannot_destroy_unarchived_success(tmp_path):
    _, repo, claim, values, task = seeded(tmp_path)
    finish(repo, claim, task, values)
    different = replace(values[7], results=(replace(values[7].results[0], translated_zh="不同"),))
    with pytest.raises(JobRepositoryError):
        repo.save_round_understanding(JOB, different, claim)
    assert repo.load_round_understanding(JOB, task.round_id) == values[7]


@pytest.mark.parametrize("payload,code", [('{"schema_version":2}', "job_schema_unsupported"), ('{"schema_version":true}', "job_shard_invalid"), ('{"schema_version":1,"schema_version":1}', "job_shard_invalid")])
def test_corrupt_task_is_inspected_without_mutation(tmp_path, payload, code):
    workspace, repo, claim, _, task = seeded(tmp_path)
    repo.initialize_round_tasks(JOB, (task,), claim)
    target = workspace.jobs_dir / JOB / "tasks/round_round-001.json"
    target.write_text(payload, encoding="utf-8")
    before = _snapshot_tree(workspace.jobs_dir / JOB)
    with pytest.raises(JobRepositoryError) as caught:
        repo.load_round_tasks(JOB)
    assert caught.value.code == code
    assert any(i.code == code and i.logical_path == "tasks/round_round-001.json" for i in repo.inspect_job(JOB).entry.issues)
    assert _snapshot_tree(workspace.jobs_dir / JOB) == before


def test_pending_residual_document_is_shape_checked_but_not_authoritative(tmp_path):
    workspace, repo, claim, values, task = seeded(tmp_path)
    repo.initialize_round_tasks(JOB, (task,), claim)
    assert repo.load_language_graph(JOB).understanding_documents == ()
    target = workspace.jobs_dir / JOB / "understanding/round_round-001.json"
    wire = values[7].to_dict()
    wire["round_id"] = "other-round"
    target.write_text(json.dumps(wire), encoding="utf-8")
    assert any(i.severity == "error" for i in repo.inspect_job(JOB).entry.issues)


def test_revoked_review_keeps_shape_and_identity_checks(tmp_path):
    from test_job_repository_review_v1 import _review_values, _register
    values = _review_values(tmp_path)
    workspace, repo, claim, language, draft, revision, _, reviewed = values
    _register(values, activate=True)
    repo.save_reviewed_timeline(JOB, reviewed, claim)
    config = next(c for c in language.configurations if c.snapshot_id == "llm-config-001")
    task = pending(config, language.understanding_documents[0])
    # Revoke authority before publishing task truth, as the coordinator must.
    opened = repo.load_job(JOB)
    repo.replace_manifest(JOB, opened.manifest.content_fingerprint(),
                          replace(opened.manifest, active_review_id=None, updated_at=ts(5)), claim)
    repo.initialize_round_tasks(JOB, (task,), claim)
    assert repo.inspect_job(JOB).entry.healthy
    assert repo.load_review_revision(JOB, revision.review_id).revision == revision
    root = workspace.jobs_dir / JOB
    target = root / "review/revisions/review_review-001/round_round-001.json"
    wire = json.loads(target.read_text("utf-8"))
    wire["round_id"] = "other-round"
    target.write_text(json.dumps(wire), encoding="utf-8")
    assert not repo.inspect_job(JOB).entry.healthy


def test_running_refs_are_append_only_and_closed_attempts_immutable(tmp_path):
    _, repo, claim, values, task = seeded(tmp_path)
    repo.initialize_round_tasks(JOB, (task,), claim)
    running = start_task(task, attempt_id="try-1", at=ts(2))
    running = replace(running, attempts=(replace(running.attempts[0], invocation_record_ids=(values[6].invocation_id,)),))
    repo.replace_round_task(JOB, task.content_fingerprint(), running, claim)
    bad = replace(running, updated_at=ts(3), attempts=(replace(running.attempts[0], invocation_record_ids=()),))
    with pytest.raises(JobRepositoryError):
        repo.replace_round_task(JOB, running.content_fingerprint(), bad, claim)
    success = succeed_task(running, at=ts(3), result_fingerprint=values[7].content_fingerprint())
    repo.replace_round_task(JOB, running.content_fingerprint(), success, claim)
    bad = replace(success, updated_at=ts(4), attempts=(replace(success.attempts[0], started_at=ts(1)),))
    with pytest.raises(JobRepositoryError):
        repo.replace_round_task(JOB, success.content_fingerprint(), bad, claim)


def _process_write(root, claim, task, record, mode, start, queue):
    from cs2pov.storage.demo_asset_repository import FileSystemDemoAssetRepository
    from cs2pov.storage.job_repository import FileSystemJobRepository
    from cs2pov.workspace.paths import WorkspacePaths
    workspace = WorkspacePaths(Path(root))
    repo = FileSystemJobRepository(workspace, FileSystemDemoAssetRepository(workspace), clock=lambda: NOW)
    start.wait(20)
    try:
        if mode == "cas":
            repo.replace_round_task(JOB, task.content_fingerprint(),
                                    start_task(task, attempt_id=record.invocation_id, at=ts(2)), claim)
        else:
            repo.merge_task_invocations(JOB, task.task_id, (record,), claim)
        queue.put("ok")
    except JobRepositoryError as exc:
        queue.put(exc.code)


@pytest.mark.parametrize("mode", ["cas", "merge"])
def test_real_process_writes_are_serialized(tmp_path, mode):
    workspace, repo, claim, values, task = seeded(tmp_path)
    repo.initialize_round_tasks(JOB, (task,), claim)
    context = multiprocessing.get_context("spawn")
    start, queue = context.Event(), context.Queue()
    processes = [
        context.Process(target=_process_write, args=(str(workspace.root), claim, task,
            replace(values[6], invocation_id=f"call-{i}"), mode, start, queue))
        for i in (1, 2)
    ]
    try:
        for process in processes:
            process.start()
        start.set()
        results = sorted(queue.get(timeout=30) for _ in processes)
        for process in processes:
            process.join(30)
            assert process.exitcode == 0
        assert results == (["job_task_conflict", "ok"] if mode == "cas" else ["ok", "ok"])
        if mode == "merge":
            assert [r.invocation_id for r in repo.load_task_invocations(JOB, task.task_id)] == ["call-1", "call-2", values[6].invocation_id]
        else:
            assert len(repo.load_round_tasks(JOB)[0].attempts) == 1
    finally:
        for process in processes:
            if process.is_alive():
                process.terminate()
                process.join(10)
        queue.close()


def test_old_heartbeat_same_run_is_valid_but_expired_claim_is_not(tmp_path):
    workspace, repo, claim, _, task = seeded(tmp_path)
    repo.clock.advance()
    refreshed = repo._heartbeat_write(JOB, claim)
    assert refreshed != claim
    repo.initialize_round_tasks(JOB, (task,), claim)
    repo.clock.value += timedelta(seconds=61)
    before = _snapshot_tree(workspace.jobs_dir / JOB)
    with pytest.raises(JobRepositoryError) as caught:
        repo.replace_round_task(JOB, task.content_fingerprint(), start_task(task, attempt_id="try-1", at=ts(2)), claim)
    assert caught.value.code == "job_write_interrupted"
    assert _snapshot_tree(workspace.jobs_dir / JOB) == before


def test_missing_lock_reads_do_not_repair(tmp_path):
    workspace, repo, _, _, _ = _seed(tmp_path)
    root = workspace.jobs_dir / JOB
    (root / "events/.write.lock").unlink()
    before = _snapshot_tree(root)
    with pytest.raises(JobRepositoryError):
        repo.load_round_tasks(JOB)
    assert _snapshot_tree(root) == before


@pytest.mark.parametrize("part", ["task", "history"])
def test_linked_task_or_history_is_rejected(tmp_path, part):
    workspace, repo, claim, values, task = seeded(tmp_path)
    finish(repo, claim, task, values)
    root = workspace.jobs_dir / JOB
    if part == "task":
        target = root / "tasks/round_round-001.json"
        payload = target.read_bytes()
        target.unlink()
        outside = tmp_path / "outside.json"
        outside.write_bytes(payload)
    else:
        target = root / "understanding/history"
        outside = tmp_path / "outside"
        outside.mkdir()
    try:
        target.symlink_to(outside, target_is_directory=part == "history")
    except OSError:
        pytest.skip("symlink privilege unavailable")
    with pytest.raises(JobRepositoryError):
        repo.load_round_tasks(JOB)
    assert not repo.inspect_job(JOB).entry.healthy


@pytest.mark.parametrize("part", ["round_id", "configuration_snapshot_id", "input_fingerprint"])
def test_task_identity_and_attempt_closure_tampering_is_rejected(tmp_path, part):
    workspace, repo, claim, values, task = seeded(tmp_path)
    success = finish(repo, claim, task, values)
    wire = success.to_dict()
    if part == "round_id":
        wire["task_id"] = wire["round_id"] = "round-002"
    elif part == "configuration_snapshot_id":
        wire[part] = wire["attempts"][0][part] = "absent"
    else:
        wire[part] = wire["attempts"][0][part] = "0" * 64
    target = workspace.jobs_dir / JOB / "tasks/round_round-001.json"
    target.write_text(json.dumps(wire), encoding="utf-8")
    with pytest.raises(JobRepositoryError):
        repo.load_round_tasks(JOB)
    assert not repo.inspect_job(JOB).entry.healthy


@pytest.mark.parametrize("part", ["draft", "reviewed"])
def test_revoked_timeline_corruption_is_not_ignored(tmp_path, part):
    from test_job_repository_review_v1 import _review_values
    workspace, repo, claim, language, _, _, _, reviewed = _review_values(tmp_path)
    if part == "reviewed":
        # Valid historical shape can exist without active authority.
        target = workspace.jobs_dir / JOB / "final/timelines/reviewed.json"
        target.write_text(json.dumps(reviewed.to_dict()), encoding="utf-8")
    config = next(c for c in language.configurations if c.snapshot_id == "llm-config-001")
    repo.initialize_round_tasks(JOB, (pending(config, language.understanding_documents[0]),), claim)
    assert repo.inspect_job(JOB).entry.healthy
    target = workspace.jobs_dir / JOB / f"final/timelines/{part}.json"
    target.write_text('{"schema_version":true}', encoding="utf-8")
    assert not repo.inspect_job(JOB).entry.healthy
