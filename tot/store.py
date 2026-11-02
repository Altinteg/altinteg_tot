"""Local data store for the prototype (SQLite).

Production uses PostgreSQL with db/schema.sql; table and column names match,
so the prototype logic carries over.
"""
from __future__ import annotations

import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS location (
  location_id TEXT PRIMARY KEY, type TEXT NOT NULL, name TEXT NOT NULL,
  storesace_store_id TEXT, storesace_warehouse TEXT);
CREATE TABLE IF NOT EXISTS lot (
  lot_id TEXT PRIMARY KEY, item_code TEXT NOT NULL, gtin TEXT NOT NULL,
  supplier_id TEXT NOT NULL, fatura_no TEXT NOT NULL, fatura_line INTEGER NOT NULL,
  supplier_batch TEXT, expiry_date TEXT NOT NULL, unit_cost REAL,
  qty_received INTEGER NOT NULL, qty_encoded INTEGER NOT NULL DEFAULT 0,
  location_id TEXT NOT NULL, created_at TEXT NOT NULL, created_by TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS serial_range (
  gtin TEXT NOT NULL, station_id TEXT NOT NULL, range_start INTEGER NOT NULL,
  range_end INTEGER NOT NULL, next_serial INTEGER NOT NULL,
  PRIMARY KEY (gtin, station_id));
CREATE TABLE IF NOT EXISTS tag (
  epc TEXT PRIMARY KEY, gtin TEXT NOT NULL, serial INTEGER NOT NULL,
  lot_id TEXT NOT NULL REFERENCES lot(lot_id), status TEXT NOT NULL,
  location_id TEXT NOT NULL, last_seen_at TEXT NOT NULL,
  UNIQUE (gtin, serial));
CREATE TABLE IF NOT EXISTS event (
  event_id TEXT PRIMARY KEY, type TEXT NOT NULL, biz_step TEXT NOT NULL,
  epc_list TEXT NOT NULL, location_id TEXT NOT NULL, event_time TEXT NOT NULL,
  document_ref TEXT, actor TEXT NOT NULL, device TEXT);
"""


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


def connect(path: str | Path) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA)
    return conn
