
from cs2pov.domain.models import PipelineConfig
from cs2pov.pipeline.manifest import PipelineManifest


def test_public_manifest_normalizes_artifact_paths_inside_job():
    manifest = PipelineManifest.create("20260610_de_mirage", PipelineConfig())
    manifest.set_artifact(
        "bilingual_srt",
        r"D:\个人项目\cs2pov\output\20260610_de_mirage\final\team_2.bilingual.srt",
    )
    manifest.set_artifact("relative", r"output\20260610_de_mirage\artifacts\glossary_used.json")

    data = manifest.to_public_dict()

    assert data["artifacts"]["bilingual_srt"] == "final/team_2.bilingual.srt"
    assert data["artifacts"]["relative"] == "artifacts/glossary_used.json"
