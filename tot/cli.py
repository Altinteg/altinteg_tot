"""Label station command line (prototype).

Example:
  python -m tot.cli label --db tot.db --line examples/fatura_line.json \
      --scan "011560123456789917261120" --batch B77 --count 12 --out run.zpl

Send the .zpl file to a Zebra RFID printer (USB/network raw port 9100).
"""
from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path

from . import labelstation
from .store import connect


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(prog="tot")
    sub = p.add_subparsers(dest="cmd", required=True)
    lab = sub.add_parser("label", help="create a lot from a fatura line and encode a print run")
    lab.add_argument("--db", default="tot.db")
    lab.add_argument("--line", required=True, help="JSON file with the fatura line")
    lab.add_argument("--scan", help="case barcode (GS1-128/DataMatrix) with batch and expiry")
    lab.add_argument("--expiry", help="YYYY-MM-DD, if not in the scan")
    lab.add_argument("--batch")
    lab.add_argument("--lot-qty", type=int, help="units in this lot (default: whole line)")
    lab.add_argument("--count", type=int, required=True, help="labels to encode now")
    lab.add_argument("--location", default="DC")
    lab.add_argument("--station", default="DC-1")
    lab.add_argument("--station-index", type=int, default=0)
    lab.add_argument("--user", default="operator")
    lab.add_argument("--out", default="run.zpl")
    a = p.parse_args(argv)

    conn = connect(a.db)
    fl = labelstation.FaturaLine(**json.loads(Path(a.line).read_text()))
    lot = labelstation.create_lot(
        conn, fl, a.location, a.user,
        expiry=date.fromisoformat(a.expiry) if a.expiry else None,
        batch=a.batch, case_scan=a.scan, qty=a.lot_qty)
    epcs, job = labelstation.encode_run(conn, lot, a.count, fl.description,
                                        fl.company_prefix_len, a.station,
                                        a.station_index, a.user)
    Path(a.out).write_text(job)
    print(f"lot {lot}: {len(epcs)} labels -> {a.out}")
    print(f"first EPC {epcs[0]}, last EPC {epcs[-1]}")


if __name__ == "__main__":
    main()
