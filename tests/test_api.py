import importlib

import pytest
from fastapi.testclient import TestClient

LINE = dict(fatura_no="FT 2026A/8922", line=3, supplier_id="LACTOGAL", item_code="DR011843",
            gtin="5601234567892", description="Iogurte natural 4x125g", qty=6,
            unit_cost=1.10, company_prefix_len=7)


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("TOT_DB", str(tmp_path / "api.db"))
    monkeypatch.setenv("TOT_EXPORTS", str(tmp_path / "exports"))
    import tot.api
    importlib.reload(tot.api)
    return TestClient(tot.api.app)


def test_end_to_end_dc_to_store(client):
    lot = client.post("/labels/lots", json={"line": LINE, "user": "aliya",
                                            "case_scan": "011560123456789917261120",
                                            "batch": "B77"}).json()["lot_id"]
    pr = client.post(f"/labels/lots/{lot}/print", json={"count": 6, "user": "aliya"}).json()
    assert len(pr["epcs"]) == 6 and pr["zpl"].count("^XA") == 6
    assert "Iogurte natural" in pr["zpl"]

    sid = client.post("/shipments", json={"from_location": "DC", "to_location": "LOJA-1"}).json()["shipment_id"]
    pk = client.post(f"/shipments/{sid}/pick", json={"reads": "\n".join(pr["epcs"]), "user": "aliya"}).json()
    assert pk["added"] == 6 and pk["lines"] == [["DR011843", 1.1, "5601234567892", 6]]

    d = client.post(f"/shipments/{sid}/dispatch", json={"guia_no": "GT 2026/15", "user": "aliya"})
    assert d.status_code == 200 and d.json()["transfer_file"].endswith("_transfer.xlsx")

    rc = client.post(f"/shipments/{sid}/receive", json={"reads": "\n".join(pr["epcs"][:5])}).json()
    assert rc["status"] == "discrepancy" and rc["matched"] == 5 and len(rc["missing"]) == 1

    ct = client.post("/counts", json={"location_id": "LOJA-1", "reads": "\n".join(pr["epcs"][:5]),
                                      "book": {"DR011843": 6}}).json()
    assert ct["lines"][0]["physical"] == 5 and ct["lines"][0]["difference"] == -1

    ds = client.post("/dispose", json={"location_id": "LOJA-1", "reads": pr["epcs"][0],
                                       "kind": "waste", "reason": "embalagem danificada"})
    assert ds.status_code == 200


def test_errors_are_400_with_reason(client):
    r = client.post("/labels/lots", json={"line": LINE, "user": "aliya"})   # no expiry
    assert r.status_code == 400 and "expiry" in r.json()["detail"]


def test_handheld_page_served(client):
    r = client.get("/handheld")
    assert r.status_code == 200 and "Leitor RFID" in r.text
