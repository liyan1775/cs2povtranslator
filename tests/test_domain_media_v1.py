import pytest

from cs2pov.domain.errors import DomainSchemaError
from cs2pov.domain.media import AudioMediaManifest, AudioMediaReference


def _reference(media_id: str = "player-audio", player_id: str = "player-a"):
    return AudioMediaReference(
        media_id,
        player_id,
        f"voice/audio/{media_id}.wav",
        "a" * 64,
        24_000,
        240,
    )


def test_audio_media_manifest_round_trips_in_deterministic_order():
    manifest = AudioMediaManifest(
        (_reference("player-z", "player-z"), _reference(),)
    )

    assert [item.media_id for item in manifest.items] == [
        "player-audio",
        "player-z",
    ]
    assert AudioMediaManifest.from_dict(manifest.to_dict()) == manifest


@pytest.mark.parametrize(
    "relative_path",
    ["C:/outside.wav", "../outside.wav", "voice/audio/other.wav"],
)
def test_audio_media_reference_rejects_uncontrolled_paths(relative_path):
    with pytest.raises(DomainSchemaError):
        AudioMediaReference(
            "player-audio",
            "player-a",
            relative_path,
            "a" * 64,
            24_000,
            240,
        )
