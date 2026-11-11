"""Frame-Header des Command-Kanals.

Bekannt (§3.4 der Spec): Requests haben 21 Byte Header, Responses 41 Byte, gefolgt
vom Base64-Body. Das **Layout der Header ist noch unbekannt** (Phase 0).

Bis dahin gilt ein *vorläufiges* Layout, das nur von ``tools/fake_camera.py`` und
den Tests gesprochen wird. Es hat die richtigen Längen und enthält ein
Längenfeld, damit der Bytestrom auf dem Kanal getrennt werden kann:

Request (21 Byte)::

    magic[4]="ECRQ" ver:u8 cmdId:u32be seq:u32be bodyLen:u32be reserved[4]

Response (41 Byte)::

    magic[4]="ECRS" ver:u8 cmdId:u32be seq:u32be bodyLen:u32be reserved[24]

Nach Phase 0 wird nur dieses Modul an das echte Layout angepasst.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

REQUEST_HEADER_LEN = 21
RESPONSE_HEADER_LEN = 41

PROVISIONAL = True  # TODO(Phase 0): echtes Header-Layout einsetzen

_REQ = struct.Struct(">4sBIII4x")
_RSP = struct.Struct(">4sBIII24x")
REQ_MAGIC = b"ECRQ"
RSP_MAGIC = b"ECRS"
VERSION = 1

assert _REQ.size == REQUEST_HEADER_LEN
assert _RSP.size == RESPONSE_HEADER_LEN


class FrameError(ValueError):
    pass


@dataclass(frozen=True)
class FrameHeader:
    is_response: bool
    cmd_id: int
    seq: int
    body_len: int

    @property
    def size(self) -> int:
        return RESPONSE_HEADER_LEN if self.is_response else REQUEST_HEADER_LEN

    def encode(self) -> bytes:
        if self.is_response:
            return _RSP.pack(RSP_MAGIC, VERSION, self.cmd_id, self.seq, self.body_len)
        return _REQ.pack(REQ_MAGIC, VERSION, self.cmd_id, self.seq, self.body_len)

    @staticmethod
    def peek_size(first4: bytes) -> int:
        """Header-Länge anhand der ersten 4 Byte (Magic)."""
        if first4 == REQ_MAGIC:
            return REQUEST_HEADER_LEN
        if first4 == RSP_MAGIC:
            return RESPONSE_HEADER_LEN
        raise FrameError(f"Unbekanntes Frame-Magic {first4!r}")

    @classmethod
    def decode(cls, data: bytes) -> FrameHeader:
        size = cls.peek_size(data[:4])
        if len(data) < size:
            raise FrameError("Header zu kurz")
        st = _RSP if size == RESPONSE_HEADER_LEN else _REQ
        _magic, _ver, cmd, seq, blen = st.unpack_from(data)
        return cls(size == RESPONSE_HEADER_LEN, cmd, seq, blen)


def encode_frame(is_response: bool, cmd_id: int, seq: int, body: bytes) -> bytes:
    return FrameHeader(is_response, cmd_id, seq, len(body)).encode() + body


def expected_wire_len(json_len: int, is_response: bool) -> int:
    """Längenmodell aus §3.4: Header + Base64(AES(PKCS#7(JSON)))."""
    from .crypto import b64_len, padded_len

    hdr = RESPONSE_HEADER_LEN if is_response else REQUEST_HEADER_LEN
    return hdr + b64_len(padded_len(json_len))
