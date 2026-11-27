# 🌤️ ČHMÚ Weather Integration - Installation Guide

## Quick Start

```bash
# 1. Restart Home Assistant to load the integration
docker-compose restart homeassistant

# 2. Wait for Home Assistant to fully start (check logs)
docker-compose logs -f homeassistant
```

## Adding the Integration

1. Open Home Assistant in your browser: `http://localhost:8123`

2. Navigate to: **Settings** → **Devices & Services**

3. Click the **+ ADD INTEGRATION** button (bottom right)

4. Search for: **ČHMÚ Weather**

5. Select your nearest weather station from the dropdown:
   - **Praha-Libuš (11406)** ← Recommended for Prague area
   - Praha-Ruzyně (11518)
   - Brno-Tuřany (11723)
   - Ostrava-Mošnov (11963)
   - Plzeň-Mikulka (11603)
   - And 6 more stations...

6. Click **SUBMIT**

## Viewing Weather Data

### Current Values
The integration creates 6 sensor entities:
- `sensor.11406_temperature` - Venkovní teplota
- `sensor.11406_humidity` - Venkovní vlhkost
- `sensor.11406_pressure` - Barometrický tlak
- `sensor.11406_precipitation` - Srážky
- `sensor.11406_wind_speed` - Rychlost větru
- `sensor.11406_wind_direction` - Směr větru

### Dashboard
Your dashboard already includes a **"🌤️ Venkovní počasí ČHMÚ"** section with:
- **Current status card** - All 6 weather sensors
- **24-hour history graph** - Temperature, humidity, pressure, precipitation trends

## Verifying Installation

### Check Integration Status
1. Go to **Settings** → **Devices & Services**
2. Look for **ČHMÚ Weather** card
3. Should show: "✓ Configured" with your station name

### Check Sensors
1. Go to **Settings** → **Devices & Services** → **ČHMÚ Weather**
2. Click on the device (e.g., "Praha-Libuš")
3. Should show 6 sensor entities with current values

### Check Dashboard
1. Go to your Home dashboard
2. Scroll to the **"🌤️ Venkovní počasí ČHMÚ"** section
3. You should see:
   - Current temperature, humidity, pressure, etc.
   - History graph showing last 24 hours

## Troubleshooting

### Integration Not Appearing
```bash
# Check if integration files exist
ls -l custom_components/chmu/

# Should show: __init__.py, api.py, sensor.py, manifest.json, etc.
```

### No Data Showing
1. **Check logs:**
   ```bash
   docker-compose logs homeassistant | grep chmu
   ```

2. **Common issues:**
   - Wait 10 minutes for first data fetch
   - Check internet connectivity from container
   - Try a different station

3. **API access:**
   - Integration uses: `https://opendata.chmi.cz/meteorology/climate/`
   - If API is unreachable, shows simulated data

### Sensors Show "Unavailable"
- Restart Home Assistant: `docker-compose restart homeassistant`
- Check API is accessible: `curl -I https://opendata.chmi.cz/meteorology/climate/`
- Wait 10 minutes for next update cycle

## Data Update Schedule

- **Frequency:** Every 10 minutes
- **Source:** ČHMÚ official meteorological stations
- **Data type:** Real measured values (not forecasts)
- **History:** Automatically stored by Home Assistant

## Customizing Dashboard

Edit `dashboard.yml` to customize the weather section:

```yaml
# Change hours shown in history graph
hours_to_show: 48  # Default is 24

# Add/remove sensors from graph
entities:
  - entity: sensor.11406_temperature
    name: Teplota
  - entity: sensor.11406_humidity
    name: Vlhkost
  # Add more...
```

## Multiple Stations

You can add multiple stations:
1. Go to **Settings** → **Devices & Services**
2. Click **+ ADD INTEGRATION** again
3. Search for **ČHMÚ Weather**
4. Select a different station

Each station creates its own device with 6 sensors.

## Advanced Configuration

### Change Update Interval

Edit `homeassistant/custom_components/chmu/__init__.py`:
```python
SCAN_INTERVAL = timedelta(minutes=10)  # Change to desired interval
```

### Add Custom Station

Edit `homeassistant/custom_components/chmu/const.py`:
```python
STATIONS = {
    "11406": "Praha-Libuš",
    "YOUR_ID": "Your Station Name",  # Add here
    # ...
}
```

## Documentation

- **User Guide:** `custom_components/chmu/README.md`
- **Architecture:** `custom_components/chmu/ARCHITECTURE.md`
- **Configuration Example:** `configuration.yaml.example`

## Support

For issues or questions:
- Check Home Assistant logs: `docker-compose logs homeassistant`
- Review ČHMÚ API status: https://opendata.chmi.cz/meteorology/climate/
- GitHub Issues: https://github.com/lipelix/home-assistant/issues

## Data Source

- **Provider:** ČHMÚ (Czech Hydrometeorological Institute)
- **License:** Open Government Data
- **API:** https://opendata.chmi.cz/meteorology/climate/
- **Documentation:** https://geoportal.gov.cz (search for ČHMÚ)

---

🎉 **Enjoy real-time weather data from official Czech meteorological stations!**
