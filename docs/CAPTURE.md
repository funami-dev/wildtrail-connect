# Netzwerk-Mitschnitt (Phase 0)

So kommst du an einen pcap des Verkehrs zwischen App/Mac und Kamera. Der
Mitschnitt klärt Header-Layout, Kanalnummern und (für Download/Live) das
AV-Frame-Format. Den **AES-Schlüssel** findet man darin nicht — der kommt aus der
App (Android-APK mit `jadx`/Ghidra oder Frida-Hook).

> Ablage immer in `captures/` — der Ordner ist in `.gitignore` und wird nie committet.
> Echte Mitschnitte enthalten Geräte-IDs; vor dem Teilen durch `tools/redact_log.py`
> schicken (für App-Logs) bzw. nur den pcap herausgeben, keine Screenshots mit UID.

## Die Ausgangslage

Die Kamera ist selbst der WLAN-Access-Point (`TrailCam_XXXX`, `192.168.43.1`).
Wer mitschneiden will, muss **am Endgerät** mitschneiden — man kann sich nicht
„dazwischen" hängen, weil die Kamera der Router ist. PPCS läuft über **UDP** zu
`192.168.43.1:11941` (eine zweite Session kann einen anderen Quellport nutzen).
Schnelltest, dass man das Richtige fängt: erstes Byte der UDP-Payload ist **`0xF1`**
(PPPP-Magic).

Zwei Ziele, die **unterschiedliche** Mitschnitte brauchen:

| Ziel | Wer muss reden | Methode |
|---|---|---|
| AES-Schlüssel + Header-Layout bestätigen | egal (Klartext der Befehle ist bekannt) | **Mac direkt** (A) — am einfachsten |
| AV-Frame-Format für Download/Live | die App (iPhone) | **iPhone über rvi** (B) |

Fang mit A an — das ist robust und braucht kein rvi.

---

## Methode A: Mac direkt (für Schlüssel + Header)

Der Mac hängt sich selbst ins Kamera-WLAN und schneidet auf `en0` mit, während
unser Tool die bekannten Befehle (Login, 512, 768) sendet. Weil der Klartext
dieser Befehle aus dem App-Log bekannt ist, reicht das, um mit
`tools/try_decrypt.py` einen Kandidatenschlüssel zu verifizieren. Funktioniert auf
jeder macOS-Version, ohne iPhone.

```bash
# 1. Mac mit dem Kamera-WLAN (TrailCam_XXXX) verbinden.
# 2. Mitschnitt starten:
cd wildtrail-connect
mkdir -p captures
sudo tcpdump -i en0 -w "captures/mac_$(date +%Y%m%d_%H%M).pcap" host 192.168.43.1

# 3. In einem zweiten Terminal unser Tool laufen lassen (Login + 512 + 768):
trailcam info
#    oder, ohne etwas zu laden:
trailcam download --dry-run

# 4. tcpdump mit Ctrl-C beenden.
```

Das `en0` ist das eingebaute WLAN; falls unklar, listet `ifconfig` die aktiven
Interfaces (das mit `inet 192.168.43.x` ist das richtige).

---

## Methode B: iPhone über rvi (für die AV-Frames)

Für Download und Livebild brauchen wir den Verkehr der **App**, weil unser Tool
den Playback-Stream noch nicht kann. Apples Remote Virtual Interface spiegelt den
**gesamten** iPhone-Verkehr per USB auf eine virtuelle Schnittstelle `rvi0` — egal
in welchem WLAN das iPhone ist.

### Voraussetzungen
- **Xcode** installiert (`rvictl` kommt damit; Command Line Tools allein reichen nicht).
- iPhone per **USB** am Mac, einmal **„Diesem Computer vertrauen"** bestätigt.

### iOS-Kompatibilität — erst testen!
Es gibt keine offizielle Obergrenze, aber in der Praxis ist rvi nur bis etwa
**iOS 15** zuverlässig. Ab **iOS 16/17/18** wird `rvi0` oft angelegt, schneidet
aber **null Pakete** mit (vor allem auf Apple-Silicon-Macs). Darum zuerst der
30-Sekunden-Test:

```bash
xcrun xctrace list devices          # UDID des iPhones ablesen
rvictl -s <UDID>                    # -> "SUCCEEDED with interface rvi0"
sudo tcpdump -i rvi0 -c 20          # iPhone dabei irgendeine Website laden lassen
```
- Pakete kommen → weiter unten mit dem echten Mitschnitt.
- `0 packets captured` → rvi ist auf dieser Kombi kaputt. Dann: iPhone/iPad mit
  iOS ≤15 nutzen, oder einen Reise-Router als Client ins Kamera-WLAN hängen und
  dort mitschneiden.

### Mitschnitt
```bash
rvictl -s <UDID>
sudo tcpdump -i rvi0 -w "captures/iphone_$(date +%Y%m%d_%H%M).pcap" host 192.168.43.1
```
Jetzt in der App, während tcpdump läuft:
- ins Kamera-WLAN verbinden, einloggen
- **ein Foto herunterladen**
- **ein Video herunterladen**
- **Live-Ansicht ~10 s öffnen**, dann schließen
- App sauber verlassen (Logout)

Beenden:
```bash
# Ctrl-C im tcpdump-Terminal
rvictl -x <UDID>                    # virtuelle Schnittstelle entfernen
```

Eigenheiten von `rvi0`: schneidet auf **IP-Ebene** mit (keine Ethernet-/WLAN-Header,
für UDP-PPCS egal) und sieht **nur IP-Verkehr** — BLE (das Aufwecken per Bluetooth)
ist nicht dabei. BLE wäre ein separater Mitschnitt mit Apples **PacketLogger** und
erst für `trailcam wake` (Phase 1b) nötig.

---

## Prüfen und weitergeben

In Wireshark auf `rvi0`/`en0` filtern mit `ip.addr == 192.168.43.1` und ein paar
Pakete ansehen: erstes UDP-Payload-Byte `0xF1` = PPPP. Dann die `.pcap` aus
`captures/` herausgeben.

Weiterverarbeitung (siehe `docs/PROTOCOL.md`):
```bash
python tools/pcap_extract.py captures/<datei>.pcap --out captures/extracted
python tools/try_decrypt.py --hex <frame-hex> --key <aes-hex>
```
