"""ZPL generation for Zebra RFID label printers (e.g. ZD621R).

Each label: encode the EPC (^RFW), print the item EAN-13 for the till,
the expiry date in plain text and a short description. Label size and
positions are defaults for a 50 x 30 mm label at 203 dpi; adjust per stock.
"""
from __future__ import annotations

from datetime import date


def _safe(text: str, limit: int) -> str:
    # ZPL control characters ^ and ~ must not appear in field data
    return text.replace("^", " ").replace("~", " ")[:limit]


def label(epc_hex: str, ean13: str, description: str, expiry: date,
          batch: str | None = None) -> str:
    if len(ean13) != 13 or not ean13.isdigit():
        raise ValueError("ean13 must be 13 digits")
    exp = expiry.strftime("%d/%m/%Y")
    lines = [
        "^XA",
        "^PW400^LL240",                         # 50 x 30 mm at 203 dpi
        "^RS8",                                 # RFID setup, Gen2 tag
        f"^RFW,H,,,A^FD{epc_hex}^FS",           # write EPC (auto-adjust PC bits)
        f"^FO16,12^A0N,24,24^FD{_safe(description, 28)}^FS",
        f"^FO16,44^A0N,30,30^FDVal: {exp}^FS",
    ]
    if batch:
        lines.append(f"^FO16,80^A0N,20,20^FDLote: {_safe(batch, 20)}^FS")
    lines += [
        # ^BE takes the first 12 digits; the printer adds the check digit
        f"^FO40,108^BY2^BEN,80,Y,N^FD{ean13[:12]}^FS",
        "^PQ1",
        "^XZ",
    ]
    return "\n".join(lines)


def print_job(labels: list[str]) -> str:
    return "\n".join(labels) + "\n"
