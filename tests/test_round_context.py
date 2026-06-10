from pathlib import Path

from cs2pov.domain.models import Round, TranscriptSegment
from cs2pov.services.round_service import RoundService
from cs2pov.storage.artifact_store import ArtifactStore
from cs2pov.storage.jsonl import write_json, write_jsonl, read_jsonl


def test_build_contexts_filters_team(tmp_path: Path):
    store = ArtifactStore(tmp_path)
    store.ensure_dirs()
    write_json(store.rounds_path, [Round(1, 0.0, 10.0), Round(2, 10.0, 20.0)])
    write_jsonl(store.transcripts_path, [
        TranscriptSegment("a", "s1", "p1", 2, 1.0, 2.0, "hello"),
        TranscriptSegment("b", "s2", "p2", 3, 1.0, 2.0, "enemy"),
        TranscriptSegment("c", "s1", "p1", 2, 11.0, 12.0, "go b"),
    ])
    contexts = RoundService().build_contexts(store, selected_team_number=2)
    assert len(contexts) == 2
    assert [s.id for s in contexts[0].segments] == ["a"]
    assert [s.id for s in contexts[1].segments] == ["c"]


def test_build_contexts_max_rounds_does_not_add_orphan_context(tmp_path: Path):
    store = ArtifactStore(tmp_path)
    store.ensure_dirs()
    write_json(store.rounds_path, [Round(1, 0.0, 10.0), Round(2, 10.0, 20.0), Round(3, 20.0, 30.0)])
    write_jsonl(store.transcripts_path, [
        TranscriptSegment("a", "s1", "p1", 2, 1.0, 2.0, "round one"),
        TranscriptSegment("b", "s1", "p1", 2, 11.0, 12.0, "round two"),
        TranscriptSegment("c", "s1", "p1", 2, 21.0, 22.0, "round three"),
    ])
    contexts = RoundService().build_contexts(store, selected_team_number=2, max_rounds=1)
    assert len(contexts) == 1
    assert contexts[0].round_number == 1
    assert [s.id for s in contexts[0].segments] == ["a"]
