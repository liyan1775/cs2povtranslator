from __future__ import annotations

import json
from pathlib import Path

from cs2pov.adapters.demoparser_adapter import DemoparserAdapter
from cs2pov.domain.models import Player, VoiceActivityCue, player_from_dict
from cs2pov.storage.artifact_store import ArtifactStore, safe_name
from cs2pov.storage.jsonl import read_json, write_jsonl


class VoiceService:
    def __init__(self, adapter: DemoparserAdapter | None = None):
        self.adapter = adapter or DemoparserAdapter()

    def extract(self, demo_path: Path, store: ArtifactStore, tick_rate: float = 64.0) -> list[Player]:
        manifest = self.adapter.extract_voice(demo_path, store.voice_dir, tick_rate=tick_rate)
        return [player_from_dict(row) for row in manifest.get("players", [])]

    def build_activity(self, store: ArtifactStore, gap_seconds: float = 0.35, min_duration: float = 0.05) -> list[VoiceActivityCue]:
        manifest = read_json(store.voice_manifest_path)
        cues: list[VoiceActivityCue] = []
        for player in manifest.get("players", []):
            packet_path = Path(player["packet_info_path"])
            packets = json.loads(packet_path.read_text(encoding="utf-8"))
            if not packets:
                continue
            grouped = _group_packets(packets, gap_seconds, min_duration)
            for idx, (start, end, count) in enumerate(grouped, 1):
                cues.append(VoiceActivityCue(
                    id=f"va_{player['steamid']}_{idx:05d}",
                    steamid=str(player["steamid"]),
                    player_name=str(player.get("name") or player["steamid"]),
                    team_number=player.get("team_number"),
                    start_time=start,
                    end_time=end,
                    packet_count=count,
                ))
        cues.sort(key=lambda x: (x.start_time, x.end_time, x.player_name))
        write_jsonl(store.voice_activity_path, cues)
        return cues


def _group_packets(packets: list[dict], gap_seconds: float, min_duration: float) -> list[tuple[float, float, int]]:
    if not packets:
        return []
    packets = sorted(packets, key=lambda p: p["demo_start"])
    start = float(packets[0]["demo_start"])
    end = float(packets[0]["demo_end"])
    count = 1
    cues: list[tuple[float, float, int]] = []
    for packet in packets[1:]:
        ps = float(packet["demo_start"])
        pe = float(packet["demo_end"])
        if ps - end <= gap_seconds:
            end = max(end, pe)
            count += 1
        else:
            if end - start >= min_duration:
                cues.append((round(start, 3), round(end, 3), count))
            start, end, count = ps, pe, 1
    if end - start >= min_duration:
        cues.append((round(start, 3), round(end, 3), count))
    return cues
