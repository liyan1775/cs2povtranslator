from cs2pov.domain.models import TranscriptSegment
from cs2pov.services.transcription_service import (
    is_probable_whisper_hallucination,
    rebase_long_segments_to_voice_activity,
)
from cs2pov.storage.artifact_store import ArtifactStore
from cs2pov.storage.jsonl import write_jsonl


def test_hallucination_filter_is_conservative():
    assert is_probable_whisper_hallucination(",,,,,,,,,,,,,,")
    assert is_probable_whisper_hallucination("... ...")
    assert not is_probable_whisper_hallucination("go")
    assert not is_probable_whisper_hallucination("A")
    assert not is_probable_whisper_hallucination("警家一个")
    assert not is_probable_whisper_hallucination("Short, hello")


def test_rebase_long_segment_to_voice_activity_clusters(tmp_path):
    store = ArtifactStore(tmp_path / "job")
    store.ensure_dirs()
    write_jsonl(store.voice_activity_path, [
        {"id": "v1", "steamid": "s1", "player_name": "p1", "team_number": 2, "start_time": 10.0, "end_time": 11.0, "packet_count": 5},
        {"id": "v2", "steamid": "s1", "player_name": "p1", "team_number": 2, "start_time": 40.0, "end_time": 41.0, "packet_count": 5},
        {"id": "v3", "steamid": "s1", "player_name": "p1", "team_number": 2, "start_time": 80.0, "end_time": 81.0, "packet_count": 5},
    ])
    seg = TranscriptSegment(
        id="tr1",
        steamid="s1",
        player_name="p1",
        team_number=2,
        start_time=0.0,
        end_time=90.0,
        original_text="one short hello",
    )

    rebased, stats = rebase_long_segments_to_voice_activity(
        store,
        [seg],
        selected_team_number=2,
        selected_rounds=None,
        threshold_seconds=15.0,
        cluster_gap_seconds=1.0,
    )

    assert stats["long_segments_rebased_to_voice_activity"] == 1
    assert len(rebased) == 3
    assert [s.original_text for s in rebased] == ["one", "short", "hello"]
    assert max(s.end_time - s.start_time for s in rebased) <= 1.0


def test_hallucination_filter_drops_punctuation_dominated_tails():
    assert is_probable_whisper_hallucination("끝,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,")
    assert is_probable_whisper_hallucination(",,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,")
    assert not is_probable_whisper_hallucination("끝")
    assert not is_probable_whisper_hallucination("да")
    assert not is_probable_whisper_hallucination("B?")


def test_round_mode_rebase_keeps_sentence_intact(tmp_path):
    store = ArtifactStore(tmp_path / "job_round")
    store.ensure_dirs()
    write_jsonl(store.voice_activity_path, [
        {"id": "v1", "steamid": "s1", "player_name": "p1", "team_number": 2, "start_time": 10.0, "end_time": 11.0, "packet_count": 5},
        {"id": "v2", "steamid": "s1", "player_name": "p1", "team_number": 2, "start_time": 40.0, "end_time": 41.0, "packet_count": 5},
        {"id": "v3", "steamid": "s1", "player_name": "p1", "team_number": 2, "start_time": 80.0, "end_time": 81.0, "packet_count": 5},
    ])
    seg = TranscriptSegment(
        id="tr1",
        steamid="s1",
        player_name="p1",
        team_number=2,
        start_time=0.0,
        end_time=90.0,
        original_text="Bench. Speak to me just a minute.",
    )

    rebased, stats = rebase_long_segments_to_voice_activity(
        store,
        [seg],
        selected_team_number=2,
        selected_rounds=None,
        threshold_seconds=15.0,
        cluster_gap_seconds=1.0,
        split_text_across_clusters=False,
    )

    assert len(rebased) == 1
    assert rebased[0].original_text == "Bench. Speak to me just a minute."
    assert rebased[0].end_time - rebased[0].start_time <= 15.0
    assert stats["long_segments_clamped_without_text_split"] == 1


def test_round_mode_rebase_uses_readable_duration_not_hard_cap(tmp_path):
    store = ArtifactStore(tmp_path / "job_round_readable")
    store.ensure_dirs()
    write_jsonl(store.voice_activity_path, [
        {"id": "v1", "steamid": "s1", "player_name": "p1", "team_number": 2, "start_time": 10.0, "end_time": 11.0, "packet_count": 5},
        {"id": "v2", "steamid": "s1", "player_name": "p1", "team_number": 2, "start_time": 40.0, "end_time": 41.0, "packet_count": 5},
        {"id": "v3", "steamid": "s1", "player_name": "p1", "team_number": 2, "start_time": 80.0, "end_time": 81.0, "packet_count": 5},
    ])
    seg = TranscriptSegment(
        id="tr1",
        steamid="s1",
        player_name="p1",
        team_number=2,
        start_time=0.0,
        end_time=90.0,
        original_text="Bench. Speak to me just a minute.",
    )

    rebased, stats = rebase_long_segments_to_voice_activity(
        store,
        [seg],
        selected_team_number=2,
        selected_rounds=None,
        threshold_seconds=10.0,
        cluster_gap_seconds=1.0,
        split_text_across_clusters=False,
    )

    assert len(rebased) == 1
    assert rebased[0].original_text == "Bench. Speak to me just a minute."
    assert 2.0 <= rebased[0].end_time - rebased[0].start_time < 10.0
    assert stats["long_segments_clamped_without_text_split"] == 1
