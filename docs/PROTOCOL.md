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

Aktualisiert anhand des Download-/Lösch-Logs (App 2.11.21).

| cmdId | Zweck | Request (Auszug) | Response (Auszug) | Status |
|---|---|---|---|---|
| 0 | Login | `usrName,password,needVideo,needAudio,utcTime,supportHeartBeat` | `result,errorCode,token` | bekannt |
| 1 | Logout | kein JSON im Log | – | vermutet |
| 258 | Seite betreten | `token,seq` | `result:0` | bekannt |
| 259 | Seite verlassen | `token,seq` | `result:0` | bekannt |
| 512 | Geräteinfo/Settings | `token,seq` | großes JSON (`batPercent,sdTotalMB,…`) | bekannt |
| 513 | Einstellung setzen | z. B. `shootMode:0` | `result:0` | bekannt |
| 525 | Heartbeat | `{"cmdId":525}` (ohne Token) | keine | bekannt |
| 768 | Medienliste | `itemCntPerPage:48,pageNo` | `mediaFiles[],cnt,pageNo` | bekannt |
| **769** | **Download = Playback-Start** | `fileType,dirNum,mediaNum` | `startPbRet,videoWidth,videoHeight,totalFrame,totalTime` | **bekannt; AV-Frames offen** |
| 772 | Thumbnails | `thumbnailReqs[]` | `cmdRet:0` (Daten auf Thumb-Kanal) | bekannt |
| **773** | **Datei löschen** | `fileType,dirNum,mediaNum` | `delRet:0,result:0` | bekannt |

### Download ist ein Playback-Stream

Es gibt **keinen** rohen Dateitransfer. Der Client sendet `cmdId 769` („Start play
cmd"); die Antwort nennt Auflösung, `totalFrame` und `totalTime`. Danach kommen die
Frames über den **AV-Kanal**, und die App remuxt sie zu einer MP4. Das erklärt, warum
die gespeicherte Dateigröße von der Rohgröße auf der Karte abweicht.

- Das **AV-Frame-Layout** (Codec-/Keyframe-/Längen-Header) ist im Textlog nicht
  enthalten und bleibt der Phase-0-Blocker für den echten Download **und** fürs
  Livebild (beide nutzen vermutlich denselben AV-Kanal).
- `fileType 2` wurde im Log als **MP4-Video** (H.264, 1280×720, ~10 s) geladen,
  obwohl `durationMs` in der Liste 0 war. `durationMs` ist also unzuverlässig; ein
  Foto-Beispiel (vermutlich `fileType 1`, JPEG) fehlt noch.

## Kanäle

`PPCS_Read` meldet Kanäle 3 und 6. Getrennte Threads laut Log: cmd, event, AV,
thumbnail, OTA. Die Zuordnung Kanalnummer → Funktion ist **offen**; die
Konstanten in `trailcam/proto/commands.py` sind vorläufig.

## Offene Punkte (Phase 0)

| # | Thema | Blockiert |
|---|---|---|
| 1 | AES-Schlüssel + Modus (ECB/CBC, IV) | alles (Log ist Klartext, pcap nötig) |
| 2 | echtes Frame-Header-Layout (21/41 Byte) | Feldzuordnung |
| 3 | AV-Frame-Layout (Codec/Keyframe/Länge) | Download (769) **und** Livebild |
| 4 | PPPP-Kanalnummern (cmd/event/AV/thumb/OTA) | Reassembly |
| 5 | Zusätzliche PPPP-Verschleierung? | evtl. Transport |

Durch die Logs inzwischen **geklärt**: Download-/Lösch-/Settings-cmdIds (769/773/513),
Seiten-Befehle (258/259), der seitenweise Listenabruf und das Längenmodell aus §3.4
(bestätigt an Login-Response 77→149 Byte, Heartbeat 13→45 Byte, Login-Request →193 Byte).

### So wird Phase 0 abgeschlossen

1. **Mitschnitt** erzeugen: App-Log + pcap mit einem Foto- und Video-Download
   und 10 s Live-Ansicht. Ablage in `captures/` (gitignored). Schritt-für-Schritt
   (Mac direkt bzw. iPhone über rvi): siehe [`CAPTURE.md`](CAPTURE.md).
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
