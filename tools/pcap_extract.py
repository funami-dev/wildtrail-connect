#!/usr/bin/env python3
"""Phase-0-Helfer: PPPP-Pakete aus einem pcap lesen und DRW-Payloads je Kanal
reassemblieren.

Liest UDP-Payloads, filtert auf PPPP-Magic ``0xF1``, sortiert DRW-Pakete nach
Kanal und Index (mit 16-Bit-Wrap) und schreibt je Kanal den reassemblierten
Bytestrom heraus. So lässt sich der Command-Kanal (21/41-Byte-Frames + Base64)
isolieren und anschließend mit ``try_decrypt.py`` prüfen.

    python tools/pcap_extract.py captures/session.pcap --out captures/out

Benötigt ``scapy`` (optional dependency, nur für Phase 0):

    pip install scapy
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from trailcam.pppp.packets import Drw, MsgType, Packet, PacketError, seq_newer  # noqa: E402


def iter_udp_payloads(pcap: Path) -> list[bytes]:
    try:
        from scapy.all import UDP, rdpcap  # type: ignore[import-untyped]
    except ImportError:
        sys.exit("scapy wird gebraucht: pip install scapy")
    out = []
    for pkt in rdpcap(str(pcap)):
        if UDP in pkt:
            out.append(bytes(pkt[UDP].payload))
    return out


def reassemble(payloads: list[bytes]) -> dict[int, bytes]:
    """Reassembliert DRW-Payloads je Kanal in Indexreihenfolge."""
    chunks: dict[int, dict[int, bytes]] = {}
    for raw in payloads:
        try:
            pkt = Packet.decode(raw)
        except PacketError:
            continue
        if pkt.type != MsgType.DRW:
            continue
        try:
            drw = Drw.from_packet(pkt)
        except PacketError:
            continue
        chunks.setdefault(drw.channel, {}).setdefault(drw.index, drw.data)

    streams: dict[int, bytes] = {}
    for channel, by_index in chunks.items():
        ordered = bytearray()
        indices = sorted(by_index)
        # Wrap-around behandeln: bei großem Sprung neu ab 0 einsortieren
        prev = None
        for idx in indices:
            if prev is not None and not seq_newer(idx, prev) and (prev - idx) & 0xFFFF > 0x8000:
                pass
            ordered += by_index[idx]
            prev = idx
        streams[channel] = bytes(ordered)
    return streams


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("pcap", type=Path)
    ap.add_argument("--out", type=Path, default=Path("captures/extracted"))
    args = ap.parse_args(argv)

    streams = reassemble(iter_udp_payloads(args.pcap))
    args.out.mkdir(parents=True, exist_ok=True)
    for channel, data in sorted(streams.items()):
        path = args.out / f"channel_{channel}.bin"
        path.write_bytes(data)
        print(f"Kanal {channel}: {len(data)} Byte -> {path}")
    if not streams:
        print("Keine DRW-Pakete gefunden.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
