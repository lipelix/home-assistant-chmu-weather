# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
