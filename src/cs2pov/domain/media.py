from __future__ import annotations

from dataclasses import dataclass

from .errors import DomainSchemaError
from .schema import (
    MAX_SOURCE_POSITION,
    require_current_schema,
    require_exact_keys,
    require_identifier,
    require_int,
    require_mapping,
    require_path_identifier,
    require_sha256,
    require_str,
    reject_private_data,
)


_AUDIO_MEDIA_MIME_TYPE = "audio/wav"


def _invalid(path: str, message: str = "音频媒体引用无效。") -> None:
    raise DomainSchemaError(
        "domain_field_invalid",
        message,
        "请检查音频媒体清单后重试。",
        path,
    )


@dataclass(frozen=True, slots=True)
class AudioMediaReference:
    """A durable, workspace-relative reference to one player audio stream."""

    media_id: str
    player_id: str
    relative_path: str
    content_sha256: str
    sample_rate: int
    sample_count: int
    mime_type: str = _AUDIO_MEDIA_MIME_TYPE

    def __post_init__(self) -> None:
        require_path_identifier(self.media_id, "media_id")
        require_identifier(self.player_id, "player_id")
        expected_path = f"voice/audio/{self.media_id}.wav"
        if self.relative_path != expected_path:
            _invalid("relative_path", "音频媒体路径必须指向当前 Job 的受控音频目录。")
        require_sha256(self.content_sha256, "content_sha256")
        require_int(self.sample_rate, "sample_rate", minimum=1, maximum=768_000)
        require_int(
            self.sample_count,
            "sample_count",
            minimum=1,
            maximum=MAX_SOURCE_POSITION,
        )
        if self.mime_type != _AUDIO_MEDIA_MIME_TYPE:
            _invalid("mime_type", "当前仅支持 WAV 音频。")
        reject_private_data(self.to_dict(), "audio_media")

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "media_id": self.media_id,
            "player_id": self.player_id,
            "relative_path": self.relative_path,
            "content_sha256": self.content_sha256,
            "sample_rate": self.sample_rate,
            "sample_count": self.sample_count,
            "mime_type": self.mime_type,
        }

    @classmethod
    def from_dict(cls, value: object) -> "AudioMediaReference":
        data = require_mapping(value, "audio_media")
        reject_private_data(data, "audio_media")
        require_current_schema(data, "audio_media")
        require_exact_keys(
            data,
            {
                "schema_version",
                "media_id",
                "player_id",
                "relative_path",
                "content_sha256",
                "sample_rate",
                "sample_count",
                "mime_type",
            },
            set(),
            "audio_media",
        )
        return cls(
            require_path_identifier(data["media_id"], "media_id"),
            require_identifier(data["player_id"], "player_id"),
            require_str(data["relative_path"], "relative_path"),
            require_sha256(data["content_sha256"], "content_sha256"),
            data["sample_rate"],
            data["sample_count"],
            require_str(data["mime_type"], "mime_type"),
        )


@dataclass(frozen=True, slots=True)
class AudioMediaManifest:
    items: tuple[AudioMediaReference, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.items, (tuple, list)) or any(
            type(item) is not AudioMediaReference for item in self.items
        ):
            _invalid("items")
        values = tuple(sorted(self.items, key=lambda item: item.media_id))
        if len({item.media_id.casefold() for item in values}) != len(values):
            _invalid("items", "音频媒体 ID 不能重复。")
        if len({item.player_id for item in values}) != len(values):
            _invalid("items", "同一玩家只能有一条持久音频流。")
        if len({item.relative_path.casefold() for item in values}) != len(values):
            _invalid("items", "音频媒体路径不能重复。")
        object.__setattr__(self, "items", values)
        reject_private_data(self.to_dict(), "audio_media_manifest")

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "items": [item.to_dict() for item in self.items],
        }

    @classmethod
    def from_dict(cls, value: object) -> "AudioMediaManifest":
        data = require_mapping(value, "audio_media_manifest")
        reject_private_data(data, "audio_media_manifest")
        require_current_schema(data, "audio_media_manifest")
        require_exact_keys(
            data,
            {"schema_version", "items"},
            set(),
            "audio_media_manifest",
        )
        if not isinstance(data["items"], (tuple, list)):
            _invalid("items")
        return cls(
            tuple(AudioMediaReference.from_dict(item) for item in data["items"])
        )
