from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import traceback

from cs2pov.domain.models import StageName


@dataclass(slots=True)
class ProgressEvent:
    stage: StageName | str
    message: str
    level: str = "info"


class ProgressSink:
    def __init__(self, log_path: Path | None = None, verbose: bool = True):
        self.log_path = log_path
        self.verbose = verbose
        if self.log_path:
            self.log_path.parent.mkdir(parents=True, exist_ok=True)

    def emit(self, stage: StageName | str, message: str, level: str = "info") -> None:
        prefix = f"[{datetime.now().strftime('%H:%M:%S')}] [{level.upper()}] [{getattr(stage, 'value', stage)}]"
        line = f"{prefix} {message}"
        if self.verbose:
            print(line)
        if self.log_path:
            with self.log_path.open("a", encoding="utf-8") as f:
                f.write(line + "\n")

    def exception(self, stage: StageName | str, exc: BaseException, error_log: Path | None = None) -> None:
        self.emit(stage, f"失败：{exc}", "error")
        if error_log:
            with error_log.open("a", encoding="utf-8") as f:
                f.write(f"\n[{datetime.now().isoformat()}] stage={getattr(stage, 'value', stage)}\n")
                f.write("".join(traceback.format_exception(exc)))
