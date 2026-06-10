from cs2pov.domain.models import TranscriptSegment
from cs2pov.services.transcription_service import build_transcription_coverage, _build_unrecognized_placeholders, UNRECOGNIZED_TEXT
from cs2pov.storage.artifact_store import ArtifactStore
from cs2pov.storage.jsonl import write_jsonl


def test_transcription_coverage_and_placeholders(tmp_path):
    store = ArtifactStore(tmp_path / "job")
    store.ensure_dirs()
    write_jsonl(store.voice_activity_path, [
        {"id": "v1", "steamid": "s1", "player_name": "p1", "team_number": 2, "start_time": 10.0, "end_time": 10.5, "packet_count": 10},
        {"id": "v2", "steamid": "s1", "player_name": "p1", "team_number": 2, "start_time": 20.0, "end_time": 20.6, "packet_count": 10},
        {"id": "v3", "steamid": "s1", "player_name": "p1", "team_number": 2, "start_time": 30.0, "end_time": 30.2, "packet_count": 2},
    ])
    transcripts = [TranscriptSegment(
        id="tr1", steamid="s1", player_name="p1", team_number=2,
        start_time=10.1, end_time=10.4, original_text="one short"
    )]

    coverage = build_transcription_coverage(store, transcripts, selected_team_number=2, unrecognized_min_duration_seconds=0.35)
    assert coverage["voice_activity_cues"] == 3
    assert coverage["voice_activity_cues_ge_min_duration"] == 2
    assert coverage["matched_voice_cues_ge_min_duration"] == 1
    assert coverage["unmatched_voice_cues_ge_min_duration"] == 1

    placeholders = _build_unrecognized_placeholders(store, transcripts, selected_team_number=2, min_duration=0.35)
    assert len(placeholders) == 1
    assert placeholders[0].start_time == 20.0
    assert placeholders[0].original_text == UNRECOGNIZED_TEXT
