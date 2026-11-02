"""Label station workflow (spec section: Workflows, 1. Label station).

1. Pick an open fatura line (item, quantity, cost).
2. Capture batch and expiry (from the case barcode or by hand).
3. Create the lot.
4. Encode a print run: allocate serials, build EPCs and labels,
   record tags + one commissioning event. Never beyond the fatura quantity.
"""
from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import date

from . import allocator, gs1, sgtin, zpl
from .store import new_id, now


class LabelStationError(RuntimeError):
    pass


@dataclass
class FaturaLine:
    fatura_no: str
    line: int
    supplier_id: str
    item_code: str          # StoresAce ItemId
    gtin: str               # item barcode (EAN-13 or GTIN-14)
    description: str
    qty: int
    unit_cost: float
    company_prefix_len: int  # GS1 company prefix length of this GTIN


def create_lot(conn: sqlite3.Connection, fl: FaturaLine, location_id: str,
               user: str, expiry: date | None = None, batch: str | None = None,
               case_scan: str | None = None, qty: int | None = None) -> str:
    """Create a lot for (part of) a fatura line. Returns lot_id."""
    if case_scan:
        parsed = gs1.parse(case_scan)
        expiry = expiry or parsed.get("expiry")
        batch = batch or parsed.get("batch")
        case_gtin = parsed.get("gtin")
        if case_gtin and sgtin.normalize_gtin(case_gtin)[1:-1] != sgtin.normalize_gtin(fl.gtin)[1:-1]:
            # case GTIN often differs only by indicator digit; anything else is a wrong product
            raise LabelStationError(f"case barcode GTIN {case_gtin} does not match item {fl.gtin}")
    if expiry is None:
        raise LabelStationError("expiry date is required")
    qty = fl.qty if qty is None else qty
    already = conn.execute(
        "SELECT COALESCE(SUM(qty_received),0) FROM lot WHERE fatura_no=? AND fatura_line=?",
        (fl.fatura_no, fl.line)).fetchone()[0]
    if already + qty > fl.qty:
        raise LabelStationError(
            f"lots for fatura {fl.fatura_no} line {fl.line} would exceed the invoiced {fl.qty}")
    lot_id = new_id("LOT")
    with conn:
        conn.execute(
            "INSERT INTO lot (lot_id,item_code,gtin,supplier_id,fatura_no,fatura_line,"
            "supplier_batch,expiry_date,unit_cost,qty_received,qty_encoded,location_id,"
            "created_at,created_by) VALUES (?,?,?,?,?,?,?,?,?,?,0,?,?,?)",
            (lot_id, fl.item_code, sgtin.normalize_gtin(fl.gtin), fl.supplier_id,
             fl.fatura_no, fl.line, batch, expiry.isoformat(), fl.unit_cost, qty,
             location_id, now(), user))
    return lot_id


def encode_run(conn: sqlite3.Connection, lot_id: str, count: int, description: str,
               company_prefix_len: int, station_id: str, station_index: int,
               user: str) -> tuple[list[str], str]:
    """Encode `count` labels for a lot. Returns (EPC list, ZPL job)."""
    lot = conn.execute("SELECT * FROM lot WHERE lot_id=?", (lot_id,)).fetchone()
    if lot is None:
        raise LabelStationError(f"unknown lot {lot_id}")
    if lot["qty_encoded"] + count > lot["qty_received"]:
        raise LabelStationError(
            f"lot {lot_id}: {lot['qty_encoded']} encoded of {lot['qty_received']}; "
            f"cannot encode {count} more")
    gtin14 = lot["gtin"]
    ean13 = gtin14[1:] if gtin14[0] == "0" else None
    if ean13 is None:
        raise LabelStationError("unit GTIN must be an EAN-13 (indicator 0) for the till barcode")
    serials = allocator.allocate(conn, gtin14, station_id, station_index, count)
    expiry = date.fromisoformat(lot["expiry_date"])
    epcs, labels = [], []
    for s in serials:
        epc = sgtin.encode(gtin14, company_prefix_len, s)
        epcs.append(epc)
        labels.append(zpl.label(epc, ean13, description, expiry, lot["supplier_batch"]))
    ts = now()
    with conn:
        conn.executemany(
            "INSERT INTO tag (epc,gtin,serial,lot_id,status,location_id,last_seen_at) "
            "VALUES (?,?,?,?, 'encoded', ?, ?)",
            [(e, gtin14, s, lot_id, lot["location_id"], ts) for e, s in zip(epcs, serials)])
        conn.execute(
            "INSERT INTO event VALUES (?,?,?,?,?,?,?,?,?)",
            (new_id("EVT"), "ObjectEvent", "commissioning", json.dumps(epcs),
             lot["location_id"], ts, f"fatura:{lot['fatura_no']}/{lot['fatura_line']}",
             user, station_id))
        conn.execute("UPDATE lot SET qty_encoded = qty_encoded + ? WHERE lot_id=?",
                     (count, lot_id))
    return epcs, zpl.print_job(labels)
