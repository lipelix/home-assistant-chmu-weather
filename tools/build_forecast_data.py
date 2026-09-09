"""Build per-station forecast JSON from ČHMÚ ALADIN CZ_1km open data.

Runs in CI, not in Home Assistant. It downloads one ALADIN model run (~63 MB),
samples every ČHMÚ station coordinate out of the 1 km grid and writes a small
JSON per station. The integration then fetches a few kilobytes instead of tens
of megabytes, and gets a forecast for its own station instead of a national one.

Output layout (published as a static site):

    v1/index.json          run metadata + station list
    v1/<station-wsi>.json  hourly and daily forecast for one station

Values are published raw (SI units, as the model emits them). Mapping cloud
cover and precipitation to a Home Assistant condition is the integration's job,
so that changing the mapping does not require regenerating the data.

Usage:
    python tools/build_forecast_data.py --out dist
    python tools/build_forecast_data.py --out dist --limit 5   # quick check
"""

from __future__ import annotations

import argparse
import bz2
import http.client
import json
import re
import sys
import time
import urllib.error
import urllib.request
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent))

from aladin import Grid, iter_messages  # noqa: E402

ALADIN_BASE = "https://opendata.chmi.cz/meteorology/weather/nwp_aladin/CZ_1km"
STATION_METADATA = "https://opendata.chmi.cz/meteorology/climate/now/metadata"
USER_AGENT = "home-assistant-chmu-weather forecast builder"
SCHEMA_VERSION = 1

# ALADIN file name stem -> (output key, converter). Hourly fields only.
HOURLY_PARAMS: dict[str, tuple[str, Any]] = {
    "CLSTEMPERATURE": ("temperature", lambda v: round(v - 273.15, 1)),
    "CLSHUMI_RELATIVE": ("humidity", lambda v: round(min(max(v, 0.0), 1.0) * 100)),
    "SURFNEBUL_TOTALE": (
        "cloud_coverage",
        lambda v: round(min(max(v, 0.0), 1.0) * 100),
    ),
    "CLSWIND_SPEED": ("wind_speed", lambda v: round(v * 3.6, 1)),  # m/s -> km/h
    "CLSWIND_DIREC": ("wind_bearing", lambda v: round(v) % 360),
    "PRECIP_TYPE": ("precipitation_type", lambda v: round(v)),
}

# Cumulative from the start of the run; published as a per-hour difference.
PRECIPITATION_PARAM = "SURFPREC_TOTAL"

# 12 hour extremes, stamped 06Z (overnight low) and 18Z (daytime high).
DAILY_PARAMS = {
    "CLSMAXI_TEMPERAT": ("temperature", 18),
    "CLSMINI_TEMPERAT": ("templow", 6),
}

REQUIRED_PARAMS = (*HOURLY_PARAMS, PRECIPITATION_PARAM, *DAILY_PARAMS)

_RUN_FILE_RE = re.compile(r"ALADCZ1K4opendata_(\d{10})_([A-Z0-9_]+)\.grb\.bz2")

# One build makes about fifteen requests to opendata.chmi.cz and used to make
# each of them once, so a single dropped connection failed the whole run - and
# the next scheduled attempt is a model cycle away, which GitHub then delays by
# up to five hours on top. That is what happened to run 34350942136: a TCP
# connect timeout on the very first directory listing.
RETRY_ATTEMPTS = 4
RETRY_BACKOFF = timedelta(seconds=5)


def _retryable(error: Exception) -> bool:
    """Is this failure worth another attempt?

    A 4xx is the server answering rather than failing, so retrying only burns
    the run's time - and load_stations needs a 404 back promptly so it can ask
    for yesterday's metadata instead. Everything else reaching here is a
    transport failure, which is exactly the transient case retries exist for.
    """
    if isinstance(error, urllib.error.HTTPError):
        return error.code == 429 or error.code >= 500
    return True


def _get(url: str, timeout: int = 300) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})

    for attempt in range(1, RETRY_ATTEMPTS + 1):
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return response.read()
        # HTTPException covers a body that stops mid-download; these files are
        # tens of megabytes, so that is a real outcome and not an OSError.
        except (OSError, http.client.HTTPException) as error:
            if attempt == RETRY_ATTEMPTS or not _retryable(error):
                raise
            delay = RETRY_BACKOFF * attempt
            print(
                f"  {url} failed ({error!r}), attempt {attempt}/{RETRY_ATTEMPTS}, "
                f"retrying in {delay.total_seconds():.0f}s",
                file=sys.stderr,
                flush=True,
            )
            time.sleep(delay.total_seconds())

    raise AssertionError("unreachable: the last attempt either returns or raises")


def find_latest_run() -> str:
    """Return the newest run id (YYYYMMDDHH) that has every parameter we need."""
    available: dict[str, set[str]] = defaultdict(set)
    for hour in ("00", "06", "12", "18"):
        index = _get(f"{ALADIN_BASE}/{hour}/", timeout=60).decode("utf-8", "replace")
        for run, param in _RUN_FILE_RE.findall(index):
            available[run].add(param)

    complete = [
        run for run, params in available.items() if set(REQUIRED_PARAMS) <= params
    ]
    if not complete:
        raise RuntimeError("no ALADIN run on opendata has the full parameter set")
    return max(complete)


def load_stations(limit: int | None = None) -> list[dict[str, Any]]:
    """Fetch ČHMÚ station metadata (today's file, yesterday's as a fallback)."""
    for delta in (0, 1):
        day = (datetime.now(UTC) - timedelta(days=delta)).strftime("%Y%m%d")
        try:
            payload = json.loads(_get(f"{STATION_METADATA}/meta1-{day}.json", 60))
        except OSError:
            continue
        # header: WSI, GH_ID, FULL_NAME, GEOGR1 (lon), GEOGR2 (lat), ELEVATION, ...
        # The metadata occasionally repeats a station verbatim, so key by WSI.
        by_id = {
            row[0]: {
                "station_id": row[0],
                "name": row[2],
                "longitude": row[3],
                "latitude": row[4],
                "elevation": row[5],
            }
            for row in payload["data"]["data"]["values"]
        }
        stations = sorted(by_id.values(), key=lambda s: s["station_id"])
        return stations[:limit] if limit else stations
    raise RuntimeError("could not download ČHMÚ station metadata")


def _param_url(run: str, param: str) -> str:
    return f"{ALADIN_BASE}/{run[8:]}/ALADCZ1K4opendata_{run}_{param}.grb.bz2"


def _sample(run: str, param: str, coordinates: list[tuple[float, float]]):
    """Download one parameter and return {valid_time: [value per coordinate]}."""
    blob = _get(_param_url(run, param))
    series: dict[datetime, list[float]] = {}
    indices: list[int] | None = None
    for message in iter_messages(bz2.decompress(blob)):
        if indices is None:
            indices = [message.grid.index(lat, lon) for lat, lon in coordinates]
        series[message.valid_time] = [message.value_at(i) for i in indices]
    print(
        f"  {param:18s} {len(blob) / 1e6:5.1f} MB  {len(series):3d} steps", flush=True
    )
    return series


def read_grid(run: str) -> Grid:
    """Read the grid definition from the smallest file of a run."""
    blob = _get(_param_url(run, "PRECIP_TYPE"))
    return next(iter_messages(bz2.decompress(blob))).grid


def build(out_dir: Path, limit: int | None = None) -> None:
    run = find_latest_run()
    reference = datetime.strptime(run, "%Y%m%d%H").replace(tzinfo=UTC)
    print(f"ALADIN CZ_1km run {reference:%Y-%m-%d %HZ}", flush=True)

    stations = load_stations(limit)
    grid = read_grid(run)
    inside = [s for s in stations if grid.contains(s["latitude"], s["longitude"])]
    skipped = len(stations) - len(inside)
    print(f"{len(inside)} stations in domain ({skipped} outside, skipped)", flush=True)

    coordinates = [(s["latitude"], s["longitude"]) for s in inside]

    hourly: dict[str, dict[datetime, list[float]]] = {}
    for param in HOURLY_PARAMS:
        hourly[param] = _sample(run, param, coordinates)
    cumulative = _sample(run, PRECIPITATION_PARAM, coordinates)
    daily = {param: _sample(run, param, coordinates) for param in DAILY_PARAMS}

    # Cumulative precipitation -> per-hour amounts, shared by all stations.
    precip_times = sorted(cumulative)
    precipitation: dict[datetime, list[float]] = {}
    previous = [0.0] * len(inside)
    for when in precip_times:
        current = cumulative[when]
        precipitation[when] = [
            max(c - p, 0.0) for c, p in zip(current, previous, strict=True)
        ]
        previous = current

    generated = datetime.now(UTC).replace(microsecond=0)
    version_dir = out_dir / "v1"
    version_dir.mkdir(parents=True, exist_ok=True)

    steps = sorted(set().union(*(series.keys() for series in hourly.values())))
    for position, station in enumerate(inside):
        entries = []
        for when in steps:
            entry = {"datetime": when.isoformat().replace("+00:00", "Z")}
            for param, (key, convert) in HOURLY_PARAMS.items():
                values = hourly[param].get(when)
                if values is not None:
                    entry[key] = convert(values[position])
            rain = precipitation.get(when)
            if rain is not None:
                entry["precipitation"] = round(rain[position], 1)
            entries.append(entry)

        days: dict[str, dict[str, Any]] = {}
        for param, (key, hour) in DAILY_PARAMS.items():
            for when, values in daily[param].items():
                if when.hour != hour:
                    continue
                day = days.setdefault(
                    when.date().isoformat(), {"date": when.date().isoformat()}
                )
                day[key] = round(values[position] - 273.15, 1)

        document = {
            "schema": SCHEMA_VERSION,
            "model": "ALADIN CZ_1km",
            "run": reference.isoformat().replace("+00:00", "Z"),
            "generated": generated.isoformat().replace("+00:00", "Z"),
            "station": station,
            "hourly": entries,
            "daily": [days[key] for key in sorted(days)],
        }
        path = version_dir / f"{station['station_id']}.json"
        path.write_text(
            json.dumps(document, ensure_ascii=False, separators=(",", ":")),
            encoding="utf-8",
        )

    index = {
        "schema": SCHEMA_VERSION,
        "model": "ALADIN CZ_1km",
        "run": reference.isoformat().replace("+00:00", "Z"),
        "generated": generated.isoformat().replace("+00:00", "Z"),
        "hours": len(steps),
        "stations": [
            {"station_id": s["station_id"], "name": s["name"]} for s in inside
        ],
    }
    (version_dir / "index.json").write_text(
        json.dumps(index, ensure_ascii=False, separators=(",", ":")), encoding="utf-8"
    )

    written = sum(p.stat().st_size for p in version_dir.glob("*.json"))
    print(
        f"wrote {len(inside) + 1} files, {written / 1e6:.1f} MB, "
        f"{len(steps)} hourly steps",
        flush=True,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=Path("dist"))
    parser.add_argument("--limit", type=int, help="only build the first N stations")
    args = parser.parse_args()
    build(args.out, args.limit)


if __name__ == "__main__":
    main()
