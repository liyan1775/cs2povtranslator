import pytest

from cs2pov.workspace.paths import WorkspacePaths
from cs2pov.domain.schema import require_path_identifier
from cs2pov.storage.job_paths import JobPaths


def test_job_paths_match_layout_and_validate_round_ids(tmp_path):
    paths = JobPaths(WorkspacePaths(tmp_path), "job-001")
    assert paths.job_dir == tmp_path / "jobs" / "job-001"
    assert paths.manifest == paths.job_dir / "job.json"
    assert paths.repository_marker == paths.job_dir / "repository.json"
    assert paths.demo_source == paths.job_dir / "source" / "demo_ref.json"
    assert paths.round_transcript("round_1") == paths.job_dir / "transcript" / "round_round_1.jsonl"
    assert paths.round_understanding("round_1") == paths.job_dir / "understanding" / "round_round_1.json"
    assert paths.review_round("review_1", "round_1").name == "round_round_1.json"
    assert paths.event_journal == paths.job_dir / "events" / "job_events.jsonl"


@pytest.mark.parametrize("value", ["../x", "A", "round.", "round ", "CON", "", True, "a\\b"])
def test_job_paths_reject_unsafe_path_identifiers(value, tmp_path):
    with pytest.raises(Exception):
        require_path_identifier(value, "id")
    with pytest.raises(Exception):
        JobPaths(WorkspacePaths(tmp_path), value)


def test_job_paths_rejects_jobs_symlink_outside_workspace(tmp_path):
    outside = tmp_path.parent / "outside-job-paths"
    outside.mkdir()
    jobs_link = tmp_path / "jobs"
    try:
        jobs_link.symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("symlink privileges unavailable")
    with pytest.raises(Exception):
        JobPaths(WorkspacePaths(tmp_path), "job-1")


@pytest.mark.parametrize("relative", [
    "final/subtitles/file.txt:evil",
    "final/subtitles/file.txt ",
    "final/subtitles/file?.txt",
    "final/subtitles/CON.txt",
])
def test_artifact_segments_reject_windows_unsafe_names(relative, tmp_path):
    paths = JobPaths(WorkspacePaths(tmp_path), "job-1")
    with pytest.raises(Exception):
        paths.final_artifact_path(relative)


def test_job_paths_rejects_regular_jobs_or_job_directory(tmp_path):
    jobs = tmp_path / "jobs"
    jobs.write_text("not a directory")
    with pytest.raises(Exception):
        JobPaths(WorkspacePaths(tmp_path), "job-1")
    jobs.unlink()
    jobs.mkdir()
    (jobs / "job-1").write_text("not a directory")
    with pytest.raises(Exception):
        JobPaths(WorkspacePaths(tmp_path), "job-1")


def test_job_paths_exposes_every_dynamic_shard_path(tmp_path):
    paths = JobPaths(WorkspacePaths(tmp_path), "job-1")
    assert paths.snapshot("snap-1").name == "snapshot_snap-1.json"
    assert paths.task_invocations("task-1").name == "task_task-1.jsonl"
    assert paths.unassigned_transcript().name == "unassigned.jsonl"
    assert paths.review_revision_manifest("review-1").name == "revision.json"
    assert paths.task_round("round-1").name == "round_round-1.json"
    assert paths.final_artifact_path("final/video/movie.mp4").name == "movie.mp4"
    assert paths.final_artifact_path("final/timelines/full.json", kind=None).parent.name == "timelines"
