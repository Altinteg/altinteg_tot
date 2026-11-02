# The Order of Things (TOT) — shop MVP

Item-level identity, batch and expiry for the Onda Limão shop and its DC,
alongside StoresAce (commercial owner) and ZoneSoft (fiscal owner).
Spec: "The Order of Things — Onda Limão MVP spec" (Claude Docs).

## Stage 1 (this code)

| Module | What it does |
| --- | --- |
| `tot/sgtin.py` | SGTIN-96 encode/decode (GS1 TDS), GTIN check digits |
| `tot/gs1.py` | Parses case barcodes (AI 01, 10, 15, 17, 21) for batch and expiry |
| `tot/allocator.py` | Non-overlapping serial ranges per GTIN per encoding station |
| `tot/labelstation.py` | Fatura line → lot → print run; blocks encoding beyond the invoiced quantity |
| `tot/zpl.py` | Zebra RFID label: EPC write (`^RFW`), EAN-13 for the till, expiry, batch |
| `tot/store.py` | SQLite store for the prototype (same names as `db/schema.sql`) |
| `db/schema.sql` | Production PostgreSQL schema |

## Run

```bash
pip install pytest
python -m pytest -q
python -m tot.cli label --line examples/fatura_line.json \
  --scan "011560123456789917261120" --batch B77 --count 12 --out run.zpl
```

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

2. Handheld (ship, receive, count) + shipments
3. StoresAce sync (items, sales, stock) + 4-column export files
4. Expiry alerts + dashboard
