from __future__ import annotations

from collections import defaultdict
from decimal import Decimal, InvalidOperation
import math
from pathlib import Path
from typing import Any
import json
import shutil
import wave

from cs2pov.adapters.opus_adapter import PyOggOpusDecoder
from cs2pov.domain.models import DemoInfo, Player, Round, VoicePacketInfo
from cs2pov.storage.artifact_store import safe_name
from cs2pov.storage.jsonl import write_json


class DemoParserAdapterError(RuntimeError):
    pass


def _import_demoparser():
    try:
        from demoparser2 import DemoParser  # type: ignore
        return DemoParser
    except Exception as exc:  # pragma: no cover - optional dependency
        raise DemoParserAdapterError("缺少 demoparser2。请运行：pip install demoparser2") from exc


def _df_to_dicts(df: Any) -> list[dict[str, Any]]:
    if df is None:
        return []
    if hasattr(df, "to_dict"):
        try:
            return list(df.to_dict(orient="records"))
        except TypeError:
            return list(df.to_dict())
    if isinstance(df, list):
        return [dict(x) for x in df]
    return []


class DemoparserAdapter:
    def decompress_if_needed(self, input_path: Path, output_path: Path) -> Path:
        input_path = Path(input_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        if input_path.suffix.lower() == ".zst":
            try:
                import zstandard as zstd  # type: ignore
            except Exception as exc:  # pragma: no cover - optional dependency
                raise DemoParserAdapterError("这是 .zst 压缩 demo，但缺少 zstandard。请运行：pip install zstandard") from exc
            with input_path.open("rb") as src, output_path.open("wb") as dst:
                dctx = zstd.ZstdDecompressor()
                dctx.copy_stream(src, dst)
            return output_path
        shutil.copy2(input_path, output_path)
        return output_path

    def inspect(self, demo_path: Path, original_input: Path | None = None) -> DemoInfo:
        DemoParser = _import_demoparser()
        parser = DemoParser(str(demo_path))
        header = dict(parser.parse_header())
        players: list[Player] = []
        try:
            player_rows = _df_to_dicts(parser.parse_player_info())
        except Exception:
            player_rows = []
        for row in player_rows:
            steamid = _normalize_steamid(row.get("steamid") or row.get("steam_id") or row.get("xuid"))
            if steamid is None:
                continue
            players.append(Player(
                steamid=steamid,
                name=str(row.get("name", row.get("player_name", ""))),
                team_number=_safe_int(row.get("team_number", row.get("team"))),
            ))
        return DemoInfo(
            input_path=str(original_input or demo_path),
            demo_path=str(demo_path),
            map_name=header.get("map_name"),
            server_name=header.get("server_name"),
            tick_rate=64.0,
            header=header,
            players=players,
        )

    def extract_voice(self, demo_path: Path, voice_dir: Path, tick_rate: float = 64.0, sample_rate: int = 24_000) -> dict[str, Any]:
        DemoParser = _import_demoparser()
        voice_dir.mkdir(parents=True, exist_ok=True)
        parser = DemoParser(str(demo_path))
        header = dict(parser.parse_header())
        player_rows = _df_to_dicts(parser.parse_player_info())
        name_by_sid: dict[str, str] = {}
        team_by_sid: dict[str, int | None] = {}
        for row in player_rows:
            sid_s = _normalize_steamid(row.get("steamid") or row.get("steam_id") or row.get("xuid"))
            if sid_s is None:
                continue
            name_by_sid[sid_s] = str(row.get("name", row.get("player_name", sid_s)))
            team_by_sid[sid_s] = _safe_int(row.get("team_number", row.get("team")))

        voice_packets = parser.parse_voice()
        grouped: dict[str, list[tuple[int, bytes]]] = defaultdict(list)
        for pkt in voice_packets:
            sid = pkt.get("steamid") if isinstance(pkt, dict) else getattr(pkt, "steamid", None)
            tick = pkt.get("tick") if isinstance(pkt, dict) else getattr(pkt, "tick", None)
            data = pkt.get("bytes") if isinstance(pkt, dict) else getattr(pkt, "bytes", None)
            if sid is None or tick is None or data is None:
                continue
            sid_s = _normalize_steamid(sid)
            if sid_s and len(sid_s) == 17 and sid_s.startswith("7656"):
                grouped[sid_s].append((int(tick), bytes(data)))

        manifest: dict[str, Any] = {
            "header": header,
            "players": [],
            "total_packets": len(voice_packets),
            "tick_rate": tick_rate,
            "sample_rate": sample_rate,
            "skipped_frames": 0,
        }
        all_skipped = 0
        for sid, packets in sorted(grouped.items(), key=lambda kv: name_by_sid.get(kv[0], kv[0]).lower()):
            packets.sort(key=lambda x: x[0])
            pcm = bytearray()
            packet_info: list[dict[str, Any]] = []
            wav_offset = 0.0
            skipped = 0
            with PyOggOpusDecoder(sample_rate=sample_rate, channels=1) as decoder:
                for tick, data in packets:
                    decoded = decoder.decode(data)
                    if not decoded:
                        skipped += 1
                        continue
                    pcm.extend(decoded)
                    duration = len(decoded) / 2 / sample_rate
                    demo_start = tick / tick_rate
                    packet_info.append({
                        "steamid": sid,
                        "player_name": name_by_sid.get(sid, sid),
                        "team_number": team_by_sid.get(sid),
                        "demo_start": round(demo_start, 3),
                        "demo_end": round(demo_start + duration, 3),
                        "wav_offset": round(wav_offset, 3),
                        "duration": round(duration, 3),
                        "tick": tick,
                        "bytes": len(data),
                    })
                    wav_offset += duration
            if not pcm:
                continue
            name = name_by_sid.get(sid, sid)
            safe = safe_name(name, 50)
            wav_path = voice_dir / f"{sid}_{safe}.wav"
            with wave.open(str(wav_path), "wb") as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(sample_rate)
                wf.writeframes(pcm)
            packet_path = voice_dir / f"{sid}_{safe}.packets.json"
            write_json(packet_path, packet_info)
            duration = len(pcm) / 2 / sample_rate
            manifest["players"].append({
                "steamid": sid,
                "name": name,
                "team_number": team_by_sid.get(sid),
                "voice_packets": len(packets),
                "decoded_packets": len(packet_info),
                "skipped": skipped,
                "compact_wav_seconds": round(duration, 2),
                "wav_path": str(wav_path),
                "packet_info_path": str(packet_path),
            })
            all_skipped += skipped
        manifest["skipped_frames"] = all_skipped
        write_json(voice_dir / "manifest.json", manifest)
        return manifest

    def parse_rounds(
        self,
        demo_path: Path,
        tick_rate: float,
        fallback_end_time: float,
        min_duration_seconds: float = 10.0,
        raw_output_path: Path | None = None,
    ) -> list[Round]:
        """Parse and clean round boundaries from demo events.

        demoparser2's round_start stream can include very short pseudo-rounds
        caused by pauses, restarts, or match-control events.  Those are useful
        for debugging, but terrible as LLM translation contexts.  We therefore
        keep a raw candidate artifact and return a cleaned, sequentially
        numbered list of usable round windows.
        """
        DemoParser = _import_demoparser()
        parser = DemoParser(str(demo_path))
        event_rows: dict[str, list[dict[str, Any]]] = {}
        for event_name in ["round_start", "round_end", "round_officially_ended", "round_freeze_end", "warmup_end"]:
            rows = self._try_parse_event(parser, event_name)
            if rows:
                event_rows[event_name] = rows

        starts = event_rows.get("round_start", [])
        if not starts:
            fallback = [Round(round_number=1, start_time=0.0, end_time=max(1.0, fallback_end_time), source="fallback_no_round_events")]
            if raw_output_path is not None:
                write_json(raw_output_path, fallback)
            return fallback

        raw_rounds: list[Round] = []
        starts_sorted = sorted(starts, key=lambda r: _event_time_or_tick(r, tick_rate)[0])
        end_rows = sorted(event_rows.get("round_end", []) + event_rows.get("round_officially_ended", []), key=lambda r: _event_time_or_tick(r, tick_rate)[0])

        for idx, row in enumerate(starts_sorted, 1):
            start_time, start_tick = _event_time_or_tick(row, tick_rate)
            if idx < len(starts_sorted):
                next_start_time, next_start_tick = _event_time_or_tick(starts_sorted[idx], tick_rate)
            else:
                next_start_time, next_start_tick = max(fallback_end_time, start_time + 1.0), None

            total_rounds = _safe_int(row.get("total_rounds_played"))
            candidate_no = total_rounds + 1 if total_rounds is not None else idx
            is_warmup = bool(row.get("is_warmup_period", row.get("isWarmup", False)))
            winner_team = _winner_from_end_row(_find_first_event_between(end_rows, start_time, next_start_time, tick_rate))
            if next_start_time > start_time:
                raw_rounds.append(Round(
                    round_number=candidate_no,
                    start_time=start_time,
                    end_time=next_start_time,
                    start_tick=start_tick,
                    end_tick=next_start_tick,
                    is_warmup=is_warmup,
                    winner_team=winner_team,
                    source="demoparser2:round_start_raw",
                ))

        if raw_output_path is not None:
            write_json(raw_output_path, raw_rounds)

        cleaned = _clean_round_candidates(raw_rounds, min_duration_seconds=min_duration_seconds)
        return cleaned or [Round(round_number=1, start_time=0.0, end_time=max(1.0, fallback_end_time), source="fallback_empty_clean_rounds")]

    def parse_player_stats(self, demo_path: Path) -> dict[str, dict[str, Any]]:
        """Return lightweight K/D/A stats keyed by SteamID when demo events allow it.

        demoparser2 has changed event column names across versions, so this
        method is deliberately tolerant: it tries common attacker/victim/assister
        SteamID fields and silently returns zeroed stats if player_death cannot
        be parsed.  The stats are only used as a user-facing identity hint.
        """
        DemoParser = _import_demoparser()
        parser = DemoParser(str(demo_path))
        try:
            player_rows = _df_to_dicts(parser.parse_player_info())
        except Exception:
            player_rows = []
        stats: dict[str, dict[str, Any]] = {}
        for row in player_rows:
            sid = _normalize_steamid(row.get("steamid") or row.get("steam_id") or row.get("xuid"))
            if not sid:
                continue
            stats[sid] = {
                "steamid": sid,
                "name": str(row.get("name", row.get("player_name", sid))),
                "team_number": _safe_int(row.get("team_number", row.get("team"))),
                "kills": 0,
                "deaths": 0,
                "assists": 0,
            }
        rows = self._try_parse_event(parser, "player_death")
        for row in rows:
            victim = _first_steamid(row, ["user_steamid", "victim_steamid", "userid_steamid", "player_steamid", "steamid"])
            attacker = _first_steamid(row, ["attacker_steamid", "killer_steamid"])
            assister = _first_steamid(row, ["assister_steamid", "assist_steamid"])
            if victim and victim in stats:
                stats[victim]["deaths"] += 1
            if attacker and attacker != victim and attacker in stats:
                stats[attacker]["kills"] += 1
            if assister and assister not in {victim, attacker} and assister in stats:
                stats[assister]["assists"] += 1
        return stats

    def _try_parse_event(self, parser: Any, event_name: str) -> list[dict[str, Any]]:
        # demoparser2 API has changed across releases and has Python/JS naming differences.
        candidates = ["parse_event", "parse_events"]
        for method_name in candidates:
            method = getattr(parser, method_name, None)
            if method is None:
                continue
            try:
                if method_name == "parse_events":
                    result = method([event_name])
                else:
                    result = method(event_name)
                rows = _df_to_dicts(result)
                if rows:
                    return rows
            except Exception:
                continue
        return []


def _normalize_steamid(value: Any) -> str | None:
    """Normalize SteamID values without routing long integer strings through float.

    SteamID64 is 17 digits.  Converting a digit string such as
    ``76561198386265483`` with ``float(...)`` rounds it to a nearby even value
    (for example ``...65488``), which breaks joins between voice packets, player
    stats and alias files.  Keep plain digit strings exact; only use Decimal for
    decimal/scientific string forms that optional parser backends may emit.
    """
    if value is None or value == "":
        return None
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        if value == 0 or not math.isfinite(value):
            return None
        return str(int(value))
    text = str(value).strip()
    if not text or text in {"None", "nan", "NaN"}:
        return None
    if text.isdigit():
        return str(int(text))
    try:
        dec = Decimal(text)
    except (InvalidOperation, ValueError):
        return text
    if dec == 0:
        return None
    if dec == dec.to_integral_value():
        return str(int(dec))
    return text


def _first_steamid(row: dict[str, Any], keys: list[str]) -> str | None:
    for key in keys:
        if key in row:
            sid = _normalize_steamid(row.get(key))
            if sid and sid not in {"0", "None"}:
                return sid
    return None


def _clean_round_candidates(raw_rounds: list[Round], min_duration_seconds: float = 10.0) -> list[Round]:
    # Some FACEIT demos emit a round_start at tick 1, then one or more very
    # short round_start intervals before the real live match begins.  Keeping
    # that preamble pollutes POV subtitles and round-level LLM contexts.
    start_index = _detect_startup_preamble_cutoff(raw_rounds, min_duration_seconds)

    cleaned: list[Round] = []
    for raw in raw_rounds[start_index:]:
        duration = raw.end_time - raw.start_time
        if raw.is_warmup:
            continue
        if duration < min_duration_seconds:
            continue
        cleaned.append(Round(
            round_number=len(cleaned) + 1,
            start_time=raw.start_time,
            end_time=raw.end_time,
            start_tick=raw.start_tick,
            end_tick=raw.end_tick,
            is_warmup=False,
            winner_team=raw.winner_team,
            source="demoparser2:round_start_cleaned",
        ))
    return cleaned


def _detect_startup_preamble_cutoff(raw_rounds: list[Round], min_duration_seconds: float) -> int:
    if len(raw_rounds) < 3:
        return 0
    if raw_rounds[0].start_time > 5.0:
        return 0

    last_early_short_idx: int | None = None
    for idx, rnd in enumerate(raw_rounds[:5]):
        duration = rnd.end_time - rnd.start_time
        if rnd.start_time <= 120.0 and duration < min_duration_seconds:
            last_early_short_idx = idx

    # If early short pseudo-rounds exist, treat everything before the last one
    # as pre-live match-control noise.  The raw artifact still keeps those
    # candidates for debugging.
    if last_early_short_idx is not None:
        return last_early_short_idx + 1
    return 0


def _find_first_event_between(rows: list[dict[str, Any]], start_time: float, end_time: float, tick_rate: float) -> dict[str, Any] | None:
    for row in rows:
        event_time, _ = _event_time_or_tick(row, tick_rate)
        if start_time <= event_time <= end_time:
            return row
    return None


def _winner_from_end_row(row: dict[str, Any] | None) -> int | None:
    if not row:
        return None
    for key in ["winner", "winner_team", "winning_team", "team", "reason"]:
        value = _safe_int(row.get(key))
        if value is not None and value in {2, 3}:
            return value
    return None


def _safe_int(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, float) and not math.isfinite(value):
        return None
    try:
        return int(value)
    except Exception:
        return None


def _event_time_or_tick(row: dict[str, Any], tick_rate: float) -> tuple[float, int | None]:
    if row.get("game_time") is not None:
        try:
            return float(row["game_time"]), _safe_int(row.get("tick"))
        except Exception:
            pass
    tick = _safe_int(row.get("tick") or row.get("event_tick"))
    if tick is not None:
        return tick / tick_rate, tick
    return 0.0, None
