"""Which ORP a point lies in, for matching ČHMÚ warnings to a station.

ČHMÚ addresses its warnings to ORPs (obce s rozšířenou působností) by their
ČSÚ code and ships no geometry with them. data/orp.json.gz holds the ORP
boundaries, built by tools/build_orp.py from ČÚZK RÚIAN (CC BY 4.0) and
simplified to about 0.002°.

Loading reads and parses a ~150 kB file, so call load_orps from the executor.
"""

from __future__ import annotations

import gzip
import json
import math
from dataclasses import dataclass
from functools import cache
from pathlib import Path

ORP_FILE = Path(__file__).parent / "data" / "orp.json.gz"

Ring = list[tuple[float, float]]  # (longitude, latitude)


@dataclass(frozen=True)
class Orp:
    """One ORP: its ČSÚ code (CISORP), name and polygons ([outer, *holes])."""

    code: str
    name: str
    polygons: tuple[tuple[Ring, ...], ...]


@cache
def load_orps() -> tuple[Orp, ...]:
    """Read the shipped ORP boundaries. Blocking; cached after the first call."""
    with gzip.open(ORP_FILE, "rt", encoding="utf-8") as handle:
        document = json.load(handle)
    return tuple(
        Orp(
            code=item["code"],
            name=item["name"],
            polygons=tuple(
                tuple([(lon, lat) for lon, lat in ring] for ring in polygon)
                for polygon in item["polygons"]
            ),
        )
        for item in document["orp"]
    )


def orp_names() -> dict[str, str]:
    """Return CISORP code -> ORP name."""
    return {orp.code: orp.name for orp in load_orps()}


def _in_ring(lon: float, lat: float, ring: Ring) -> bool:
    """Ray casting: whether the point lies inside the closed ring."""
    inside = False
    previous_lon, previous_lat = ring[-1]
    for ring_lon, ring_lat in ring:
        if (ring_lat > lat) != (previous_lat > lat):
            crossing = (previous_lon - ring_lon) * (lat - ring_lat) / (
                previous_lat - ring_lat
            ) + ring_lon
            if lon < crossing:
                inside = not inside
        previous_lon, previous_lat = ring_lon, ring_lat
    return inside


def _contains(orp: Orp, lon: float, lat: float) -> bool:
    return any(
        _in_ring(lon, lat, polygon[0])
        and not any(_in_ring(lon, lat, hole) for hole in polygon[1:])
        for polygon in orp.polygons
    )


def _distance_to_ring_km(lon: float, lat: float, ring: Ring) -> float:
    """Distance from the point to the nearest edge of the ring, in km.

    Uses a local equirectangular projection, which is accurate to well under a
    percent over the few kilometres this is ever asked about.
    """
    scale_x = 111.32 * math.cos(math.radians(lat))
    scale_y = 110.57
    best = math.inf
    previous = ring[-1]
    for current in ring:
        ax = (previous[0] - lon) * scale_x
        ay = (previous[1] - lat) * scale_y
        bx = (current[0] - lon) * scale_x
        by = (current[1] - lat) * scale_y
        dx, dy = bx - ax, by - ay
        length = dx * dx + dy * dy
        t = 0.0 if length == 0 else max(0.0, min(1.0, -(ax * dx + ay * dy) / length))
        best = min(best, math.hypot(ax + t * dx, ay + t * dy))
        previous = current
    return best


# A point further than this from every ORP is not in Czechia at all.
NEAREST_ORP_LIMIT_KM = 5.0


def find_orp(latitude: float, longitude: float) -> Orp | None:
    """Return the ORP containing the point, or None outside Czechia.

    Simplifying the boundaries moves them by up to ~200 m, which leaves a
    station standing right on the state border (Višňová) just outside every
    polygon. Such a point gets the nearest ORP, as long as it is within
    NEAREST_ORP_LIMIT_KM.
    """
    orps = load_orps()
    for orp in orps:
        if _contains(orp, longitude, latitude):
            return orp

    distance, nearest = min(
        (
            min(
                _distance_to_ring_km(longitude, latitude, polygon[0])
                for polygon in orp.polygons
            ),
            index,
        )
        for index, orp in enumerate(orps)
    )
    return orps[nearest] if distance <= NEAREST_ORP_LIMIT_KM else None
