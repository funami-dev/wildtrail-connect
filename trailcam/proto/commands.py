"""Bekannte cmdIds (siehe docs/PROTOCOL.md)."""

from __future__ import annotations

from enum import IntEnum


class Cmd(IntEnum):
    LOGIN = 0
    LOGOUT = 1  # TODO(Phase 0): unbestätigt, im Log nur als "Logout" sichtbar
    UNKNOWN_258 = 258
    UNKNOWN_259 = 259
    DEVICE_INFO = 512
    HEARTBEAT = 525
    MEDIA_LIST = 768
    THUMBNAILS = 772
    # TODO(Phase 0): echter Wert unbekannt. Vorläufig nur für fake_camera/Tests.
    DOWNLOAD = 0x7F01


class FileType(IntEnum):
    PHOTO = 2
    VIDEO = 1  # TODO(Phase 0): Vermutung


# PPPP-Kanäle, vorläufig. Das Log meldet PPCS_Read auf Kanal 3 und 6.
# TODO(Phase 0): Zuordnung bestätigen.
CH_CMD = 0
CH_EVENT = 1
CH_AV = 2
CH_THUMB = 3
CH_FILE = 4
CH_OTA = 6

HEARTBEAT_SEQ_START = 0x10001
