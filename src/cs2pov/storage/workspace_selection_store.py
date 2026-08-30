import json
import os
import sys
import tempfile
from pathlib import Path

from cs2pov.application.workspace import WorkspaceSelection


class WorkspaceSelectionStoreError(Exception):
    def __init__(self, code, message):
        self.code, self.message_zh, self.suggestion_zh = code, message, "请检查状态文件后重试。"
        super().__init__(message)


def default_state_file(*, environ=None, home=None, platform=None):
    env = os.environ if environ is None else environ
    platform = sys.platform if platform is None else platform
    explicit = env.get("CS2POV_STATE_FILE")
    if explicit is not None:
        if not explicit.strip() or not Path(explicit).is_absolute():
            raise WorkspaceSelectionStoreError("selection_state_location_unavailable", "状态文件路径必须是非空绝对路径。")
        return Path(explicit).absolute()
    if platform.startswith("win"):
        base = env.get("LOCALAPPDATA")
        if not base or not Path(base).is_absolute():
            raise WorkspaceSelectionStoreError("selection_state_location_unavailable", "缺少有效的 LOCALAPPDATA 状态目录。")
        return (Path(base) / "CS2POV" / "state.json").absolute()
    base = env.get("XDG_STATE_HOME")
    if base:
        if not Path(base).is_absolute():
            raise WorkspaceSelectionStoreError("selection_state_location_unavailable", "XDG_STATE_HOME 必须是绝对路径。")
        return (Path(base) / "cs2pov" / "state.json").absolute()
    if home is None:
        home = Path.home()
    return (Path(home) / ".local" / "state" / "cs2pov" / "state.json").absolute()


class JsonWorkspaceSelectionStore:
    def __init__(self, state_file):
        if not isinstance(state_file, (str, Path)) or not str(state_file).strip() or not Path(state_file).is_absolute():
            raise WorkspaceSelectionStoreError("selection_state_location_unavailable", "状态文件路径必须是非空绝对路径。")
        self.state_file = Path(state_file).absolute()

    def load(self):
        path = self.state_file
        if not path.exists() and not path.is_symlink():
            return None
        if path.is_symlink() or not path.is_file():
            raise WorkspaceSelectionStoreError("selection_state_invalid", "状态文件必须是普通文件。")
        try:
            raw = path.read_text(encoding="utf-8")
        except OSError as exc:
            raise WorkspaceSelectionStoreError("selection_state_read_failed", "无法读取工作区选择状态。") from exc
        try:
            return WorkspaceSelection.from_dict(json.loads(raw))
        except Exception as exc:
            raise WorkspaceSelectionStoreError("selection_state_invalid", "状态文件内容无效，请重新选择工作区。") from exc

    def save(self, selection):
        if not isinstance(selection, WorkspaceSelection):
            raise WorkspaceSelectionStoreError("selection_state_write_failed", "只能保存有效的工作区选择。")
        temporary = None
        try:
            self.state_file.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(dir=self.state_file.parent, prefix=".state-", suffix=".tmp", mode="w", encoding="utf-8", delete=False) as stream:
                temporary = Path(stream.name)
                json.dump(selection.to_dict(), stream, ensure_ascii=False, indent=2)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.state_file)
        except Exception as exc:
            raise WorkspaceSelectionStoreError("selection_state_write_failed", "无法保存工作区选择，请重试。") from exc
        finally:
            if temporary is not None:
                try:
                    temporary.unlink(missing_ok=True)
                except OSError:
                    pass

    def forget(self):
        if not self.state_file.exists() and not self.state_file.is_symlink():
            return False
        try:
            self.state_file.unlink()
            return True
        except Exception as exc:
            raise WorkspaceSelectionStoreError("selection_state_forget_failed", "无法忘记工作区选择，请重试。") from exc
