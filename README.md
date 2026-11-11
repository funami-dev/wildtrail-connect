# trailcam-dl

Offener Kommandozeilen-Client für die **Wi-Fi-TrailCam** (Ingenic T31, EasyCam-SDK
über CS2 PPCS/PPPP). Verbindet sich ohne die Hersteller-App mit der Kamera.

- **Phase 1 (MVP):** Mit der Kamera verbinden und alle Dateien der SD-Karte
  herunterladen. Schon geladene Dateien werden übersprungen (idempotent).
- **Phase 2:** Livebild (noch nicht verfügbar, siehe unten).

> **Status:** Die Transportschicht (PPPP/UDP), das Befehls-Framing, Krypto, die
> Download-Logik und ein vollständiger Emulator stehen und sind getestet.
> Aus den App-Logs sind inzwischen die cmdIds bekannt (Download = Playback-Start
> `769`, Löschen `773`, Settings `513`, Seiten `258/259`) und das Längenmodell ist
> an echten Werten bestätigt. Was noch an **Phase 0** (Mitschnitt mit echter Kamera)
> hängt: der **AES-Schlüssel/-Modus** (die Logs sind Klartext) und das **AV-Frame-
> Layout** – darüber laufen sowohl der eigentliche Datei-Download als auch das
> Livebild. Diese Stellen sind im Code mit `TODO(Phase 0)` markiert.

## Installation

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev,progress]"
```

Python 3.11+. `ffmpeg` wird erst für Phase 2 (Live) gebraucht.

## Konfiguration

Alle Zugangsdaten kommen aus Umgebungsvariablen bzw. einer lokalen `.env`
(wird nie committet). Vorlage kopieren und ausfüllen:

```bash
cp .env.example .env
$EDITOR .env
```

| Variable | Bedeutung |
|---|---|
| `CAM_HOST` / `CAM_PORT` | Kamera-Hotspot (Default `192.168.43.1:11941`) |
| `CAM_UID` | PPCS-UID, Format `LBCS-000000-XXXXX` |
| `CAM_USER` / `CAM_PASSWORD` | Login (Default-User `admin`) |
| `CAM_AES_KEY` | AES-Schlüssel als Hex (aus Phase 0) |
| `CAM_AES_MODE` | `ecb` \| `cbc-zero` \| `cbc-key` |
| `DOWNLOAD_DIR` | Zielordner |
| `LOG_LEVEL` | `INFO` / `DEBUG` |

## Benutzung

```bash
# Mit dem WLAN der Kamera (TrailCam_…) verbinden, dann:
trailcam info                       # Akku, SD-Belegung, Firmware, Anzahl Dateien
trailcam download                   # alles laden, Bekanntes überspringen
trailcam download --type photo --since 2026-01-01
trailcam download --dry-run         # nur anzeigen, was geladen würde
trailcam download --delete-after    # nach gesichertem Download auf der Kamera löschen (773)
trailcam live                       # Phase 2 (noch nicht verfügbar)
```

Je Datei: Download läuft in eine `*.part`-Datei und wird erst nach vollständigem
Transfer atomar umbenannt. Ein Abbruch hinterlässt also nie eine halbe Zieldatei.
Ein `manifest.json` im Zielordner hält Name, Größe, sha256 und Ladezeitpunkt fest.

## Sicherheit / Secrets

- **Keine Passwörter, Schlüssel oder UIDs im Repository** – nicht in Code, Tests,
  Fixtures, Doku oder Commit-Messages. Alles kommt aus `.env` (gitignored).
- Das Logging maskiert `CAM_PASSWORD`, `WIFI_PASSWORD`, `CAM_AES_KEY` und
  JSON-`password`-Felder zentral durch `***` – auch bei `LOG_LEVEL=DEBUG`
  (per Unit-Test abgesichert).
- `tools/redact_log.py` schwärzt App-Logs (Passwörter, WLAN-Passwort, UID, MAC),
  bevor man sie teilt.
- **pre-commit mit gitleaks** verhindert versehentliche Commits von Secrets:

  ```bash
  pip install pre-commit
  pre-commit install
  ```

  gitleaks läuft außerdem in CI.

## Entwicklung & Tests

Die Integrationstests laufen gegen eine **emulierte Kamera** (`tools/fake_camera.py`),
komplett ohne Hardware – auch in CI.

```bash
ruff check . && ruff format --check .
mypy
pytest -m "not hardware"     # Hardware-Tests brauchen echte Mitschnitte in captures/
```

Die Fake-Kamera lässt sich auch eigenständig starten:

```bash
python tools/fake_camera.py --port 11941 --photos 20 --videos 2
# in .env: CAM_HOST=127.0.0.1, CAM_UID=LBCS-000000-TESTA,
#          CAM_PASSWORD=test1234, CAM_AES_KEY=000102030405060708090a0b0c0d0e0f
trailcam download
```

## Phase 0: Protokoll-Discovery

Einige Protokolldetails sind nur mit echter Kamera ermittelbar. Vorgehen und
Werkzeuge (`tools/pcap_extract.py`, `tools/try_decrypt.py`) sind in
[`docs/PROTOCOL.md`](docs/PROTOCOL.md) beschrieben. Kurz:

1. Neues App-Log mit einem Foto- und Video-Download und 10 s Live-Ansicht.
2. Netzwerkmitschnitt (`captures/`, gitignored) — Anleitung in [`docs/CAPTURE.md`](docs/CAPTURE.md).
3. AES-Schlüssel aus der Android-App ermitteln → in `.env`, **nie ins Repo**.
4. `try_decrypt.py` bestätigt Schlüssel/Modus; `docs/PROTOCOL.md` wird gefüllt.

## Lizenz / Rechtliches

Nur für das eigene Gerät gedacht (Interoperabilität). Keine Hersteller-Binaries
oder -Schlüssel im Repository.
