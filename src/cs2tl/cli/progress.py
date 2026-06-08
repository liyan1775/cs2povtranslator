"""Rich terminal progress bar for the 7-stage translation pipeline.

Provides ``PipelineProgress`` — a thin wrapper around ``rich.progress.Progress``
that exposes per-stage task helpers and a context manager for clean lifecycle
management.  Used by both the CLI translate command and the Web server.
"""

from __future__ import annotations

from rich.console import Console
from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    SpinnerColumn,
    TaskID,
    TextColumn,
    TimeElapsedColumn,
    TimeRemainingColumn,
)

_STAGE_LABELS = {
    "extract": "提取语音",
    "transcribe": "语音转写",
    "dictionary": "加载词典",
    "rounds": "识别回合",
    "players": "识别球员",
    "translate": "LLM 翻译",
    "subtitles": "生成字幕",
}


class PipelineProgress:
    """Rich progress bar controller for the 7-stage CS2 TL pipeline.

    Usage::

        with PipelineProgress(enabled=True) as pp:
            t1 = pp.task_model()
            # ... download model ...
            pp.stage_done(t1, "Whisper base loaded")

            t2 = pp.task_extract(10)
            pp.update(t2, advance=1)
            pp.stage_done(t2, "10 voice files")

    Output goes to ``stdout``; ``uvicorn`` logs should be directed to ``stderr``
    so they don't interfere with the progress display.
    """

    def __init__(
        self,
        enabled: bool = True,
        transient: bool = False,
    ) -> None:
        self._enabled = enabled
        self.console = Console()
        self._progress: Progress | None = None
        self._transient = transient  # hide completed tasks after completion

    # ---- context manager ----

    def __enter__(self) -> "PipelineProgress":
        if self._enabled:
            self._progress = Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                BarColumn(),
                MofNCompleteColumn(),
                TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
                TimeElapsedColumn(),
                TimeRemainingColumn(),
                console=self.console,
                transient=self._transient,
            )
            self._progress.start()
        return self

    def __exit__(self, *args: object) -> None:
        if self._progress is not None:
            self._progress.stop()

    # ---- task factory helpers ----

    def task_model(self, description: str = "下载 Whisper 模型...") -> TaskID:
        """Spinner-only task for indeterminate-length operations (e.g. model download)."""
        if self._progress is None:
            return TaskID(-1)
        return self._progress.add_task(description, total=None)

    def task_extract(self, count: int | None = None) -> TaskID:
        """Bar task with optional total (player voice extraction)."""
        if self._progress is None:
            return TaskID(-1)
        total = float(count) if count else None
        return self._progress.add_task("提取语音...", total=total)

    def task_transcribe(self, total: int) -> TaskID:
        """Bar + percentage task (Whisper transcription of N voice files)."""
        if self._progress is None:
            return TaskID(-1)
        return self._progress.add_task("语音转写...", total=float(total))

    def task_dictionary(self) -> TaskID:
        """Spinner task for dictionary loading."""
        if self._progress is None:
            return TaskID(-1)
        return self._progress.add_task("加载词典...", total=None)

    def task_rounds(self) -> TaskID:
        """Spinner task for round detection."""
        if self._progress is None:
            return TaskID(-1)
        return self._progress.add_task("识别回合...", total=None)

    def task_players(self, count: int) -> TaskID:
        """Bar task for player resolution."""
        if self._progress is None:
            return TaskID(-1)
        return self._progress.add_task("识别球员...", total=float(count))

    def task_translate(self, total: int) -> TaskID:
        """Bar + percentage task for LLM translation batches."""
        if self._progress is None:
            return TaskID(-1)
        return self._progress.add_task("LLM 翻译...", total=float(total))

    def task_subtitles(self, total: int) -> TaskID:
        """Bar task for SRT generation."""
        if self._progress is None:
            return TaskID(-1)
        return self._progress.add_task("生成字幕...", total=float(total))

    # ---- status helpers ----

    def update(
        self,
        task_id: TaskID,
        *,
        advance: float = 0,
        completed: float | None = None,
        description: str | None = None,
    ) -> None:
        """Update task progress. No-op when progress is disabled."""
        if self._progress is None or task_id == TaskID(-1):
            return
        kwargs: dict = {}
        if advance:
            kwargs["advance"] = advance
        if completed is not None:
            kwargs["completed"] = completed
        if description is not None:
            kwargs["description"] = description
        if kwargs:
            self._progress.update(task_id, **kwargs)

    def stage_done(self, task_id: TaskID, label: str = "") -> None:
        """Mark a stage as successfully completed."""
        if self._progress is None or task_id == TaskID(-1):
            return
        if label:
            self._progress.update(task_id, description=f"✅ {label}")
        self._progress.update(task_id, completed=self._progress.tasks[task_id].total or 1.0)
        self._progress.remove_task(task_id)

    def stage_failed(self, task_id: TaskID, error: str) -> None:
        """Mark a stage as failed with an error message."""
        if self._progress is None or task_id == TaskID(-1):
            return
        self._progress.update(task_id, description=f"❌ {error}")
        self._progress.stop_task(task_id)

    @property
    def enabled(self) -> bool:
        return self._enabled
