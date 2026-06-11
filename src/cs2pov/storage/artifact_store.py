from __future__ import annotations

from pathlib import Path
from datetime import datetime
import re


def safe_name(text: str, max_len: int = 80) -> str:
    cleaned = re.sub(r"[^\w.\-]+", "_", text, flags=re.UNICODE).strip("_")
    return (cleaned or "unnamed")[:max_len]


class ArtifactStore:
    def __init__(self, job_dir: Path):
        self.job_dir = Path(job_dir)
        self.input_dir = self.job_dir / "input"
        self.artifacts_dir = self.job_dir / "artifacts"
        self.voice_dir = self.artifacts_dir / "voice"
        self.final_dir = self.job_dir / "final"
        self.review_dir = self.job_dir / "review"
        self.debug_dir = self.job_dir / "debug"
        self.temp_audio_dir = self.artifacts_dir / "temp_audio"

    @classmethod
    def create(cls, output_root: Path, map_name: str | None = None, job_id: str | None = None) -> "ArtifactStore":
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        suffix = safe_name(map_name or "unknown_map")
        name = job_id or f"{stamp}_{suffix}"
        store = cls(Path(output_root) / name)
        store.ensure_dirs()
        return store

    def ensure_dirs(self) -> None:
        for p in [self.input_dir, self.artifacts_dir, self.voice_dir, self.temp_audio_dir, self.final_dir, self.review_dir, self.debug_dir]:
            p.mkdir(parents=True, exist_ok=True)

    def rename_suffix(self, suffix: str) -> "ArtifactStore":
        """Rename an auto-created job directory from *_unknown_map to *_<map>.

        The store is intentionally immutable-ish: this method moves the existing
        directory and returns a fresh ArtifactStore pointing at the new path.
        Custom job ids are not changed by callers.
        """
        suffix = safe_name(suffix or "unknown_map")
        old_name = self.job_dir.name
        if old_name.endswith(f"_{suffix}"):
            return self
        if old_name.endswith("_unknown_map"):
            new_name = old_name[: -len("unknown_map")] + suffix
        else:
            new_name = f"{old_name}_{suffix}"
        target = self.job_dir.with_name(new_name)
        if target.exists():
            base = target
            idx = 2
            while target.exists():
                target = base.with_name(f"{base.name}_{idx}")
                idx += 1
        self.job_dir.rename(target)
        store = ArtifactStore(target)
        store.ensure_dirs()
        return store

    @property
    def manifest_path(self) -> Path:
        return self.job_dir / "manifest.json"

    @property
    def progress_log_path(self) -> Path:
        return self.job_dir / "progress.log"

    @property
    def error_log_path(self) -> Path:
        return self.job_dir / "errors.log"

    @property
    def demo_info_path(self) -> Path:
        return self.artifacts_dir / "demo_info.json"

    @property
    def voice_manifest_path(self) -> Path:
        return self.voice_dir / "manifest.json"

    @property
    def player_stats_path(self) -> Path:
        return self.artifacts_dir / "player_stats.json"

    @property
    def player_aliases_path(self) -> Path:
        return self.artifacts_dir / "player_aliases.json"

    @property
    def voice_activity_path(self) -> Path:
        return self.artifacts_dir / "voice_activity.jsonl"

    @property
    def rounds_path(self) -> Path:
        return self.artifacts_dir / "rounds.json"

    @property
    def raw_rounds_path(self) -> Path:
        return self.artifacts_dir / "rounds_raw.json"

    @property
    def transcripts_path(self) -> Path:
        return self.artifacts_dir / "transcript_segments.jsonl"

    @property
    def round_contexts_path(self) -> Path:
        return self.artifacts_dir / "round_contexts.jsonl"

    @property
    def transcription_coverage_path(self) -> Path:
        return self.artifacts_dir / "transcription_coverage.json"

    @property
    def translations_path(self) -> Path:
        return self.artifacts_dir / "translated_segments.jsonl"

    @property
    def glossary_used_path(self) -> Path:
        return self.artifacts_dir / "glossary_used.json"

    @property
    def glossary_warnings_path(self) -> Path:
        return self.artifacts_dir / "glossary_warnings.json"


def directory_size_bytes(path: Path) -> int:
    if not path.exists():
        return 0
    if path.is_file():
        return path.stat().st_size
    total = 0
    for child in path.rglob("*"):
        if child.is_file():
            total += child.stat().st_size
    return total
