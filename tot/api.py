"""TOT HTTP API for the label station and the handheld (prototype).

Run:  TOT_DB=tot.db TOT_EXPORTS=exports uvicorn tot.api:app --host 0.0.0.0 --port 8000
Open: http://<server>:8000/handheld on the handheld's browser.
"""
from __future__ import annotations

import os
from dataclasses import asdict
from datetime import date
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from . import labelstation, movements
from .allocator import AllocationError
from .exports import ExportError
from .gs1 import Gs1Error
from .sgtin import SgtinError
from .store import connect

DB = os.environ.get("TOT_DB", "tot.db")
EXPORTS = os.environ.get("TOT_EXPORTS", "exports")
ERRORS = (labelstation.LabelStationError, movements.MovementError, ExportError,
          AllocationError, SgtinError, Gs1Error, ValueError)

app = FastAPI(title="The Order of Things — shop MVP", version="0.2")


def db():
    conn = connect(DB)
    try:
        yield conn
    finally:
        conn.close()


def run(fn, *a, **kw):
    try:
        return fn(*a, **kw)
    except ERRORS as e:
        raise HTTPException(status_code=400, detail=str(e))


# ---------------------------------------------------------------- label station
class LotIn(BaseModel):
    line: dict                     # FaturaLine fields
    location_id: str = "DC"
    user: str
    expiry: date | None = None
    batch: str | None = None
    case_scan: str | None = None
    qty: int | None = None


class PrintIn(BaseModel):
    count: int
    station_id: str = "DC-1"
    station_index: int = 0
    user: str


@app.post("/labels/lots")
def create_lot(body: LotIn, conn=Depends(db)):
    fl = run(labelstation.FaturaLine, **body.line)
    lot_id = run(labelstation.create_lot, conn, fl, body.location_id, body.user,
                 expiry=body.expiry, batch=body.batch, case_scan=body.case_scan, qty=body.qty)
    return {"lot_id": lot_id}


@app.post("/labels/lots/{lot_id}/print")
def print_run(lot_id: str, body: PrintIn, conn=Depends(db)):
    epcs, zpl = run(labelstation.encode_run, conn, lot_id, body.count, None, None,
                    body.station_id, body.station_index, body.user)
    return {"lot_id": lot_id, "epcs": epcs, "zpl": zpl}


# ---------------------------------------------------------------- handheld
class ShipmentIn(BaseModel):
    from_location: str
    to_location: str


class ReadsIn(BaseModel):
    reads: str
    user: str = "operator"
    device: str | None = None


class DispatchIn(BaseModel):
    guia_no: str
    atcud: str | None = None
    user: str
    device: str | None = None


class CountIn(ReadsIn):
    location_id: str
    book: dict[str, int] | None = None


class DisposeIn(ReadsIn):
    location_id: str
    kind: str          # waste | own_use
    reason: str


@app.post("/shipments")
def create_shipment(body: ShipmentIn, conn=Depends(db)):
    return {"shipment_id": run(movements.create_shipment, conn, body.from_location, body.to_location)}


@app.post("/shipments/{sid}/pick")
def pick(sid: str, body: ReadsIn, conn=Depends(db)):
    r = run(movements.pick, conn, sid, body.reads)
    return {"added": len(r.added), "rejected": r.rejected,
            "lines": movements.shipment_lines(conn, sid)}


@app.get("/shipments/{sid}/lines")
def lines(sid: str, conn=Depends(db)):
    return {"lines": movements.shipment_lines(conn, sid)}


@app.post("/shipments/{sid}/dispatch")
def dispatch(sid: str, body: DispatchIn, conn=Depends(db)):
    path = run(movements.dispatch, conn, sid, body.guia_no, body.atcud, body.user,
               body.device, EXPORTS)
    return {"status": "in_transit", "transfer_file": Path(path).name}


@app.post("/shipments/{sid}/receive")
def receive(sid: str, body: ReadsIn, conn=Depends(db)):
    r = run(movements.receive, conn, sid, body.reads, body.user, body.device)
    return {"status": r.status, "matched": len(r.matched), "missing": r.missing,
            "extra": r.extra, "unknown": r.unknown}


@app.post("/counts")
def count(body: CountIn, conn=Depends(db)):
    r = run(movements.count, conn, body.location_id, body.reads, body.user, body.device, body.book)
    return {"lines": [asdict(x) for x in r.lines], "misplaced": r.misplaced,
            "unknown": r.unknown, "newly_missing": r.newly_missing}


@app.post("/dispose")
def dispose(body: DisposeIn, conn=Depends(db)):
    path = run(movements.dispose, conn, body.location_id, body.reads, body.kind, body.reason,
               body.user, body.device, EXPORTS)
    return {"export_file": Path(path).name}


@app.get("/handheld", response_class=HTMLResponse)
def handheld():
    return (Path(__file__).parent / "static" / "handheld.html").read_text(encoding="utf-8")
