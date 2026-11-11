"""Medienliste, Dateinamen, Download mit .part/atomarem Rename, Manifest."""

from __future__ import annotations

import contextlib
import datetime as dt
import hashlib
import json
import logging
import os
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .proto.client import CameraError, Client
from .proto.commands import CH_FILE, Cmd, FileType

log = logging.getLogger(__name__)

PAGE_SIZE = 48
MANIFEST = "manifest.json"
DOWNLOAD_RETRIES = 2

ProgressCb = Callable[[int, int], None]


@dataclass(frozen=True)
class MediaItem:
    file_type: int
    dir_num: int
    media_num: int
    media_id: int | str
    media_time: int
    duration_ms: int = 0
    raw: dict[str, Any] = field(default_factory=dict, compare=False, hash=False, repr=False)

    @classmethod
    def from_json(cls, d: dict[str, Any]) -> MediaItem:
        return cls(
            file_type=int(d["fileType"]),
            dir_num=int(d["mediaDirNum"]),
            media_num=int(d["mediaNum"]),
            media_id=d.get("mediaId", f"{d['mediaDirNum']}-{d['mediaNum']}"),
            media_time=int(d.get("mediaTime", 0)),
            duration_ms=int(d.get("durationMs", 0)),
            raw=d,
        )

    @property
    def is_video(self) -> bool:
        # fileType 2 = Foto (bestätigt durch durationMs 0); Videos haben eine Dauer
        return self.duration_ms > 0 or self.file_type == FileType.VIDEO

    @property
    def extension(self) -> str:
        return "mp4" if self.is_video else "jpg"

    @property
    def timestamp(self) -> dt.datetime:
        return dt.datetime.fromtimestamp(self.media_time, tz=dt.UTC)

    @property
    def filename(self) -> str:
        ts = self.timestamp.strftime("%Y%m%d_%H%M%S")
        return f"{ts}_{self.dir_num}-{self.media_num:04d}.{self.extension}"


def filter_items(
    items: Iterable[MediaItem], kind: str = "all", since: dt.date | None = None
) -> list[MediaItem]:
    out = []
    for it in items:
        if kind == "photo" and it.is_video:
            continue
        if kind == "video" and not it.is_video:
            continue
        if since and it.timestamp.date() < since:
            continue
        out.append(it)
    return out


async def list_media(client: Client, page_size: int = PAGE_SIZE) -> list[MediaItem]:
    """Paginiert cmdId 768, bis eine Seite weniger als ``page_size`` Einträge hat."""
    items: list[MediaItem] = []
    page = 0
    while True:
        resp = await client.send_cmd(Cmd.MEDIA_LIST, itemCntPerPage=page_size, pageNo=page)
        files = resp.get("mediaFiles") or []
        items.extend(MediaItem.from_json(f) for f in files)
        cnt = int(resp.get("cnt", len(files)))
        log.debug("Seite %d: %d Einträge", page, cnt)
        if cnt < page_size:
            break
        page += 1
    return items


# --- Manifest -------------------------------------------------------------------


class Manifest:
    def __init__(self, directory: Path) -> None:
        self.path = directory / MANIFEST
        self.entries: dict[str, dict[str, Any]] = {}
        if self.path.exists():
            try:
                data = json.loads(self.path.read_text("utf-8"))
                self.entries = {e["name"]: e for e in data.get("files", [])}
            except (ValueError, KeyError) as e:
                log.warning("manifest.json unlesbar (%s), beginne neu", e)

    def get(self, name: str) -> dict[str, Any] | None:
        return self.entries.get(name)

    def add(self, item: MediaItem, path: Path, sha256: str) -> None:
        self.entries[path.name] = {
            "mediaId": item.media_id,
            "name": path.name,
            "size": path.stat().st_size,
            "sha256": sha256,
            "downloadedAt": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
        }

    def save(self) -> None:
        tmp = self.path.with_suffix(".json.part")
        files = sorted(self.entries.values(), key=lambda e: e["name"])
        tmp.write_text(json.dumps({"files": files}, indent=2, ensure_ascii=False), "utf-8")
        os.replace(tmp, self.path)


def already_downloaded(path: Path, manifest: Manifest) -> bool:
    if not path.exists():
        return False
    size = path.stat().st_size
    if size == 0:
        return False
    entry = manifest.get(path.name)
    return entry is None or entry.get("size") == size


# --- Download -------------------------------------------------------------------


async def fetch_file(client: Client, item: MediaItem, out: Any, progress: ProgressCb) -> int:
    """Überträgt eine Datei in das Dateiobjekt ``out``.

    TODO(Phase 0): Download-cmdId und Datei-Stream-Format sind unbekannt. Bis dahin
    gilt das vorläufige Protokoll von tools/fake_camera.py: Antwort enthält
    ``fileSize``, danach kommen genau so viele Rohbytes auf CH_FILE.
    """
    assert client.session is not None
    resp = await client.send_cmd(
        Cmd.DOWNLOAD,
        fileType=item.file_type,
        dirNum=item.dir_num,
        mediaNum=item.media_num,
    )
    total = int(resp["fileSize"])
    done = 0
    while done < total:
        chunk = await client.session.read_some(CH_FILE, timeout=client.timeout)
        chunk = chunk[: total - done]
        out.write(chunk)
        done += len(chunk)
        progress(done, total)
    return total


@dataclass
class DownloadResult:
    new: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    failed: dict[str, str] = field(default_factory=dict)


async def download_one(
    client: Client, item: MediaItem, directory: Path, progress: ProgressCb
) -> tuple[Path, str]:
    target = directory / item.filename
    part = target.with_name(target.name + ".part")
    h = hashlib.sha256()

    class _Hashing:
        def __init__(self, f: Any) -> None:
            self.f = f

        def write(self, b: bytes) -> None:
            h.update(b)
            self.f.write(b)

    # Bei Abbruch (Ctrl-C) bleibt nur die .part-Datei liegen, nie eine halbe Zieldatei.
    with part.open("wb") as f:
        await fetch_file(client, item, _Hashing(f), progress)
        f.flush()
        os.fsync(f.fileno())
    os.replace(part, target)
    return target, h.hexdigest()


async def download_all(
    client: Client,
    items: list[MediaItem],
    directory: Path,
    *,
    dry_run: bool = False,
    progress_factory: Callable[[MediaItem], ProgressCb] | None = None,
) -> DownloadResult:
    directory.mkdir(parents=True, exist_ok=True)
    manifest = Manifest(directory)
    result = DownloadResult()
    try:
        for item in items:
            target = directory / item.filename
            if already_downloaded(target, manifest):
                result.skipped.append(item.filename)
                continue
            if dry_run:
                log.info("[dry-run] würde laden: %s", item.filename)
                result.new.append(item.filename)
                continue
            last_err = ""
            for attempt in range(DOWNLOAD_RETRIES + 1):
                cb = progress_factory(item) if progress_factory else (lambda d, t: None)
                try:
                    path, sha = await download_one(client, item, directory, cb)
                except (CameraError, TimeoutError, OSError, KeyError, ValueError) as e:
                    last_err = f"{type(e).__name__}: {e}"
                    log.warning("%s: Versuch %d fehlgeschlagen: %s", item.filename, attempt + 1, e)
                    with contextlib.suppress(OSError):
                        (directory / (item.filename + ".part")).unlink()
                    continue
                manifest.add(item, path, sha)
                manifest.save()
                result.new.append(item.filename)
                break
            else:
                result.failed[item.filename] = last_err
    finally:
        if not dry_run:
            manifest.save()
    return result
