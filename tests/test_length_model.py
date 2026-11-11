"""Regressionstest für das Längenmodell aus SPEC §3.4."""

import pytest

from trailcam.proto.frame import expected_wire_len

# (JSON-Länge, ist_Response, erwartete Wire-Länge) aus dem App-Log
CASES = [
    (13, False, 45),  # Heartbeat: 21 + b64(16) = 21 + 24
    (2271, True, 3073),  # Geräteinfo: 41 + b64(2272) = 41 + 3032
]


@pytest.mark.parametrize("json_len,is_resp,expected", CASES)
def test_wire_length(json_len, is_resp, expected):
    assert expected_wire_len(json_len, is_resp) == expected
