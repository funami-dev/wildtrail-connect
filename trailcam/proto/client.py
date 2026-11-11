"""EasyCam-Client: Login/Logout, Befehle mit token/seq, Heartbeat."""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import time
from types import TracebackType
from typing import Any

from ..config import Settings
from ..pppp.session import Session, SessionClosed
from .commands import CH_CMD, HEARTBEAT_SEQ_START, Cmd
from .crypto import CryptoError, PayloadCipher
from .frame import FrameError, FrameHeader, encode_frame

log = logging.getLogger(__name__)

Json = dict[str, Any]


class CameraError(Exception):
    def __init__(self, cmd_id: int, response: Json) -> None:
        self.cmd_id = cmd_id
        self.response = response
        code = response.get("errorCode", response.get("result", response.get("cmdRet")))
        super().__init__(f"Kamera meldet Fehler bei cmdId {cmd_id}: {code}")


def _is_error(resp: Json) -> bool:
    return any(resp.get(k, 0) not in (0, None) for k in ("result", "cmdRet"))


class Client:
    """Hochsprachiger Client. Als ``async with`` benutzen: loggt immer aus."""

    def __init__(
        self,
        settings: Settings,
        cipher: PayloadCipher | None = None,
        *,
        timeout: float = 10.0,
        heartbeat_interval: float = 3.0,
    ) -> None:
        self.settings = settings
        self.cipher = cipher or PayloadCipher(settings.aes_key_bytes, settings.cam_aes_mode)
        self.timeout = timeout
        self.heartbeat_interval = heartbeat_interval
        self.session: Session | None = None
        self.token: int | str | None = None
        self._seq = 0
        self._hb_seq = HEARTBEAT_SEQ_START
        self._pending: dict[int, tuple[int, asyncio.Future[Json]]] = {}
        self._tasks: list[asyncio.Task[None]] = []
        self.events: asyncio.Queue[Json] = asyncio.Queue(maxsize=256)

    # --- Lebenszyklus ---------------------------------------------------------

    async def __aenter__(self) -> Client:
        await self.connect()
        try:
            await self.login()
        except BaseException:
            await self.close()
            raise
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self.close()

    async def connect(self) -> None:
        s = self.settings
        self.session = await Session.connect(
            s.cam_host, s.cam_port, s.cam_uid or None, timeout=self.timeout
        )
        self._tasks.append(asyncio.get_running_loop().create_task(self._reader()))

    async def login(self, need_video: bool = False, need_audio: bool = False) -> Json:
        s = self.settings
        resp = await self.send_cmd(
            Cmd.LOGIN,
            usrName=s.cam_user,
            password=s.cam_password,
            needVideo=int(need_video),
            needAudio=int(need_audio),
            utcTime=int(time.time()),
            supportHeartBeat=True,
            _auth=False,
        )
        token = resp.get("token", resp.get("Token"))
        if token is None:
            raise CameraError(Cmd.LOGIN, resp)
        self.token = token
        log.info("Login ok")
        self._tasks.append(asyncio.get_running_loop().create_task(self._heartbeat()))
        return resp

    async def close(self) -> None:
        """Logout (best effort) und Connect-Break. Nie eine Exception."""
        for t in self._tasks:
            if t is not asyncio.current_task():
                t.cancel()
        sess = self.session
        if sess is None:
            return
        if self.token is not None and not sess.closed:
            try:
                await self.send_cmd(Cmd.LOGOUT, _timeout=2.0, _retries=0)
            except Exception as e:  # noqa: BLE001 - Logout ist best effort
                log.debug("Logout fehlgeschlagen: %s", e)
            with contextlib.suppress(Exception):
                await sess.drain(CH_CMD, timeout=1.0)
        self.token = None
        await sess.close()
        for f in (fut for _, fut in self._pending.values()):
            if not f.done():
                f.set_exception(SessionClosed("Verbindung geschlossen"))
        self._pending.clear()
        self.session = None
        log.info("Verbindung getrennt")

    # --- Befehle --------------------------------------------------------------

    def _next_seq(self) -> int:
        self._seq += 1
        return self._seq

    async def _send_raw(self, cmd_id: int, seq: int, payload: Json) -> None:
        assert self.session is not None, "nicht verbunden"
        body = json.dumps(payload, separators=(",", ":")).encode()
        log.debug("→ %s", body.decode())
        await self.session.write(CH_CMD, encode_frame(False, cmd_id, seq, self.cipher.seal(body)))

    async def send_cmd(
        self,
        cmd_id: int,
        *,
        _auth: bool = True,
        _timeout: float | None = None,
        _retries: int = 1,
        **fields: Any,
    ) -> Json:
        """Sendet ``{"cmdId": cmd_id, **fields, token, seq}`` und wartet auf die Antwort."""
        if self.session is None:
            raise SessionClosed("nicht verbunden")
        payload: Json = {"cmdId": int(cmd_id), **fields}
        seq = 0
        if _auth:
            seq = self._next_seq()
            payload["token"] = self.token
            payload["seq"] = seq
        key = seq if _auth else -int(cmd_id)
        timeout = self.timeout if _timeout is None else _timeout

        last: Exception | None = None
        for attempt in range(_retries + 1):
            fut: asyncio.Future[Json] = asyncio.get_running_loop().create_future()
            self._pending[key] = (int(cmd_id), fut)
            try:
                await self._send_raw(int(cmd_id), seq, payload)
                resp = await asyncio.wait_for(fut, timeout)
                break
            except TimeoutError as e:
                last = e
                log.warning("Timeout bei cmdId %d (Versuch %d)", cmd_id, attempt + 1)
            finally:
                self._pending.pop(key, None)
        else:
            raise TimeoutError(f"Keine Antwort auf cmdId {cmd_id}") from last

        if _is_error(resp):
            raise CameraError(int(cmd_id), resp)
        return resp

    async def _heartbeat(self) -> None:
        while True:
            await asyncio.sleep(self.heartbeat_interval)
            try:
                await self._send_raw(Cmd.HEARTBEAT, self._hb_seq, {"cmdId": int(Cmd.HEARTBEAT)})
            except SessionClosed:
                return
            self._hb_seq += 1

    # --- Empfang --------------------------------------------------------------

    async def _read_frame(self) -> tuple[FrameHeader, bytes]:
        assert self.session is not None
        sess = self.session
        first = await sess.read_exactly(CH_CMD, 4)
        size = FrameHeader.peek_size(first)
        hdr = FrameHeader.decode(first + await sess.read_exactly(CH_CMD, size - 4))
        body = await sess.read_exactly(CH_CMD, hdr.body_len)
        return hdr, body

    async def _reader(self) -> None:
        while self.session is not None and not self.session.closed:
            try:
                hdr, body = await self._read_frame()
            except SessionClosed:
                return
            except FrameError as e:
                log.error("Frame-Fehler auf Kommandokanal: %s", e)
                return
            try:
                msg: Json = json.loads(self.cipher.open(body))
            except (CryptoError, ValueError) as e:
                log.warning("Antwort nicht entschlüsselbar: %s", e)
                continue
            log.debug("← %s", json.dumps(msg, separators=(",", ":")))
            self._dispatch(hdr, msg)

    def _dispatch(self, hdr: FrameHeader, msg: Json) -> None:
        cmd_id = int(msg.get("cmdId", hdr.cmd_id))
        seq = msg.get("seq", hdr.seq)
        entry = self._pending.get(seq) if seq else None
        if entry is None:
            # Fallback: ältester offener Request mit gleicher cmdId (z. B. Login ohne seq)
            entry = next((e for e in self._pending.values() if e[0] == cmd_id), None)
        if entry is not None and not entry[1].done():
            entry[1].set_result(msg)
            return
        with contextlib.suppress(asyncio.QueueFull):
            self.events.put_nowait(msg)
