"""Export files for StoresAce (spec: Integration, file import first).

Format = the 4-column import template already used in the shop:
  Artigo - Código | Preço Unitário | Artigo - Cód. Barras | Quantidade
Artigo - Código is the StoresAce item code (ItemId); Preço Unitário is the
lot cost. Files are written as .xlsx (numeric cells, no decimal-comma issues).

Every file is registered with a SHA-256 over its kind, document reference and
rows, so the same export can never be produced (and imported) twice.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

from openpyxl import Workbook

from .store import new_id, now

HEADER = ["Artigo - Código", "Preço Unitário", "Artigo - Cód. Barras", "Quantidade"]
KINDS = {"transfer", "delivery", "waste", "own_use", "adjustment"}


class ExportError(RuntimeError):
    pass


def rows_for_tags(conn: sqlite3.Connection, epcs: list[str]) -> list[list]:
    """Group tags by item: [item_code, avg unit cost, EAN-13, quantity]."""
    if not epcs:
        return []
    marks = ",".join("?" * len(epcs))
    q = conn.execute(
        f"SELECT l.item_code, t.gtin, COUNT(*) AS qty, "
        f"SUM(COALESCE(l.unit_cost,0)) AS cost "
        f"FROM tag t JOIN lot l ON l.lot_id = t.lot_id WHERE t.epc IN ({marks}) "
        f"GROUP BY l.item_code, t.gtin ORDER BY l.item_code", epcs).fetchall()
    return [[r["item_code"], round(r["cost"] / r["qty"], 4), r["gtin"][1:], r["qty"]] for r in q]


def write(conn: sqlite3.Connection, kind: str, location_id: str, document_ref: str,
          rows: list[list], out_dir: str | Path) -> Path:
    if kind not in KINDS:
        raise ExportError(f"unknown export kind {kind!r}")
    if not rows:
        raise ExportError("nothing to export")
    digest = hashlib.sha256(json.dumps([kind, document_ref, rows], sort_keys=True,
                                       default=str).encode()).hexdigest()
    if conn.execute("SELECT 1 FROM export_file WHERE sha256=?", (digest,)).fetchone():
        raise ExportError("this export already exists; it must not be imported twice")
    file_id = new_id("EXP")
    wb = Workbook()
    ws = wb.active
    ws.title = kind
    ws.append(HEADER)
    for r in rows:
        ws.append(r)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"{file_id}_{kind}.xlsx"
    wb.save(path)
    with conn:
        conn.execute("INSERT INTO export_file VALUES (?,?,?,?,?,?,0)",
                     (file_id, kind, location_id, document_ref, now(), digest))
    return path
