from cs2pov.services.voice_service import _group_packets


def test_group_packets_by_gap():
    packets = [
        {"demo_start": 1.0, "demo_end": 1.1},
        {"demo_start": 1.2, "demo_end": 1.3},
        {"demo_start": 3.0, "demo_end": 3.2},
    ]
    cues = _group_packets(packets, gap_seconds=0.35, min_duration=0.01)
    assert cues == [(1.0, 1.3, 2), (3.0, 3.2, 1)]
