from __future__ import annotations

import json
import os
import shutil
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any

from cs2pov.storage.config_store import load_config, save_config
from cs2pov.application.workspace_runtime import WorkspaceRuntime


@dataclass(frozen=True, slots=True)
class TranscriptionProfile:
    id: str
    label: str
    model: str
    device: str
    compute_type: str
    description: str
    audience: str


TRANSCRIPTION_PROFILES: dict[str, TranscriptionProfile] = {
    "fast": TranscriptionProfile(
        "fast", "快速预览", "tiny", "cpu", "int8",
        "最快，适合确认 demo 能跑通和检查流程。", "普通 CPU / 首次测试",
    ),
    "balanced": TranscriptionProfile(
        "balanced", "平衡质量", "base", "cpu", "int8",
        "速度和质量比较平衡，适合作为保守默认。", "普通 CPU",
    ),
    "quality": TranscriptionProfile(
        "quality", "高质量 CPU", "small", "cpu", "int8",
        "更适合认真剪视频。用户实测办公本 CPU 完整 demo 约 18 分钟。", "办公本 CPU / 剪辑推荐",
    ),
    "medium_cpu": TranscriptionProfile(
        "medium_cpu", "实验高质量 CPU", "medium", "cpu", "int8",
        "质量可能更好，但 CPU 耗时明显增加，建议先用 3 回合 benchmark。", "愿意等待更久的 CPU 用户",
    ),
    "cuda_quality": TranscriptionProfile(
        "cuda_quality", "CUDA 高质量", "small", "cuda", "float16",
        "适合 NVIDIA 显卡用户；需要正确安装 CUDA/cuDNN 相关依赖。", "NVIDIA CUDA 用户",
    ),
}


@dataclass(frozen=True, slots=True)
class ModelCatalogItem:
    name: str
    approx_size: str
    recommended_for: str
    notes: str


MODEL_CATALOG: tuple[ModelCatalogItem, ...] = (
    ModelCatalogItem("tiny", "约 100 MB 级", "快速预览", "最快，但报点/口音识别质量一般。"),
    ModelCatalogItem("base", "约 200~300 MB 级", "平衡质量", "普通 CPU 用户的稳妥起点。"),
    ModelCatalogItem("small", "约 1 GB 级", "高质量 CPU", "推荐剪视频使用；质量通常明显优于 tiny/base。"),
    ModelCatalogItem("medium", "约 3 GB 级", "实验高质量", "CPU 可试，但建议先跑短 benchmark。"),
    ModelCatalogItem("large-v3", "约 5~6 GB 级", "高质量 GPU", "不建议办公本 CPU 日常默认使用。"),
    ModelCatalogItem("large-v3-turbo", "约 1~2 GB 级", "高级实验", "更快的 large-v3 派生模型；具体可用性取决于本地 faster-whisper 支持和缓存仓库。"),
)


def profile_to_config(profile_id: str) -> dict[str, str]:
    profile = TRANSCRIPTION_PROFILES.get((profile_id or "").strip())
    if not profile:
        raise ValueError(f"未知转录质量档位：{profile_id}")
    return {
        "transcription_profile": profile.id,
        "whisper_model": profile.model,
        "whisper_device": profile.device,
        "whisper_compute_type": profile.compute_type,
    }


def apply_profile_to_values(
    profile_id: str | None,
    *,
    whisper_model: str | None = None,
    whisper_device: str | None = None,
    whisper_compute_type: str | None = None,
) -> dict[str, str | None]:
    """Resolve final Whisper values from a profile plus explicit overrides."""
    if profile_id:
        base: dict[str, str | None] = profile_to_config(profile_id)
    else:
        base = {"transcription_profile": None, "whisper_model": None, "whisper_device": None, "whisper_compute_type": None}
    if whisper_model is not None:
        base["whisper_model"] = whisper_model
    if whisper_device is not None:
        base["whisper_device"] = whisper_device
    if whisper_compute_type is not None:
        base["whisper_compute_type"] = whisper_compute_type
    return base


def configured_cache_dir() -> Path | None:
    cfg = load_config()
    value = cfg.get("whisper_cache_dir")
    if value:
        return Path(str(value)).expanduser()
    return None


def default_hf_cache_dir() -> Path:
    # Mirrors the common Hugging Face cache convention.  Users can override it
    # with HF_HOME / HF_HUB_CACHE or this tool's project-level whisper_cache_dir.
    hf_hub_cache = os.environ.get("HF_HUB_CACHE")
    if hf_hub_cache:
        return Path(hf_hub_cache).expanduser()
    hf_home = os.environ.get("HF_HOME")
    if hf_home:
        return Path(hf_home).expanduser() / "hub"
    return Path.home() / ".cache" / "huggingface" / "hub"


def cache_candidates(runtime: WorkspaceRuntime | None = None) -> list[Path]:
    if runtime is None:
        return []
    return [runtime.paths.whisper_cache_dir, runtime.paths.huggingface_hub_cache_dir]


def _hub_dir_from_cache_root(path: Path) -> Path:
    text = str(path).replace("\\", "/").rstrip("/")
    if text.endswith("/hub"):
        return path
    return path / "hub"


def format_bytes(num: int) -> str:
    value = float(num)
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if value < 1024 or unit == "TB":
            if unit == "B":
                return f"{int(value)} {unit}"
            return f"{value:.1f} {unit}"
        value /= 1024
    return f"{num} B"


def directory_size(path: Path) -> int:
    total = 0
    if not path.exists():
        return 0
    for item in path.rglob("*"):
        try:
            if item.is_file():
                total += item.stat().st_size
        except OSError:
            continue
    return total


def scan_current_models(runtime: WorkspaceRuntime) -> list[dict[str, Any]]:
    models: list[dict[str, Any]] = []
    for cache in cache_candidates(runtime):
        if not cache.exists():
            continue
        for item in sorted(cache.glob("models--*--*")):
            if not item.is_dir():
                continue
            name = _display_model_name_from_cache_dir(item.name)
            if not _looks_like_whisper_model(name, item.name):
                continue
            size = directory_size(item)
            models.append({
                "name": name,
                "cache_dir": str(cache),
                "path": str(item),
                "size_bytes": size,
                "size_human": format_bytes(size),
                "status": "可用" if size > 0 else "目录存在但大小为 0，请检查下载是否完整",
                "managed": True,
                "source": "workspace",
            })
    unique: dict[str, dict[str, Any]] = {}
    for row in models:
        unique.setdefault(row["name"], row)
    return list(unique.values())


def scan_legacy_candidates(*, configured_cache=None, hf_home=None, hf_hub_cache=None, default_hf=None, runtime=None):
    managed = {p.resolve() for p in cache_candidates(runtime)} if runtime else set()
    rows, seen = [], set()
    sources = [("configured", configured_cache), ("HF_HOME", hf_home), ("HF_HUB_CACHE", hf_hub_cache), ("platform_default", default_hf)]
    for source, value in sources:
        if value is None:
            continue
        roots = [Path(value).expanduser()]
        if source == "configured":
            roots.append(roots[0] / "hub")
        elif source == "HF_HOME":
            roots = [roots[0] / "hub"]
        for path in roots:
            key = path.resolve()
            if key in seen or key in managed or (runtime and runtime.root in key.parents) or not path.is_dir():
                continue
            seen.add(key)
            rows.append({"path": str(key), "source": source, "managed": False})
    return rows


def scan_legacy_models(candidates):
    rows = []
    for candidate in candidates:
        root = Path(candidate["path"])
        for item in sorted(root.glob("models--*--*")):
            if item.is_dir():
                name = _display_model_name_from_cache_dir(item.name)
                if _looks_like_whisper_model(name, item.name):
                    rows.append({"name": name, "path": str(item), "cache_dir": str(root), "managed": False, "source": candidate["source"], "size_bytes": directory_size(item), "size_human": format_bytes(directory_size(item))})
    return rows


def scan_downloaded_models(runtime: WorkspaceRuntime | None = None) -> list[dict[str, Any]]:
    return scan_current_models(runtime) if runtime else []


def _display_model_name_from_cache_dir(dirname: str) -> str:
    # Hugging Face cache dirs look like models--Systran--faster-whisper-small.
    parts = dirname.split("--")
    repo = parts[-1] if parts else dirname
    if repo.startswith("faster-whisper-"):
        return repo[len("faster-whisper-"):]
    if repo.startswith("whisper-"):
        return repo[len("whisper-"):]
    return repo


def _looks_like_whisper_model(display_name: str, dirname: str) -> bool:
    text = (display_name + " " + dirname).lower()
    return "whisper" in text or display_name in {item.name for item in MODEL_CATALOG}


def build_models_info(runtime: WorkspaceRuntime) -> dict[str, Any]:
    cfg = load_config()
    return {
        "workspace_cache": {"whisper": str(runtime.paths.whisper_cache_dir), "huggingface_hub": str(runtime.paths.huggingface_hub_cache_dir)},
        "deprecated_config": {"present": bool(cfg.get("whisper_cache_dir")), "deprecated": bool(cfg.get("whisper_cache_dir"))},
    "legacy_candidates": scan_legacy_candidates(configured_cache=Path(cfg["whisper_cache_dir"]) if cfg.get("whisper_cache_dir") else None, hf_home=Path(os.environ["HF_HOME"]) if os.environ.get("HF_HOME") else None, hf_hub_cache=Path(os.environ["HF_HUB_CACHE"]) if os.environ.get("HF_HUB_CACHE") else None, default_hf=Path.home() / ".cache" / "huggingface" / "hub", runtime=runtime),
        "current_defaults": {
            "transcription_profile": cfg.get("transcription_profile") or "balanced",
            "whisper_model": cfg.get("whisper_model"),
            "whisper_device": cfg.get("whisper_device"),
            "whisper_compute_type": cfg.get("whisper_compute_type"),
        },
    }


def print_models_info(runtime: WorkspaceRuntime, json_mode: bool = False) -> int:
    payload = build_models_info(runtime)
    if json_mode:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0
    print("Whisper 模型缓存信息")
    print("=" * 72)
    print(f"工作区缓存根目录: {payload['workspace_cache']['whisper']}")
    print("受管缓存目录：")
    for path in payload["workspace_cache"].values():
        print(f"  - {path}")
    print(f"旧配置缓存路径：{'存在（已弃用）' if payload['deprecated_config']['present'] else '未设置'}")
    for row in payload["legacy_candidates"]:
        print(f"  旧缓存候选：{row['path']}")
    d = payload["current_defaults"]
    print("当前转录默认值：")
    print(f"  profile={d['transcription_profile']} model={d['whisper_model']} device={d['whisper_device']} compute_type={d['whisper_compute_type']}")
    print("\n提示：模型缓存跟随当前工作区；旧缓存仅提供只读迁移提示，不会自动移动。")
    return 0


def print_models_list(runtime: WorkspaceRuntime, json_mode: bool = False) -> int:
    models = scan_current_models(runtime)
    cfg = load_config()
    candidates = scan_legacy_candidates(configured_cache=Path(cfg["whisper_cache_dir"]) if cfg.get("whisper_cache_dir") else None, hf_home=Path(os.environ["HF_HOME"]) if os.environ.get("HF_HOME") else None, hf_hub_cache=Path(os.environ["HF_HUB_CACHE"]) if os.environ.get("HF_HUB_CACHE") else None, default_hf=Path.home() / ".cache" / "huggingface" / "hub", runtime=runtime)
    payload = {"model_count": len(models), "models": models, "legacy_candidates": candidates, "legacy_models": scan_legacy_models(candidates)}
    if json_mode:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0
    print("已下载/已缓存的 Whisper 模型")
    print("=" * 72)
    if not models:
        print("没有在候选缓存目录中发现 faster-whisper/whisper 模型。")
        print("可先运行 cs2pov models recommend 查看常用模型大小，再在向导或 run 中选择模型触发下载。")
        return 0
    for item in models:
        print(f"- {item['name']:<16} {item['size_human']:<10} {item['status']}")
        print(f"  path: {item['path']}")
    return 0


def print_models_recommend(json_mode: bool = False) -> int:
    payload = {
        "profiles": [asdict(p) for p in TRANSCRIPTION_PROFILES.values()],
        "catalog": [asdict(item) for item in MODEL_CATALOG],
        "notes": [
            "实际占用以本机 cs2pov models list 扫描结果为准。",
            "办公本 CPU 推荐先用 quality/small；CUDA 用户可再试 cuda_quality。",
            "medium/large 适合先用 benchmark-asr 跑少量回合再决定是否下载。",
        ],
    }
    if json_mode:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0
    print("Whisper 模型与转录质量档位建议")
    print("=" * 72)
    print("质量档位：")
    for p in TRANSCRIPTION_PROFILES.values():
        print(f"- {p.id:<12} {p.label:<12} model={p.model:<8} device={p.device:<4} compute={p.compute_type:<12} {p.description}")
    print("\n常用模型大小（近似）：")
    for item in MODEL_CATALOG:
        print(f"- {item.name:<16} {item.approx_size:<14} {item.recommended_for:<12} {item.notes}")
    print("\n建议：办公本剪视频优先试 quality/small；medium 请先用 cs2pov benchmark-asr 跑 3 回合对比。")
    return 0


def set_cache_dir(path: Path) -> Path:
    raise RuntimeError("模型缓存目录设置入口已弃用；缓存跟随当前工作区。")


def test_model_load(model: str, device: str, compute_type: str, cache_dir: str | None = None, local_only: bool = False) -> dict[str, Any]:
    if not cache_dir:
        return {"ok": False, "code": "model_cache_required", "error": "必须显式提供工作区模型缓存路径。"}
    try:
        from faster_whisper import WhisperModel  # type: ignore
    except Exception as exc:  # pragma: no cover - optional dependency
        return {"ok": False, "error_type": type(exc).__name__, "error": "缺少 faster-whisper。请运行 pip install -e .[all]"}
    kwargs: dict[str, Any] = {"device": device, "compute_type": compute_type}
    effective_cache = str(Path(cache_dir).expanduser())
    kwargs["download_root"] = effective_cache
    if local_only:
        kwargs["local_files_only"] = True
    try:
        WhisperModel(model, **kwargs)
        return {"ok": True, "model": model, "device": device, "compute_type": compute_type, "cache_dir": effective_cache}
    except Exception as exc:  # pragma: no cover - external model/env dependent
        return {"ok": False, "code": "model_load_failed", "model": model, "device": device, "compute_type": compute_type, "cache_dir": effective_cache, "error_type": type(exc).__name__, "error": str(exc)}


def remove_cache_dir(path: Path) -> int:
    # Intentionally not wired into CLI.  Model deletion is a risky destructive
    # operation and should be added only after more user testing.
    if path.exists():
        shutil.rmtree(path)
        return 1
    return 0
