# ČHMÚ Weather Home Assistant Integration

🇨🇿 **Integrace pro Home Assistant poskytující data z meteorologických stanic Českého hydrometeorologického ústavu (ČHMÚ). Primárně určeno pro české uživatele z důvodu geografické dostupnosti stanic.**

🇬🇧 **Home Assistant integration providing weather data from Czech Hydrometeorological Institute (ČHMÚ) meteorological stations. Primarily intended for Czech audience due to the geographic proximity of weather stations.**

![Brno weather station](assets/brno_sensor_teaser.png)

---

A Home Assistant integration to fetch weather data from ČHMÚ (Czech Hydrometeorological Institute).

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://github.com/hacs/integration)
[![GitHub Release](https://img.shields.io/github/v/release/lipelix/home-assistant-chmu-weather)](https://github.com/lipelix/home-assistant-chmu-weather/releases)
[![Deploy](https://github.com/lipelix/home-assistant-chmu-weather/actions/workflows/ci.yml/badge.svg)](https://github.com/lipelix/home-assistant-chmu-weather/actions/workflows/ci.yml/badge.svg)

## Installation

### HACS (Recommended)

1. Open HACS in your Home Assistant instance
2. Click on "Integrations"
3. Click the three dots in the top right corner
4. Select "Custom repositories"
5. Add this repository URL: `https://github.com/lipelix/home-assistant-chmu-weather`
6. Select category: `Integration`
7. Click "Add"
8. Find "ČHMÚ Weather" in the integration list and click "Download"
9. Restart Home Assistant
10. Go to Settings → Devices & Services → Add Integration
11. Search for "ČHMÚ Weather" and follow the configuration steps

### Manual Installation

1. Copy the `custom_components/chmu` directory to your Home Assistant `config/custom_components/` directory
2. Restart Home Assistant
3. Go to Settings → Devices & Services → Add Integration
4. Search for "ČHMÚ Weather" and follow the configuration steps

## Configuration

The integration is configured via the UI (Config Flow). No YAML configuration is needed.

## Features

- Fetches weather data from all ČHMÚ stations publishing 10-minute data —
  the 40 professional WMO stations plus ~430 automatic stations
- Provides temperature, humidity, pressure, precipitation, wind speed and
  wind direction, plus the ČHMÚ text forecast for the Czech Republic
- A weather entity with a **per-station forecast**: 72 hours hourly and 3 days
  daily, from the ČHMÚ ALADIN 1 km model sampled at your station's coordinates
- Creates only the sensors a station actually measures (many automatic
  stations report precipitation only)
- Pre-selects the station nearest to your Home Assistant location
- Easy configuration through the Home Assistant UI

### Where the forecast comes from

ČHMÚ publishes forecasts only as national prose for 14 regions or as raw model
output — roughly 70 MB of GRIB per run, which no integration can download every
hour. The national text is up to 10 °C off for mountain stations, so this
integration does not use it for the forecast.

Instead a scheduled job in this repository
([`.github/workflows/forecast-data.yml`](.github/workflows/forecast-data.yml))
downloads one ALADIN CZ_1km run, samples the ~1 km grid at all 758 station
coordinates and publishes about 1.5 kB per station as a static site. Your Home
Assistant fetches only its own station's file, and revalidates with an ETag so
an unchanged forecast transfers no body at all.

Nothing about that request is logged, counted or analysed: no accounts, no
analytics, no personal data. If the job ever stops, the integration warns after
12 hours and stops serving the forecast after 48 rather than quietly showing a
week old one. The measured sensors keep working either way.

See [`custom_components/chmu/ARCHITECTURE.md`](custom_components/chmu/ARCHITECTURE.md)
for the pipeline in detail.

## Development

### Running Tests

To run the tests locally:

```bash
# Install development dependencies
pip install -r requirements-dev.txt

# Run tests
pytest tests/ -v
```

The test suite includes unit tests for API helpers and data parsing. Tests are automatically run via pre-commit hooks before each commit to ensure code quality.

### Code Quality

Before committing, ensure your code passes linting:

```bash
./lint.sh  # Runs ruff + HACS validation
```

Pre-commit hooks will automatically run ruff and pytest on commit. To set up pre-commit hooks:

```bash
pip install pre-commit
pre-commit install
```

## Support

If you have issues or questions, please:
- Check the [documentation](https://github.com/lipelix/home-assistant-chmu-weather)
- Open an [issue](https://github.com/lipelix/home-assistant-chmu-weather/issues)

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.
