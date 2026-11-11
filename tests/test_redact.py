import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

from redact_log import redact_line


def test_redacts_uid():
    assert "LBCS-000000-ABCDE" not in redact_line("UID=LBCS-000000-ABCDE connected")


def test_redacts_mac():
    assert "AA:BB:CC:DD:EE:FF" not in redact_line("mac AA:BB:CC:DD:EE:FF")


def test_redacts_json_password():
    out = redact_line('{"ssid":"Trail","pwd":"secret99"}')
    assert "secret99" not in out
    assert "Trail" in out


def test_redacts_wifi_password_kv():
    assert "letmein" not in redact_line("WIFI_PASSWORD=letmein")
