-- The Order of Things (TOT) — production schema, PostgreSQL 15+
-- Matches spec section "Data model". Commercial data (items, prices, cost of
-- record, book stock) stays in StoresAce; item_cache is a read-only copy.

CREATE TABLE location (
  location_id          text PRIMARY KEY,
  type                 text NOT NULL CHECK (type IN ('DC','store','zone')),
  name                 text NOT NULL,
  storesace_store_id   text,
  storesace_warehouse  text
);

CREATE TABLE item_cache (                       -- refreshed from StoresAce Products API
  item_code       text PRIMARY KEY,             -- StoresAce ItemId
  gtin            char(14),
  ean_list        text[] NOT NULL DEFAULT '{}',
  description     text NOT NULL,
  vat             numeric(5,2),
  family          text,
  sold_by_weight  boolean NOT NULL DEFAULT false,
  refreshed_at    timestamptz NOT NULL
);

CREATE TABLE item_rules (                       -- owned by TOT
  item_code        text REFERENCES item_cache(item_code),
  location_id      text REFERENCES location(location_id),
  min_qty          integer,
  max_qty          integer,
  critical_qty     integer,
  shelf_life_days  integer,
  markdown_days    integer NOT NULL DEFAULT 3,
  tag_required     boolean NOT NULL DEFAULT false,
  PRIMARY KEY (item_code, location_id)
);

CREATE TABLE lot (                              -- immutable after creation
  lot_id          text PRIMARY KEY,
  item_code       text NOT NULL,
  gtin            char(14) NOT NULL,
  supplier_id     text NOT NULL,
  fatura_no       text NOT NULL,
  fatura_line     integer NOT NULL,
  supplier_batch  text,
  expiry_date     date NOT NULL,
  unit_cost       numeric(12,4),
  qty_received    integer NOT NULL CHECK (qty_received > 0),
  qty_encoded     integer NOT NULL DEFAULT 0 CHECK (qty_encoded <= qty_received),
  location_id     text NOT NULL REFERENCES location(location_id),
  created_at      timestamptz NOT NULL DEFAULT now(),
  created_by      text NOT NULL,
  description     text,                         -- label text, from the fatura line
  company_prefix_len smallint CHECK (company_prefix_len BETWEEN 6 AND 12)
);
CREATE INDEX lot_fatura_idx ON lot (fatura_no, fatura_line);
CREATE INDEX lot_batch_idx  ON lot (supplier_batch);
CREATE INDEX lot_expiry_idx ON lot (expiry_date);

CREATE TABLE serial_range (                     -- one range per GTIN per station
  gtin         char(14) NOT NULL,
  station_id   text NOT NULL,
  range_start  bigint NOT NULL,
  range_end    bigint NOT NULL,
  next_serial  bigint NOT NULL,
  PRIMARY KEY (gtin, station_id)
);

CREATE TYPE tag_status AS ENUM
  ('encoded','in_stock','in_transit','on_shelf','sold','wasted','own_use','returned','missing','void');

CREATE TABLE tag (
  epc           char(24) PRIMARY KEY,           -- SGTIN-96 hex
  gtin          char(14) NOT NULL,
  serial        bigint NOT NULL,
  lot_id        text NOT NULL REFERENCES lot(lot_id),
  status        tag_status NOT NULL,
  location_id   text NOT NULL REFERENCES location(location_id),
  last_seen_at  timestamptz NOT NULL,
  missed_counts integer NOT NULL DEFAULT 0,       -- counts in a row not seen; 2 -> missing
  UNIQUE (gtin, serial)                         -- a serial is never reused
);
CREATE INDEX tag_lot_idx ON tag (lot_id);
CREATE INDEX tag_loc_status_idx ON tag (location_id, status);

CREATE TABLE shipment (
  shipment_id    text PRIMARY KEY,
  from_location  text NOT NULL REFERENCES location(location_id),
  to_location    text NOT NULL REFERENCES location(location_id),
  guia_no        text,
  atcud          text,
  status         text NOT NULL CHECK (status IN ('picking','in_transit','received','discrepancy')),
  created_at     timestamptz NOT NULL DEFAULT now(),
  dispatched_at  timestamptz,
  received_at    timestamptz
);

CREATE TABLE shipment_tag (
  shipment_id  text NOT NULL REFERENCES shipment(shipment_id),
  epc          char(24) NOT NULL REFERENCES tag(epc),
  received     boolean NOT NULL DEFAULT false,
  PRIMARY KEY (shipment_id, epc)
);

CREATE TABLE export_file (                      -- every file sent to StoresAce, never twice
  file_id       text PRIMARY KEY,
  kind          text NOT NULL CHECK (kind IN ('transfer','delivery','waste','own_use','adjustment')),
  location_id   text NOT NULL REFERENCES location(location_id),
  document_ref  text,
  created_at    timestamptz NOT NULL DEFAULT now(),
  sha256        char(64) NOT NULL UNIQUE,
  imported      boolean NOT NULL DEFAULT false
);

CREATE TABLE event (                            -- append-only, EPCIS 2.0 ObjectEvent shape
  event_id      text PRIMARY KEY,
  type          text NOT NULL DEFAULT 'ObjectEvent',
  biz_step      text NOT NULL,                  -- commissioning, shipping, receiving, ...
  epc_list      char(24)[] NOT NULL,
  location_id   text NOT NULL REFERENCES location(location_id),
  event_time    timestamptz NOT NULL,
  document_ref  text,                           -- fatura:<no>/<line>, guia:<no>, sale:<invoice>
  actor         text NOT NULL,
  device        text
);
CREATE INDEX event_time_idx ON event (event_time);

-- Events are never edited or deleted.
CREATE RULE event_no_update AS ON UPDATE TO event DO INSTEAD NOTHING;
CREATE RULE event_no_delete AS ON DELETE TO event DO INSTEAD NOTHING;
