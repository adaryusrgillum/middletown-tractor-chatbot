# Middletown Tractor Chatbot + Android App

End-to-end build for [middletowntractor.com](https://www.middletowntractor.com/):

1. **Web chatbot** — Floating chat widget grounded in scraped site content via BM25 retrieval + a local LLM through Ollama (default `gemma2:2b`). Canned answers handle the 10 most-asked questions instantly with no LLM call.
2. **Android APK** — Offline, content-rich Android app bundling all 500 scraped pages and 1,271 product photos, with the chatbot widget embedded on every page.

```
middletown-chatbot/
├── backend/
│   ├── server.py          # FastAPI: retrieval + Ollama streaming + /api/suggestions
│   ├── chunks.json        # ~1100 text chunks (BM25 corpus)
│   ├── canned.json        # 14 pre-written Q&A pairs (chips + hidden location details)
│   └── supplemental.json  # Hand-added info (e.g. Buckhannon location)
├── scraper/
│   ├── scrape_full.py     # Deep crawl: 500 pages + image-URL extraction
│   ├── download_images.py # Fetches every unique image to site_bundle/images/
│   ├── build_site.py      # Generates the offline static site
│   └── make_icons.py      # PWA / launcher icons
├── widget/                # Embeddable chat bubble (HTML/JS/CSS)
├── site_bundle/           # Generated (gitignored) - the Android app's web root
│   ├── pages.json         # Tracked: scraped page list
│   ├── images.json        # Tracked: scraped image URL list
│   ├── image_map.json     # Tracked: URL -> local filename map
│   ├── images/            # Generated: downloaded photos
│   ├── pages/             # Generated: per-product HTML
│   ├── assets/            # Generated: widget files + icons + canned.json
│   ├── index.html         # Generated: home with categorized links
│   └── manifest.json      # Generated: PWA manifest
├── android/               # Capacitor-generated Android project
├── capacitor.config.json
├── package.json           # Node deps for Capacitor
├── requirements.txt       # Python deps
├── launch.ps1             # Desktop launcher: starts Ollama + backend + opens browser
└── README.md
```

## Quick start (web chatbot only)

```powershell
# Python env + deps
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt

# Make sure standalone Ollama is running and has gemma2:2b pulled
ollama pull gemma2:2b
ollama serve

# Scrape and run
python scraper\scrape_full.py            # one-time: builds chunks.json
uvicorn backend.server:app --port 8000
# Open http://localhost:8000
```

Or just double-click `Middletown Chatbot.lnk` on your desktop (created by `launch.ps1`) — it auto-starts Ollama + the backend + opens the browser.

## Building the Android APK from scratch

Prerequisites (Windows; Scoop is the easiest installer):

| | |
|---|---|
| **OpenJDK 21** | `scoop install openjdk21` (Capacitor 8 requires Java 21) |
| **Android SDK CLI tools** | `scoop install android-clt` — must have `platforms;android-35` and `build-tools;35.0.0` |
| **Node.js + npm** | any recent version |
| **Python 3.10+** | for scrape/build scripts |

Then:

```powershell
# 1. Python deps + scrape (~15 min, 500 pages)
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt pillow
python scraper\scrape_full.py

# 2. Download images (~5 min, ~32 MB)
python scraper\download_images.py

# 3. Generate the static site bundle (~5 s)
python scraper\make_icons.py
python scraper\build_site.py

# 4. Node deps + Capacitor + APK
npm install
$env:JAVA_HOME = "$env:USERPROFILE\scoop\apps\openjdk21\current"
npx cap sync android
cd android
.\gradlew.bat assembleDebug --no-daemon
```

Output: `android/app/build/outputs/apk/debug/app-debug.apk` (~34 MB).

## What's inside the APK

| | |
|---|---|
| HTML pages | 500 (categories + every product detail page) |
| Product images | 1,271 (bundled, 32 MB) |
| Categories | 11 (Locations, John Deere, Honda Power, Ventrac, Stihl, Tractor Packages, Parts, Service, About, etc.) |
| Chatbot widget | embedded on every page |
| Canned chip answers | 14 (10 visible chips + 4 hidden location-detail entries) |
| PWA manifest + icons | yes (192, 512, 1024 PNG) |
| App ID | `com.middletowntractor.app` |
| Min Android | Android 6.0+ |

The chatbot widget works **fully offline** for the 10 suggestion chips (canned JSON bundled inside the APK). Free-typed questions require a live backend — set `window.MT_BACKEND_URL` in `site_bundle/index.html` or `site_bundle/pages/*.html` (or, more practically, a `<script>` snippet in `widget/index.html` before re-running `build_site.py`).

## Install the APK on a Samsung / Android phone

1. Transfer `app-debug.apk` to the phone (USB, OneDrive, email, etc.)
2. Open the file from Files / Downloads
3. Grant "Install unknown apps" permission for that source when prompted
4. Tap **Install**

## Architecture notes

- **Retrieval**: BM25 over chunks of scraped text. A location-name boost (`+50` for matching city, `-50` for the others) ensures Buckhannon questions only retrieve the Buckhannon chunk — keeps small models from mixing up addresses.
- **Canned chips**: served from `/api/suggestions` (backend) for the live web app; bundled as `assets/canned.json` for the APK so the chips work without network.
- **Streaming**: SSE from FastAPI → token-by-token rendering in the widget.
- **No-cache headers**: middleware on `/`, `*.html`, `*.js`, `*.css` so widget edits don't get cached.

## License & content

The dealership content and product images embedded in the APK are © Middletown Tractor Sales and their CDN partners. This repo is a personal/dev artifact; redistribution of the bundled APK requires the dealership's consent.
