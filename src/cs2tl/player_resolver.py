"""Steam ID → player name + team resolution via demoparser2.

In v0.0, player names were parsed from csgove WAV filenames
({prefix}_{PLAYER_NAME}_{STEAM_ID}.wav) and teams came from demoparser2.
With v0.1's native extraction (demoparser2 + pyogg), WAV files are named
{steam_id}.wav — so both name and team now come from demoparser2's
parse_player_info() in a single call (D6 decision).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from cs2tl.shared import decompress_zst

logger = logging.getLogger(__name__)

# BOT filter: real Steam ID64s are exactly 17 digits and start with "7656".
STEAM_ID_LENGTH = 17
STEAM_ID_PREFIX = "7656"


@dataclass
class PlayerInfo:
    """Player information extracted from the demo."""

    steam_id: str
    player_name: str = ""  # in-game name, e.g., "donk"
    team: str = "unknown"  # "2" | "3" | "unknown"

    def __post_init__(self) -> None:
        if not self.player_name:
            self.player_name = self.steam_id


def resolve_players(
    demo_path: Path,
    steam_ids: list[str],
) -> dict[str, PlayerInfo]:
    """Parse the demo via demoparser2 to get player names and teams.

    Strategy:
      1. Decompress .dem.zst → temp .dem (via shared.decompress_zst).
      2. Call demoparser2.parse_player_info() — returns DataFrame with
         steamid, name, team_number columns.
      3. Match against the provided steam_ids.
      4. Fall back to steam_id string for unresolvable players.

    Args:
        demo_path: Path to the .dem or .dem.zst file.
        steam_ids: List of Steam ID64 strings to resolve.

    Returns:
        Mapping: steam_id -> PlayerInfo.
    """
    result: dict[str, PlayerInfo] = {}

    # Default: all unknown until resolved
    for sid in steam_ids:
        result[sid] = PlayerInfo(steam_id=sid, player_name=sid, team="unknown")

    # Try demoparser2 for name + team (D6 decision)
    tmp_dem: Path | None = None
    try:
        # Handle .dem.zst
        actual_demo = demo_path
        if demo_path.suffix == ".zst":
            tmp_dem = decompress_zst(demo_path)
            actual_demo = tmp_dem
            logger.debug("Decompressed %s → %s for player resolution", demo_path.name, actual_demo.name)

        from demoparser2 import DemoParser
        parser = DemoParser(str(actual_demo))
        df = parser.parse_player_info()

        resolved = 0
        for _, row in df.iterrows():
            sid = str(int(row["steamid"]))
            # Filter BOTs
            if len(sid) == STEAM_ID_LENGTH and sid.startswith(STEAM_ID_PREFIX):
                name = str(row["name"])
                team_num = int(row["team_number"])
                team = str(team_num)

                if sid in result:
                    result[sid].player_name = name
                    result[sid].team = team
                else:
                    # Player not in our steam_ids list (e.g., enemy team
                    # players without voice). Create record anyway for
                    # completeness.
                    result[sid] = PlayerInfo(steam_id=sid, player_name=name, team=team)

                logger.debug("demoparser2: %s → %s (team %s)", sid, name, team)
                resolved += 1

        logger.info("demoparser2 resolved %d players (names + teams)", resolved)

    except Exception as e:
        logger.warning("demoparser2 failed to resolve players: %s", e)
        logger.warning("Players will show as Steam ID numbers — translation still works")
    finally:
        if tmp_dem is not None:
            try:
                tmp_dem.unlink()
            except OSError:
                pass

    # Log resolution summary
    named = sum(1 for p in result.values() if p.player_name != p.steam_id)
    teamed = sum(1 for p in result.values() if p.team != "unknown")
    logger.info("Resolved %d players: %d named, %d teamed", len(result), named, teamed)

    return result
