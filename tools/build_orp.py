"""Build the ORP boundary file the weather warnings are matched against.

ČHMÚ issues its warnings (CAP, see custom_components/chmu/warnings.py) per ORP,
obec s rozšířenou působností, and names the ORP only by its ČSÚ code
(`CISORP`): the messages carry no geometry. A station has only coordinates, so
the integration needs the ORP boundaries to tell which warnings concern it.

Sources, both free to use:

- ORP polygons from ČÚZK RÚIAN (CC BY 4.0), layer ObecSRozsirenouPusobnosti of
  the RUIAN map service, requested in WGS84 and simplified on the server to
  about 0.002° (150-220 m). That keeps the file small and moves a boundary by
  less than the distance between neighbouring stations.
- ČSÚ codelist 65 (CISORP), whose `kod_ruian` column translates the RÚIAN ORP
  code (Benešov = 27) to the code ČHMÚ uses (Benešov = 2101).

ČHMÚ deviates from the ČSÚ codelist in one place: Prague is 1100 in the CAP
messages and 1000 in the codelist. Every other code matches.

Usage:
    python tools/build_orp.py
    python tools/build_orp.py --out /tmp/orp.json.gz

Rerun when ORPs change, which last happened in 2003.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import io
import json
import urllib.parse
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

RUIAN_LAYER = "https://ags.cuzk.cz/arcgis/rest/services/RUIAN/MapServer/14/query"  # ORP
CSU_CODELIST = "https://apl2.czso.cz/iSMS/do_cis_export"
SIMPLIFY_DEGREES = 0.002
PRECISION = 4

# ČHMÚ's code for an ORP where it differs from the ČSÚ codelist.
CHMU_CODE_OVERRIDES = {"1000": "1100"}

DEFAULT_OUT = (
    Path(__file__).resolve().parents[1]
    / "custom_components"
    / "chmu"
    / "data"
    / "orp.json.gz"
)

USER_AGENT = "Home-Assistant-CHMU-Integration/1.0 (build_orp)"


def _get(url: str, params: dict[str, str]) -> bytes:
    request = urllib.request.Request(
        f"{url}?{urllib.parse.urlencode(params)}",
        headers={"User-Agent": USER_AGENT},
    )
    with urllib.request.urlopen(request, timeout=120) as response:
        return response.read()


def fetch_ruian_to_cisorp() -> dict[str, str]:
    """Return RÚIAN ORP code -> CISORP code for the ORPs valid today."""
    raw = _get(
        CSU_CODELIST,
        {
            "kodcis": "65",
            "typdat": "0",
            "cisjaz": "203",
            "format": "2",
            "separator": ",",
        },
    )
    today = datetime.now(UTC).date().isoformat()
    mapping = {}
    for row in csv.DictReader(io.StringIO(raw.decode("utf-8"))):
        if not row["admplod"] <= today <= row["admnepo"]:
            continue
        code = CHMU_CODE_OVERRIDES.get(row["chodnota"], row["chodnota"])
        mapping[row["kod_ruian"]] = code
    return mapping


def fetch_orp_polygons() -> list[dict[str, Any]]:
    """Return the ORP features as GeoJSON, simplified, in WGS84."""
    raw = _get(
        RUIAN_LAYER,
        {
            "where": "1=1",
            "outFields": "kod,nazev",
            "outSR": "4326",
            "maxAllowableOffset": str(SIMPLIFY_DEGREES),
            "geometryPrecision": str(PRECISION),
            "f": "geojson",
        },
    )
    return json.loads(raw)["features"]


def _polygons(geometry: dict[str, Any]) -> list[list[list[list[float]]]]:
    """Return the geometry as a list of polygons, each [outer, *holes]."""
    if geometry["type"] == "Polygon":
        polygons = [geometry["coordinates"]]
    elif geometry["type"] == "MultiPolygon":
        polygons = geometry["coordinates"]
    else:
        raise ValueError(f"Unexpected ORP geometry {geometry['type']}")
    return [
        [
            [[round(lon, PRECISION), round(lat, PRECISION)] for lon, lat in ring]
            for ring in polygon
        ]
        for polygon in polygons
    ]


def build() -> dict[str, Any]:
    """Join the polygons with their CISORP codes."""
    codes = fetch_ruian_to_cisorp()
    orps = []
    for feature in fetch_orp_polygons():
        properties = feature["properties"]
        ruian_code = str(properties["kod"])
        if ruian_code not in codes:
            raise ValueError(f"RÚIAN ORP {ruian_code} has no CISORP code")
        orps.append(
            {
                "code": codes[ruian_code],
                "name": properties["nazev"],
                "polygons": _polygons(feature["geometry"]),
            }
        )

    if len(orps) != len(codes):
        raise ValueError(f"{len(orps)} ORP polygons for {len(codes)} ORP codes")

    orps.sort(key=lambda orp: orp["code"])
    return {
        "source": (
            "ORP boundaries: ČÚZK RÚIAN (CC BY 4.0), simplified to "
            f"{SIMPLIFY_DEGREES}°; codes: ČSÚ codelist 65 (CISORP)"
        ),
        "orp": orps,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()

    document = build()
    payload = json.dumps(document, ensure_ascii=False, separators=(",", ":"))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    # mtime=0 keeps the file byte-identical between runs on unchanged data.
    with gzip.GzipFile(args.out, "wb", mtime=0) as handle:
        handle.write(payload.encode("utf-8"))
    print(f"Wrote {len(document['orp'])} ORPs to {args.out}")


if __name__ == "__main__":
    main()
