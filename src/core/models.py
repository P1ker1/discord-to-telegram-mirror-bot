from dataclasses import dataclass, field
from typing import Optional


@dataclass(frozen=True)
class MediaAttachment:
    """
    Normalized representation of a media attachment.
    Decoupled from external platform SDKs (e.g. discord.Attachment).
    """
    url: str
    filename: str
    content_type: Optional[str] = None
    is_animation: bool = False

    @property
    def is_image(self) -> bool:
        if self.is_animation:
            return False
        if self.content_type and self.content_type.startswith("image/"):
            return True
        name = (self.filename or "").lower()
        return name.endswith((".png", ".jpg", ".jpeg", ".webp"))

    @property
    def is_video(self) -> bool:
        if self.content_type and self.content_type.startswith("video/"):
            return True
        name = (self.filename or "").lower()
        return name.endswith((".mp4", ".mov", ".mkv", ".webm"))


@dataclass(frozen=True)
class Announcement:
    """
    Platform-agnostic representation of an announcement to mirror.
    """
    source_message_id: int
    channel_id: int
    author_name: str
    author_is_bot: bool
    content: str
    attachments: list[MediaAttachment] = field(default_factory=list)
    raw_embeds: list[dict] = field(default_factory=list)
    animation_url: Optional[str] = None
