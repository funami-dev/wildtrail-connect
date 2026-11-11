import json

import pytest

from trailcam.proto.crypto import (
    BLOCK,
    CryptoError,
    PayloadCipher,
    b64_len,
    padded_len,
    pkcs7_pad,
    pkcs7_unpad,
)

KEY = bytes.fromhex("000102030405060708090a0b0c0d0e0f")


@pytest.mark.parametrize("n", range(0, 40))
def test_pkcs7_roundtrip(n):
    data = bytes(range(n % 256)) * (1 + n // 10)
    data = data[:n]
    padded = pkcs7_pad(data)
    assert len(padded) % BLOCK == 0
    assert len(padded) > len(data)
    assert pkcs7_unpad(padded) == data


def test_pkcs7_rejects_bad_padding():
    with pytest.raises(CryptoError):
        pkcs7_unpad(b"\x00" * 16)
    with pytest.raises(CryptoError):
        pkcs7_unpad(b"abc")


@pytest.mark.parametrize("mode", ["ecb", "cbc-zero", "cbc-key"])
def test_cipher_roundtrip(mode):
    c = PayloadCipher(KEY, mode)
    payload = json.dumps({"cmdId": 0, "x": "ä" * 10}).encode()
    sealed = c.seal(payload)
    assert c.open(sealed) == payload


def test_open_rejects_garbage():
    c = PayloadCipher(KEY, "ecb")
    with pytest.raises(CryptoError):
        c.open(b"!!!!not base64!!!!")


def test_bad_key_length():
    with pytest.raises(CryptoError):
        PayloadCipher(b"short", "ecb")


def test_len_helpers():
    assert padded_len(13) == 16
    assert padded_len(16) == 32  # PKCS#7 fügt immer an
    assert b64_len(16) == 24
    assert b64_len(2272) == 3032
