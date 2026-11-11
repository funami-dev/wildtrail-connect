"""Integrationstest: echter Client gegen tools/fake_camera.py über localhost-UDP."""

import hashlib

import pytest
from fake_camera import TEST_KEY_HEX, TEST_PASSWORD, TEST_UID, start_fake_camera

from trailcam.config import Settings
from trailcam.media import download_all, list_media
from trailcam.proto.client import CameraError, Client
from trailcam.proto.commands import Cmd
from trailcam.proto.crypto import PayloadCipher


def make_settings(port: int, **kw) -> Settings:
    defaults = dict(
        cam_host="127.0.0.1",
        cam_port=port,
        cam_uid=TEST_UID,
        cam_user="admin",
        cam_password=TEST_PASSWORD,
        cam_aes_key=TEST_KEY_HEX,
        cam_aes_mode="ecb",
    )
    defaults.update(kw)
    return Settings(**defaults)


async def _client(port: int, **kw):
    s = make_settings(port, **kw)
    return Client(
        s, PayloadCipher(bytes.fromhex(TEST_KEY_HEX), "ecb"), timeout=5.0, heartbeat_interval=0.2
    )


@pytest.mark.asyncio
async def test_login_info_and_list():
    cam, port = await start_fake_camera(photos=5, videos=2)
    try:
        async with await _client(port) as client:
            info = await client.send_cmd(Cmd.DEVICE_INFO)
            assert info["batPercent"] == 87
            items = await list_media(client, page_size=3)  # erzwingt Paginierung
            assert len(items) == 7
    finally:
        cam._abort()


@pytest.mark.asyncio
async def test_bad_password_fails_login():
    cam, port = await start_fake_camera()
    try:
        c = await _client(port)
        c.settings = make_settings(port, cam_password="wrong")
        with pytest.raises(CameraError):
            async with c:
                pass
    finally:
        cam._abort()


@pytest.mark.asyncio
async def test_download_is_idempotent_and_correct(tmp_path):
    cam, port = await start_fake_camera(photos=4, videos=1)
    expected = {}
    for m in cam.media:
        data = cam.file_bytes(m["mediaNum"])
        expected[m["mediaNum"]] = hashlib.sha256(data).hexdigest()
    try:
        async with await _client(port) as client:
            items = await list_media(client)
            res = await download_all(client, items, tmp_path)
        assert len(res.new) == 5
        assert not res.failed
        # Inhalte stimmen
        files = sorted(tmp_path.glob("2025*"))
        assert len(files) == 5
        for f, item in zip(files, sorted(items, key=lambda i: i.media_num), strict=True):
            got = hashlib.sha256(f.read_bytes()).hexdigest()
            assert got == expected[item.media_num]
        # kein .part übrig
        assert not list(tmp_path.glob("*.part"))

        # zweiter Lauf lädt nichts erneut
        async with await _client(port) as client:
            items = await list_media(client)
            res2 = await download_all(client, items, tmp_path)
        assert not res2.new
        assert len(res2.skipped) == 5
    finally:
        cam._abort()


@pytest.mark.asyncio
async def test_download_retries_then_recovers(tmp_path):
    cam, port = await start_fake_camera(photos=2, videos=0, fail_downloads=1)
    try:
        async with await _client(port) as client:
            items = await list_media(client)
            res = await download_all(client, items, tmp_path)
        # Erster Download schlägt einmal fehl, Retry gelingt -> am Ende alles da
        assert len(res.new) == 2
        assert not res.failed
    finally:
        cam._abort()


@pytest.mark.asyncio
async def test_dry_run_writes_nothing(tmp_path):
    cam, port = await start_fake_camera(photos=3, videos=0)
    try:
        async with await _client(port) as client:
            items = await list_media(client)
            res = await download_all(client, items, tmp_path, dry_run=True)
        assert len(res.new) == 3
        assert not list(tmp_path.glob("2025*"))
    finally:
        cam._abort()
