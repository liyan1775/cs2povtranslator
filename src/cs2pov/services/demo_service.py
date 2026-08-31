from __future__ import annotations

from pathlib import Path

from cs2pov.adapters.demoparser_adapter import DemoparserAdapter
from cs2pov.domain.models import DemoInfo
from cs2pov.storage.artifact_store import ArtifactStore
from cs2pov.storage.jsonl import write_json


class DemoService:
    def __init__(self, adapter: DemoparserAdapter | None = None):
        self.adapter = adapter or DemoparserAdapter()

    def prepare_input(self, input_path: Path, store: ArtifactStore) -> Path:
        input_path = Path(input_path).expanduser().resolve()
        if not input_path.exists():
            raise FileNotFoundError(f"找不到 demo 文件：{input_path}")
        target = store.input_dir / (input_path.name[:-4] if input_path.name.lower().endswith(".zst") else input_path.name)
        if target.suffix.lower() != ".dem":
            target = target.with_suffix(".dem")
        if input_path == target.resolve():
            return target
        return self.adapter.decompress_if_needed(input_path, target)

    def inspect(
        self,
        demo_path: Path,
        original_input: Path,
        store: ArtifactStore,
        *,
        public_input_path: str | None = None,
        public_demo_path: str | None = None,
    ) -> DemoInfo:
        info = self.adapter.inspect(demo_path, original_input)
        if public_input_path is not None:
            info.input_path = public_input_path
        if public_demo_path is not None:
            info.demo_path = public_demo_path
        write_json(store.demo_info_path, info)
        return info
