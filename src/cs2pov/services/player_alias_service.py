from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

from cs2pov.storage.artifact_store import ArtifactStore
from cs2pov.storage.jsonl import read_json, write_json


PLAYER_ALIASES_SCHEMA_VERSION = 1


def load_player_aliases(store: ArtifactStore) -> dict[str, str]:
    """Load speaker display-name aliases keyed by SteamID.

    The alias file is intentionally job-local because POV nicknames often only
    make sense for one demo (for example Ebule -> donk).  Export applies these
    aliases without mutating source transcript/translation artifacts.
    """
    path = store.player_aliases_path
    if not path.exists():
        return {}
    try:
        data = read_json(path)
    except Exception:
        return {}
    aliases = data.get("aliases", data) if isinstance(data, dict) else {}
    if not isinstance(aliases, dict):
        return {}
    return {str(k): str(v).strip() for k, v in aliases.items() if str(k).strip() and str(v).strip()}


def save_player_aliases(store: ArtifactStore, aliases: dict[str, str], *, source: str = "manual") -> Path:
    cleaned = {str(k): str(v).strip() for k, v in aliases.items() if str(k).strip() and str(v).strip()}
    write_json(store.player_aliases_path, {
        "schema_version": PLAYER_ALIASES_SCHEMA_VERSION,
        "updated_at": datetime.now().isoformat(timespec="seconds"),
        "source": source,
        "aliases": cleaned,
    })
    return store.player_aliases_path


def merge_player_aliases(store: ArtifactStore, updates: dict[str, str], *, source: str = "manual") -> Path:
    aliases = load_player_aliases(store)
    aliases.update({str(k): str(v).strip() for k, v in updates.items() if str(v).strip()})
    return save_player_aliases(store, aliases, source=source)


def remove_player_alias(store: ArtifactStore, steamid: str) -> Path:
    aliases = load_player_aliases(store)
    aliases.pop(str(steamid), None)
    return save_player_aliases(store, aliases, source="manual")


def apply_player_aliases(store: ArtifactStore, items: Iterable[Any]) -> list[Any]:
    aliases = load_player_aliases(store)
    if not aliases:
        return list(items)
    out: list[Any] = []
    for item in items:
        sid = str(getattr(item, "steamid", ""))
        alias = aliases.get(sid)
        if not alias:
            out.append(item)
            continue
        try:
            out.append(replace(item, player_name=alias))
        except TypeError:
            item.player_name = alias
            out.append(item)
    return out


def apply_aliases_to_player_rows(players: list[dict[str, Any]], aliases: dict[str, str]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for player in players:
        row = dict(player)
        sid = str(row.get("steamid", ""))
        if sid in aliases:
            row["display_name"] = aliases[sid]
        rows.append(row)
    return rows
