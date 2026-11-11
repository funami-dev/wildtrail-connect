#!/usr/bin/env python3
"""Schwärzt Secrets in App-Logs, bevor sie geteilt werden.

Ersetzt Passwörter, WLAN-Passwort, UID und MAC-Adressen durch ***.

    python tools/redact_log.py app.log > app.redacted.log
    python tools/redact_log.py < app.log > app.redacted.log
"""

from __future__ import annotations

import argparse
import re
import sys
from collections.abc import Iterable

MASK = "***"

PATTERNS: tuple[re.Pattern[str], ...] = (
    # JSON- und key=value-Felder
    re.compile(r'("(?:password|pwd|passwd|key|aesKey)"\s*:\s*)"(?:[^"\\]|\\.)*"', re.I),
    re.compile(r"\b((?:password|pwd|wifi_?password|aes_?key)\s*[=:]\s*)\S+", re.I),
    # PPCS-UID, z. B. LBCS-000000-ABCDE
    re.compile(r"\b[A-Z]{3,7}-?\d{4,9}-?[A-Z0-9]{3,8}\b"),
    # MAC-Adressen
    re.compile(r"\b(?:[0-9A-Fa-f]{2}[:-]){5}[0-9A-Fa-f]{2}\b"),
)


def redact_line(line: str) -> str:
    line = PATTERNS[0].sub(lambda m: f'{m.group(1)}"{MASK}"', line)
    line = PATTERNS[1].sub(lambda m: f"{m.group(1)}{MASK}", line)
    for pat in PATTERNS[2:]:
        line = pat.sub(MASK, line)
    return line


def redact(lines: Iterable[str]) -> Iterable[str]:
    return (redact_line(line) for line in lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("file", nargs="?", help="Logdatei (Default: stdin)")
    args = ap.parse_args(argv)
    import contextlib

    with contextlib.ExitStack() as stack:
        if args.file:
            src = stack.enter_context(open(args.file, encoding="utf-8", errors="replace"))
        else:
            src = sys.stdin
        for line in redact(src):
            sys.stdout.write(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
