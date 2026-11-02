from datetime import date

import pytest
from openpyxl import load_workbook

from tot import exports, labelstation, movements
from tot.store import connect


@pytest.fixture
def env(tmp_path):
    conn = connect(tmp_path / "t.db")
    fl = labelstation.FaturaLine(
        fatura_no="FT 2026A/8922", line=3, supplier_id="LACTOGAL", item_code="DR011843",
        gtin="5601234567892", description="Iogurte natural 4x125g", qty=10,
        unit_cost=1.10, company_prefix_len=7)
    lot = labelstation.create_lot(conn, fl, "DC", "aliya", expiry=date(2026, 11, 20))
    epcs, _ = labelstation.encode_run(conn, lot, 10, fl.description, 7, "DC-1", 0, "aliya")
    return conn, epcs, tmp_path / "out"


def test_parse_reads_dedupes_and_filters():
    raw = "303555DF483775574876E800\n303555df483775574876e800\nE2801160600002\nNOISE"
    assert movements.parse_reads(raw) == ["303555DF483775574876E800"]


def test_ship_and_receive_full(env):
    conn, epcs, out = env
    sid = movements.create_shipment(conn, "DC", "STORE-1")
    res = movements.pick(conn, sid, "\n".join(epcs[:6]))
    assert len(res.added) == 6 and not res.rejected
    assert movements.shipment_lines(conn, sid) == [["DR011843", 1.1, "5601234567892", 6]]
    path = movements.dispatch(conn, sid, "GT 2026/15", "JJ37B-15", "aliya", "HH-1", out)
    ws = load_workbook(path).active
    assert [c.value for c in ws[1]] == exports.HEADER
    assert [c.value for c in ws[2]] == ["DR011843", 1.1, "5601234567892", 6]
    r = movements.receive(conn, sid, epcs[:6], "deysi", "HH-2")
    assert r.status == "received" and len(r.matched) == 6 and not r.missing
    row = conn.execute("SELECT status, location_id FROM tag WHERE epc=?", (epcs[0],)).fetchone()
    assert tuple(row) == ("in_stock", "STORE-1")


def test_receive_with_missing_then_late_receipt(env):
    conn, epcs, out = env
    sid = movements.create_shipment(conn, "DC", "STORE-1")
    movements.pick(conn, sid, epcs[:4])
    movements.dispatch(conn, sid, "GT 2026/16", None, "aliya", None, out)
    r = movements.receive(conn, sid, epcs[:3] + [epcs[8]], "deysi", None)
    assert r.status == "discrepancy" and r.missing == [epcs[3]] and r.extra == [epcs[8]]
    r2 = movements.receive(conn, sid, [epcs[3]], "deysi", None)
    assert r2.status == "received"


def test_dispatch_needs_guia_and_cannot_repeat(env):
    conn, epcs, out = env
    sid = movements.create_shipment(conn, "DC", "STORE-1")
    movements.pick(conn, sid, epcs[:2])
    with pytest.raises(movements.MovementError):
        movements.dispatch(conn, sid, "", None, "aliya", None, out)
    movements.dispatch(conn, sid, "GT 2026/17", None, "aliya", None, out)
    with pytest.raises(movements.MovementError):
        movements.dispatch(conn, sid, "GT 2026/17", None, "aliya", None, out)


def test_cannot_pick_tag_from_other_location(env):
    conn, epcs, out = env
    sid = movements.create_shipment(conn, "STORE-1", "DC")
    res = movements.pick(conn, sid, epcs[:1])
    assert epcs[0] in res.rejected


def test_count_flags_missing_after_two_counts(env):
    conn, epcs, out = env
    seen = epcs[:8]
    c1 = movements.count(conn, "DC", seen, "aliya", None, book={"DR011843": 10})
    line = c1.lines[0]
    assert (line.physical, line.expected, line.book, line.difference) == (8, 10, 10, -2)
    assert not c1.newly_missing
    c2 = movements.count(conn, "DC", seen, "aliya", None)
    assert sorted(c2.newly_missing) == sorted(epcs[8:])
    # found again on the third count -> back in stock
    movements.count(conn, "DC", epcs, "aliya", None)
    assert conn.execute("SELECT COUNT(*) FROM tag WHERE status='missing'").fetchone()[0] == 0


def test_waste_removes_stock_and_exports(env):
    conn, epcs, out = env
    path = movements.dispose(conn, "DC", epcs[:2], "waste", "expired", "aliya", None, out)
    assert [c.value for c in load_workbook(path).active[2]] == ["DR011843", 1.1, "5601234567892", 2]
    assert conn.execute("SELECT COUNT(*) FROM tag WHERE status='wasted'").fetchone()[0] == 2
    with pytest.raises(movements.MovementError):
        movements.dispose(conn, "DC", epcs[:1], "waste", "expired", "aliya", None, out)


def test_same_export_cannot_be_written_twice(env):
    conn, epcs, out = env
    rows = exports.rows_for_tags(conn, epcs[:1])
    exports.write(conn, "adjustment", "DC", "count:1", rows, out)
    with pytest.raises(exports.ExportError):
        exports.write(conn, "adjustment", "DC", "count:1", rows, out)
