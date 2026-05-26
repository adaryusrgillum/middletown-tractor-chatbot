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

The latest pre-built APKs live in [`releases/`](./releases/). Browse to that
folder or use a direct link:

- **v5** (latest): https://github.com/adaryusrgillum/middletown-tractor-chatbot/raw/main/releases/middletown-tractor-v5.apk
- **v4**: https://github.com/adaryusrgillum/middletown-tractor-chatbot/raw/main/releases/middletown-tractor-v4.apk

Then on your phone:

1. Open the direct link above (or transfer a built `app-debug.apk` over USB / OneDrive / email).
2. Open the file from Files / Downloads.
3. Grant "Install unknown apps" permission for that source when prompted.
4. Tap **Install**.

> **Why isn't there a GitHub Release?** The Releases tab is empty for v4/v5
> because GitHub Actions is locked on this account due to a billing issue,
> so the `release-apk.yml` workflow can't auto-publish. Clearing the billing
> block at https://github.com/settings/billing and re-pushing `release-v5`
> will populate the Releases tab automatically.

## Schedule Service form + push notifications

The app has a **Schedule Service / Maintenance** form (linked from the "Service"
card on the home page, available at `pages/schedule-service.html` inside the
APK). Submissions POST to the FastAPI backend, which:

1. Stores the request in `backend/service_requests.db` (SQLite, gitignored).
2. Sends a real-time push notification to your phone via [ntfy.sh](https://ntfy.sh).

### Setup (one time)

1. **Pick a hard-to-guess ntfy topic.** Anyone who knows the topic name can
   subscribe to it, so treat it like a low-stakes password. Example:
   `mts-svc-7f2k9q1x`.
2. **Install the ntfy app** on your phone (iOS App Store / Google Play / F-Droid).
3. In the ntfy app, tap **+** → enter your topic name → subscribe.
4. **Configure the backend** with the topic via env var:

   ```bash
   # backend/.env (or Render dashboard)
   NTFY_TOPIC=mts-svc-7f2k9q1x
   ```

5. **Deploy the backend** so phones can reach it (see "Deploy" below), or run
   it locally for testing: `uvicorn backend.server:app --port 8000`.
6. In `widget/index.html` (web) or `site_bundle/pages/schedule-service.html`
   (APK), set the backend URL:

   ```html
   <script>window.MT_BACKEND_URL = "https://your-backend.onrender.com";</script>
   ```

   Or rebuild the bundle with that snippet templated in.

### Testing locally

```bash
# Submit a request
curl -X POST http://localhost:8000/api/service-request \
  -H 'Content-Type: application/json' \
  -d '{"name":"Test","phone":"304-555-0100","email":"t@x.com",
       "location":"Fairmont, WV","service_type":"Routine maintenance",
       "equipment":"John Deere 1025R","notes":"100-hr service"}'

# See recent requests
curl http://localhost:8000/api/service-requests/recent
```

### Deploy the backend (Render free tier)

`render.yaml` at the repo root configures a free Render web service. Steps:

1. Push to a GitHub repo Render can read.
2. In Render: **New + → Blueprint → pick the repo → Apply**.
3. After provisioning, open the service in the dashboard and set the secret
   `NTFY_TOPIC` (and optionally `OLLAMA_HOST` if you wire the chatbot up to a
   remote LLM).
4. Render gives you a URL like `https://middletown-tractor-backend.onrender.com`.
   Use that as `MT_BACKEND_URL` when you rebuild the site / APK.

Render's free tier spins down after 15 min of inactivity (cold-start ~30s).
Requests during sleep still go through, just with a delay — fine for low-traffic
service requests.

## Architecture notes

- **Retrieval**: BM25 over chunks of scraped text. A location-name boost (`+50` for matching city, `-50` for the others) ensures Buckhannon questions only retrieve the Buckhannon chunk — keeps small models from mixing up addresses.
- **Canned chips**: served from `/api/suggestions` (backend) for the live web app; bundled as `assets/canned.json` for the APK so the chips work without network.
- **Streaming**: SSE from FastAPI → token-by-token rendering in the widget.
- **No-cache headers**: middleware on `/`, `*.html`, `*.js`, `*.css` so widget edits don't get cached.

## License & content

The dealership content and product images embedded in the APK are © Middletown Tractor Sales and their CDN partners. This repo is a personal/dev artifact; redistribution of the bundled APK requires the dealership's consent.
