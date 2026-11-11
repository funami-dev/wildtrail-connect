"""Phase 2: Livebild über den AV-Kanal.

Noch nicht implementiert. Voraussetzungen aus Phase 0 (siehe docs/PROTOCOL.md):
Stream-Start-Befehl, AV-Kanalnummer und Frame-Header-Layout (Codec, Keyframe-Flag,
Zeitstempel, Länge). Erwartet wird H.264/H.265 im Annex-B-Format.

Geplante Ausgabemodi: pipe (stdin an VLC/ffplay), udp, rtsp (MediaMTX), record.
"""

from __future__ import annotations


class LiveNotAvailable(NotImplementedError):
    """Live-Funktion hängt an Phase 0."""
