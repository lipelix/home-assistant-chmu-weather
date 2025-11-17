# Publishing to HACS - Guide

This document describes how to publish and maintain this integration in HACS.

## Prerequisites

Before submitting to HACS, ensure:

1. ✅ Your repository is public on GitHub
2. ✅ The repository has a proper description
3. ✅ The repository has topics including `home-assistant` and `hacs`
4. ✅ You have a valid `hacs.json` file in the root
5. ✅ You have a valid `manifest.json` in `custom_components/chmu/`
6. ✅ You have a comprehensive README.md
7. ✅ You have a LICENSE file (MIT in this case)

## Repository Structure

```
home-assistant-chmu-weather/
├── .github/
│   └── workflows/
│       ├── ci.yml          # Linting workflow
│       ├── release.yml     # Release automation
│       └── validate.yml    # HACS validation
├── custom_components/
│   └── chmu/              # Your integration code
│       ├── __init__.py
│       ├── manifest.json
│       ├── sensor.py
│       └── ...
├── CHANGELOG.md
├── hacs.json
├── LICENSE
└── README.md
```

## Steps to Publish to HACS

### 1. Push Your Repository to GitHub

```bash
git add .
git commit -m "Initial commit for HACS publication"
git push origin main
```

### 2. Create a Release Tag

```bash
git tag -a v1.0.0 -m "Release v1.0.0"
git push origin v1.0.0
```

Or create a release through GitHub UI:
- Go to your repository on GitHub
- Click on "Releases" → "Create a new release"
- Tag version: `v1.0.0`
- Release title: `v1.0.0`
- Description: Copy from CHANGELOG.md
- Click "Publish release"

The GitHub Action will automatically create a ZIP file and attach it to the release.

### 3. Add GitHub Topics

Add these topics to your repository:
- `home-assistant`
- `hacs`
- `homeassistant`
- `custom-component`
- `weather`
- `chmu`

### 4. Submit to HACS

You have two options:

#### Option A: Submit as Default Repository (Recommended if it meets criteria)

1. Fork https://github.com/hacs/default
2. Edit `integration` file
3. Add your repository:
   ```json
   {
     "name": "lipelix/home-assistant-chmu-weather"
   }
   ```
4. Create a Pull Request
5. Wait for review and approval

#### Option B: Add as Custom Repository (Quick start)

Users can add your integration manually:
1. In Home Assistant, go to HACS
2. Click on "Integrations"
3. Click the three dots menu → "Custom repositories"
4. Add: `https://github.com/lipelix/home-assistant-chmu-weather`
5. Category: `Integration`
6. Click "Add"

## Maintaining Your Integration

### Creating New Releases

1. Update `version` in `custom_components/chmu/manifest.json`
2. Update `CHANGELOG.md` with changes
3. Commit and push changes
4. Create a new tag and release:
   ```bash
   git tag -a v1.1.0 -m "Release v1.1.0"
   git push origin v1.1.0
   ```
5. The GitHub Action will automatically create the release asset

### Validation

The `validate.yml` workflow runs:
- On every push
- On every pull request
- Daily (via cron)

This ensures your repository stays compliant with HACS requirements.

## Troubleshooting

### HACS Validation Fails

Check the Actions tab in your GitHub repository to see specific errors. Common issues:
- Missing required files
- Invalid JSON in `hacs.json` or `manifest.json`
- Missing version in `manifest.json`

### Integration Not Showing Up

- Ensure all required files are present
- Check that `content_in_root` is set to `false` in `hacs.json`
- Verify the integration directory name matches the domain in `manifest.json`

## Resources

- [HACS Documentation](https://www.hacs.xyz/docs/publish/integration)
- [Home Assistant Integration Documentation](https://developers.home-assistant.io/docs/creating_integration_manifest/)
- [Home Assistant Integration Manifest](https://developers.home-assistant.io/docs/creating_integration_manifest/)

## Support

If users have issues:
- Direct them to open an issue on GitHub
- Check Home Assistant logs for errors
- Verify integration is properly installed
