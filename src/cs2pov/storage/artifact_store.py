from __future__ import annotations

from pathlib import Path
from datetime import datetime
from contextlib import contextmanager
import re
import os
import time

from cs2pov.application.job_runtime import JobRuntimeError


def safe_name(text: str, max_len: int = 80) -> str:
    cleaned = re.sub(r"[^\w.\-]+", "_", text, flags=re.UNICODE).strip("_")
    cleaned = cleaned.rstrip(". ")[:max_len].rstrip(". ")
    return cleaned or "unnamed"


class ArtifactStore:
    def __init__(
        self,
        job_dir: Path,
        *,
        audio_cache_root: Path | None = None,
        keep_temp_audio: bool = False,
    ):
        self.job_dir = Path(job_dir)
        self.input_dir = self.job_dir / "input"
        self.artifacts_dir = self.job_dir / "artifacts"
        self.voice_dir = self.artifacts_dir / "voice"
        self.final_dir = self.job_dir / "final"
        self.review_dir = self.job_dir / "review"
        self.debug_dir = self.job_dir / "debug"
        self._audio_cache_root = Path(audio_cache_root) if audio_cache_root is not None else None
        self._keep_temp_audio = bool(keep_temp_audio)
        self.temp_audio_dir = self._temp_audio_path(self.job_dir)

    def _temp_audio_path(self, job_dir: Path) -> Path:
        if self._keep_temp_audio:
            return job_dir / "debug" / "temp_audio"
        if self._audio_cache_root is not None:
            return self._audio_cache_root / job_dir.name
        # A store loaded from an old Job keeps its historical layout.
        return job_dir / "artifacts" / "temp_audio"

    @classmethod
    def create(
        cls,
        output_root: Path,
        map_name: str | None = None,
        job_id: str | None = None,
        *,
        audio_cache_root: Path | None = None,
        keep_temp_audio: bool = False,
    ) -> "ArtifactStore":
        if job_id is not None:
            _validate_job_id(job_id)
        root = _normalize_output_root(output_root)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        suffix = safe_name(map_name or "unknown_map")
        name = job_id or f"{stamp}_{suffix}"
        index = 1
        while True:
            candidate_name = name if index == 1 else f"{name}_{index}"
            candidate = root / candidate_name
            _reject_escaped_candidate(candidate, root)
            collided = False
            with _rename_claim(root, candidate_name):
                try:
                    # The candidate claim serializes create and rename before
                    # either operation can observe/create the Job directory.
                    candidate.mkdir(parents=True, exist_ok=False)
                except FileExistsError:
                    collided = True
                else:
                    store = cls(candidate, audio_cache_root=audio_cache_root, keep_temp_audio=keep_temp_audio)
                    try:
                        store.ensure_dirs()
                    except Exception:
                        import shutil
                        shutil.rmtree(candidate, ignore_errors=True)
                        raise
            if collided:
                index += 1
                continue
            return store

    def ensure_dirs(self) -> None:
        paths = [self.input_dir, self.artifacts_dir, self.voice_dir, self.final_dir, self.review_dir, self.debug_dir]
        if self._keep_temp_audio or self._audio_cache_root is None:
            paths.append(self.temp_audio_dir)
        for p in paths:
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
        base = target
        idx = 2
        old_temp_audio = self.temp_audio_dir
        external_audio_cache = self._audio_cache_root is not None and not self._keep_temp_audio
        while True:
            target_temp_audio: Path | None = None
            collided = False
            renamed = False
            with _rename_claim(self.job_dir.parent, target.name):
                _reject_escaped_candidate(target, self.job_dir.parent.resolve())
                if target.exists() or target.is_symlink():
                    collided = True
                else:
                    target_temp_audio = self._temp_audio_path(target)
                    if external_audio_cache and old_temp_audio.exists():
                        # Audio cache names share the same candidate-level
                        # claim policy as Job directories, but live under the
                        # workspace cache root rather than inside the Job.
                        with _rename_claim(self._audio_cache_root, target.name):
                            if target_temp_audio.exists():
                                collided = True
                            else:
                                try:
                                    old_temp_audio.rename(target_temp_audio)
                                except FileExistsError:
                                    collided = True
                                else:
                                    try:
                                        self.job_dir.rename(target)
                                    except FileExistsError:
                                        try:
                                            target_temp_audio.rename(old_temp_audio)
                                        except Exception as rollback_error:
                                            raise JobRuntimeError(
                                                "job_rename_rollback_failed",
                                                "Job 重命名失败，临时音频回滚也失败。",
                                                "请保留旧/新 cache/audio 目录，按日志诊断后再处理。",
                                            ) from rollback_error
                                        collided = True
                                    except Exception:
                                        try:
                                            target_temp_audio.rename(old_temp_audio)
                                        except Exception as rollback_error:
                                            raise JobRuntimeError(
                                                "job_rename_rollback_failed",
                                                "Job 重命名失败，临时音频回滚也失败。",
                                                "请保留旧/新 cache/audio 目录，按日志诊断后再处理。",
                                            ) from rollback_error
                                        raise
                                    else:
                                        renamed = True
                    else:
                        try:
                            self.job_dir.rename(target)
                        except FileExistsError:
                            collided = True
                        else:
                            renamed = True
            if renamed:
                break
            target = base.with_name(f"{base.name}_{idx}")
            idx += 1
        store = ArtifactStore(target, audio_cache_root=self._audio_cache_root, keep_temp_audio=self._keep_temp_audio)
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


_WINDOWS_RESERVED_NAMES = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}


def _validate_job_id(job_id: str) -> None:
    if not isinstance(job_id, str) or not job_id or job_id != job_id.strip():
        raise JobRuntimeError("job_id_invalid", "Job ID 不能为空且不能包含首尾空白。", "请使用字母、数字、中文、连字符或下划线。")
    if len(job_id) > 80:
        raise JobRuntimeError("job_id_invalid", "Job ID 过长，无法作为跨平台目录名。", "请将 Job ID 缩短到 80 个字符以内。")
    if job_id in {".", ".."} or "/" in job_id or "\\" in job_id or "\x00" in job_id:
        raise JobRuntimeError("job_id_invalid", "Job ID 不能是路径或包含目录分隔符。", "请提供单段 Job ID，不要使用绝对路径或 ..。")
    # pathlib on POSIX does not recognize a Windows drive, so check it explicitly.
    if len(job_id) >= 2 and job_id[1] == ":" and job_id[0].isalpha():
        raise JobRuntimeError("job_id_invalid", "Job ID 不能包含盘符。", "请提供单段 Job ID，不要使用 Windows 路径。")
    if any(ord(char) < 32 or char in '<>:"|?*' for char in job_id):
        raise JobRuntimeError("job_id_invalid", "Job ID 含有跨平台不支持的字符。", "请移除控制字符和 Windows 非法字符后重试。")
    if job_id[-1] in ". ":
        raise JobRuntimeError("job_id_invalid", "Job ID 不能以点或空格结尾。", "请移除尾随点或空格后重试。")
    stem = job_id.rstrip(" .").split(".", 1)[0].upper()
    if stem in _WINDOWS_RESERVED_NAMES:
        raise JobRuntimeError("job_id_invalid", "Job ID 使用了 Windows 保留设备名。", "请改用普通的可读 Job ID。")


def _normalize_output_root(output_root: Path) -> Path:
    try:
        root = Path(output_root).expanduser().resolve()
    except (OSError, RuntimeError, TypeError, ValueError) as exc:
        raise JobRuntimeError("job_path_escape", "Job 输出根目录路径无效。", "请提供可访问的目录后重试。") from exc
    try:
        root.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise JobRuntimeError("job_path_escape", "Job 输出根目录不可用。", "请检查目录权限后重试。") from exc
    return root


def _reject_escaped_candidate(candidate: Path, root: Path) -> None:
    try:
        candidate.resolve(strict=False).relative_to(root.resolve())
    except (OSError, RuntimeError, ValueError) as exc:
        raise JobRuntimeError("job_path_escape", "Job 路径超出输出根目录。", "请改用工作区 jobs 或明确的输出目录。") from exc


@contextmanager
def _rename_claim(parent: Path, candidate_name: str):
    """Acquire a cooperative, observable claim for one candidate name.

    ``rename`` has no portable no-replace mode: on POSIX it can replace an
    existing empty directory.  A mkdir-based claim serializes all cooperating
    ArtifactStore renames, while the stale claim error makes a crash residue
    visible instead of silently deleting or taking it over.
    """
    claim = parent / f".{candidate_name}.job.claim"
    deadline = time.monotonic() + 10.0
    while True:
        try:
            claim.mkdir()
            owner = claim / "owner"
            try:
                owner.write_text(f"pid={os.getpid()}\n", encoding="ascii")
            except OSError as exc:
                try:
                    claim.rmdir()
                except OSError:
                    pass
                raise JobRuntimeError("job_path_claim_failed", "无法记录 Job claim。", "请检查 Job 根目录权限后重试。") from exc
            break
        except FileExistsError:
            try:
                age = time.time() - claim.stat().st_mtime
            except OSError as exc:
                raise JobRuntimeError("job_path_claim_busy", "Job 重命名正在被其他任务占用。", "请稍后重试。") from exc
            if age > 30.0:
                raise JobRuntimeError(
                    "job_path_claim_stale",
                    f"检测到未清理的 Job 重命名 claim：{claim.name}。",
                    "请确认没有运行中的任务后手动移除该 claim，再重试。",
                )
            if time.monotonic() >= deadline:
                raise JobRuntimeError("job_path_claim_busy", "Job 重命名正在被其他任务占用。", "请稍后重试。")
            time.sleep(0.01)
        except OSError as exc:
            raise JobRuntimeError("job_path_claim_failed", "无法取得 Job 重命名 claim。", "请检查 Job 根目录权限后重试。") from exc
    try:
        yield
    finally:
        try:
            (claim / "owner").unlink()
            claim.rmdir()
        except OSError:
            # A crash leaves the claim observable for the next invocation;
            # cleanup failures must not cause an unsafe fallback rename.
            pass
