from pathlib import Path

from cs2pov.domain.models import Round
from cs2pov.services.transcription_service import _demo_window_to_wav_offsets, _selected_rounds_for_transcription
from cs2pov.storage.artifact_store import ArtifactStore
from cs2pov.storage.jsonl import write_json, write_jsonl


def test_demo_window_to_wav_offsets_uses_overlapping_packets():
    packets = [
        {"demo_start": 10.0, "demo_end": 10.1, "wav_offset": 0.0, "duration": 0.1},
        {"demo_start": 10.2, "demo_end": 10.3, "wav_offset": 0.1, "duration": 0.1},
        {"demo_start": 20.0, "demo_end": 20.1, "wav_offset": 0.2, "duration": 0.1},
    ]
    assert _demo_window_to_wav_offsets(10.15, 10.25, packets) == (0.1, 0.2)


def test_selected_rounds_for_transcription_uses_first_rounds_with_selected_team_voice(tmp_path: Path):
    store = ArtifactStore(tmp_path / "job")
    store.ensure_dirs()
    write_json(store.rounds_path, [Round(1, 0.0, 10.0), Round(2, 10.0, 20.0), Round(3, 20.0, 30.0)])
    write_jsonl(store.voice_activity_path, [
        {"id": "v1", "steamid": "s1", "player_name": "p1", "team_number": 3, "start_time": 1.0, "end_time": 2.0, "packet_count": 1},
        {"id": "v2", "steamid": "s2", "player_name": "p2", "team_number": 2, "start_time": 11.0, "end_time": 12.0, "packet_count": 1},
        {"id": "v3", "steamid": "s2", "player_name": "p2", "team_number": 2, "start_time": 21.0, "end_time": 22.0, "packet_count": 1},
    ])

    selected = _selected_rounds_for_transcription(store, selected_team_number=2, max_rounds=1)

    assert selected is not None
    assert [r.round_number for r in selected] == [2]
