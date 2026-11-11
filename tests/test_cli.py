from trailcam.cli import build_parser, main


def test_parser_download_defaults():
    args = build_parser().parse_args(["download"])
    assert args.command == "download"
    assert args.type == "all"


def test_missing_config_exits_2(monkeypatch, capsys):
    for var in ("CAM_PASSWORD", "CAM_UID", "CAM_AES_KEY"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("CAM_HOST", "192.168.43.1")
    rc = main(["info"])
    assert rc == 2
    assert "Fehlende Konfiguration" in capsys.readouterr().err


def test_live_not_available(capsys):
    rc = main(["live"])
    assert rc == 2
    assert "noch nicht" in capsys.readouterr().err.lower()
