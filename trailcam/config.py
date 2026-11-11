"""Settings aus Umgebungsvariablen (lokal per .env)."""

from __future__ import annotations

import ipaddress
import os
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

SECRET_ENV_VARS = ("CAM_PASSWORD", "WIFI_PASSWORD", "CAM_AES_KEY")
AES_MODES = ("ecb", "cbc-zero", "cbc-key")


class ConfigError(Exception):
    """Fehlender oder ungültiger Konfigurationswert."""


@dataclass(frozen=True)
class Settings:
    cam_host: str = "192.168.43.1"
    cam_port: int = 11941
    cam_uid: str = ""
    cam_user: str = "admin"
    cam_password: str = field(default="", repr=False)
    wifi_ssid: str = ""
    wifi_password: str = field(default="", repr=False)
    cam_aes_key: str = field(default="", repr=False)
    cam_aes_mode: str = "ecb"
    download_dir: Path = Path("./downloads")
    log_level: str = "INFO"

    @property
    def aes_key_bytes(self) -> bytes:
        return bytes.fromhex(self.cam_aes_key)

    def secrets(self) -> list[str]:
        """Alle Secret-Werte (für den Masking-Filter)."""
        return [s for s in (self.cam_password, self.wifi_password, self.cam_aes_key) if s]

    def require(self, *names: str) -> None:
        """Bricht mit klarer Meldung ab, wenn Pflichtwerte fehlen."""
        missing = [n for n in names if not getattr(self, n.lower())]
        if missing:
            raise ConfigError(
                "Fehlende Konfiguration: "
                + ", ".join(missing)
                + ". Bitte in .env setzen (Vorlage: .env.example)."
            )


def _validate(s: Settings) -> None:
    try:
        ipaddress.IPv4Address(s.cam_host)
    except ValueError as e:
        raise ConfigError(f"CAM_HOST ist keine IPv4-Adresse: {s.cam_host!r}") from e
    if not 0 < s.cam_port < 65536:
        raise ConfigError(f"CAM_PORT ungültig: {s.cam_port}")
    if s.cam_aes_key and (
        not re.fullmatch(r"[0-9a-fA-F]+", s.cam_aes_key) or len(s.cam_aes_key) not in (32, 48, 64)
    ):
        raise ConfigError("CAM_AES_KEY muss 16, 24 oder 32 Byte als Hex sein.")
    if s.cam_aes_mode not in AES_MODES:
        raise ConfigError(f"CAM_AES_MODE muss eines von {AES_MODES} sein.")
    if s.cam_uid and not re.fullmatch(r"[A-Z]{1,7}-?\d{1,9}-?[A-Z]{0,8}", s.cam_uid):
        raise ConfigError("CAM_UID hat kein gültiges Format (erwartet z. B. LBCS-000000-XXXXX).")


def load_settings(env: Mapping[str, str] | None = None, dotenv: bool = True) -> Settings:
    """Lädt Settings aus ``env`` (Default: os.environ, vorher .env eingelesen)."""
    if env is None:
        if dotenv:
            from dotenv import load_dotenv

            load_dotenv(override=False)
        env = os.environ

    def get(name: str, default: str = "") -> str:
        return env.get(name, default).strip()

    try:
        port = int(get("CAM_PORT", "11941"))
    except ValueError as e:
        raise ConfigError("CAM_PORT muss eine Zahl sein.") from e

    s = Settings(
        cam_host=get("CAM_HOST", "192.168.43.1"),
        cam_port=port,
        cam_uid=get("CAM_UID"),
        cam_user=get("CAM_USER", "admin"),
        cam_password=get("CAM_PASSWORD"),
        wifi_ssid=get("WIFI_SSID"),
        wifi_password=get("WIFI_PASSWORD"),
        cam_aes_key=get("CAM_AES_KEY"),
        cam_aes_mode=get("CAM_AES_MODE", "ecb").lower(),
        download_dir=Path(get("DOWNLOAD_DIR", "./downloads")),
        log_level=get("LOG_LEVEL", "INFO").upper(),
    )
    _validate(s)
    return s
