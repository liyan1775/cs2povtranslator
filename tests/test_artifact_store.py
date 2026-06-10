from pathlib import Path

from cs2pov.storage.artifact_store import ArtifactStore


def test_rename_unknown_map_suffix_moves_existing_job(tmp_path: Path):
    store = ArtifactStore.create(tmp_path, None)
    marker = store.input_dir / "demo.dem"
    marker.write_text("x", encoding="utf-8")
    old_dir = store.job_dir

    renamed = store.rename_suffix("de_mirage")

    assert renamed.job_dir.name.endswith("_de_mirage")
    assert not old_dir.exists()
    assert (renamed.input_dir / "demo.dem").read_text(encoding="utf-8") == "x"
