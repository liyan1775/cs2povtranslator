from __future__ import annotations

from dataclasses import replace
import hashlib
from pathlib import Path

import pytest

from cs2pov.application.subtitle_ports import (
    CurrentJobSubtitleApplicationService,
    SubtitlePortError,
)
from cs2pov.domain.job import (
    FinalArtifactEntry,
    FinalArtifactKind,
    FinalArtifactTimebase,
)
from cs2pov.domain.review import ReviewAction, ReviewDecision, compose_reviewed_timeline
from cs2pov.domain.validation import compose_draft_timeline
from cs2pov.storage import job_repository as job_repository_module
from test_job_repository_language_shards_v1 import _persist_closed_language_graph


def _draft_job(tmp_path: Path):
    workspace, repository, claim, _values = _persist_closed_language_graph(tmp_path)
    language = repository.load_language_graph("job-language")
    draft = compose_draft_timeline(
        language.timeline,
        language.transcripts,
        language.understanding_documents,
        language.configurations,
        language.invocations,
    )
    repository.save_draft_timeline("job-language", draft, claim)
    repository._release_write("job-language", claim)
    return workspace, repository, draft, language.timeline


def test_current_job_export_registers_full_and_round_subtitles(tmp_path):
    workspace, repository, draft, _ = _draft_job(tmp_path)

    report = CurrentJobSubtitleApplicationService(repository).export(
        "job-language", source="draft", preset="editing"
    )

    assert report.source == "draft"
    assert report.preset == "editing"
    assert len(report.artifacts) == 6  # 3 formats for the full demo and one round
    assert {entry.kind for entry in report.artifacts} == {FinalArtifactKind.SUBTITLE}
    assert {entry.timebase for entry in report.artifacts} == {
        FinalArtifactTimebase.DEMO_GLOBAL,
        FinalArtifactTimebase.ROUND_LOCAL,
    }
    manifest = repository.load_job("job-language").manifest
    assert len(manifest.final_artifacts) == 6
    assert all(
        (workspace.jobs_dir / "job-language" / entry.relative_path).exists()
        for entry in report.artifacts
    )
    for entry in report.artifacts:
        path = workspace.jobs_dir / "job-language" / entry.relative_path
        assert hashlib.sha256(path.read_bytes()).hexdigest() == entry.content_sha256
    assert "[Alpha] one jungle" in (
        workspace.jobs_dir
        / "job-language"
        / next(
            entry.relative_path
            for entry in report.artifacts
            if ".bilingual." in entry.relative_path and entry.round_id is None
        )
    ).read_text("utf-8")
    round_path = workspace.jobs_dir / "job-language" / next(
        entry.relative_path
        for entry in report.artifacts
        if ".bilingual." in entry.relative_path and entry.round_id == "round-001"
    )
    assert "00:00:00,000 --> 00:00:00,700" in round_path.read_text("utf-8")
    assert draft.timebase == "demo-microseconds"
    assert repository.inspect_job("job-language").entry.healthy


def test_current_job_export_uses_reviewed_translation_and_debug_formats(tmp_path):
    workspace, repository, claim, values = _persist_closed_language_graph(tmp_path)
    clock = repository.clock
    language = repository.load_language_graph("job-language")
    draft = compose_draft_timeline(
        language.timeline,
        language.transcripts,
        language.understanding_documents,
        language.configurations,
        language.invocations,
    )
    repository.save_draft_timeline("job-language", draft, claim)
    decision = ReviewDecision(
        "decision-001",
        draft.cues[0].cue_id,
        draft.cues[0].understanding_result_fingerprint,
        ReviewAction.EDIT,
        "2026-09-01T08:00:00.000000Z",
        "local-user",
        "人工修订",
        None,
        None,
        "人工翻译",
    )
    from cs2pov.domain.review import ReviewRevisionManifest, RoundReviewDocument

    review = ReviewRevisionManifest(
        "review-001",
        draft.content_fingerprint(),
        "2026-09-01T08:00:01.000000Z",
        ("round-001",),
    )
    clock.advance()
    repository.register_review_revision(
        "job-language",
        review,
        (RoundReviewDocument("review-001", "round-001", draft.content_fingerprint(), (decision,)),),
        repository.load_job("job-language").manifest.content_fingerprint(),
        True,
        claim,
    )
    reviewed = compose_reviewed_timeline(draft, (decision,))
    repository.save_reviewed_timeline("job-language", reviewed, claim)
    repository._release_write("job-language", claim)

    report = CurrentJobSubtitleApplicationService(repository).export(
        "job-language", source="reviewed", preset="review"
    )
    bilingual = next(
        entry for entry in report.artifacts
        if ".bilingual." in entry.relative_path and entry.round_id is None
    )
    text = (workspace.jobs_dir / "job-language" / bilingual.relative_path).read_text("utf-8")
    assert "人工翻译" in text
    assert "[中文] 警家一个" not in text
    assert any(".debug." in entry.relative_path for entry in report.artifacts)


def test_subtitle_export_failure_does_not_change_manifest_or_create_files(tmp_path):
    workspace, repository, _, _ = _draft_job(tmp_path)
    before = repository.load_job("job-language").manifest

    with pytest.raises(SubtitlePortError) as exc_info:
        CurrentJobSubtitleApplicationService(repository).export(
            "job-language", source="draft", preset="missing"
        )

    assert exc_info.value.code == "pipeline_subtitle_preset_invalid"
    after = repository.load_job("job-language").manifest
    assert after == before
    assert not any((workspace.jobs_dir / "job-language/final/subtitles").iterdir())


def test_repository_publish_cleans_new_files_when_file_write_fails(tmp_path, monkeypatch):
    workspace, repository, _, _ = _draft_job(tmp_path)
    opened = repository.load_job("job-language")
    payload = b"subtitle\n"
    relative_path = "final/subtitles/failure-probe.srt"
    entry = FinalArtifactEntry(
        "failure-probe",
        FinalArtifactKind.SUBTITLE,
        relative_path,
        hashlib.sha256(payload).hexdigest(),
        None,
        FinalArtifactTimebase.DEMO_GLOBAL,
    )
    candidate = replace(
        opened.manifest,
        updated_at="2026-09-01T08:00:00.000001Z",
        final_artifacts=(entry,),
    )
    with repository.acquire_write("job-language", lease_us=60_000_000) as session:
        monkeypatch.setattr(
            job_repository_module,
            "atomic_write_bytes",
            lambda *args, **kwargs: (_ for _ in ()).throw(OSError("disk full")),
        )
        with pytest.raises(OSError):
            repository.publish_final_artifacts(
                "job-language",
                (entry,),
                {relative_path: payload},
                opened.manifest.content_fingerprint(),
                candidate,
                session.claim,
            )
    assert repository.load_job("job-language").manifest == opened.manifest
    assert not (workspace.jobs_dir / "job-language" / relative_path).exists()
