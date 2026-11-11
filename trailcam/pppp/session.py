"""PPPP-Session über UDP: LAN-Direktverbindung, DRW-Kanäle, ACK/Retransmit.

Pro Kanal ist die Session ein zuverlässiger, geordneter Bytestrom (ähnlich TCP).
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field

from .packets import DeviceId, Drw, DrwAck, MsgType, Packet, PacketError

log = logging.getLogger(__name__)

MAX_DRW_DATA = 1024
WINDOW = 64
RETRANSMIT_AFTER = 0.5
MAX_RETRANSMITS = 20
KEEPALIVE_EVERY = 5.0

Codec = Callable[[bytes], bytes]


def _identity(b: bytes) -> bytes:
    return b


class SessionError(Exception):
    pass


class SessionClosed(SessionError):
    pass


@dataclass
class _Pending:
    data: bytes
    sent_at: float
    tries: int = 1


@dataclass
class _Channel:
    # Empfang
    next_rx: int = 0
    out_of_order: dict[int, bytes] = field(default_factory=dict)
    buffer: bytearray = field(default_factory=bytearray)
    data_event: asyncio.Event = field(default_factory=asyncio.Event)
    # Senden
    next_tx: int = 0
    unacked: dict[int, _Pending] = field(default_factory=dict)
    acked_event: asyncio.Event = field(default_factory=asyncio.Event)


class Session(asyncio.DatagramProtocol):
    """Eine PPPP-Verbindung zu genau einem Gerät."""

    def __init__(
        self,
        obfuscate: Codec = _identity,
        deobfuscate: Codec = _identity,
    ) -> None:
        self._obf = obfuscate
        self._deobf = deobfuscate
        self._transport: asyncio.DatagramTransport | None = None
        self._peer: tuple[str, int] | None = None
        self._channels: dict[int, _Channel] = {}
        self._connected = asyncio.Event()
        self._closed = False
        self._tasks: list[asyncio.Task[None]] = []
        self._last_tx = 0.0
        self.device_id: DeviceId | None = None
        self._expected_did: DeviceId | None = None

    # --- Lebenszyklus ---------------------------------------------------------

    @classmethod
    async def connect(
        cls,
        host: str,
        port: int,
        uid: str | None = None,
        timeout: float = 10.0,
        local_addr: tuple[str, int] = ("0.0.0.0", 0),
        **kw: Codec,
    ) -> Session:
        loop = asyncio.get_running_loop()
        _, proto = await loop.create_datagram_endpoint(lambda: cls(**kw), local_addr=local_addr)
        try:
            await proto._handshake((host, port), uid, timeout)
        except BaseException:
            proto._abort()
            raise
        return proto

    async def _handshake(self, peer: tuple[str, int], uid: str | None, timeout: float) -> None:
        self._peer = peer
        self._expected_did = DeviceId.parse(uid) if uid else None
        t0 = time.monotonic()
        deadline = t0 + timeout
        while not self._connected.is_set():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise SessionError(f"Keine Antwort von {peer[0]}:{peer[1]} (LAN-Handshake)")
            self._send(Packet(MsgType.LAN_SEARCH))
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self._connected.wait(), min(0.5, remaining))
        log.info(
            "PPPP verbunden mit %s:%d (%.0f ms)", peer[0], peer[1], (time.monotonic() - t0) * 1e3
        )
        self._start_background()

    def _start_background(self) -> None:
        loop = asyncio.get_running_loop()
        self._tasks.append(loop.create_task(self._retransmit_loop()))
        self._tasks.append(loop.create_task(self._keepalive_loop()))

    async def close(self) -> None:
        """Schickt CLOSE (Connect-Break) und beendet alle Tasks."""
        if self._closed:
            return
        if self._transport and self._peer:
            for _ in range(3):
                self._send(Packet(MsgType.CLOSE))
        self._abort()
        await asyncio.sleep(0)

    def _abort(self) -> None:
        self._closed = True
        for t in self._tasks:
            t.cancel()
        for ch in self._channels.values():
            ch.data_event.set()
            ch.acked_event.set()
        if self._transport:
            self._transport.close()

    @property
    def closed(self) -> bool:
        return self._closed

    # --- DatagramProtocol -----------------------------------------------------

    def connection_made(self, transport: asyncio.BaseTransport) -> None:
        assert isinstance(transport, asyncio.DatagramTransport)
        self._transport = transport

    def connection_lost(self, exc: Exception | None) -> None:
        self._closed = True
        for ch in self._channels.values():
            ch.data_event.set()
            ch.acked_event.set()

    def datagram_received(self, data: bytes, addr: tuple[str, int]) -> None:
        if self._peer and addr[0] != self._peer[0]:
            return
        try:
            pkt = Packet.decode(self._deobf(data))
        except PacketError as e:
            log.debug("Verwerfe Datagramm von %s: %s", addr, e)
            return
        self._handle(pkt, addr)

    def _handle(self, pkt: Packet, addr: tuple[str, int]) -> None:
        t = pkt.type
        if t == MsgType.PUNCH_PKT:
            did = DeviceId.decode(pkt.payload) if len(pkt.payload) >= DeviceId.SIZE else None
            if self._expected_did and did and did != self._expected_did:
                log.warning("Fremdes Gerät antwortet (%s), ignoriere", did)
                return
            self.device_id = did or self._expected_did
            self._peer = addr  # Gerät kann von anderem Port antworten
            self._send(Packet(MsgType.P2P_RDY, pkt.payload))
            self._connected.set()
        elif t == MsgType.P2P_RDY:
            self._peer = addr
            self._connected.set()
        elif t == MsgType.DRW:
            self._on_drw(Drw.from_packet(pkt))
        elif t == MsgType.DRW_ACK:
            self._on_ack(DrwAck.from_packet(pkt))
        elif t == MsgType.ALIVE:
            self._send(Packet(MsgType.ALIVE_ACK))
        elif t == MsgType.ALIVE_ACK:
            pass
        elif t == MsgType.CLOSE:
            log.info("Gerät hat die Verbindung geschlossen")
            self._abort()
        else:
            log.debug("Unbehandelter Pakettyp %s", pkt.type_name)

    # --- Empfang --------------------------------------------------------------

    def _chan(self, n: int) -> _Channel:
        ch = self._channels.get(n)
        if ch is None:
            ch = self._channels[n] = _Channel()
        return ch

    def _on_drw(self, d: Drw) -> None:
        self._send(DrwAck(d.channel, (d.index,)).to_packet())
        ch = self._chan(d.channel)
        if d.index == ch.next_rx:
            ch.buffer += d.data
            ch.next_rx = (ch.next_rx + 1) & 0xFFFF
            while ch.next_rx in ch.out_of_order:
                ch.buffer += ch.out_of_order.pop(ch.next_rx)
                ch.next_rx = (ch.next_rx + 1) & 0xFFFF
            ch.data_event.set()
        elif ((d.index - ch.next_rx) & 0xFFFF) < 0x8000:
            ch.out_of_order.setdefault(d.index, d.data)
        # sonst: Duplikat, schon ge-ACKt

    async def read_some(self, channel: int, timeout: float | None = None) -> bytes:
        """Liefert alle gepufferten Bytes eines Kanals (wartet auf mindestens 1 Byte)."""
        ch = self._chan(channel)
        while not ch.buffer:
            if self._closed:
                raise SessionClosed("Verbindung geschlossen")
            ch.data_event.clear()
            await asyncio.wait_for(ch.data_event.wait(), timeout)
        out = bytes(ch.buffer)
        ch.buffer.clear()
        return out

    async def read_exactly(self, channel: int, n: int, timeout: float | None = None) -> bytes:
        ch = self._chan(channel)

        async def _wait() -> bytes:
            while len(ch.buffer) < n:
                if self._closed:
                    raise SessionClosed("Verbindung geschlossen")
                ch.data_event.clear()
                await ch.data_event.wait()
            out = bytes(ch.buffer[:n])
            del ch.buffer[:n]
            return out

        return await asyncio.wait_for(_wait(), timeout)

    # --- Senden ---------------------------------------------------------------

    def _send(self, pkt: Packet) -> None:
        if self._transport is None or self._transport.is_closing() or self._peer is None:
            return
        self._transport.sendto(self._obf(pkt.encode()), self._peer)
        self._last_tx = time.monotonic()

    async def write(self, channel: int, data: bytes) -> None:
        """Sendet ``data`` zuverlässig auf ``channel`` (wartet nur auf Fenster-Platz)."""
        ch = self._chan(channel)
        for off in range(0, len(data), MAX_DRW_DATA):
            while len(ch.unacked) >= WINDOW:
                if self._closed:
                    raise SessionClosed("Verbindung geschlossen")
                ch.acked_event.clear()
                await ch.acked_event.wait()
            if self._closed:
                raise SessionClosed("Verbindung geschlossen")
            chunk = data[off : off + MAX_DRW_DATA]
            idx = ch.next_tx
            ch.next_tx = (idx + 1) & 0xFFFF
            ch.unacked[idx] = _Pending(chunk, time.monotonic())
            self._send(Drw(channel, idx, chunk).to_packet())

    async def drain(self, channel: int, timeout: float | None = None) -> None:
        """Wartet, bis alle gesendeten Daten des Kanals bestätigt sind."""
        ch = self._chan(channel)

        async def _wait() -> None:
            while ch.unacked:
                if self._closed:
                    raise SessionClosed("Verbindung geschlossen")
                ch.acked_event.clear()
                await ch.acked_event.wait()

        await asyncio.wait_for(_wait(), timeout)

    def _on_ack(self, ack: DrwAck) -> None:
        ch = self._chan(ack.channel)
        for i in ack.indices:
            ch.unacked.pop(i, None)
        ch.acked_event.set()

    async def _retransmit_loop(self) -> None:
        while not self._closed:
            await asyncio.sleep(RETRANSMIT_AFTER / 2)
            now = time.monotonic()
            for n, ch in self._channels.items():
                for idx, p in ch.unacked.items():
                    if now - p.sent_at >= RETRANSMIT_AFTER:
                        if p.tries >= MAX_RETRANSMITS:
                            log.error("Kanal %d: Paket %d nie bestätigt, gebe auf", n, idx)
                            self._abort()
                            return
                        p.tries += 1
                        p.sent_at = now
                        self._send(Drw(n, idx, p.data).to_packet())

    async def _keepalive_loop(self) -> None:
        while not self._closed:
            await asyncio.sleep(1.0)
            if time.monotonic() - self._last_tx >= KEEPALIVE_EVERY:
                self._send(Packet(MsgType.ALIVE))
