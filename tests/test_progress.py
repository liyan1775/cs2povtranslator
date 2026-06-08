"""Tests for PipelineProgress (Rich terminal progress bars)."""

from __future__ import annotations

from rich.progress import TaskID

from cs2tl.cli.progress import PipelineProgress


class TestPipelineProgress:
    """Tests for the PipelineProgress context manager and task helpers."""

    def test_context_manager_enabled(self):
        """Context manager enters/exits cleanly when enabled."""
        with PipelineProgress(enabled=True) as pp:
            assert pp.enabled is True
            assert pp._progress is not None

    def test_context_manager_disabled(self):
        """When disabled, _progress is None and all task methods return TaskID(-1)."""
        with PipelineProgress(enabled=False) as pp:
            assert pp._progress is None
            tid = pp.task_model()
            assert tid == TaskID(-1)

    def test_task_model_returns_spinner(self):
        """task_model creates a task with total=None (spinner)."""
        with PipelineProgress(enabled=True) as pp:
            tid = pp.task_model("Load model...")
            assert tid != TaskID(-1)
            # In Rich, total=None means spinner mode
            task = pp._progress.tasks[tid]
            assert task.total is None

    def test_task_transcribe_is_bar(self):
        """task_transcribe creates a task with a known total."""
        with PipelineProgress(enabled=True) as pp:
            tid = pp.task_transcribe(10)
            assert tid != TaskID(-1)
            task = pp._progress.tasks[tid]
            assert task.total == 10.0

    def test_stage_done_removes_task(self):
        """stage_done marks the task complete and removes it."""
        with PipelineProgress(enabled=True) as pp:
            tid = pp.task_extract(5)
            initial_count = len(pp._progress.tasks)
            pp.stage_done(tid, "Done!")
            # After removal, task is no longer in the task list
            assert len(pp._progress.tasks) == initial_count - 1

    def test_stage_failed_stops_task(self):
        """stage_failed marks the task with an error description."""
        with PipelineProgress(enabled=True) as pp:
            tid = pp.task_translate(20)
            pp.stage_failed(tid, "API error")
            task = pp._progress.tasks[tid]
            # The task description should include the error marker
            assert "API error" in task.description

    def test_update_noop_when_disabled(self):
        """update() is a no-op when progress is disabled."""
        with PipelineProgress(enabled=False) as pp:
            pp.update(TaskID(-1), advance=10.0, description="test")
            # Should not raise

    def test_update_with_advance(self):
        """update() advances the task progress."""
        with PipelineProgress(enabled=True) as pp:
            tid = pp.task_transcribe(100)
            pp.update(tid, advance=50.0)
            task = pp._progress.tasks[tid]
            assert task.completed >= 50.0

    def test_task_subtitles_total(self):
        """task_subtitles creates a task for 2 team SRT files."""
        with PipelineProgress(enabled=True) as pp:
            tid = pp.task_subtitles(2)
            task = pp._progress.tasks[tid]
            assert task.total == 2.0
