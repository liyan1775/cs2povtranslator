from cs2pov.services.transcription_service import _map_wav_offset_to_demo_time


def test_map_compact_wav_offset_to_demo_time():
    packets = [
        {"wav_offset": 0.0, "duration": 0.1, "demo_start": 10.0},
        {"wav_offset": 0.1, "duration": 0.1, "demo_start": 20.0},
    ]
    assert round(_map_wav_offset_to_demo_time(0.05, packets), 3) == 10.05
    assert round(_map_wav_offset_to_demo_time(0.15, packets), 3) == 20.05
