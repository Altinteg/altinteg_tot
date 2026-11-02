"""SGTIN-96 encoding and decoding (GS1 EPC Tag Data Standard).

An SGTIN identifies one unit: GTIN + serial number.
The GS1 Company Prefix length is needed to split the GTIN; it is NOT
derivable from the GTIN alone. Pass it explicitly (look it up in the GS1
GCP length table, or use your own prefix length for own-packed products).
"""
from __future__ import annotations

from dataclasses import dataclass

HEADER_SGTIN96 = 0x30
SERIAL_BITS = 38
MAX_SERIAL = (1 << SERIAL_BITS) - 1

# partition -> (company prefix bits, company prefix digits, item ref bits, item ref digits)
PARTITIONS = {
    0: (40, 12, 4, 1),
    1: (37, 11, 7, 2),
    2: (34, 10, 10, 3),
    3: (30, 9, 14, 4),
    4: (27, 8, 17, 5),
    5: (24, 7, 20, 6),
    6: (20, 6, 24, 7),
}
PARTITION_BY_CP_DIGITS = {v[1]: k for k, v in PARTITIONS.items()}

# Filter values (TDS): 1 = point-of-sale trade item
FILTER_POS_ITEM = 1


class SgtinError(ValueError):
    pass


def gtin_check_digit(body: str) -> int:
    """GS1 mod-10 check digit for the digits before the check digit."""
    total = 0
    for i, ch in enumerate(reversed(body)):
        total += int(ch) * (3 if i % 2 == 0 else 1)
    return (10 - total % 10) % 10


def normalize_gtin(gtin: str) -> str:
    """Return a validated GTIN-14 from an 8/12/13/14-digit GTIN."""
    g = gtin.strip()
    if not g.isdigit() or len(g) not in (8, 12, 13, 14):
        raise SgtinError(f"GTIN must be 8, 12, 13 or 14 digits: {gtin!r}")
    g = g.zfill(14)
    if gtin_check_digit(g[:-1]) != int(g[-1]):
        raise SgtinError(f"GTIN check digit is wrong: {gtin!r}")
    return g


@dataclass(frozen=True)
class Sgtin:
    gtin14: str
    company_prefix_len: int
    serial: int
    filter_value: int = FILTER_POS_ITEM

    @property
    def company_prefix(self) -> str:
        return self.gtin14[1 : 1 + self.company_prefix_len]

    @property
    def item_reference(self) -> str:
        # indicator digit first, then the rest of the item reference
        return self.gtin14[0] + self.gtin14[1 + self.company_prefix_len : 13]

    @property
    def pure_uri(self) -> str:
        return f"urn:epc:id:sgtin:{self.company_prefix}.{self.item_reference}.{self.serial}"

    @property
    def tag_uri(self) -> str:
        return (
            f"urn:epc:tag:sgtin-96:{self.filter_value}."
            f"{self.company_prefix}.{self.item_reference}.{self.serial}"
        )


def encode(gtin: str, company_prefix_len: int, serial: int,
           filter_value: int = FILTER_POS_ITEM) -> str:
    """Encode an SGTIN-96 and return 24 uppercase hex characters."""
    g = normalize_gtin(gtin)
    if company_prefix_len not in PARTITION_BY_CP_DIGITS:
        raise SgtinError("company prefix length must be 6-12 digits")
    if not 0 <= serial <= MAX_SERIAL:
        raise SgtinError(f"serial must be 0..{MAX_SERIAL} for SGTIN-96")
    if not 0 <= filter_value <= 7:
        raise SgtinError("filter value must be 0..7")
    s = Sgtin(g, company_prefix_len, serial, filter_value)
    partition = PARTITION_BY_CP_DIGITS[company_prefix_len]
    cp_bits, _, ir_bits, _ = PARTITIONS[partition]
    value = HEADER_SGTIN96
    value = (value << 3) | filter_value
    value = (value << 3) | partition
    value = (value << cp_bits) | int(s.company_prefix)
    value = (value << ir_bits) | int(s.item_reference)
    value = (value << SERIAL_BITS) | serial
    return f"{value:024X}"


def decode(epc_hex: str) -> Sgtin:
    """Decode a 24-hex-character SGTIN-96 EPC."""
    h = epc_hex.strip().upper()
    if len(h) != 24:
        raise SgtinError("SGTIN-96 EPC must be 24 hex characters")
    value = int(h, 16)
    header = value >> 88
    if header != HEADER_SGTIN96:
        raise SgtinError(f"not an SGTIN-96 header: {header:#04x}")
    filter_value = (value >> 85) & 0b111
    partition = (value >> 82) & 0b111
    if partition not in PARTITIONS:
        raise SgtinError(f"invalid partition {partition}")
    cp_bits, cp_digits, ir_bits, ir_digits = PARTITIONS[partition]
    serial = value & MAX_SERIAL
    ir = (value >> SERIAL_BITS) & ((1 << ir_bits) - 1)
    cp = (value >> (SERIAL_BITS + ir_bits)) & ((1 << cp_bits) - 1)
    cp_s, ir_s = str(cp).zfill(cp_digits), str(ir).zfill(ir_digits)
    body = ir_s[0] + cp_s + ir_s[1:]
    gtin14 = body + str(gtin_check_digit(body))
    return Sgtin(gtin14, cp_digits, serial, filter_value)
