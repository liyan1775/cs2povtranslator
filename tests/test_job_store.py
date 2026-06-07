"""Tests for JobStore — JSON Lines persistence, state machine, migration."""

from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest

from cs2tl.web.job_store import JobRecord, JobStatus, JobStore


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def tmp_store(tmp_path: Path) -> JobStore:
    """A JobStore backed by a temp file — no side effects on real ~/.cs2tl/."""
    store_path = tmp_path / "jobs.json"
    return JobStore(store_path=store_path)


# ---------------------------------------------------------------------------
# Create & retrieve
# ---------------------------------------------------------------------------


class TestCreateJob:
    def test_create_adds_record(self, tmp_store: JobStore):
        record = tmp_store.create(
            demo_name="test.dem",
            demo_path="/tmp/test.dem",
            cache_dir="/tmp/cache/abc",
        )
        assert record.job_id
        assert len(record.job_id) == 8
        assert record.status == JobStatus.CREATED
        assert record.demo_name == "test.dem"

    def test_create_with_demo_info(self, tmp_store: JobStore):
        record = tmp_store.create(
            demo_name="test.dem",
            demo_path="/tmp/test.dem",
            cache_dir="/tmp/cache/abc",
            demo_info={
                "player_count": 10,
                "team_2": ["Alice", "Bob"],
                "team_3": ["Charlie"],
            },
        )
        assert record.player_count == 10
        assert record.team_2_names == ["Alice", "Bob"]
        assert record.team_3_names == ["Charlie"]

    def test_create_persists_to_disk(self, tmp_store: JobStore):
        tmp_store.create(demo_name="test.dem", demo_path="/p", cache_dir="/c")
        # Reload from disk
        store2 = JobStore(store_path=tmp_store._path)
        store2.load()
        jobs = store2.list_all()
        assert len(jobs) == 1
        assert jobs[0].demo_name == "test.dem"


class TestGetJob:
    def test_get_returns_none_for_unknown(self, tmp_store: JobStore):
        assert tmp_store.get("nonexist") is None

    def test_get_returns_record(self, tmp_store: JobStore):
        record = tmp_store.create(demo_name="x.dem", demo_path="/p", cache_dir="/c")
        assert tmp_store.get(record.job_id) is record


# ---------------------------------------------------------------------------
# State machine
# ---------------------------------------------------------------------------


class TestStateTransitions:
    def test_created_to_running(self, tmp_store: JobStore):
        r = tmp_store.create(demo_name="d", demo_path="/p", cache_dir="/c")
        tmp_store.start(r.job_id)
        assert tmp_store.get(r.job_id).status == JobStatus.RUNNING

    def test_running_to_completed(self, tmp_store: JobStore):
        r = tmp_store.create(demo_name="d", demo_path="/p", cache_dir="/c")
        tmp_store.start(r.job_id)
        tmp_store.complete(r.job_id)
        assert tmp_store.get(r.job_id).status == JobStatus.COMPLETED

    def test_running_to_failed(self, tmp_store: JobStore):
        r = tmp_store.create(demo_name="d", demo_path="/p", cache_dir="/c")
        tmp_store.start(r.job_id)
        tmp_store.fail(r.job_id, "something broke")
        job = tmp_store.get(r.job_id)
        assert job.status == JobStatus.FAILED
        assert job.error == "something broke"

    def test_completed_is_terminal(self, tmp_store: JobStore):
        r = tmp_store.create(demo_name="d", demo_path="/p", cache_dir="/c")
        tmp_store.start(r.job_id)
        tmp_store.complete(r.job_id)
        with pytest.raises(ValueError, match="Illegal transition"):
            tmp_store.start(r.job_id)

    def test_failed_is_terminal(self, tmp_store: JobStore):
        r = tmp_store.create(demo_name="d", demo_path="/p", cache_dir="/c")
        tmp_store.start(r.job_id)
        tmp_store.fail(r.job_id, "boom")
        with pytest.raises(ValueError, match="Illegal transition"):
            tmp_store.complete(r.job_id)

    def test_cannot_skip_created_to_completed(self, tmp_store: JobStore):
        r = tmp_store.create(demo_name="d", demo_path="/p", cache_dir="/c")
        with pytest.raises(ValueError, match="Illegal transition"):
            tmp_store.complete(r.job_id)

    def test_unknown_job_raises_keyerror(self, tmp_store: JobStore):
        with pytest.raises(KeyError, match="not found"):
            tmp_store.start("nonexist")


# ---------------------------------------------------------------------------
# Atomic writes & corruption recovery
# ---------------------------------------------------------------------------


class TestAtomicWrites:
    def test_no_temp_file_left_behind(self, tmp_store: JobStore):
        tmp_store.create(demo_name="d", demo_path="/p", cache_dir="/c")
        tmp_path = tmp_store._path.with_suffix(".json.tmp")
        assert not tmp_path.exists()

    def test_reload_preserves_all_fields(self, tmp_store: JobStore):
        tmp_store.create(
            demo_name="round.dem",
            demo_path="/demos/round.dem",
            cache_dir="/cache/abc",
            demo_info={"player_count": 8, "team_2": ["A"], "team_3": ["B"]},
        )
        store2 = JobStore(store_path=tmp_store._path)
        store2.load()
        jobs = store2.list_all()
        assert len(jobs) == 1
        j = jobs[0]
        assert j.demo_name == "round.dem"
        assert j.demo_path == "/demos/round.dem"
        assert j.cache_dir == "/cache/abc"
        assert j.player_count == 8


class TestCorruptionRecovery:
    def test_skips_corrupted_lines(self, tmp_store: JobStore, tmp_path: Path):
        # Write a file with one good line and one corrupted line
        good = json.dumps({
            "job_id": "abc12345",
            "demo_name": "good.dem",
            "demo_path": "/p",
            "cache_dir": "/c",
            "status": "completed",
            "created_at": "2026-01-01T00:00:00",
            "player_count": 0,
            "team_2_names": [],
            "team_3_names": [],
            "error": None,
        })
        tmp_store._path.write_text(
            good + "\n" + "this is not json\n" + good + "\n",
            encoding="utf-8",
        )
        tmp_store.load()
        # Both copies of the good record should load (same job_id → deduped by dict key)
        assert len(tmp_store.list_all()) == 1
        assert tmp_store.list_all()[0].demo_name == "good.dem"

    def test_entirely_corrupt_file_starts_fresh(self, tmp_store: JobStore):
        tmp_store._path.write_text("not json at all\n{{{ broken\n", encoding="utf-8")
        tmp_store.load()
        assert len(tmp_store.list_all()) == 0
        # Corrupt file should be renamed to a backup
        assert not tmp_store._path.exists() or tmp_store._path.read_text() == ""


# ---------------------------------------------------------------------------
# List ordering
# ---------------------------------------------------------------------------


class TestListAll:
    def test_newest_first(self, tmp_store: JobStore):
        # Create jobs with known created_at values by directly manipulating
        r1 = tmp_store.create(demo_name="first.dem", demo_path="/p1", cache_dir="/c1")
        r2 = tmp_store.create(demo_name="second.dem", demo_path="/p2", cache_dir="/c2")
        # Override created_at for deterministic ordering
        r1.created_at = "2026-01-01T00:00:00"
        r2.created_at = "2026-06-01T00:00:00"
        tmp_store._flush()
        tmp_store.load()
        jobs = tmp_store.list_all()
        assert jobs[0].demo_name == "second.dem"  # newer first
        assert jobs[1].demo_name == "first.dem"


# ---------------------------------------------------------------------------
# Migration from v0.1 cache dirs
# ---------------------------------------------------------------------------


class TestMigration:
    def test_imports_v0_1_cache_dir(self, tmp_store: JobStore, tmp_path: Path):
        # Simulate a v0.1 cache layout
        cache_root = tmp_path / "cache"
        job_dir = cache_root / "abc12345"
        job_dir.mkdir(parents=True)
        (job_dir / "test.dem").write_text("fake")
        progress = {
            "stage": "subtitles",
            "done": 7,
            "total": 7,
            "stage_desc": "字幕已生成",
            "error": None,
        }
        (job_dir / "progress.json").write_text(json.dumps(progress))

        # Patch the store so cache dir resolves relative to tmp_path
        store_path = tmp_path / "jobs.json"
        store = JobStore(store_path=store_path)

        # Override _migrate_v0_1_cache to use our tmp cache dir
        with patch.object(store, "_migrate_v0_1_cache", wraps=store._migrate_v0_1_cache) as mock_migrate:
            # We need to make the migration look at our tmp cache dir.
            # The default implementation looks at store._path.parent / "cache".
            # By placing our store at tmp_path/jobs.json, it'll look at tmp_path/cache.
            pass

        # Actually, the store._path is already tmp_path/jobs.json, so
        # _migrate_v0_1_cache looks at tmp_path/cache. Let's just call it.
        store._migrate_v0_1_cache()

        jobs = store.list_all()
        assert len(jobs) == 1
        assert jobs[0].job_id == "abc12345"
        assert jobs[0].status == JobStatus.COMPLETED
        assert jobs[0].demo_name == "test.dem"

    def test_migration_skips_already_tracked_jobs(self, tmp_store: JobStore, tmp_path: Path):
        # Create a v0.1 cache dir
        cache_root = tmp_path / "cache"
        job_dir = cache_root / "existing"
        job_dir.mkdir(parents=True)
        (job_dir / "test.dem").write_text("fake")
        (job_dir / "progress.json").write_text(
            json.dumps({"stage": "subtitles", "done": 7, "total": 7})
        )

        # Also register the same job_id manually
        tmp_store.create(demo_name="already.dem", demo_path="/p", cache_dir=str(job_dir))
        # Force the job_id to match
        for jid in list(tmp_store._jobs.keys()):
            record = tmp_store._jobs.pop(jid)
            record.job_id = "existing"
            tmp_store._jobs["existing"] = record
            break
        tmp_store._flush()

        # Now migrate — should skip "existing"
        tmp_store._migrate_v0_1_cache()
        jobs = tmp_store.list_all()
        assert len(jobs) == 1
        assert jobs[0].demo_name == "already.dem"  # not overwritten by migration

    def test_failed_job_from_corrupted_progress(self, tmp_store: JobStore, tmp_path: Path):
        cache_root = tmp_path / "cache"
        job_dir = cache_root / "badjob"
        job_dir.mkdir(parents=True)
        (job_dir / "progress.json").write_text("not valid json {{{")

        tmp_store._migrate_v0_1_cache()
        jobs = tmp_store.list_all()
        assert len(jobs) == 1
        assert jobs[0].status == JobStatus.FAILED
        assert "corrupted" in (jobs[0].error or "").lower()


# ---------------------------------------------------------------------------
# JobRecord serialization round-trip
# ---------------------------------------------------------------------------


class TestJobRecordSerialization:
    def test_round_trip(self):
        original = JobRecord(
            job_id="abc12345",
            demo_name="test.dem",
            demo_path="/tmp/test.dem",
            cache_dir="/tmp/cache/abc",
            status=JobStatus.COMPLETED,
            created_at="2026-06-07T12:00:00",
            player_count=10,
            team_2_names=["Alice", "Bob"],
            team_3_names=["Charlie"],
            error=None,
        )
        data = original.to_dict()
        restored = JobRecord.from_dict(data)
        assert restored.job_id == original.job_id
        assert restored.demo_name == original.demo_name
        assert restored.status == original.status
        assert restored.player_count == original.player_count
        assert restored.team_2_names == original.team_2_names

    def test_from_dict_handles_unknown_status(self):
        data = {
            "job_id": "x",
            "demo_name": "x",
            "demo_path": "/p",
            "cache_dir": "/c",
            "status": "garbage",
        }
        record = JobRecord.from_dict(data)
        assert record.status == JobStatus.CREATED  # fallback
