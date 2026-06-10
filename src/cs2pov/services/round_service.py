from __future__ import annotations

from pathlib import Path

from cs2pov.adapters.demoparser_adapter import DemoparserAdapter
from cs2pov.domain.models import Round, RoundContext, TranscriptSegment, round_from_dict, transcript_from_dict
from cs2pov.storage.artifact_store import ArtifactStore
from cs2pov.storage.jsonl import read_json, read_jsonl, write_json, write_jsonl


class RoundService:
    def __init__(self, adapter: DemoparserAdapter | None = None):
        self.adapter = adapter or DemoparserAdapter()

    def parse_rounds(self, demo_path: Path, store: ArtifactStore, tick_rate: float = 64.0, min_duration_seconds: float = 10.0) -> list[Round]:
        fallback_end = self._max_voice_time(store)
        rounds = self.adapter.parse_rounds(
            demo_path,
            tick_rate=tick_rate,
            fallback_end_time=fallback_end,
            min_duration_seconds=min_duration_seconds,
            raw_output_path=store.raw_rounds_path,
        )
        write_json(store.rounds_path, rounds)
        return rounds

    def build_contexts(self, store: ArtifactStore, selected_team_number: int | None = None, max_rounds: int | None = None) -> list[RoundContext]:
        rounds = [round_from_dict(row) for row in read_json(store.rounds_path)]
        transcripts = [transcript_from_dict(row) for row in read_jsonl(store.transcripts_path)]
        if selected_team_number is not None:
            transcripts = [s for s in transcripts if s.team_number == selected_team_number]
        transcripts.sort(key=lambda s: (s.start_time, s.end_time))

        contexts: list[RoundContext] = []
        processed_rounds = 0
        for rnd in rounds:
            segs: list[TranscriptSegment] = []
            for seg in transcripts:
                if rnd.start_time <= seg.start_time < rnd.end_time:
                    seg.round_number = rnd.round_number
                    segs.append(seg)
            if not segs:
                continue
            contexts.append(RoundContext(round_number=rnd.round_number, start_time=rnd.start_time, end_time=rnd.end_time, segments=segs))
            processed_rounds += 1
            if max_rounds is not None and processed_rounds >= max_rounds:
                break

        # Only append true orphan transcripts in a full run. When max_rounds is set,
        # unassigned transcripts are usually outside the requested smoke-test range;
        # adding them as round 0 would silently defeat the limit and can trigger
        # unexpectedly expensive LLM calls.
        if max_rounds is None:
            assigned_ids = {s.id for ctx in contexts for s in ctx.segments}
            orphans = [s for s in transcripts if s.id not in assigned_ids]
            if orphans:
                for s in orphans:
                    s.round_number = None
                contexts.append(RoundContext(round_number=0, start_time=min(s.start_time for s in orphans), end_time=max(s.end_time for s in orphans), segments=orphans))

        write_jsonl(store.round_contexts_path, contexts)
        write_jsonl(store.transcripts_path, transcripts)
        return contexts

    def _max_voice_time(self, store: ArtifactStore) -> float:
        rows = read_jsonl(store.voice_activity_path)
        if not rows:
            return 1.0
        return max(float(row.get("end_time", 0.0)) for row in rows)
