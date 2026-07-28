from __future__ import annotations

import sys
from pathlib import Path

EXPECTED_VERSION = "0.9.8"


def _is_relative_to(path: Path, base: Path) -> bool:
    try:
        path.relative_to(base)
        return True
    except ValueError:
        return False


def main() -> int:
    cwd = Path.cwd().resolve()
    local_src = cwd / "src"
    if local_src.exists():
        # Prefer the source tree next to the .bat even when the shell did not set PYTHONPATH.
        sys.path.insert(0, str(local_src))
    print(f"[启动自检] 当前运行目录: {cwd}")

    nested = cwd / "cs2pov_arch_project" / "Start_CS2_POV_Translator.bat"
    if nested.exists():
        print("[警告] 当前目录下面还存在 cs2pov_arch_project\\Start_CS2_POV_Translator.bat。")
        print("[警告] 这通常说明你把新版本解压进了旧目录，可能会双击到旧 .bat。")
        print("[建议] 请把 zip 解压到一个全新的 clean-room 目录，例如 cs2pov_arch_project_v0_9_8。")

    try:
        import cs2pov  # type: ignore
    except Exception as exc:  # pragma: no cover - visible startup diagnostic
        print(f"[错误] 无法导入 cs2pov: {type(exc).__name__}: {exc}")
        print("[建议] 请先运行 Install_CS2_POV_Translator.bat，或确认当前目录包含 src\\cs2pov。")
        return 2

    package_file = Path(cs2pov.__file__).resolve()
    version = getattr(cs2pov, "__version__", "unknown")
    expected_src_root = cwd / "src"
    print(f"[启动自检] cs2pov 版本: {version}")
    print(f"[启动自检] Python 加载源码: {package_file}")

    ok = True
    if version != EXPECTED_VERSION:
        print(f"[错误] 版本不一致：期望 {EXPECTED_VERSION}，实际 {version}。")
        ok = False
    if not _is_relative_to(package_file, expected_src_root.resolve()):
        print("[错误] Python 没有加载当前文件夹 src 里的源码，可能被旧 .venv / 旧安装污染。")
        print(f"[期望] {expected_src_root}")
        ok = False
    if not ok:
        print("[处理] 请解压到全新目录后重新运行 Install，再双击本目录下的 Start_CS2_POV_Translator.bat。")
        return 2

    print("[启动自检] 通过：正在进入 v0.9.8 极简菜单。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
