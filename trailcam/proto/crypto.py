"""AES + PKCS#7 + Base64 für die JSON-Nutzdaten.

Schlüssel und Modus sind noch unbekannt (Phase 0). Unterstützte Hypothesen:

* ``ecb``      AES-ECB
* ``cbc-zero`` AES-CBC mit IV = 16 × 0x00
* ``cbc-key``  AES-CBC mit IV = erste 16 Byte des Schlüssels
"""

from __future__ import annotations

import base64
import binascii
from dataclasses import dataclass, field

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

BLOCK = 16
MODES = ("ecb", "cbc-zero", "cbc-key")


class CryptoError(ValueError):
    pass


def pkcs7_pad(data: bytes, block: int = BLOCK) -> bytes:
    n = block - len(data) % block
    return data + bytes([n]) * n


def pkcs7_unpad(data: bytes, block: int = BLOCK) -> bytes:
    if not data or len(data) % block:
        raise CryptoError("Länge ist kein Vielfaches der Blockgröße")
    n = data[-1]
    if not 1 <= n <= block or data[-n:] != bytes([n]) * n:
        raise CryptoError("Ungültiges PKCS#7-Padding")
    return data[:-n]


def padded_len(n: int, block: int = BLOCK) -> int:
    """Länge nach PKCS#7 (immer mindestens 1 Byte Padding)."""
    return (n // block + 1) * block


def zero_padded_len(n: int, block: int = BLOCK) -> int:
    """Länge nach Null-Padding (kein Extra-Block bei exakter Länge)."""
    return -(-n // block) * block


def b64_len(n: int) -> int:
    return 4 * -(-n // 3)


@dataclass(frozen=True)
class PayloadCipher:
    key: bytes = field(repr=False)
    mode: str = "ecb"

    def __post_init__(self) -> None:
        if len(self.key) not in (16, 24, 32):
            raise CryptoError("AES-Schlüssel muss 16, 24 oder 32 Byte lang sein")
        if self.mode not in MODES:
            raise CryptoError(f"Unbekannter Modus {self.mode!r}")

    def _cipher(self) -> Cipher[modes.ECB] | Cipher[modes.CBC]:
        alg = algorithms.AES(self.key)
        if self.mode == "ecb":
            return Cipher(alg, modes.ECB())
        iv = bytes(BLOCK) if self.mode == "cbc-zero" else self.key[:BLOCK]
        return Cipher(alg, modes.CBC(iv))

    def encrypt(self, plaintext: bytes) -> bytes:
        enc = self._cipher().encryptor()
        return bytes(enc.update(pkcs7_pad(plaintext)) + enc.finalize())

    def decrypt(self, ciphertext: bytes) -> bytes:
        if len(ciphertext) % BLOCK:
            raise CryptoError("Ciphertext-Länge ist kein Vielfaches von 16")
        dec = self._cipher().decryptor()
        return pkcs7_unpad(bytes(dec.update(ciphertext) + dec.finalize()))

    def seal(self, plaintext: bytes) -> bytes:
        """JSON-Bytes → Base64(AES(...))."""
        return base64.b64encode(self.encrypt(plaintext))

    def open(self, sealed: bytes) -> bytes:
        """Base64(AES(...)) → JSON-Bytes."""
        try:
            raw = base64.b64decode(sealed.strip(b"\0 \r\n"), validate=True)
        except binascii.Error as e:
            raise CryptoError(f"Kein gültiges Base64: {e}") from e
        return self.decrypt(raw)
