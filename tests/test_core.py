from datetime import date

import pytest

from tot import allocator, gs1, labelstation, sgtin
from tot.store import connect


# --- SGTIN-96 -----------------------------------------------------------
def test_gs1_tds_reference_vector():
    # GS1 TDS example: urn:epc:tag:sgtin-96:3.0614141.812345.6789
    gtin = "80614141123458"  # indicator 8, CP 0614141, item ref 12345, check 8
    epc = sgtin.encode(gtin, 7, 6789, filter_value=3)
    assert epc == "3074257BF7194E4000001A85"
    d = sgtin.decode(epc)
    assert d.tag_uri == "urn:epc:tag:sgtin-96:3.0614141.812345.6789"
    assert d.gtin14 == gtin


@pytest.mark.parametrize("cp_len", [6, 7, 8, 9, 10, 11, 12])
def test_roundtrip_every_partition(cp_len):
    gtin = "05601234567890"[:13]
    gtin = gtin + str(sgtin.gtin_check_digit(gtin))
    epc = sgtin.encode(gtin, cp_len, 123456789)
    d = sgtin.decode(epc)
    assert d.gtin14 == gtin and d.serial == 123456789 and d.company_prefix_len == cp_len


def test_rejects_bad_check_digit():
    with pytest.raises(sgtin.SgtinError):
        sgtin.encode("5601234567891", 7, 1)


def test_rejects_serial_over_38_bits():
    with pytest.raises(sgtin.SgtinError):
        sgtin.encode("5601234567892", 7, 1 << 38)


# --- GS1 case barcode ---------------------------------------------------
def test_parse_case_barcode():
    r = gs1.parse("]C10115601234567899" + "17270215" + "10L2026-45")
    assert r["gtin"] == "15601234567899"
    assert r["expiry"] == date(2027, 2, 15)
    assert r["batch"] == "L2026-45"


def test_parse_day_zero_is_month_end():
    assert gs1.parse("17270200")["expiry"] == date(2027, 2, 28)


# --- allocator ----------------------------------------------------------
def test_stations_never_overlap(tmp_path):
    conn = connect(tmp_path / "t.db")
    a = allocator.allocate(conn, "05601234567892", "DC-1", 0, 5)
    b = allocator.allocate(conn, "05601234567892", "DC-2", 1, 5)
    c = allocator.allocate(conn, "05601234567892", "DC-1", 0, 5)
    assert not set(a) & set(b)
    assert c[0] == a[-1] + 1


# --- label station ------------------------------------------------------
def _line(**kw):
    base = dict(fatura_no="FT 2026A/8922", line=3, supplier_id="LACTOGAL",
                item_code="DR011843", gtin="5601234567892", description="Iogurte natural 4x125g",
                qty=24, unit_cost=1.10, company_prefix_len=7)
    base.update(kw)
    return labelstation.FaturaLine(**base)


def test_lot_and_print_run(tmp_path):
    conn = connect(tmp_path / "t.db")
    fl = _line()
    lot = labelstation.create_lot(conn, fl, "DC", "aliya",
                                  case_scan="0115601234567899" + "17261120" + "10B77")
    epcs, job = labelstation.encode_run(conn, lot, 10, fl.description, 7, "DC-1", 0, "aliya")
    assert len(epcs) == len(set(epcs)) == 10
    assert job.count("^XA") == 10 and "^RFW,H" in job and "Val: 20/11/2026" in job
    assert conn.execute("SELECT COUNT(*) FROM tag WHERE lot_id=?", (lot,)).fetchone()[0] == 10
    ev = conn.execute("SELECT biz_step, document_ref FROM event").fetchone()
    assert ev["biz_step"] == "commissioning" and ev["document_ref"] == "fatura:FT 2026A/8922/3"


def test_cannot_encode_beyond_fatura_qty(tmp_path):
    conn = connect(tmp_path / "t.db")
    fl = _line(qty=5)
    lot = labelstation.create_lot(conn, fl, "DC", "aliya", expiry=date(2026, 11, 20))
    labelstation.encode_run(conn, lot, 5, fl.description, 7, "DC-1", 0, "aliya")
    with pytest.raises(labelstation.LabelStationError):
        labelstation.encode_run(conn, lot, 1, fl.description, 7, "DC-1", 0, "aliya")


def test_two_expiries_two_lots_capped_at_fatura(tmp_path):
    conn = connect(tmp_path / "t.db")
    fl = _line(qty=24)
    labelstation.create_lot(conn, fl, "DC", "aliya", expiry=date(2026, 11, 20), qty=12)
    labelstation.create_lot(conn, fl, "DC", "aliya", expiry=date(2026, 11, 25), qty=12)
    with pytest.raises(labelstation.LabelStationError):
        labelstation.create_lot(conn, fl, "DC", "aliya", expiry=date(2026, 11, 30), qty=1)


def test_wrong_case_barcode_is_rejected(tmp_path):
    conn = connect(tmp_path / "t.db")
    with pytest.raises(labelstation.LabelStationError):
        labelstation.create_lot(conn, _line(), "DC", "aliya",
                                case_scan="0115609999999993" + "17261120")
