from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from cs2pov.cli.job_ops import resolve_job_dir
from cs2pov.services.player_alias_service import load_player_aliases, merge_player_aliases, remove_player_alias, save_player_aliases
from cs2pov.storage.artifact_store import ArtifactStore
from cs2pov.storage.jsonl import read_json


def load_player_rows(path: Path) -> tuple[Path, list[dict[str, Any]], dict[str, str]]:
    job_dir = resolve_job_dir(path)
    if job_dir is None:
        raise FileNotFoundError(f"找不到 Job 目录：{path}")
    store = ArtifactStore(job_dir)
    if not store.voice_manifest_path.exists():
        raise FileNotFoundError("该 Job 尚未生成 voice manifest。请先运行到 extract_voice / build_voice_activity 阶段。")
    manifest = read_json(store.voice_manifest_path)
    rows = list(manifest.get("players", [])) if isinstance(manifest, dict) else []
    aliases = load_player_aliases(store)
    return job_dir, rows, aliases


def build_players_report(path: Path) -> dict[str, Any]:
    job_dir, rows, aliases = load_player_rows(path)
    players: list[dict[str, Any]] = []
    for row in sorted(rows, key=lambda p: ((p.get("team_number") or 999), -(float(p.get("compact_wav_seconds") or 0.0)), str(p.get("name", "")).lower())):
        sid = str(row.get("steamid", ""))
        kills = row.get("kills")
        deaths = row.get("deaths")
        assists = row.get("assists")
        kda = _kda(kills, deaths, assists)
        players.append({
            "steamid": sid,
            "team_number": row.get("team_number"),
            "name": row.get("name"),
            "display_name": aliases.get(sid) or row.get("display_name") or row.get("name"),
            "alias_configured": sid in aliases,
            "kills": kills,
            "deaths": deaths,
            "assists": assists,
            "kda": kda,
            "voice_seconds": row.get("compact_wav_seconds"),
            "voice_packets": row.get("voice_packets"),
        })
    return {"job_dir": str(job_dir), "players": players, "alias_count": len(aliases)}


def print_players_report(report: dict[str, Any]) -> None:
    print("玩家识别 / 字幕显示名")
    print("=" * 96)
    print(f"Job: {report['job_dir']}")
    print("编号  Team  Demo昵称                  字幕显示名                K-D-A      语音时长   包数")
    print("----  ----  ------------------------  ------------------------  ---------  --------  ------")
    for idx, p in enumerate(report.get("players", []), 1):
        marker = "*" if p.get("alias_configured") else " "
        team = str(p.get("team_number")) if p.get("team_number") is not None else "?"
        voice_seconds = float(p.get("voice_seconds") or 0.0)
        packets = int(p.get("voice_packets") or 0)
        print(f"{idx:>2}.{marker}  {team:>4}  {str(p.get('name') or '')[:24]:<24}  {str(p.get('display_name') or '')[:24]:<24}  {p.get('kda'):<9}  {voice_seconds:>7.1f}s  {packets:>6}")
    print("\n说明：带 * 的行已经设置字幕显示名。K-D-A 只用于帮助识别谁是谁；如果 demo 事件解析失败，会显示 ?-?-?。")


def set_player_alias(path: Path, *, steamid: str | None = None, name: str | None = None, display_name: str) -> dict[str, Any]:
    job_dir, rows, aliases = load_player_rows(path)
    store = ArtifactStore(job_dir)
    sid = steamid or _resolve_name_to_steamid(rows, name)
    if not sid:
        raise ValueError("请提供 --steamid，或提供能唯一匹配玩家的 --name。")
    merge_player_aliases(store, {sid: display_name}, source="manual")
    _annotate_voice_manifest(store)
    return build_players_report(job_dir)


def clear_player_alias(path: Path, *, steamid: str | None = None, name: str | None = None, all_aliases: bool = False) -> dict[str, Any]:
    job_dir, rows, aliases = load_player_rows(path)
    store = ArtifactStore(job_dir)
    if all_aliases:
        save_player_aliases(store, {}, source="manual")
    else:
        sid = steamid or _resolve_name_to_steamid(rows, name)
        if not sid:
            raise ValueError("请提供 --steamid / --name，或使用 --all。")
        remove_player_alias(store, sid)
    _annotate_voice_manifest(store)
    return build_players_report(job_dir)


def _annotate_voice_manifest(store: ArtifactStore) -> None:
    manifest = read_json(store.voice_manifest_path)
    aliases = load_player_aliases(store)
    changed = False
    for row in manifest.get("players", []):
        sid = str(row.get("steamid", ""))
        if sid in aliases:
            row["display_name"] = aliases[sid]
            changed = True
        elif "display_name" in row:
            row.pop("display_name", None)
            changed = True
    if changed:
        from cs2pov.storage.jsonl import write_json
        write_json(store.voice_manifest_path, manifest)


def _resolve_name_to_steamid(rows: list[dict[str, Any]], name: str | None) -> str | None:
    if not name:
        return None
    target = name.strip().lower()
    matches = [str(row.get("steamid")) for row in rows if str(row.get("name", "")).strip().lower() == target]
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        raise ValueError(f"玩家名 {name!r} 匹配到多名玩家，请改用 --steamid。")
    raise ValueError(f"找不到玩家名 {name!r}。可先运行 cs2pov players list。")


def _kda(kills: Any, deaths: Any, assists: Any) -> str:
    if kills is None and deaths is None and assists is None:
        return "?-?-?"
    return f"{int(kills or 0)}-{int(deaths or 0)}-{int(assists or 0)}"
