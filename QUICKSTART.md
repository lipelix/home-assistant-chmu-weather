# Quick Start Guide 🚀

## Immediate Next Steps

### 1️⃣ Initial Git Setup & Push (5 minutes)
```bash
cd /Users/liborvachal/Work/home-assistant-chmu-weather
git add .
git commit -m "Initial commit - Setup for HACS publication"
git push origin main
```

### 2️⃣ Create Your First Release (2 minutes)
```bash
git tag -a v1.0.0 -m "Release v1.0.0"
git push origin v1.0.0
```
Then go to GitHub → Releases → Create release from the tag

### 3️⃣ Configure Repository on GitHub (3 minutes)
1. Add description: "Home Assistant integration for ČHMÚ weather data"
2. Add topics: `home-assistant`, `hacs`, `homeassistant`, `custom-component`, `weather`, `chmu`
3. Check that Actions are running (they should pass ✅)

### 4️⃣ Test Installation (10 minutes)
Add as custom repository in your HACS:
- URL: `https://github.com/lipelix/home-assistant-chmu-weather`
- Category: Integration
- Install and verify it works

### 5️⃣ Submit to HACS Default (optional, can do later)
Fork https://github.com/hacs/default and add your repo

---

## What's Already Done ✅

- ✅ Integration code copied to `custom_components/chmu/`
- ✅ `hacs.json` configured correctly
- ✅ `manifest.json` updated with proper URLs
- ✅ GitHub Actions for validation and releases
- ✅ Professional README with badges
- ✅ CHANGELOG following best practices
- ✅ Issue templates for users
- ✅ Complete documentation (PUBLISHING.md, SETUP_SUMMARY.md)

---

## Files You Can Safely Commit

All files are ready to commit! The repository structure is complete and HACS-compliant.

---

## For Future Updates

When you want to release a new version:

1. Update version in `custom_components/chmu/manifest.json`
2. Update `CHANGELOG.md`
3. Commit changes
4. Create new tag: `git tag -a v1.1.0 -m "Release v1.1.0"`
5. Push tag: `git push origin v1.1.0`
6. GitHub Actions will automatically create the release ZIP

---

## Need Help?

- See `PUBLISHING.md` for detailed publishing guide
- See `SETUP_SUMMARY.md` for complete setup details
- Check [HACS docs](https://www.hacs.xyz/docs/publish/integration)

Happy publishing! 🎉
