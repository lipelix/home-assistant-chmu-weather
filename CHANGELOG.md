# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.7.0] - 2026-09-11

### Fixed
- The daily forecast tab no longer spins forever when a model run arrives
  without its 12 hour maxima. A day with no published high used to be dropped,
  so a run missing that one field left no days at all - and Home Assistant
  reports an empty forecast the same way it reports one that has not been
  fetched yet, which the frontend renders as a spinner that never resolves.
  A missing high is now taken from the day's own hourly rows; the published
  12 hour value is still preferred wherever the run carries it. The fallback
  only applies where the hourly rows cover the afternoon from both sides, so
  the current day is not given the temperature of whatever evening hour
  happens to be left - a number that can land below that day's own overnight
  low and draw an inverted tile

### Changed
- Stations no longer suggest an "Outdoors" area. An area name is stored
  verbatim and cannot be translated, so it put an English word above every
  entity regardless of the configured language - and from Home Assistant
  2026.9, which builds entity ids from the area as well, in front of every
  entity id too (`weather.outdoors_plzen_mikulka`). `suggested_area` is also
  deprecated in Home Assistant as of 2026.9. Existing installations keep the
  area they already have; it can be renamed or cleared in Settings → Areas

## [1.6.1] - 2026-09-09

### Fixed
- The forecast publishing job no longer loses a whole model cycle to one
  dropped connection. It makes about fifteen requests to ČHMÚ per run and made
  each of them exactly once, so a single TCP timeout failed the job and left
  the published forecast on the previous run until the next scheduled slot -
  which GitHub delays by up to five hours on top of the six hour interval.
  A failed download is now attempted three more times with a growing backoff,
  and the retrying is bounded so it cannot eat the time the job needs to
  publish. A refusal such as 404 still comes straight back, so the station
  metadata fallback keeps working; 408, 425 and 429 are the server asking to be
  asked again, so they are retried like any other transport failure

## [1.6.0] - 2026-09-09

### Added
- A measurement is only served while it is fresh enough to mean anything: one
  more than 2 hours old logs a warning, and one more than 6 hours old is
  refused, so the sensors go unavailable rather than presenting a stale reading
  as current. A station that stops reporting used to leave its last value
  standing all day
- `measured_at` attribute on every measurement sensor, carrying the time ČHMÚ
  measured the value. A sensor state is stamped with the time of the poll, so
  this is the only place the real age is visible

### Fixed
- Measurements no longer disappear for the first hours of the day (#5). ČHMÚ
  names the 10 minute data file after the UTC day and publishes a new day's
  first chunk only at about 01:02 UTC, while the integration asked for the
  file named after the host's *local* day - so from local midnight until
  03:02 CEST (02:02 CET) every poll 404'd. The file name now follows the UTC
  day and falls back to the previous one, so the sensors keep the last real
  measurement and a restart inside that window no longer leaves the
  integration unloaded
- Station metadata is likewise requested for the UTC day rather than the local
  one, so adding or reconfiguring a station in that window no longer needs a
  second request to succeed
- A malformed response body or a change to ČHMÚ's document shape is reported
  as itself instead of being retried as a missing day and served as yesterday's
  data

## [1.5.0] - 2026-09-08

### Added
- `weather.` entity per station: 72 hours hourly and 3 days daily, from the
  ALADIN CZ_1km model (~1 km grid) sampled at the station's own coordinates.
  Current conditions stay measured; only the condition comes from the model,
  because ČHMÚ stations report no cloud cover
- Per-station forecast data pipeline (`.github/workflows/forecast-data.yml`):
  a scheduled job decodes one ALADIN GRIB run and publishes about 1.5 kB per
  station as a static site, so the integration downloads its own station's file
  instead of ~70 MB of GRIB. Revalidated with an ETag, so an unchanged forecast
  transfers no body
- Day and night conditions from the sun's actual position at the station
- A `Tests` job in CI, which previously ran no tests at all

### Changed
- Forecast age is surfaced rather than hidden: data published more than 18 hours
  ago logs a warning, and a model run older than 48 hours is refused instead of
  being served as a week old forecast
- The forecast and the measurements fail independently - neither outage takes
  the other down - and the first forecast download no longer delays startup

## [1.4.0] - 2026-09-06

### Added
- Support for ČHMÚ automatic stations (`0-203-0-...`), expanding the station
  list from 40 to ~474 stations (#6)
- Station element metadata (`meta2`) is used to offer only stations that
  publish usable 10-minute data

### Changed
- Sensors are created only for elements a station actually measures; existing
  config entries keep all sensors
- Stations sharing a name are disambiguated by station id in the picker
- Measurements a station does not report are omitted instead of reported as
  `None`/`0`

## [1.3.0] - 2026-03-05

### Added
- Weather Description sensor with text forecast from ČHMÚ forecast API
- Full forecast text available as `full_text` extra attribute when exceeding 255 characters
- Forecast update timestamp exposed as `forecast_updated_at` extra attribute

## [1.2.0] - 2026-01-02

### Added
- Pytest infrastructure and initial API test suite
- Pre-commit hook for automated testing

### Fixed
- Metadata fetching now falls back to previous day when current day unavailable (#1)
- Improved reliability in early morning hours when ČHMÚ metadata not yet published

### Changed
- Updated GitHub Actions workflows
- Enhanced documentation (README, ARCHITECTURE, IMPLEMENTATION-SUMMARY)

## [1.1.0] - 2025-11-24

### Added
- HACS Action validation to CI workflow for enhanced integration validation

### Changed
- Specified country to CZ in hacs.json for better regional categorization
- Added *.code-workspace to .gitignore for cleaner repository

## [1.0.2] - 2025-11-17

### Changed
- Enhanced README with bilingual descriptions (Czech and English)
- Added flag emojis to emphasize Czech audience focus
- Improved documentation clarity about geographic station availability

## [1.0.1] - 2025-11-17

### Fixed
- Fixed manifest.json key ordering for hassfest validation
- Fixed hacs.json format (removed invalid fields)
- Added local linting and validation tools
- Added pre-commit hooks for automatic linting
- Simplified CI workflow (Lint + Hassfest)

## [1.0.0] - 2025-11-17

### Added
- Initial release of ČHMÚ Weather integration
- Config flow for easy UI-based configuration
- Sensor entities for ČHMÚ weather data
- Support for Czech Hydrometeorological Institute API
- HACS integration support
- Automated GitHub Actions for validation and releases
