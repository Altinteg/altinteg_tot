"""Handheld workflows (spec: Workflows 2, 3, 4, 6).

Ship:    create shipment -> pick reads -> dispatch with guia number + ATCUD
Receive: read the crate -> matched / missing / extra -> tags into store stock
Count:   sweep a location -> physical vs expected (and vs StoresAce book stock)
Dispose: waste or own use -> tags leave stock, export line for StoresAce

Reads arrive as raw strings from the reader (one EPC per line, or keystrokes
from DataWedge). Duplicates and non-SGTIN-96 reads are dropped.
"""
from __future__ import annotations

import json
import re
import sqlite3
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from . import exports
from .store import new_id, now

EPC_RE = re.compile(r"\b30[0-9A-F]{22}\b")      # SGTIN-96 header 0x30
IN_STOCK = ("encoded", "in_stock", "on_shelf", "missing")
MISSING_AFTER = 2                                # counts not seen before 'missing'


class MovementError(RuntimeError):
    pass


def parse_reads(raw: str | list[str]) -> list[str]:
    text = raw if isinstance(raw, str) else "\n".join(raw)
    seen, out = set(), []
    for epc in EPC_RE.findall(text.upper()):
        if epc not in seen:
            seen.add(epc)
            out.append(epc)
    return out


def _tags(conn, epcs):
    if not epcs:
        return {}
    marks = ",".join("?" * len(epcs))
    return {r["epc"]: r for r in conn.execute(
        f"SELECT * FROM tag WHERE epc IN ({marks})", epcs)}


def _event(conn, biz_step, epcs, location_id, doc, user, device):
    conn.execute("INSERT INTO event VALUES (?,?,?,?,?,?,?,?,?)",
                 (new_id("EVT"), "ObjectEvent", biz_step, json.dumps(epcs),
                  location_id, now(), doc, user, device))


# ---------------------------------------------------------------- shipping
def create_shipment(conn, from_location: str, to_location: str) -> str:
    if from_location == to_location:
        raise MovementError("a shipment needs two different locations")
    sid = new_id("SHP")
    with conn:
        conn.execute("INSERT INTO shipment (shipment_id,from_location,to_location,status,created_at)"
                     " VALUES (?,?,?,'picking',?)", (sid, from_location, to_location, now()))
    return sid


@dataclass
class PickResult:
    added: list[str] = field(default_factory=list)
    rejected: dict[str, str] = field(default_factory=dict)   # epc -> reason


def pick(conn, shipment_id: str, raw_reads) -> PickResult:
    shp = _shipment(conn, shipment_id)
    if shp["status"] != "picking":
        raise MovementError(f"shipment {shipment_id} is {shp['status']}, not picking")
    epcs = parse_reads(raw_reads)
    tags = _tags(conn, epcs)
    res = PickResult()
    with conn:
        for e in epcs:
            t = tags.get(e)
            if t is None:
                res.rejected[e] = "unknown tag"
            elif t["location_id"] != shp["from_location"] or t["status"] not in IN_STOCK:
                res.rejected[e] = f"tag is {t['status']} at {t['location_id']}"
            elif conn.execute("SELECT 1 FROM shipment_tag WHERE shipment_id=? AND epc=?",
                              (shipment_id, e)).fetchone():
                continue
            else:
                conn.execute("INSERT INTO shipment_tag (shipment_id, epc) VALUES (?,?)",
                             (shipment_id, e))
                res.added.append(e)
    return res


def shipment_lines(conn, shipment_id: str) -> list[list]:
    """Item list for the guia de transporte and the StoresAce transfer."""
    epcs = [r["epc"] for r in conn.execute(
        "SELECT epc FROM shipment_tag WHERE shipment_id=?", (shipment_id,))]
    return exports.rows_for_tags(conn, epcs)


def dispatch(conn, shipment_id: str, guia_no: str, atcud: str | None, user: str,
             device: str | None, out_dir: str | Path) -> Path:
    """Close picking, record the guia, move tags in transit, write the transfer file."""
    shp = _shipment(conn, shipment_id)
    if shp["status"] != "picking":
        raise MovementError(f"shipment {shipment_id} is already {shp['status']}")
    if not guia_no:
        raise MovementError("a guia de transporte number is required before dispatch")
    epcs = [r["epc"] for r in conn.execute(
        "SELECT epc FROM shipment_tag WHERE shipment_id=?", (shipment_id,))]
    if not epcs:
        raise MovementError("shipment is empty")
    rows = exports.rows_for_tags(conn, epcs)
    path = exports.write(conn, "transfer", shp["from_location"], f"guia:{guia_no}", rows, out_dir)
    marks = ",".join("?" * len(epcs))
    with conn:
        conn.execute(f"UPDATE tag SET status='in_transit', last_seen_at=? WHERE epc IN ({marks})",
                     [now(), *epcs])
        conn.execute("UPDATE shipment SET status='in_transit', guia_no=?, atcud=?, dispatched_at=?"
                     " WHERE shipment_id=?", (guia_no, atcud, now(), shipment_id))
        _event(conn, "shipping", epcs, shp["from_location"], f"guia:{guia_no}", user, device)
    return path


@dataclass
class ReceiveResult:
    matched: list[str]
    missing: list[str]
    extra: list[str]
    unknown: list[str]
    status: str


def receive(conn, shipment_id: str, raw_reads, user: str, device: str | None) -> ReceiveResult:
    shp = _shipment(conn, shipment_id)
    if shp["status"] not in ("in_transit", "discrepancy"):
        raise MovementError(f"shipment {shipment_id} is {shp['status']}, not in transit")
    reads = parse_reads(raw_reads)
    expected = {r["epc"]: r["received"] for r in conn.execute(
        "SELECT epc, received FROM shipment_tag WHERE shipment_id=?", (shipment_id,))}
    known = _tags(conn, reads)
    matched = [e for e in reads if e in expected and not expected[e]]
    extra = [e for e in reads if e not in expected and e in known]
    unknown = [e for e in reads if e not in known]
    ts = now()
    with conn:
        if matched:
            marks = ",".join("?" * len(matched))
            conn.execute(f"UPDATE tag SET status='in_stock', location_id=?, last_seen_at=?, "
                         f"missed_counts=0 WHERE epc IN ({marks})",
                         [shp["to_location"], ts, *matched])
            conn.execute(f"UPDATE shipment_tag SET received=1 WHERE shipment_id=? AND epc IN ({marks})",
                         [shipment_id, *matched])
            _event(conn, "receiving", matched, shp["to_location"],
                   f"guia:{shp['guia_no']}", user, device)
        still = [e for e, rec in expected.items() if not rec and e not in matched]
        status = "received" if not still else "discrepancy"
        conn.execute("UPDATE shipment SET status=?, received_at=? WHERE shipment_id=?",
                     (status, ts, shipment_id))
    return ReceiveResult(matched, still, extra, unknown, status)


# ---------------------------------------------------------------- counting
@dataclass
class CountLine:
    item_code: str
    ean: str
    physical: int          # tags read now
    expected: int          # tags TOT believed were here
    book: int | None       # StoresAce stock, if supplied
    difference: int | None # physical - book


@dataclass
class CountResult:
    lines: list[CountLine]
    misplaced: list[str]   # read here, but TOT has them elsewhere / sold
    unknown: list[str]
    newly_missing: list[str]


def count(conn, location_id: str, raw_reads, user: str, device: str | None,
          book: dict[str, int] | None = None) -> CountResult:
    reads = set(parse_reads(raw_reads))
    known = _tags(conn, list(reads))
    marks = ",".join("?" * len(IN_STOCK))
    here = {r["epc"]: r for r in conn.execute(
        f"SELECT t.*, l.item_code FROM tag t JOIN lot l ON l.lot_id=t.lot_id "
        f"WHERE t.location_id=? AND t.status IN ({marks})", [location_id, *IN_STOCK])}
    seen = [e for e in reads if e in here]
    misplaced = [e for e in reads if e in known and e not in here]
    unknown = [e for e in reads if e not in known]
    not_seen = [e for e in here if e not in reads]
    ts, newly_missing = now(), []
    with conn:
        for e in seen:
            conn.execute("UPDATE tag SET missed_counts=0, last_seen_at=?, status=CASE "
                         "WHEN status IN ('missing','encoded') THEN 'in_stock' ELSE status END "
                         "WHERE epc=?", (ts, e))
        for e in not_seen:
            n = here[e]["missed_counts"] + 1
            st = "missing" if n >= MISSING_AFTER else here[e]["status"]
            if st == "missing" and here[e]["status"] != "missing":
                newly_missing.append(e)
            conn.execute("UPDATE tag SET missed_counts=?, status=? WHERE epc=?", (n, st, e))
        if seen:
            _event(conn, "cycle_counting", seen, location_id, None, user, device)
    expected = Counter((r["item_code"], r["gtin"][1:]) for e, r in here.items()
                       if r["status"] != "missing")
    physical = Counter((here[e]["item_code"], here[e]["gtin"][1:]) for e in seen)
    keys = set(expected) | set(physical)
    codes = {code for code, _ in keys}
    keys |= {(code, "") for code in (book or {}) if code not in codes}
    lines = []
    for item_code, ean in sorted(keys):
        phys = physical.get((item_code, ean), 0)
        b = (book or {}).get(item_code)
        lines.append(CountLine(item_code, ean, phys, expected.get((item_code, ean), 0),
                               b, None if b is None else phys - b))
    return CountResult(lines, misplaced, unknown, newly_missing)


# ---------------------------------------------------------------- disposal
DISPOSE = {"waste": ("wasted", "destroying"), "own_use": ("own_use", "own_use")}


def dispose(conn, location_id: str, raw_reads, kind: str, reason: str, user: str,
            device: str | None, out_dir: str | Path) -> Path:
    if kind not in DISPOSE:
        raise MovementError("kind must be 'waste' or 'own_use'")
    epcs = parse_reads(raw_reads)
    tags = _tags(conn, epcs)
    bad = [e for e in epcs if e not in tags or tags[e]["location_id"] != location_id
           or tags[e]["status"] not in IN_STOCK]
    if bad:
        raise MovementError(f"{len(bad)} tag(s) are not in stock at {location_id}: {bad[:5]}")
    status, step = DISPOSE[kind]
    doc = f"{kind}:{new_id('DOC')}:{reason}"
    path = exports.write(conn, kind, location_id, doc, exports.rows_for_tags(conn, epcs), out_dir)
    marks = ",".join("?" * len(epcs))
    with conn:
        conn.execute(f"UPDATE tag SET status=?, last_seen_at=? WHERE epc IN ({marks})",
                     [status, now(), *epcs])
        _event(conn, step, epcs, location_id, doc, user, device)
    return path


def _shipment(conn, shipment_id):
    s = conn.execute("SELECT * FROM shipment WHERE shipment_id=?", (shipment_id,)).fetchone()
    if s is None:
        raise MovementError(f"unknown shipment {shipment_id}")
    return s
