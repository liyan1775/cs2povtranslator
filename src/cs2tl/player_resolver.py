"""Steam ID → player name resolution.

Parses the demo via awpy to extract player information (name, team)
and maps each voice file's steam_id to a human-readable player name.

Key P1 constraints:
  - P1-12: Player name prefix in SRT output
  - Missing steam_id fallback to steam_id string
  - Integration point between extraction and translation
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class PlayerInfo:
    """Player information extracted from the demo."""

    steam_id: str
    player_name: str  # in-game name, e.g., "donk"
    team: str  # "T" | "CT" | "unknown"


def resolve_players(
    demo_path: Path,
    wav_files: dict[str, Path],
) -> dict[str, PlayerInfo]:
    """Parse the demo to get player names and teams, matched to voice steam_ids.

    Strategy:
      1. Parse player names from csgove WAV filenames (always works).
         Format: {prefix}_{PLAYER_NAME}_{STEAM_ID64}.wav
      2. Try demoparser2 for team info (handles newer CS2 demos).

    Args:
        demo_path: Path to the .dem file.
        wav_files: {steam_id: WAV path} mapping from extraction.

    Returns:
        Mapping: steam_id -> PlayerInfo.
    """
    # Extract player names from WAV filenames (csgove embeds them)
    # Format: {demo_name}_{temp_suffix}_{PLAYER_NAME}_{STEAM_ID64}
    name_from_filename: dict[str, str] = {}
    for steam_id, wav_path in wav_files.items():
        stem = wav_path.stem  # filename without .wav
        parts = stem.rsplit("_", 2)  # last 2 segments: player_name, steam_id
        if len(parts) >= 3:
            player_name_candidate = parts[-2]
            # Only use if it looks like a player name (not a hex suffix or temp suffix)
            if not _looks_like_temp_suffix(player_name_candidate):
                name_from_filename[steam_id] = player_name_candidate
                logger.debug("Parsed player name from filename: %s → %s", steam_id, player_name_candidate)
            else:
                name_from_filename[steam_id] = "unknown"
        else:
            name_from_filename[steam_id] = "unknown"

    # Try demoparser2 for team info (handles newer CS2 demos that awpy can't parse)
    team_from_demo: dict[str, str] = {}
    tmp_dem: Path | None = None
    try:
        # Handle .dem.zst: decompress to temp .dem for demoparser2
        actual_demo = demo_path
        if demo_path.suffix == ".zst":
            import zstandard as zstd
            import tempfile, os
            with open(demo_path, "rb") as f:
                compressed = f.read()
            dctx = zstd.ZstdDecompressor()
            decompressed = dctx.decompress(compressed)
            base_name = demo_path.stem
            if not base_name.endswith(".dem"):
                base_name = demo_path.with_suffix("").name
            fd, tmp_path = tempfile.mkstemp(suffix=".dem", prefix=base_name + "_")
            with os.fdopen(fd, "wb") as f:
                f.write(decompressed)
            actual_demo = Path(tmp_path)
            tmp_dem = actual_demo
            logger.debug("Decompressed %s → %s for team parsing", demo_path.name, actual_demo.name)

        from demoparser2 import DemoParser
        parser = DemoParser(str(actual_demo))
        df = parser.parse_player_info()
        for _, row in df.iterrows():
            sid = str(int(row["steamid"]))
            # Filter out BOTs: real Steam ID64s are 17 digits starting with 7656
            if len(sid) == 17 and sid.startswith("7656"):
                team_num = int(row["team_number"])
                team_from_demo[sid] = str(team_num)
                logger.debug("demoparser2: %s → team_%d", sid, team_num)
        logger.info("demoparser2 resolved %d players to teams", len(team_from_demo))
    except Exception as e:
        logger.warning("demoparser2 failed to parse demo for team info: %s", e)
    finally:
        # Clean up temp decompressed .dem
        if tmp_dem is not None:
            try:
                tmp_dem.unlink()
            except OSError:
                pass

    # Build result
    result: dict[str, PlayerInfo] = {}
    for steam_id in wav_files:
        player_name = name_from_filename.get(steam_id, "unknown")
        team = team_from_demo.get(steam_id, "unknown")

        if player_name == "unknown":
            player_name = steam_id  # last resort
            logger.debug("No player name in filename for %s — using ID", steam_id)
        else:
            logger.info("Resolved %s → %s (%s)", steam_id, player_name, team)

        result[steam_id] = PlayerInfo(steam_id=steam_id, player_name=player_name, team=team)

    logger.info("Resolved %d players", len(result))
    return result


def _looks_like_temp_suffix(s: str) -> bool:
    """Check if a string looks like a random temp suffix, not a player name.

    csgove's Go runtime generates temp dirs like "s6m0aepr" — exactly 8 chars,
    all lowercase+digits, random-looking. Player names like "l23n" or "m0T11-"
    have mixed case, hyphens, or different lengths.
    """
    # Temp suffixes from Go's os.MkdirTemp: exactly 8 chars, all lowercase+digits
    if len(s) == 8 and s.isalnum() and s.islower() and any(c.isdigit() for c in s):
        return True
    return False


def _extract_steam_id(filename_stem: str) -> str:
    """Extract the 17-digit Steam ID64 from a WAV filename stem.

    csgove names files as: {demo}_{temp}_{PLAYER_NAME}_{STEAM_ID64}
    The Steam ID64 is always the last underscore-separated segment if
    it's 17 digits; otherwise fall back to the full stem.
    """
    parts = filename_stem.rsplit("_", 1)
    if len(parts) >= 2 and parts[-1].isdigit() and len(parts[-1]) == 17:
        return parts[-1]
    return filename_stem


def _parse_player_list(demo_path: Path) -> list[PlayerInfo]:
    """Extract player list from the demo via awpy."""
    try:
        import awpy
    except ImportError:
        logger.warning("awpy not installed — cannot resolve player names. Install: pip install awpy")
        return []

    try:
        demo = awpy.Demo(str(demo_path))
    except Exception as e:
        logger.warning("Failed to parse demo for player info: %s", e)
        return []

    players: list[PlayerInfo] = []
    try:
        # awpy stores players in demo.players or demo.match_info
        raw_players = getattr(demo, "players", []) or []
        for p in raw_players:
            sid = str(p.get("steamID", "") or p.get("steamid", ""))
            name = str(p.get("name", "") or p.get("playerName", ""))
            if not sid:
                continue
            if not name:
                name = sid  # fallback
            team = str(p.get("team", "unknown"))
            players.append(PlayerInfo(steam_id=sid, player_name=name, team=team))
    except Exception as e:
        logger.warning("Failed to extract player info: %s", e)

    return players
