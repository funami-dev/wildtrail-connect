import pytest

from trailcam.pppp.packets import (
    DeviceId,
    Drw,
    DrwAck,
    MsgType,
    Packet,
    PacketError,
    seq_newer,
)


def test_packet_roundtrip():
    p = Packet(MsgType.DRW, b"hello")
    assert Packet.decode(p.encode()) == p


def test_packet_bad_magic():
    with pytest.raises(PacketError):
        Packet.decode(b"\x00\x00\x00\x00")


def test_drw_roundtrip():
    d = Drw(channel=4, index=0x1234, data=b"payload")
    assert Drw.from_packet(d.to_packet()) == d


def test_drw_ack_roundtrip():
    a = DrwAck(channel=0, indices=(1, 2, 65535))
    assert DrwAck.from_packet(a.to_packet()) == a


def test_device_id_roundtrip():
    did = DeviceId.parse("LBCS-000042-ABCDE")
    assert str(did) == "LBCS-000042-ABCDE"
    assert DeviceId.decode(did.encode()) == did


def test_seq_newer_wraparound():
    assert seq_newer(5, 4)
    assert not seq_newer(4, 5)
    assert seq_newer(1, 65535)
    assert not seq_newer(65535, 1)
