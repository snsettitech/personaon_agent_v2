"""Shared Meeting OS constants.

Keep these values aligned with the Phase 30 database constraints. Runtime
services should import these instead of duplicating mode/capture strings.
"""
from __future__ import annotations

from typing import Final, Literal

MeetingMode = Literal["off", "note_taker", "augmented", "delegated"]
CaptureMethod = Literal[
    "none",
    "google_meet_artifact",
    "google_meet_media_api",
    "recall_bot",
]
PrivacyLevel = Literal["public", "team", "private"]

MEETING_MODE_OFF: Final = "off"
MEETING_MODE_NOTE_TAKER: Final = "note_taker"
MEETING_MODE_AUGMENTED: Final = "augmented"
MEETING_MODE_DELEGATED: Final = "delegated"

MEETING_MODES: Final[tuple[MeetingMode, ...]] = (
    MEETING_MODE_OFF,
    MEETING_MODE_NOTE_TAKER,
    MEETING_MODE_AUGMENTED,
    MEETING_MODE_DELEGATED,
)

CAPTURE_METHOD_NONE: Final = "none"
CAPTURE_METHOD_GOOGLE_MEET_ARTIFACT: Final = "google_meet_artifact"
CAPTURE_METHOD_GOOGLE_MEET_MEDIA_API: Final = "google_meet_media_api"
CAPTURE_METHOD_RECALL_BOT: Final = "recall_bot"

CAPTURE_METHODS: Final[tuple[CaptureMethod, ...]] = (
    CAPTURE_METHOD_NONE,
    CAPTURE_METHOD_GOOGLE_MEET_ARTIFACT,
    CAPTURE_METHOD_GOOGLE_MEET_MEDIA_API,
    CAPTURE_METHOD_RECALL_BOT,
)

PRIVACY_LEVEL_PUBLIC: Final = "public"
PRIVACY_LEVEL_TEAM: Final = "team"
PRIVACY_LEVEL_PRIVATE: Final = "private"

PRIVACY_LEVELS: Final[tuple[PrivacyLevel, ...]] = (
    PRIVACY_LEVEL_PUBLIC,
    PRIVACY_LEVEL_TEAM,
    PRIVACY_LEVEL_PRIVATE,
)

DEFAULT_MEETING_MODE: Final[MeetingMode] = MEETING_MODE_OFF
DEFAULT_CAPTURE_METHOD: Final[CaptureMethod] = CAPTURE_METHOD_NONE
DEFAULT_MEETING_PRIVACY_LEVEL: Final[PrivacyLevel] = PRIVACY_LEVEL_PRIVATE

BOTLESS_CAPTURE_METHODS: Final[frozenset[CaptureMethod]] = frozenset(
    {
        CAPTURE_METHOD_GOOGLE_MEET_ARTIFACT,
        CAPTURE_METHOD_GOOGLE_MEET_MEDIA_API,
    }
)
BOT_BASED_CAPTURE_METHODS: Final[frozenset[CaptureMethod]] = frozenset(
    {CAPTURE_METHOD_RECALL_BOT}
)
BOT_BASED_MEETING_MODES: Final[frozenset[MeetingMode]] = frozenset(
    {
        MEETING_MODE_AUGMENTED,
        MEETING_MODE_DELEGATED,
    }
)
