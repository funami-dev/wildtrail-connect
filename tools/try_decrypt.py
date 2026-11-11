#!/usr/bin/env python3
"""Phase-0-Helfer: versucht, den Base64-Teil eines Frames zu entschlüsseln.

Trennt den Header ab (21 Byte Request, 41 Byte Response), nimmt den Base64-Body
und probiert einen Kandidatenschlüssel in allen Modi. Erfolg = valides JSON.

    python tools/try_decrypt.py --hex <frame-hex> --key <aes-hex>
    python tools/try_decrypt.py --b64 <body-b64> --key <aes-hex>
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from trailcam.proto.crypto import MODES, CryptoError, PayloadCipher  # noqa: E402
from trailcam.proto.frame import REQUEST_HEADER_LEN, RESPONSE_HEADER_LEN  # noqa: E402


def extract_body(frame: bytes) -> bytes:
    for hdr in (REQUEST_HEADER_LEN, RESPONSE_HEADER_LEN):
        if len(frame) > hdr:
            tail = frame[hdr:]
            try:
                tail.decode("ascii")
                return tail
            except UnicodeDecodeError:
                continue
    return frame


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--hex", help="komplettes Frame als Hex")
    g.add_argument("--b64", help="nur der Base64-Body")
    ap.add_argument("--key", required=True, help="AES-Schlüssel als Hex")
    ap.add_argument("--mode", choices=(*MODES, "all"), default="all")
    args = ap.parse_args(argv)

    body = args.b64.encode() if args.b64 else extract_body(bytes.fromhex(args.hex))
    key = bytes.fromhex(args.key)
    modes = MODES if args.mode == "all" else (args.mode,)

    for mode in modes:
        try:
            plain = PayloadCipher(key, mode).open(body)
            parsed = json.loads(plain)
        except (CryptoError, ValueError):
            print(f"[{mode:9}] kein valides JSON")
            continue
        print(f"[{mode:9}] TREFFER: {json.dumps(parsed, ensure_ascii=False)}")
        return 0
    print("Kein Modus ergab valides JSON. Schlüssel oder Header-Länge prüfen.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
