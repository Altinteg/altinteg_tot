"""Parse GS1 element strings from case barcodes (GS1-128 / DataMatrix).

Handles the application identifiers the label station needs:
01 GTIN, 10 batch, 17 expiry (YYMMDD), 15 best before, 21 serial.
Variable-length fields end at a GS character (ASCII 29) or the string end.
Scanners often prefix ]C1 / ]d2; those are stripped.
"""
from __future__ import annotations

from datetime import date

GS = "\x1d"
FIXED = {"01": 14, "02": 14, "11": 6, "13": 6, "15": 6, "17": 6}
VARIABLE = {"10": 20, "21": 20, "37": 8}


class Gs1Error(ValueError):
    pass


def yymmdd(value: str) -> date:
    yy, mm, dd = int(value[:2]), int(value[2:4]), int(value[4:6])
    year = 2000 + yy if yy < 51 else 1900 + yy
    if dd == 0:  # GS1: day 00 = last day of the month
        nxt = date(year + (mm == 12), mm % 12 + 1, 1)
        return date.fromordinal(nxt.toordinal() - 1)
    return date(year, mm, dd)


def parse(data: str) -> dict:
    s = data.strip()
    for prefix in ("]C1", "]d2", "]Q3", "]e0"):
        if s.startswith(prefix):
            s = s[len(prefix):]
    s = s.lstrip(GS)
    out: dict = {}
    i = 0
    while i < len(s):
        ai = s[i:i + 2]
        i += 2
        if ai in FIXED:
            n = FIXED[ai]
            value = s[i:i + n]
            if len(value) != n:
                raise Gs1Error(f"AI {ai} too short")
            i += n
            if i < len(s) and s[i] == GS:
                i += 1
        elif ai in VARIABLE:
            end = s.find(GS, i)
            end = len(s) if end == -1 else end
            value = s[i:end][:VARIABLE[ai]]
            i = end + 1
        else:
            raise Gs1Error(f"unsupported AI {ai!r} at position {i - 2}")
        out[ai] = value
    result: dict = {}
    if "01" in out:
        result["gtin"] = out["01"]
    if "10" in out:
        result["batch"] = out["10"]
    if "17" in out:
        result["expiry"] = yymmdd(out["17"])
    elif "15" in out:
        result["expiry"] = yymmdd(out["15"])
    if "21" in out:
        result["serial"] = out["21"]
    return result
