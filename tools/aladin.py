"""Minimal GRIB edition 1 reader for ČHMÚ ALADIN CZ_1km open data.

The ALADIN CZ_1km files are a lucky special case: a regular latitude/longitude
grid with simple (fixed bit width) packing and no bitmap. That means a single
grid point can be read with plain bit arithmetic - no eccodes, no cfgrib, no
numpy, nothing outside the standard library.

Only the subset of GRIB1 that ČHMÚ actually emits is implemented. Anything else
raises, on purpose: silently mis-decoding weather data is worse than failing.

Reference: https://opendata.chmi.cz/meteorology/weather/nwp_aladin/
"""

from __future__ import annotations

import bz2
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

# Grid definition section, data representation type (octet 6).
_GDS_LATLON = 0

# Binary data section flags (octet 4). The high nibble must be all zero:
# grid point data, simple packing, float values, no additional flags.
_BDS_SIMPLE_PACKING = 0x00

# Time range indicator values we know how to turn into a valid time.
_TRI_INSTANT = 0  # valid at reference + P1
_TRI_ANALYSIS = 1  # the analysis itself, valid at the reference time
_TRI_ACCUMULATION = 4  # accumulated over reference + P1 .. reference + P2
_TRI_P1_IS_TWO_OCTETS = 10  # valid at reference + (P1 << 8 | P2)


def _u3(b: bytes) -> int:
    return (b[0] << 16) | (b[1] << 8) | b[2]


def _i2(b: bytes) -> int:
    v = (b[0] << 8) | b[1]
    return -(v & 0x7FFF) if v & 0x8000 else v


def _i3(b: bytes) -> int:
    v = _u3(b)
    return -(v & 0x7FFFFF) if v & 0x800000 else v


def _ibm_float(b: bytes) -> float:
    """Decode a 4 byte IBM/360 single precision float (GRIB1 reference value)."""
    sign = -1 if b[0] & 0x80 else 1
    exponent = (b[0] & 0x7F) - 64
    mantissa = (b[1] << 16) | (b[2] << 8) | b[3]
    return sign * mantissa * (16.0**exponent) / (1 << 24)


@dataclass(frozen=True)
class Grid:
    """Regular latitude/longitude grid, as described by the GRIB1 GDS."""

    ni: int
    nj: int
    lat1: float
    lon1: float
    di: float
    dj: float

    @classmethod
    def from_gds(cls, gds: bytes) -> Grid:
        if gds[5] != _GDS_LATLON:
            raise ValueError(f"unsupported GRIB1 grid type {gds[5]}, expected latlon")
        return cls(
            ni=(gds[6] << 8) | gds[7],
            nj=(gds[8] << 8) | gds[9],
            lat1=_i3(gds[10:13]) / 1000,
            lon1=_i3(gds[13:16]) / 1000,
            di=_i2(gds[23:25]) / 1000,
            dj=_i2(gds[25:27]) / 1000,
        )

    def contains(self, lat: float, lon: float) -> bool:
        i = round((lon - self.lon1) / self.di)
        j = round((lat - self.lat1) / self.dj)
        return 0 <= i < self.ni and 0 <= j < self.nj

    def index(self, lat: float, lon: float) -> int:
        """Return the flat index of the grid point nearest to lat/lon.

        Scanning mode 0x40 (west to east, south to north, i consecutive) is the
        only one ČHMÚ uses for this product, so the layout is simply j * ni + i.
        """
        i = round((lon - self.lon1) / self.di)
        j = round((lat - self.lat1) / self.dj)
        if not (0 <= i < self.ni and 0 <= j < self.nj):
            raise ValueError(f"point {lat},{lon} outside the ALADIN CZ_1km domain")
        return j * self.ni + i


@dataclass
class Message:
    """One decoded GRIB1 message: a single parameter at a single valid time."""

    parameter: int
    valid_time: datetime
    grid: Grid
    _reference: float
    _binary_scale: int
    _decimal_scale: int
    _bits: int
    _data: bytes

    def value_at(self, index: int) -> float:
        """Read one packed value by flat grid index."""
        bit = index * self._bits
        first = bit // 8
        offset = bit % 8
        span = (offset + self._bits + 7) // 8
        chunk = int.from_bytes(self._data[first : first + span], "big")
        packed = (chunk >> (span * 8 - offset - self._bits)) & ((1 << self._bits) - 1)
        scaled = self._reference + packed * 2.0**self._binary_scale
        return scaled / 10.0**self._decimal_scale


def _valid_time(pds: bytes) -> datetime:
    century, year = pds[24], pds[12]
    reference = datetime(
        (century - 1) * 100 + year, pds[13], pds[14], pds[15], pds[16], tzinfo=UTC
    )

    unit, p1, p2, tri = pds[17], pds[18], pds[19], pds[20]
    if unit != 1:
        raise ValueError(f"unsupported GRIB1 time unit {unit}, expected hours")

    if tri == _TRI_ANALYSIS:
        step = 0
    elif tri == _TRI_INSTANT:
        step = p1
    elif tri in (_TRI_ACCUMULATION, _TRI_P1_IS_TWO_OCTETS):
        # Accumulations are stamped with the end of their period; for TRI 10 the
        # two octets together are the (larger than 255) forecast step.
        step = (p1 << 8) | p2 if tri == _TRI_P1_IS_TWO_OCTETS else p2
    else:
        raise ValueError(f"unsupported GRIB1 time range indicator {tri}")

    return reference + timedelta(hours=step)


def iter_messages(raw: bytes) -> Iterator[Message]:
    """Walk every GRIB1 message in a decompressed ALADIN file."""
    offset = 0
    while offset < len(raw):
        if raw[offset : offset + 4] != b"GRIB":
            raise ValueError(f"expected a GRIB header at byte {offset}")
        total = _u3(raw[offset + 4 : offset + 7])
        if raw[offset + 7] != 1:
            raise ValueError(f"unsupported GRIB edition {raw[offset + 7]}, expected 1")

        cursor = offset + 8
        pds = raw[cursor : cursor + _u3(raw[cursor : cursor + 3])]
        cursor += len(pds)

        if not pds[7] & 0x80:
            raise ValueError("message has no grid definition section")
        gds = raw[cursor : cursor + _u3(raw[cursor : cursor + 3])]
        cursor += len(gds)

        if pds[7] & 0x40:
            raise ValueError("bitmapped messages are not supported")

        bds = raw[cursor : cursor + _u3(raw[cursor : cursor + 3])]
        if bds[3] & 0xF0 != _BDS_SIMPLE_PACKING:
            raise ValueError(f"unsupported BDS packing flags {bds[3]:#04x}")

        yield Message(
            parameter=pds[8],
            valid_time=_valid_time(pds),
            grid=Grid.from_gds(gds),
            _reference=_ibm_float(bds[6:10]),
            _binary_scale=_i2(bds[4:6]),
            _decimal_scale=_i2(pds[26:28]),
            _bits=bds[10],
            _data=bds[11:],
        )
        offset += total


def series_at_points(
    compressed: bytes, coordinates: Sequence[tuple[float, float]]
) -> dict[datetime, list[float]]:
    """Decode a .grb.bz2 blob into {valid_time: [value per coordinate]}.

    Every message is visited once and sampled for all coordinates, so adding
    stations costs a few bit reads rather than another pass over the file.
    """
    raw = bz2.decompress(compressed)
    series: dict[datetime, list[float]] = {}
    indices: list[int] | None = None
    for message in iter_messages(raw):
        if indices is None:
            indices = [message.grid.index(lat, lon) for lat, lon in coordinates]
        series[message.valid_time] = [message.value_at(i) for i in indices]
    return series
