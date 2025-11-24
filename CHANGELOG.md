# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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

