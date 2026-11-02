# The Order of Things (TOT) — shop MVP

Item-level identity, batch and expiry for the Onda Limão shop and its DC,
alongside StoresAce (commercial owner) and ZoneSoft (fiscal owner).
Spec: "The Order of Things — Onda Limão MVP spec" (Claude Docs).

## What's built

### Stage 1 — label station

| Module | What it does |
| --- | --- |
| `tot/sgtin.py` | SGTIN-96 encode/decode (GS1 TDS), GTIN check digits |
| `tot/gs1.py` | Parses case barcodes (AI 01, 10, 15, 17, 21) for batch and expiry |
| `tot/allocator.py` | Non-overlapping serial ranges per GTIN per encoding station |
| `tot/labelstation.py` | Fatura line → lot → print run; blocks encoding beyond the invoiced quantity |
| `tot/zpl.py` | Zebra RFID label: EPC write (`^RFW`), EAN-13 for the till, expiry, batch |
| `tot/store.py` | SQLite store for the prototype (same names as `db/schema.sql`) |
| `db/schema.sql` | Production PostgreSQL schema |

### Stage 2 — handheld flows

| Module | What it does |
| --- | --- |
| `tot/movements.py` | Ship (pick → dispatch with guia + ATCUD), receive (matched / missing / extra), cycle count (vs expected and StoresAce book stock; missing after 2 counts), waste and own use |
| `tot/exports.py` | StoresAce 4-column import files (.xlsx); each file registered by SHA-256 so it can't be produced twice |
| `tot/api.py` | HTTP API for the label station and handheld |
| `tot/static/handheld.html` | Mobile screen in Portuguese: Expedir, Receber, Contar, Quebra. Zebra DataWedge (or any reader in keyboard mode) types EPCs into the read box |

## Run

```bash
pip install -r requirements.txt
python -m pytest -q

# API + handheld screen
TOT_DB=tot.db TOT_EXPORTS=exports uvicorn tot.api:app --host 0.0.0.0 --port 8000
# then open http://<server>:8000/handheld on the handheld, API docs at /docs

python -m tot.cli label --line examples/fatura_line.json \
  --scan "011560123456789917261120" --batch B77 --count 12 --out run.zpl
```

### Handheld setup (Zebra)

DataWedge profile for the browser: RFID input on, keystroke output, send
ENTER after each tag, EPC as hex. Each trigger pull fills the read box; the
screen counts unique tags and sends them in one batch.

Send `run.zpl` to a Zebra RFID printer (raw TCP port 9100, or USB).

## Notes

- The GS1 company prefix length is needed to encode an SGTIN; it cannot be
  derived from the GTIN. It is stored per item (`company_prefix_len`).
- Label positions assume 50 × 30 mm at 203 dpi; tune `tot/zpl.py` to the
  label stock and inlay position, and calibrate the printer (`~JC`, RFID
  calibration) before the first run.
- Serials start at 1e11 per station range to stay clear of serials a brand
  owner may use on the same GTIN.

## Next stages

3. StoresAce sync (items, sales, stock) and FEFO sale matching
4. Expiry alerts + dashboard (book vs physical, shipments, exports to import)
5. Native Android handheld if the browser + DataWedge route proves too limited
