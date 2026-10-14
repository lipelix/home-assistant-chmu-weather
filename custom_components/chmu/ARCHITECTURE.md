# ČHMÚ Weather Integration Architecture

## System Overview

```
 opendata.chmi.cz                          lipelix.github.io/.../v1
 ├─ climate/now/data/10m-{WSI}-{day}.json  └─ {wsi}.json  (per-station forecast,
 ├─ climate/now/metadata/meta1|meta2           published by forecast-data.yml)
 └─ weather/forecast/now/  (national text)          │
        │                                            │
        ▼ every 10 min                               ▼ every hour (5 min until
 ┌──────────────────────────┐            ┌──────────────────────────┐  the first
 │ Measurement coordinator  │            │ Forecast coordinator     │  one lands)
 │ api.ChmuApi              │            │ forecast.ChmuForecastApi │
 └───────┬──────────┬───────┘            └────────────┬─────────────┘
         │          │                                 │
         │          └──────────────┐   ┌──────────────┘
         ▼                         ▼   ▼
 ┌────────────────┐  ┌──────────────────────────────┐
 │ sensor.py      │  │ weather.py                   │
 │ one sensor per │  │ current conditions: measured │
 │ measured       │  │ forecast: ALADIN per station │
 │ element + text │  │ today's low: measured night  │
 │ forecast       │  │   when the run lacks it      │
 └───────┬────────┘  └──────────────────────────────┘
         ▼
 ┌──────────────────────────────┐
 │ statistics.py / _import.py   │
 │ whole 10 min batch → hourly  │
 │ external statistics          │
 └──────────────────────────────┘
```

## Data Flow

1. **Config flow** offers every station publishing 10 minute data and
   pre-selects the nearest one measuring temperature
2. **Measurement coordinator** polls the station's 10 minute file every 10
   minutes, plus the latest national text forecast
3. **Sensors** take the newest value of each element the station measures
4. **Hourly statistics** keep the rest of each published batch (see below)
5. **Forecast coordinator** fetches the station's published forecast every hour
6. **Weather entity** combines both: measured current conditions, the model's
   hourly and daily forecast

## Available Weather Stations

The station list is discovered at runtime from the ČHMÚ metadata, so no station
table is hardcoded in the integration. Two families of stations are offered:

| WSI prefix | Type | Count (2026-10) |
|------------|------|-----------------|
| `0-20000-0-` | Professional WMO stations (Praha-Ruzyně, Brno-Tuřany, …) | 40 |
| `0-203-0-` | Automatic / climatological stations | 435 |

**Station id stored in the config entry**

- Professional stations keep the bare WMO id (`11518`) so that config entries
  created before automatic stations were supported keep working unchanged.
- All other stations store the full WSI (`0-203-0-10102001101`).

`api.station_id_to_wsi()` / `api.wsi_to_station_id()` convert between the two.

**Every published file is named after the UTC day**, and the timestamps inside
carry a `Z`. A ČHMÚ file name is therefore never derived from the host's local
date — on a Prague host the local day rolls over one or two hours before the
UTC day, so a local-dated name asks for a file that does not exist yet. See
`api._utc_day_candidates()`.

**Metadata files**

| File | Content | Used for |
|------|---------|----------|
| `meta1-YYYYMMDD.json` | `WSI, GH_ID, FULL_NAME, GEOGR1, GEOGR2, ELEVATION, BEGIN_DATE` | Names + coordinates (nearest-station suggestion) |
| `meta2-YYYYMMDD.json` | `OBS_TYPE, WSI, EG_EL_ABBREVIATION, NAME, UN_DESCRIPTION, HEIGHT, SCHEDULE` | Which elements a station publishes on the 10M schedule |

Only stations with at least one `10M` element the integration maps to a sensor
are offered, and only the matching sensors are created — many automatic
stations report precipitation only.

## Sensor Specifications

| Sensor | Device Class | Unit | State Class |
|--------|--------------|------|-------------|
| Temperature | temperature | °C | measurement |
| Humidity | humidity | % | measurement |
| Pressure | pressure | hPa | measurement |
| Precipitation | precipitation | mm | total_increasing |
| Wind Speed | wind_speed | m/s | measurement |
| Wind Direction | - | ° | measurement |
| Weather Description | - | text (national forecast) | - |

## Forecast Pipeline

ČHMÚ publishes no per-point forecast API. The options it does offer are a
national text forecast for 14 regions and the raw ALADIN model output as GRIB1,
about 70 MB per run — far too much to download inside Home Assistant, and the
national text is up to 10 °C off for mountain stations.

The forecast therefore comes from a build step in this repository:

```
opendata.chmi.cz                 GitHub Actions                  Home Assistant
ALADIN CZ_1km  ──70 MB GRIB1──▶  tools/aladin.py       ┐
(501 x 290 grid,                 samples ~750 station  │  ~9.6 MB
 ~1 km, 00/06/12/18 UTC)         points, stdlib only   ├──▶ GitHub Pages
                                 tools/build_forecast_ │      v1/<wsi>.json
                                 data.py               ┘      ~1.5 kB gzip ──▶ forecast.py
```

- `tools/aladin.py` decodes GRIB1 with the standard library only. The CZ_1km
  product is a regular latitude/longitude grid with simple packing and no
  bitmap, so reading one grid point is bit arithmetic: no eccodes, no numpy.
- `.github/workflows/forecast-data.yml` has no schedule of its own: GitHub's
  scheduler delivered about one firing every four hours however many slots
  were asked for. A Cloudflare Worker on a cron trigger (three times an hour,
  Terraform in the private `liplab-tech-infra` repository) compares the
  opendata listing with the published index and dispatches the workflow only
  when a newer complete run is there - about four builds a day. The build
  checks again before its ~63 MB download and deploys to GitHub Pages. No
  accounts, no analytics, no personal data.
- `custom_components/chmu/forecast.py` downloads only its own station's file and
  revalidates with `If-None-Match`, so an unchanged forecast costs a 304 with no
  body. It is free of Home Assistant imports so the mapping and the day/night
  maths are unit-testable.
- `custom_components/chmu/weather.py` is the entity: measured values for the
  current conditions, the model for the forecast.

Two coordinators run per config entry. A forecast failure is logged and leaves
the measured sensors untouched. The two age limits measure different things:
data published more than 18 hours ago warns (about three missed model
runs - the publishing job has probably stopped), while a model run older
than 48 hours is refused outright however recently it was published. That is
how a stopped publishing job becomes visible instead of silently serving a week
old forecast.

Values are published in the model's own units and mapped to Home Assistant
conditions in the integration, so the mapping can change without regenerating
the data. ALADIN does emit a precipitation type field, but ČHMÚ documents no
code table for it, so it is used only as a wetness hint and rain versus snow is
decided by temperature.

### What the forecast covers

| | Range | Why |
|---|---|---|
| Hourly | 62-70 hours | A run reaches +72 h from its start but is published 3-4½ h after it and replaced 6 h later |
| Daily | 3 days, 4 in the evening | Built from the hourly rows plus the published 12 hour extremes; a day is kept only when it has a high (`DAILY_HIGH_HOUR` / `TAIL_HIGH_HOUR`) |
| Past 3 days | none | ČHMÚ's longer forecast is national only; ALADIN stops at +72 h |

Home Assistant's frontend discards a forecast of two entries or fewer and
shows a spinner, so the daily rules are tuned to keep at least three days
through every point of a run's life.

**Today's low.** The builder stamps ALADIN's 18Z-06Z minimum at 06Z, so only
the 00Z run carries one for today; from about noon the served run has none.
`forecast.with_measured_low()` then fills it with the minimum the station
measured between 00Z and 06Z (its data file starts at 00Z) - once a reading at
or after 06Z exists, never over a published low, and never above the day's
high. A new measurement batch therefore also pushes the daily forecast.

## Hourly Statistics

ČHMÚ measures every 10 minutes but rewrites a station's file only once an hour,
adding the previous hour's six rows in one batch. Only the newest row can
become a sensor state, so five of every six measurements used to be downloaded
and dropped, leaving an hour-long flat line in the recorder followed by a jump.

Those rows are now folded into one statistics row per hour and imported as
**external statistics** under `chmu:{station}_{element}`:

| Module | Role |
|---|---|
| `api.py` | Collects every row of the batch as `history` alongside the newest value |
| `statistics.py` | Folds the rows into hourly mean / minimum / maximum. No Home Assistant imports, so it is testable from a bare virtualenv |
| `statistics_import.py` | Builds the recorder metadata and queues the rows |

Notes on the shape of this:

- Home Assistant has no API for backdating an entity state, and imported
  statistics **must** start at the top of an hour, so the six rows cannot be
  replayed as six points. The hour they describe is what can be kept.
- The same hour is re-offered on every poll while ČHMÚ serves it. The recorder
  replaces a row with the same statistic id and start, so an hour that is still
  filling up ends up complete and nothing is double counted.
- Wind direction uses the circular mean, the same computation the recorder uses
  for wind bearing sensors; minimum and maximum of an angle are meaningless and
  are left out.
- Precipitation is left out entirely: whether a `SRA10M` row is the amount
  fallen in those 10 minutes or a running total is unsettled, and the two
  readings need different arithmetic.
- The recorder is an `after_dependencies` entry, not a dependency: without one
  the statistics are skipped with a warning and the sensors carry on.

## API Details

**Base URL:** `https://opendata.chmi.cz/meteorology/climate`

**Endpoints:**
- National text forecast: `https://opendata.chmi.cz/meteorology/weather/forecast/now/`
  (newest `web_pCRntx_*` file; optional - a failure leaves the sensors working)
- 10-minute data: `/now/data/10m-{WSI}-{YYYYMMDD}.json` (one file per station
  per UTC day, rewritten hourly at about `HH:02` UTC)
- Station metadata: `/now/metadata/meta1-{YYYYMMDD}.json`, `meta2-{YYYYMMDD}.json`
  (published at about `00:02` UTC on the day they are named after)

**Polling Strategy:**
1. Try the current UTC day's file
2. Fall back to the previous UTC day — a new day's first chunk does not appear
   until about `01:02` UTC, so for the first hour of every UTC day only the
   previous file exists
3. Bound the result's age with `MEASUREMENT_STALE_AFTER` (warn) and
   `MEASUREMENT_UNUSABLE_AFTER` (refuse), so a station that has gone quiet
   cannot be served as a current reading. The measurement time is exposed as
   the `measured_at` attribute on every sensor

**Timeout:** 30 seconds per request
**Update Interval:** 10 minutes (measurements), 1 hour (forecast)

## Security & Privacy

✅ **Read-only access** - No authentication required (public data)
✅ **No user data collected** - Only fetches public weather data
✅ **HTTPS only** - Secure API communication
✅ **No external dependencies** - Uses Home Assistant's built-in libraries
✅ **Local storage** - All history stored in Home Assistant database

## Testing Strategy

CI (`.github/workflows/ci.yml`, on pull requests, pushes to main and nightly)
runs ruff, pytest, pyright, hassfest and HACS validation.

- `forecast.py`, `statistics.py` and the API parsing are free of Home Assistant
  imports and tested from a bare virtualenv, with the clock pinned - the
  day/night and local-date rules made the suite clock-dependent before.
- `tests/test_weather_ha.py` and `tests/test_statistics_ha.py` set the entry up
  in a real Home Assistant via `pytest-homeassistant-custom-component`; they
  skip when it is not installed. Network access is blocked there, so every
  request is mocked.
- Live checks run against the `ghcr.io/home-assistant/home-assistant:stable`
  container with the integration mounted.
