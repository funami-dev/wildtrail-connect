"""Bekannte cmdIds (siehe docs/PROTOCOL.md).

Die meisten Werte sind durch das SDK-Debug-Log (App 2.11.21) bestätigt. Was dort
nur als Klartext-JSON zu sehen war, ist mit "bestätigt" markiert; offene Punkte
(z. B. das Format der AV-Frames) stehen in docs/PROTOCOL.md.
"""

from __future__ import annotations

from enum import IntEnum


class Cmd(IntEnum):
    LOGIN = 0
    LOGOUT = 1  # TODO(Phase 0): kein JSON im Log, nur EC_Logout + PPCS_Connect_Break
    ENTER_PAGE = 258  # Seite betreten (umrahmt Listen-/Settings-Zugriffe), result:0
    LEAVE_PAGE = 259  # Seite verlassen, result:0
    DEVICE_INFO = 512  # Geräteinfo/Settings
    SET_CONFIG = 513  # Einstellung setzen, z. B. {"cmdId":513,"shootMode":0}
    HEARTBEAT = 525  # ohne Token, seq ab 0x10001
    MEDIA_LIST = 768  # seitenweise, itemCntPerPage 48
    # Download = Playback-Start. Frames kommen danach über den AV-Kanal; die App
    # remuxt sie zu MP4. Antwort: startPbRet, videoWidth, videoHeight,
    # totalFrame, totalTime. Das AV-Frame-Layout ist noch offen (Phase 0).
    PLAYBACK_START = 769
    THUMBNAILS = 772  # Daten auf separatem Thumbnail-Kanal
    DELETE = 773  # Datei löschen: {fileType,dirNum,mediaNum} -> {delRet,result}

    # Rückwärtskompatibler Alias: "Download" ist der Playback-Start.
    DOWNLOAD = 769


class FileType(IntEnum):
    # Im Log werden fileType-2-Einträge als MP4 (H.264, 1280x720, ~10 s) geladen.
    # durationMs in der Medienliste ist dabei 0 und damit unzuverlässig.
    # TODO(Phase 0): Foto-Beispiel fehlt noch; Zuordnung Foto/Video bestätigen.
    PHOTO = 1
    VIDEO = 2


# PPPP-Kanäle, teils bestätigt. Das Log meldet PPCS_Read auf Kanal 3 und 6,
# eigene Threads für cmd, event, AV, thumbnail und OTA.
# TODO(Phase 0): genaue Nummern aus pcap bestätigen.
CH_CMD = 0
CH_EVENT = 1
CH_AV = 2
CH_THUMB = 3
CH_FILE = 2  # Download/Playback läuft über den AV-Kanal
CH_OTA = 6

HEARTBEAT_SEQ_START = 0x10001
