# ČHMÚ Weather Integration Architecture

## System Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                     Home Assistant                               │
│                                                                   │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │          ČHMÚ Weather Integration                         │  │
│  │                                                            │  │
│  │  ┌──────────────┐        ┌──────────────┐                │  │
│  │  │ Config Flow  │        │ Coordinator  │                │  │
│  │  │              │        │              │                │  │
│  │  │ • UI Setup   │───────▶│ • Polling    │                │  │
│  │  │ • Station    │        │ • 10min      │                │  │
│  │  │   Selection  │        │   interval   │                │  │
│  │  └──────────────┘        └───────┬──────┘                │  │
│  │                                   │                        │  │
│  │                          ┌────────▼────────┐              │  │
│  │                          │   ČHMÚ API      │              │  │
│  │                          │   Client        │              │  │
│  │                          │                 │              │  │
│  │                          │ • Fetch data    │              │  │
│  │                          │ • Parse JSON    │              │  │
│  │                          │ • Fallback      │              │  │
│  │                          └────────┬────────┘              │  │
│  │                                   │                        │  │
│  │  ┌───────────────────────────────┴────────────┐          │  │
│  │  │            Sensor Entities                  │          │  │
│  │  │                                              │          │  │
│  │  │  🌡️  Temperature    💧 Humidity            │          │  │
│  │  │  🎚️  Pressure       🌧️ Precipitation      │          │  │
│  │  │  💨 Wind Speed      🧭 Wind Direction       │          │  │
│  │  │                                              │          │  │
│  │  │  • Device Class    • Unit of Measurement    │          │  │
│  │  │  • State Class     • History Recording      │          │  │
│  │  └──────────────────────────────────────────────┘          │  │
│  └──────────────────────────────────────────────────────────┘  │
│                              │                                   │
│                              ▼                                   │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │                    Dashboard                              │  │
│  │                                                            │  │
│  │  📊 History Graph Card    📋 Entity Card                  │  │
│  │  • 24h weather trends     • Current values                │  │
│  │  • Temperature            • All 6 sensors                 │  │
│  │  • Humidity               • Live updates                  │  │
│  │  • Pressure                                               │  │
│  └──────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                    ČHMÚ Open Data API                            │
│                                                                   │
│  https://opendata.chmi.cz/meteorology/climate/                  │
│                                                                   │
│  • /now/data/{date}.json          (daily data)                  │
│  • /recent/data/1hour/{filename}  (hourly data)                 │
│                                                                   │
│  Data format: JSON with meteorological measurements             │
└─────────────────────────────────────────────────────────────────┘
```

## Data Flow

1. **User Configuration** → Config Flow UI selects station
2. **Coordinator** → Polls API every 10 minutes
3. **API Client** → Fetches JSON data from ČHMÚ servers
4. **Data Parsing** → Extracts measurements (temp, humidity, etc.)
5. **Sensor Update** → Updates entity states in Home Assistant
6. **History Recording** → Automatic long-term statistics
7. **Dashboard Display** → Real-time values and historical graphs

## Available Weather Stations

The station list is discovered at runtime from the ČHMÚ metadata, so no station
table is hardcoded in the integration. Two families of stations are offered:

| WSI prefix | Type | Count (2026-09) |
|------------|------|-----------------|
| `0-20000-0-` | Professional WMO stations (Praha-Ruzyně, Brno-Tuřany, …) | 40 |
| `0-203-0-` | Automatic / climatological stations | 434 |

**Station id stored in the config entry**

- Professional stations keep the bare WMO id (`11518`) so that config entries
  created before automatic stations were supported keep working unchanged.
- All other stations store the full WSI (`0-203-0-10102001101`).

`api.station_id_to_wsi()` / `api.wsi_to_station_id()` convert between the two.

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

## API Details

**Base URL:** `https://opendata.chmi.cz/meteorology/climate`

**Endpoints:**
- Daily data: `/now/data/YYYY-MM-DD.json`
- Hourly data: `/recent/data/1hour/dly-1-YYMMDD-HHMM-{station_id}.json`

**Polling Strategy:**
1. Try today's daily data
2. Fallback to recent hourly data
3. Try last 6 hours of data
4. Use simulated data if all fail (development mode)

**Timeout:** 30 seconds per request
**Update Interval:** 10 minutes
**Retry Logic:** Multiple file attempts for recent data

## Security & Privacy

✅ **Read-only access** - No authentication required (public data)
✅ **No user data collected** - Only fetches public weather data
✅ **HTTPS only** - Secure API communication
✅ **No external dependencies** - Uses Home Assistant's built-in libraries
✅ **Local storage** - All history stored in Home Assistant database

## Testing Strategy

Due to network restrictions in CI environment:
- ✅ Code structure validated
- ✅ Configuration flow implemented
- ⚠️ API integration requires live environment
- 📝 Simulated data fallback for offline testing

**Validation required:**
1. Install integration in live Home Assistant
2. Configure with station ID
3. Verify sensor entities created
4. Check data updates every 10 minutes
5. Confirm history graph displays correctly
