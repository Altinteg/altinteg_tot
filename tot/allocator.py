"""Serial allocator.

Each (GTIN, station) pair gets a reserved, non-overlapping serial range,
so two encoding stations can never issue the same SGTIN. Serials are never
reused, including after a void label.
"""
from __future__ import annotations

import sqlite3

# Station ranges: station N owns [base + N*size, base + (N+1)*size - 1].
# The base keeps clear of low serials a brand owner might use itself.
RANGE_BASE = 100_000_000_000   # 1e11, well inside the 38-bit limit (~2.7e11)
RANGE_SIZE = 10_000_000_000    # 1e10 serials per station per GTIN


class AllocationError(RuntimeError):
    pass


def station_range(station_index: int) -> tuple[int, int]:
    start = RANGE_BASE + station_index * RANGE_SIZE
    return start, start + RANGE_SIZE - 1


def allocate(conn: sqlite3.Connection, gtin14: str, station_id: str,
             station_index: int, count: int) -> list[int]:
    """Reserve `count` consecutive serials for this GTIN at this station."""
    if count <= 0:
        raise AllocationError("count must be positive")
    start, end = station_range(station_index)
    with conn:  # one transaction
        row = conn.execute(
            "SELECT next_serial, range_end FROM serial_range WHERE gtin=? AND station_id=?",
            (gtin14, station_id)).fetchone()
        if row is None:
            conn.execute(
                "INSERT INTO serial_range VALUES (?,?,?,?,?)",
                (gtin14, station_id, start, end, start))
            nxt, rend = start, end
        else:
            nxt, rend = row["next_serial"], row["range_end"]
        if nxt + count - 1 > rend:
            raise AllocationError(f"serial range exhausted for {gtin14} at {station_id}")
        conn.execute(
            "UPDATE serial_range SET next_serial=? WHERE gtin=? AND station_id=?",
            (nxt + count, gtin14, station_id))
    return list(range(nxt, nxt + count))
