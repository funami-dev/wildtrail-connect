import datetime as dt

from trailcam.media import Manifest, MediaItem, already_downloaded, filter_items

PHOTO = {
    "fileType": 2,
    "mediaDirNum": 100,
    "mediaNum": 3,
    "durationMs": 0,
    "mediaId": 100003,
    "mediaTime": 1762000000,
}
VIDEO = {
    "fileType": 1,
    "mediaDirNum": 100,
    "mediaNum": 9,
    "durationMs": 10000,
    "mediaId": 100009,
    "mediaTime": 1762100000,
}


def test_filename_photo():
    it = MediaItem.from_json(PHOTO)
    assert not it.is_video
    assert it.filename.endswith("_100-0003.jpg")
    assert it.filename.startswith("2025")


def test_filename_video():
    it = MediaItem.from_json(VIDEO)
    assert it.is_video
    assert it.filename.endswith("_100-0009.mp4")


def test_filter_type_and_since():
    items = [MediaItem.from_json(PHOTO), MediaItem.from_json(VIDEO)]
    assert len(filter_items(items, "photo")) == 1
    assert len(filter_items(items, "video")) == 1
    assert len(filter_items(items, "all")) == 2
    since = dt.date(2025, 11, 2)
    assert all(i.is_video for i in filter_items(items, "all", since))


def test_manifest_roundtrip_and_skip(tmp_path):
    it = MediaItem.from_json(PHOTO)
    target = tmp_path / it.filename
    target.write_bytes(b"x" * 1234)
    m = Manifest(tmp_path)
    # Datei existiert, nicht leer, nicht im Manifest -> als vorhanden behandeln (überspringen)
    assert already_downloaded(target, m)
    m.add(it, target, "abc")
    m.save()
    m2 = Manifest(tmp_path)
    assert already_downloaded(target, m2)
    target.write_bytes(b"y" * 9999)
    assert not already_downloaded(target, m2)  # Größe passt nicht


def test_already_downloaded_empty_file(tmp_path):
    it = MediaItem.from_json(PHOTO)
    target = tmp_path / it.filename
    target.write_bytes(b"")
    assert not already_downloaded(target, Manifest(tmp_path))
