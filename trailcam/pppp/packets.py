"""PPCS/PPPP-Paketformat.

Jedes UDP-Datagramm::

    F1 <type:u8> <len:u16be> <payload[len]>

Referenzen: palant.info "PPPP"-Artikelserie, Wireshark-Dissector magicus/pppp-dissector.
Die optionale Verschleierung ("P2P_Proprietary_Encrypt") ist hier noch nicht
implementiert; siehe ``Session(obfuscator=...)``.
"""

from __future__ import annotations

import re
import struct
from dataclasses import dataclass
from enum import IntEnum

MAGIC = 0xF1
DRW_MARKER = 0xD1
DRW_ACK_MARKER = 0xD2
HEADER = struct.Struct(">BBH")


class MsgType(IntEnum):
    HELLO = 0x00
    HELLO_ACK = 0x01
    LAN_SEARCH = 0x30
    LAN_SEARCH_EXT = 0x32
    PUNCH_PKT = 0x41
    P2P_RDY = 0x42
    DRW = 0xD0
    DRW_ACK = 0xD1
    ALIVE = 0xE0
    ALIVE_ACK = 0xE1
    CLOSE = 0xF0


class PacketError(ValueError):
    pass


@dataclass(frozen=True)
class Packet:
    type: int
    payload: bytes = b""

    def encode(self) -> bytes:
        if len(self.payload) > 0xFFFF:
            raise PacketError("Payload zu groß")
        return HEADER.pack(MAGIC, self.type, len(self.payload)) + self.payload

    @classmethod
    def decode(cls, data: bytes) -> Packet:
        if len(data) < HEADER.size:
            raise PacketError(f"Paket zu kurz ({len(data)} Byte)")
        magic, typ, length = HEADER.unpack_from(data)
        if magic != MAGIC:
            raise PacketError(f"Falsches Magic 0x{magic:02x}")
        payload = data[HEADER.size : HEADER.size + length]
        if len(payload) != length:
            raise PacketError(f"Payload abgeschnitten ({len(payload)}/{length})")
        return cls(typ, payload)

    @property
    def type_name(self) -> str:
        try:
            return MsgType(self.type).name
        except ValueError:
            return f"0x{self.type:02x}"


# --- DRW (Daten) ---------------------------------------------------------------


@dataclass(frozen=True)
class Drw:
    channel: int
    index: int
    data: bytes

    def to_packet(self) -> Packet:
        hdr = struct.pack(">BBH", DRW_MARKER, self.channel, self.index & 0xFFFF)
        return Packet(MsgType.DRW, hdr + self.data)

    @classmethod
    def from_packet(cls, pkt: Packet) -> Drw:
        if pkt.type != MsgType.DRW or len(pkt.payload) < 4:
            raise PacketError("Kein DRW-Paket")
        marker, channel, index = struct.unpack_from(">BBH", pkt.payload)
        if marker != DRW_MARKER:
            raise PacketError(f"Falscher DRW-Marker 0x{marker:02x}")
        return cls(channel, index, pkt.payload[4:])


@dataclass(frozen=True)
class DrwAck:
    channel: int
    indices: tuple[int, ...]

    def to_packet(self) -> Packet:
        body = struct.pack(">BBH", DRW_ACK_MARKER, self.channel, len(self.indices))
        body += b"".join(struct.pack(">H", i & 0xFFFF) for i in self.indices)
        return Packet(MsgType.DRW_ACK, body)

    @classmethod
    def from_packet(cls, pkt: Packet) -> DrwAck:
        if pkt.type != MsgType.DRW_ACK or len(pkt.payload) < 4:
            raise PacketError("Kein DRW_ACK-Paket")
        marker, channel, count = struct.unpack_from(">BBH", pkt.payload)
        if marker != DRW_ACK_MARKER:
            raise PacketError(f"Falscher DRW_ACK-Marker 0x{marker:02x}")
        if len(pkt.payload) < 4 + 2 * count:
            raise PacketError("DRW_ACK abgeschnitten")
        idx = struct.unpack_from(f">{count}H", pkt.payload, 4)
        return cls(channel, tuple(idx))


# --- Geräte-ID (DID/UID) ---------------------------------------------------------

_DID_RE = re.compile(r"^([A-Z]{1,7})-?(\d{1,9})-?([A-Z]{0,7})$")


@dataclass(frozen=True)
class DeviceId:
    """PPCS-Geräte-ID, z. B. ``LBCS-000000-XXXXX``.

    Wire-Format (20 Byte): prefix[8] (NUL-gepadded), serial u32be, check[8].
    """

    prefix: str
    serial: int
    check: str

    SIZE = 20

    @classmethod
    def parse(cls, uid: str) -> DeviceId:
        m = _DID_RE.match(uid.strip().upper())
        if not m:
            raise PacketError("Ungültige UID")
        return cls(m.group(1), int(m.group(2)), m.group(3))

    def __str__(self) -> str:
        return f"{self.prefix}-{self.serial:06d}-{self.check}"

    def encode(self) -> bytes:
        return (
            self.prefix.encode().ljust(8, b"\0")
            + struct.pack(">I", self.serial)
            + self.check.encode().ljust(8, b"\0")
        )

    @classmethod
    def decode(cls, data: bytes) -> DeviceId:
        if len(data) < cls.SIZE:
            raise PacketError("DID zu kurz")
        prefix = data[:8].rstrip(b"\0").decode("ascii", "replace")
        (serial,) = struct.unpack_from(">I", data, 8)
        check = data[12:20].rstrip(b"\0").decode("ascii", "replace")
        return cls(prefix, serial, check)


def seq_newer(a: int, b: int) -> bool:
    """True, wenn 16-Bit-Index ``a`` (mit Wrap-around) nach ``b`` kommt."""
    return a != b and ((a - b) & 0xFFFF) < 0x8000
