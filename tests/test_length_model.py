"""Regressionstest für das Längenmodell aus SPEC §3.4.

Bestätigt an echten Sende-/Empfangslängen aus den App-Logs.
"""

import pytest

from trailcam.proto.frame import expected_wire_len

# (JSON-Länge, ist_Response, erwartete Wire-Länge) aus den App-Logs
CASES = [
    (13, False, 45),  # Heartbeat: 21 + b64(pad(13)=16) = 21 + 24
    (2271, True, 3073),  # Geräteinfo: 41 + b64(2272) = 41 + 3032
    (77, True, 149),  # Login-Response: dataLen 77 -> pad 80, 41 + b64(80) = 41 + 108
]


@pytest.mark.parametrize("json_len,is_resp,expected", CASES)
def test_wire_length(json_len, is_resp, expected):
    assert expected_wire_len(json_len, is_resp) == expected
