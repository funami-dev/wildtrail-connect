"""Kommandozeile: ``trailcam info | download | live``."""

from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import ipaddress
import logging
import socket
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

from . import __version__
from .config import ConfigError, Settings, load_settings
from .logging import setup_logging
from .media import MediaItem, ProgressCb, download_all, filter_items, list_media
from .pppp.session import SessionError
from .proto.client import CameraError, Client
from .proto.commands import Cmd
from .proto.crypto import CryptoError

log = logging.getLogger("trailcam")

REQUIRED = ("CAM_PASSWORD", "CAM_UID", "CAM_AES_KEY")
LOW_BATTERY = 10


def local_ip_for(host: str) -> str | None:
    """Lokale IPv4, über die ``host`` erreicht würde (ohne Pakete zu senden)."""
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        try:
            s.connect((host, 9))
            return str(s.getsockname()[0])
        except OSError:
            return None


def check_network(settings: Settings) -> None:
    cam = ipaddress.IPv4Address(settings.cam_host)
    if cam.is_loopback:
        return
    local = local_ip_for(settings.cam_host)
    net = ipaddress.IPv4Network(f"{cam}/24", strict=False)
    if local is None or ipaddress.IPv4Address(local) not in net:
        ssid = settings.wifi_ssid or "TrailCam_…"
        raise SessionError(
            f"Keine lokale Adresse im Kamera-Netz {net}. Bitte mit WLAN {ssid} verbinden."
        )


def _fmt_info(info: dict[str, Any]) -> str:
    keys = [
        ("Modell", "model"),
        ("Firmware", "fwVerName"),
        ("Akku %", "batPercent"),
        ("SD gesamt (MB)", "sdTotalMB"),
        ("SD frei (MB)", "sdFreeMB"),
    ]
    return "\n".join(f"{label:16} {info[k]}" for label, k in keys if k in info)


async def _device_info(client: Client) -> dict[str, Any]:
    info = await client.send_cmd(Cmd.DEVICE_INFO)
    bat = info.get("batPercent")
    log.info(
        "Akku %s%%, SD frei %s/%s MB, Firmware %s",
        bat,
        info.get("sdFreeMB"),
        info.get("sdTotalMB"),
        info.get("fwVerName"),
    )
    if isinstance(bat, int) and bat < LOW_BATTERY:
        log.warning("Akku fast leer (%d %%)!", bat)
    return info


async def cmd_info(settings: Settings, args: argparse.Namespace) -> int:
    async with Client(settings) as client:
        info = await _device_info(client)
        items = await list_media(client)
    print(_fmt_info(info))
    photos = sum(not i.is_video for i in items)
    print(f"{'Dateien':16} {len(items)} ({photos} Fotos, {len(items) - photos} Videos)")
    return 0


def _progress_factory() -> tuple[Callable[[MediaItem], ProgressCb], Callable[[], None]]:
    try:
        from rich.progress import (
            BarColumn,
            DownloadColumn,
            Progress,
            TextColumn,
            TransferSpeedColumn,
        )
    except ImportError:

        def factory(item: MediaItem) -> ProgressCb:
            def cb(done: int, total: int) -> None:
                if done == total:
                    print(f"  {item.filename}  {total} B", file=sys.stderr)

            return cb

        return factory, lambda: None

    progress = Progress(
        TextColumn("{task.description}"),
        BarColumn(),
        DownloadColumn(),
        TransferSpeedColumn(),
        transient=False,
    )
    progress.start()

    def rich_factory(item: MediaItem) -> ProgressCb:
        task = progress.add_task(item.filename, total=None)

        def cb(done: int, total: int) -> None:
            progress.update(task, completed=done, total=total)

        return cb

    return rich_factory, progress.stop


async def cmd_download(settings: Settings, args: argparse.Namespace) -> int:
    if args.delete_after:
        print("--delete-after wird noch nicht unterstützt (Lösch-Befehl unbekannt).")
        return 2
    out = Path(args.out) if args.out else settings.download_dir
    async with Client(settings) as client:
        await _device_info(client)
        items = await list_media(client)
        selected = filter_items(items, args.type, args.since)
        log.info("%d Dateien auf der Karte, %d ausgewählt", len(items), len(selected))
        factory, stop = _progress_factory()
        try:
            res = await download_all(
                client, selected, out, dry_run=args.dry_run, progress_factory=factory
            )
        finally:
            stop()
    verb = "würden geladen" if args.dry_run else "neu"
    print(
        f"{len(res.new)} {verb}, {len(res.skipped)} übersprungen, {len(res.failed)} fehlgeschlagen"
    )
    for name, err in res.failed.items():
        print(f"  FEHLER {name}: {err}", file=sys.stderr)
    return 1 if res.failed else 0


async def cmd_live(settings: Settings, args: argparse.Namespace) -> int:
    print(
        "Livebild ist noch nicht verfügbar: Stream-Befehl und Frame-Header sind unbekannt "
        "(Phase 0, siehe docs/PROTOCOL.md).",
        file=sys.stderr,
    )
    return 2


def _date(s: str) -> dt.date:
    try:
        return dt.date.fromisoformat(s)
    except ValueError as e:
        raise argparse.ArgumentTypeError("Datum im Format YYYY-MM-DD erwartet") from e


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="trailcam", description=__doc__)
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    p.add_argument("-v", "--verbose", action="store_true", help="LOG_LEVEL=DEBUG")
    sub = p.add_subparsers(dest="command", required=True)

    sub.add_parser("info", help="Geräteinfo: Akku, SD, Firmware, Anzahl Dateien")

    d = sub.add_parser("download", help="Alle Dateien der SD-Karte laden")
    d.add_argument("--out", help="Zielordner (Default: DOWNLOAD_DIR)")
    d.add_argument("--since", type=_date, help="Nur Dateien ab diesem Datum (UTC)")
    d.add_argument("--type", choices=("photo", "video", "all"), default="all")
    d.add_argument("--dry-run", action="store_true")
    d.add_argument("--no-thumbs", action="store_true", help="(Thumbnails werden nie geladen)")
    d.add_argument("--delete-after", action="store_true", help="noch nicht unterstützt")

    lv = sub.add_parser("live", help="Livebild (Phase 2, noch nicht verfügbar)")
    lv.add_argument("--out", default="-")
    lv.add_argument("--udp")
    lv.add_argument("--rtsp")
    lv.add_argument("--record")
    lv.add_argument("--seconds", type=int)
    return p


COMMANDS = {"info": cmd_info, "download": cmd_download, "live": cmd_live}


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        settings = load_settings()
    except ConfigError as e:
        print(f"Konfigurationsfehler: {e}", file=sys.stderr)
        return 2
    setup_logging("DEBUG" if args.verbose else settings.log_level, settings.secrets())

    if args.command != "live":
        try:
            settings.require(*REQUIRED)
            check_network(settings)
        except (ConfigError, SessionError) as e:
            print(str(e), file=sys.stderr)
            return 2
    try:
        return asyncio.run(COMMANDS[args.command](settings, args))
    except KeyboardInterrupt:
        print("Abgebrochen.", file=sys.stderr)
        return 130
    except (SessionError, CameraError, CryptoError, TimeoutError) as e:
        log.error("%s", e)
        return 1


if __name__ == "__main__":
    sys.exit(main())
