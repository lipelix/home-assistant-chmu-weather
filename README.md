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

- Fetches weather data from ČHMÚ stations
- Provides temperature, humidity, and other meteorological data
- Easy configuration through the Home Assistant UI

## Support

If you have issues or questions, please:
- Check the [documentation](https://github.com/lipelix/home-assistant-chmu-weather)
- Open an [issue](https://github.com/lipelix/home-assistant-chmu-weather/issues)

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

