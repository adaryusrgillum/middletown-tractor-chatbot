# Pre-built APKs

This folder holds debug-signed Android APKs for direct install. These are the
same APKs the CI workflow at `.github/workflows/release-apk.yml` produces;
they're committed here so users can grab one without waiting for CI.

> **Note:** The GitHub Releases tab (`/releases` on the repo page) is empty
> because GitHub Actions is currently locked on this account due to a billing
> issue. Until that clears, **this folder is the official release surface.**

## Latest

| Version | File | Size | Highlights |
|---|---|---|---|
| **v5** | [middletown-tractor-v5.apk](./middletown-tractor-v5.apk) | 38 MB | Schedule Service form + ntfy.sh push notifications, branded inventory panels with real manufacturer logos (JD, STIHL, Ventrac, Honda, Kuhn, Frontier, Alamo Industrial), chip-collapse UX, removed Featured Inventory |
| v4 | [middletown-tractor-v4.apk](./middletown-tractor-v4.apk) | 38 MB | Light/dark theme toggle, JD brand palette, real scraped promo banners (Memorial Day, EARTHQUAKER, SAVE $30), 5-tab bottom nav |

## Install (Android phone)

1. On your phone, open the **direct download link** for the version you want
   (right-click → copy link from the table above, paste into your phone
   browser, or just tap the link if you're already on the phone).
   - **v5 direct:** https://github.com/adaryusrgillum/middletown-tractor-chatbot/raw/main/releases/middletown-tractor-v5.apk
2. After the download completes, open the file from **Downloads** /
   **Files**.
3. Android will prompt: *"For your security, your phone isn't allowed to
   install unknown apps from this source."* — tap **Settings** and toggle
   **Allow from this source** on for your browser / file manager.
4. Tap **Install**.
5. Open **Middletown Tractor** from the app drawer.

## Build from source

```bash
# Prereqs: Java 21, Android SDK (platforms;android-35, build-tools;35.0.0),
#          Node 22, Python 3.11

python scraper/download_images.py   # ~3 min, 1,270 images
python scraper/make_icons.py
python scraper/build_site.py

npm install
npx cap sync android

cd android
./gradlew assembleDebug --no-daemon
# Output: app/build/outputs/apk/debug/app-debug.apk
```
