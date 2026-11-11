#!/usr/bin/env python3
"""Emulierte TrailCam für Tests ohne Hardware.

Spricht PPPP-LAN (LAN_SEARCH → PUNCH_PKT → P2P_RDY), DRW-Kanäle und die Befehle
0/1/258/259/512/525/768 sowie den *vorläufigen* Download-Befehl. Alle Daten sind
synthetisch (Zugangsdaten admin/test1234, Testschlüssel 00 01 … 0f).

    python tools/fake_camera.py --port 11941 --photos 60 --videos 3
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import hashlib
import json
import logging
import random
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from trailcam.pppp.packets import DeviceId, MsgType, Packet  # noqa: E402
from trailcam.pppp.session import Session  # noqa: E402
from trailcam.proto.commands import CH_CMD, CH_FILE, Cmd  # noqa: E402
from trailcam.proto.crypto import PayloadCipher  # noqa: E402
from trailcam.proto.frame import FrameHeader, encode_frame  # noqa: E402

log = logging.getLogger("fake_camera")

TEST_USER = "admin"
TEST_PASSWORD = "test1234"
TEST_KEY_HEX = "000102030405060708090a0b0c0d0e0f"
TEST_UID = "LBCS-000000-TESTA"
BASE_TIME = 1_762_000_000  # 2025-11-01, synthetisch


def synthetic_file(media_num: int, video: bool) -> bytes:
    """Deterministische Pseudo-Datei (JPEG- bzw. MP4-artiger Rahmen)."""
    rnd = random.Random(media_num * 7919 + int(video))
    size = rnd.randint(3_000, 12_000) * (4 if video else 1)
    body = rnd.randbytes(size)
    if video:
        return b"\x00\x00\x00\x18ftypisom" + body
    return b"\xff\xd8\xff\xe0" + body + b"\xff\xd9"


class FakeCamera(Session):
    def __init__(
        self,
        *,
        photos: int = 5,
        videos: int = 1,
        key: bytes = bytes.fromhex(TEST_KEY_HEX),
        mode: str = "ecb",
        uid: str = TEST_UID,
        password: str = TEST_PASSWORD,
        drop_rate: float = 0.0,
        fail_downloads: int = 0,
    ) -> None:
        super().__init__()
        self.cipher = PayloadCipher(key, mode)
        self.did = DeviceId.parse(uid)
        self.password = password
        self.drop_rate = drop_rate
        self.fail_downloads = fail_downloads
        self._rng = random.Random(1)
        self.token: int | None = None
        self.received: list[dict[str, Any]] = []
        self.media: list[dict[str, Any]] = []
        n = 0
        for i in range(photos):
            n += 1
            self.media.append(self._entry(2, n, BASE_TIME + i * 3600, 0))
        for i in range(videos):
            n += 1
            self.media.append(self._entry(1, n, BASE_TIME + (photos + i) * 3600, 10_000))
        self._worker: asyncio.Task[None] | None = None
        self._bg_started = False

    @staticmethod
    def _entry(ftype: int, num: int, t: int, dur: int) -> dict[str, Any]:
        return {
            "fileType": ftype,
            "mediaDirNum": 100,
            "mediaNum": num,
            "durationMs": dur,
            "mediaId": 100_000 + num,
            "mediaTime": t,
        }

    def file_bytes(self, num: int) -> bytes:
        e = next(m for m in self.media if m["mediaNum"] == num)
        return synthetic_file(num, e["durationMs"] > 0)

    # --- Transport ------------------------------------------------------------

    def _send(self, pkt: Packet) -> None:
        if self.drop_rate and pkt.type == MsgType.DRW and self._rng.random() < self.drop_rate:
            return
        super()._send(pkt)

    def datagram_received(self, data: bytes, addr: tuple[str, int]) -> None:
        if self.drop_rate and self._rng.random() < self.drop_rate:
            return
        try:
            pkt = Packet.decode(data)
        except ValueError:
            return
        if pkt.type == MsgType.LAN_SEARCH:
            if self._peer != addr:
                self._reset()
            self._peer = addr
            self._send(Packet(MsgType.PUNCH_PKT, self.did.encode()))
            return
        if pkt.type == MsgType.P2P_RDY:
            self._peer = addr
            self._send(Packet(MsgType.P2P_RDY, self.did.encode()))
            if not self._bg_started:
                self._bg_started = True
                self._start_background()
            if self._worker is None or self._worker.done():
                self._worker = asyncio.get_running_loop().create_task(self._serve())
            return
        if pkt.type == MsgType.CLOSE:
            log.info("Client hat getrennt")
            self._reset()
            self._peer = None
            return
        if self._peer is None or addr != self._peer:
            return
        self._handle(pkt, addr)

    def _reset(self) -> None:
        if self._worker:
            self._worker.cancel()
            self._worker = None
        self._channels.clear()
        self.token = None

    # --- Befehle --------------------------------------------------------------

    async def _reply(self, hdr: FrameHeader, msg: dict[str, Any]) -> None:
        msg = {"cmdId": hdr.cmd_id, **msg}
        if hdr.seq:
            msg["seq"] = hdr.seq
        body = self.cipher.seal(json.dumps(msg, separators=(",", ":")).encode())
        await self.write(CH_CMD, encode_frame(True, hdr.cmd_id, hdr.seq, body))

    async def _serve(self) -> None:
        from trailcam.pppp.session import SessionClosed

        try:
            await self._serve_loop()
        except (SessionClosed, asyncio.CancelledError):
            return

    async def _serve_loop(self) -> None:
        while True:
            first = await self.read_exactly(CH_CMD, 4)
            size = FrameHeader.peek_size(first)
            hdr = FrameHeader.decode(first + await self.read_exactly(CH_CMD, size - 4))
            body = await self.read_exactly(CH_CMD, hdr.body_len)
            req = json.loads(self.cipher.open(body))
            self.received.append(req)
            await self._handle_cmd(hdr, req)

    async def _handle_cmd(self, hdr: FrameHeader, req: dict[str, Any]) -> None:
        cmd = req.get("cmdId")
        if cmd == Cmd.HEARTBEAT:
            return
        if cmd == Cmd.LOGIN:
            if req.get("usrName") == TEST_USER and req.get("password") == self.password:
                self.token = 44368485
                await self._reply(hdr, {"result": 0, "errorCode": 0, "token": self.token})
            else:
                await self._reply(hdr, {"result": -1, "errorCode": 1})
            return
        if req.get("token") != self.token or self.token is None:
            await self._reply(hdr, {"result": -2, "errorCode": 2})
            return
        if cmd == Cmd.LOGOUT:
            self.token = None
            await self._reply(hdr, {"result": 0})
        elif cmd == Cmd.DEVICE_INFO:
            await self._reply(
                hdr,
                {
                    "result": 0,
                    "batPercent": 87,
                    "sdTotalMB": 30436,
                    "sdFreeMB": 29000,
                    "fwVerName": "3.0.0.5",
                    "model": "Wi-Fi TrailCam",
                },
            )
        elif cmd == Cmd.MEDIA_LIST:
            per = int(req["itemCntPerPage"])
            page = int(req["pageNo"])
            files = self.media[page * per : (page + 1) * per]
            await self._reply(hdr, {"mediaFiles": files, "cnt": len(files), "pageNo": page})
        elif cmd in (Cmd.UNKNOWN_258, Cmd.UNKNOWN_259):
            await self._reply(hdr, {"result": 0})
        elif cmd == Cmd.DOWNLOAD:
            if self.fail_downloads > 0:
                self.fail_downloads -= 1
                await self._reply(hdr, {"result": -3})
                return
            data = self.file_bytes(int(req["mediaNum"]))
            await self._reply(hdr, {"result": 0, "fileSize": len(data)})
            await self.write(CH_FILE, data)
        else:
            await self._reply(hdr, {"result": -100})


async def start_fake_camera(
    host: str = "127.0.0.1", port: int = 0, **kw: Any
) -> tuple[FakeCamera, int]:
    loop = asyncio.get_running_loop()
    transport, cam = await loop.create_datagram_endpoint(
        lambda: FakeCamera(**kw), local_addr=(host, port)
    )
    return cam, transport.get_extra_info("sockname")[1]


async def _main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=11941)
    ap.add_argument("--photos", type=int, default=60)
    ap.add_argument("--videos", type=int, default=3)
    ap.add_argument("--drop", type=float, default=0.0, help="Paketverlustrate 0..1")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO)
    cam, port = await start_fake_camera(
        args.host, args.port, photos=args.photos, videos=args.videos, drop_rate=args.drop
    )
    print(f"Fake-Kamera auf {args.host}:{port}, UID {TEST_UID}, Login admin/{TEST_PASSWORD}")
    print(f"Testschlüssel CAM_AES_KEY={TEST_KEY_HEX}")
    print("sha256 der Dateien:")
    for m in cam.media:
        print(" ", m["mediaNum"], hashlib.sha256(cam.file_bytes(m["mediaNum"])).hexdigest()[:16])
    await asyncio.Event().wait()


if __name__ == "__main__":
    with contextlib.suppress(KeyboardInterrupt):
        asyncio.run(_main())
