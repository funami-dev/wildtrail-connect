# TrailCam-Protokoll (Arbeitsstand)

Dieses Dokument hält fest, was über das Protokoll **bekannt**, **hergeleitet**
oder noch **offen** ist. Es enthält **keine** echten Schlüssel oder Zugangsdaten.

Quelle der Ausgangsfakten: Debug-Log der iOS-App 2.11.21 (siehe SPEC §3).

## Schichten

```
UDP  ──  PPPP/PPCS  ──  Frame-Header  ──  Base64  ──  AES  ──  JSON
         (Magic 0xF1)   (21/41 Byte)                  (Block 16)
```

- **PPPP/PPCS** (`trailcam/pppp/`): UDP-Transport, LAN-Direktverbindung,
  DRW-Datenkanäle mit Index/ACK/Retransmit. Entspricht grob der von
  palant.info und `magicus/pppp-dissector` dokumentierten Struktur.
- **Frame-Header** (`trailcam/proto/frame.py`): trennt den Bytestrom eines
  Kanals in Nachrichten. Länge bekannt (21 Request / 41 Response), **Layout offen**.
- **Krypto** (`trailcam/proto/crypto.py`): AES + PKCS#7 + Base64.
- **Befehle** (`trailcam/proto/client.py`): JSON mit `cmdId`, `token`, `seq`.

## Längenmodell (bestätigt, SPEC §3.4)

Für alle 5 Requests und alle Responses im Log passt exakt:

```
request  = 21 Byte Header + Base64( AES_block( PKCS7(JSON) ) )
response = 41 Byte Header + Base64( AES_block( PKCS7(JSON) ) )
```

In `tests/test_length_model.py` als Regressionstest hinterlegt
(Heartbeat 13 → 45 Byte, Geräteinfo 2271 → 3073 Byte).

## Verbindungsablauf

1. (optional) BLE weckt das WLAN und liefert `{ssid, pwd, bssid}` (Phase 1b).
2. Client verbindet sich mit dem Hotspot (`192.168.43.1/24`).
3. PPPP-LAN-Handshake: `LAN_SEARCH → PUNCH_PKT → P2P_RDY`.
4. `cmdId 0` Login → `token`.
5. Befehle tragen `token` + fortlaufendes `seq` (ab 1).
6. Heartbeat `cmdId 525` alle ~3 s, ohne Token, `seq` ab `0x10001`.
7. Logout, dann Connect-Break (`CLOSE`).

## Befehle (cmdId)

| cmdId | Zweck | Status |
|---|---|---|
| 0 | Login | bekannt |
| 1 | Logout | **vermutet** (Wert unbestätigt) |
| 258 / 259 | Seite betreten/verlassen? Stream-Steuerung? | offen |
| 512 | Geräteinfo/Settings | bekannt |
| 525 | Heartbeat | bekannt |
| 768 | Medienliste (seitenweise, 48/Seite) | bekannt |
| 772 | Thumbnails (separater Kanal) | bekannt |
| Datei-Download | **unbekannt** | **Phase 0** |
| Livestream start/stop | unbekannt (evtl. Login `needVideo:1`) | **Phase 0** |

`fileType 2` = Foto (`durationMs 0`). Videos: vermutlich anderer Typ mit `durationMs > 0`.

## Kanäle

`PPCS_Read` meldet Kanäle 3 und 6. Getrennte Threads laut Log: cmd, event, AV,
thumbnail, OTA. Die Zuordnung Kanalnummer → Funktion ist **offen**; die
Konstanten in `trailcam/proto/commands.py` sind vorläufig.

## Offene Punkte (Phase 0)

| # | Thema | Blockiert |
|---|---|---|
| 1 | AES-Schlüssel + Modus (ECB/CBC, IV) | alles |
| 2 | echtes Frame-Header-Layout (21/41 Byte) | Feldzuordnung |
| 3 | Download-cmdId + Datei-Stream-Format | Phase 1 (echte HW) |
| 4 | Stream-Start-cmdId + Frame-Header | Phase 2 |
| 5 | Zusätzliche PPPP-Verschleierung? | evtl. Transport |

### So wird Phase 0 abgeschlossen

1. **Mitschnitt** erzeugen: App-Log + pcap mit einem Foto- und Video-Download
   und 10 s Live-Ansicht. Ablage in `captures/` (gitignored).
2. **Schlüssel suchen**: Android-App mit `jadx`/`Ghidra` (Suchbegriffe
   `EC_Login`, `AES`, `PPCS_Initialize`), alternativ Frida-Hook auf
   `AES_set_encrypt_key`/`CCCrypt`. Ergebnis → `.env` `CAM_AES_KEY`, **nie ins Repo**.
3. **Bestätigen**: `python tools/try_decrypt.py --hex <frame> --key <hex>` muss
   das JSON aus dem App-Log liefern.
4. **Header entschlüsseln**: `tools/pcap_extract.py` reassembliert die DRW-Payloads;
   die 21/41-Byte-Präfixe mit mehreren Mitschnitten vergleichen (Magic, Länge,
   seq, Kanal) und `trailcam/proto/frame.py` an das echte Layout anpassen.
5. **Download/Stream**: cmdIds und Chunk-/Frame-Format aus dem Download- bzw.
   Live-Mitschnitt ablesen und `trailcam/media.py` bzw. `trailcam/live.py` füllen.

**Exit-Kriterium:** `try_decrypt.py` entschlüsselt einen echten Request zum
geloggten JSON **und** der Download-Befehl ist bekannt.

## Vorläufiges Framing (nur Emulator/Tests)

Bis Phase 0 abgeschlossen ist, benutzen `tools/fake_camera.py` und die Tests ein
*Platzhalter*-Header-Layout mit den korrekten Längen (Magic `ECRQ`/`ECRS`,
Version, cmdId, seq, bodyLen). Es dient **nur** dazu, die Transport-, Krypto-
und Download-Logik hardwareunabhängig zu testen, und wird bei Phase-0-Abschluss
durch das echte Layout ersetzt. Es spiegelt **nicht** das Format der echten Kamera.
