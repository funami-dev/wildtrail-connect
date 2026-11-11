"""Logging-Setup mit zentralem Secret-Masking."""

from __future__ import annotations

import logging
import re
import sys
from collections.abc import Iterable

MASK = "***"

# JSON-Feld "password" (auch "pwd"), egal ob als String oder Zahl
_JSON_SECRET_RE = re.compile(r'("(?:password|pwd|passwd)"\s*:\s*)("(?:[^"\\]|\\.)*"|[^,}\s]+)')
# key=value-Form, z. B. in repr() oder Kommandozeilen
_KV_SECRET_RE = re.compile(
    r"((?:CAM_PASSWORD|WIFI_PASSWORD|CAM_AES_KEY|password|pwd)\s*[=:]\s*)(['\"]?)([^\s,'\"}]+)\2",
    re.IGNORECASE,
)


class SecretMaskingFilter(logging.Filter):
    """Ersetzt bekannte Secret-Werte und Passwortfelder durch ``***``.

    Der Filter formatiert die Nachricht vorab (``record.getMessage()``), damit auch
    Secrets in ``args`` erfasst werden, und setzt danach ``args`` zurück.
    """

    def __init__(self, secrets: Iterable[str] = ()) -> None:
        super().__init__()
        self._secrets: list[str] = []
        self.add_secrets(secrets)

    def add_secrets(self, secrets: Iterable[str]) -> None:
        for s in secrets:
            if s and s not in self._secrets:
                self._secrets.append(s)
        # Längste zuerst, damit Teilstrings nicht zuerst ersetzt werden
        self._secrets.sort(key=len, reverse=True)

    def mask(self, text: str) -> str:
        for s in self._secrets:
            text = text.replace(s, MASK)
        text = _JSON_SECRET_RE.sub(lambda m: f'{m.group(1)}"{MASK}"', text)
        text = _KV_SECRET_RE.sub(lambda m: f"{m.group(1)}{MASK}", text)
        return text

    def filter(self, record: logging.LogRecord) -> bool:
        msg = record.getMessage()
        if record.exc_info and not record.exc_text:
            record.exc_text = logging.Formatter().formatException(record.exc_info)
        if record.exc_text:
            record.exc_text = self.mask(record.exc_text)
        record.msg = self.mask(msg)
        record.args = None
        return True


_filter = SecretMaskingFilter()


def get_masking_filter() -> SecretMaskingFilter:
    return _filter


def setup_logging(level: str = "INFO", secrets: Iterable[str] = ()) -> SecretMaskingFilter:
    """Konfiguriert den Root-Logger (stderr) mit Secret-Masking auf dem Handler."""
    _filter.add_secrets(secrets)
    root = logging.getLogger()
    root.setLevel(level)
    for h in list(root.handlers):
        if getattr(h, "_trailcam", False):
            root.removeHandler(h)
    handler = logging.StreamHandler(sys.stderr)
    handler._trailcam = True  # type: ignore[attr-defined]
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s"))
    handler.addFilter(_filter)
    root.addHandler(handler)
    return _filter


def add_file_handler(path: str) -> None:
    handler = logging.FileHandler(path, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s"))
    handler.addFilter(_filter)
    logging.getLogger().addHandler(handler)
