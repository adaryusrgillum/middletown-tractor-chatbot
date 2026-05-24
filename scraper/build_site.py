"""
Generate a static, offline-browseable site from the scraped pages.

Reads:
  site_bundle/pages.json     (page list from scrape_full.py)
  site_bundle/image_map.json (URL -> local path from download_images.py)
  backend/canned.json        (canned chatbot answers - bundled for offline use)
  widget/{widget.js,widget.css,index.html ignored}

Writes:
  site_bundle/index.html             (home page with category nav + chatbot widget)
  site_bundle/pages/<slug>.html      (one page per scraped URL)
  site_bundle/assets/widget.js       (chatbot widget, modified for offline canned mode)
  site_bundle/assets/widget.css
  site_bundle/assets/canned.json     (so the widget can render chips without backend)
"""
from __future__ import annotations

import hashlib
import html
import json
import re
import shutil
import sys
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent.parent
BUNDLE = ROOT / "site_bundle"
PAGES_DIR = BUNDLE / "pages"
ASSETS_DIR = BUNDLE / "assets"


def slug_for(url: str) -> str:
    """Stable, safe filename for a page URL."""
    h = hashlib.sha1(url.encode("utf-8")).hexdigest()[:8]
    path = urlparse(url).path.strip("/")
    base = re.sub(r"[^A-Za-z0-9._-]+", "-", path)[:60].strip("-") or "home"
    return f"{base}_{h}.html"


def categorize(pages: list[dict]) -> dict[str, list[dict]]:
    """Group pages into rough categories by URL pattern + title."""
    cats: dict[str, list[dict]] = {
        "Locations": [],
        "Inventory - John Deere": [],
        "Inventory - Honda Power": [],
        "Inventory - Ventrac": [],
        "Inventory - Stihl": [],
        "Inventory - Other Brands": [],
        "Tractor Packages & Offers": [],
        "Parts": [],
        "Service": [],
        "About & Info": [],
        "Other": [],
    }
    for p in pages:
        u, t = p["url"].lower(), p["title"].lower()
        if "hours" in u or "map-and-directions" in u or "map-directions" in u:
            cats["Locations"].append(p)
        elif "/john-deere" in u or "deere" in t:
            cats["Inventory - John Deere"].append(p)
        elif "honda-power" in u or "honda" in t:
            cats["Inventory - Honda Power"].append(p)
        elif "ventrac" in u or "ventrac" in t:
            cats["Inventory - Ventrac"].append(p)
        elif "stihl" in u or "stihl" in t:
            cats["Inventory - Stihl"].append(p)
        elif "/inventory" in u and "Current" in p["url"]:
            cats["Inventory - Other Brands"].append(p)
        elif "package" in u or "tractor-packages" in u or "drive-green" in u or "deerday" in u:
            cats["Tractor Packages & Offers"].append(p)
        elif "parts" in u:
            cats["Parts"].append(p)
        elif "service" in u or "repair" in u:
            cats["Service"].append(p)
        elif "about" in u or "review" in u or "testimonial" in u or "contact" in u:
            cats["About & Info"].append(p)
        else:
            cats["Other"].append(p)
    return {k: v for k, v in cats.items() if v}


def render_page_html(page: dict, image_map: dict[str, str]) -> str:
    title = html.escape(page["title"] or page["url"])
    body_paragraphs = []
    for para in (page["text"] or "").split("\n\n"):
        para = para.strip()
        if para:
            body_paragraphs.append(f"<p>{html.escape(para)}</p>")
    body_html = "\n".join(body_paragraphs)

    img_html_parts = []
    for img_url in page.get("images", []):
        local = image_map.get(img_url)
        if not local:
            continue
        img_html_parts.append(
            f'<img class="page-image" loading="lazy" src="../{html.escape(local)}" alt="">'
        )
    img_html = "\n".join(img_html_parts)
    img_section = f'<div class="image-grid">\n{img_html}\n</div>' if img_html else ""

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{title} - Middletown Tractor Sales</title>
  <link rel="stylesheet" href="../assets/site.css">
  <link rel="stylesheet" href="../assets/widget.css">
</head>
<body>
  <header class="site-header">
    <a href="../index.html" class="site-brand">Middletown Tractor Sales</a>
    <nav><a href="../index.html">Home</a></nav>
  </header>
  <main class="page">
    <h1>{title}</h1>
    {img_section}
    <div class="body">
      {body_html}
    </div>
    <p class="source"><a href="{html.escape(page['url'])}" rel="external">View on middletowntractor.com</a></p>
  </main>
  <div id="mt-chat-root"></div>
  <script>window.MT_CHAT_CONFIG = {{ apiUrl: window.MT_BACKEND_URL || '' , suggestionsUrl: '/assets/canned.json' }};</script>
  <script src="../assets/widget.js" defer></script>
</body>
</html>
"""


def render_index_html(cats: dict[str, list[dict]]) -> str:
    sections = []
    for cat_name, pages in cats.items():
        items = "\n".join(
            f'<li><a href="pages/{slug_for(p["url"])}">{html.escape(p["title"] or p["url"])}</a></li>'
            for p in pages
        )
        sections.append(
            f"<section><h2>{html.escape(cat_name)} <span class='count'>({len(pages)})</span></h2>\n<ul>{items}</ul></section>"
        )
    sections_html = "\n".join(sections)

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Middletown Tractor Sales</title>
  <link rel="stylesheet" href="assets/site.css">
  <link rel="stylesheet" href="assets/widget.css">
  <link rel="manifest" href="manifest.json">
  <meta name="theme-color" content="#2f7a3a">
</head>
<body>
  <header class="site-header hero">
    <div>
      <h1>Middletown Tractor Sales</h1>
      <p>John Deere &middot; STIHL &middot; Honda Power &middot; Ventrac &middot; serving WV &amp; PA since 1955</p>
      <p class="locations-bar">
        <strong>4 Locations:</strong>
        Fairmont WV &middot; Buckhannon WV &middot; Uniontown PA &middot; Washington PA
      </p>
    </div>
  </header>
  <main class="home">
    <p class="intro">Browse our equipment, parts, and service info below, or tap the chat bubble in the corner to ask a question.</p>
    {sections_html}
  </main>
  <div id="mt-chat-root"></div>
  <script>window.MT_CHAT_CONFIG = {{ apiUrl: window.MT_BACKEND_URL || '', suggestionsUrl: '/assets/canned.json' }};</script>
  <script src="assets/widget.js" defer></script>
</body>
</html>
"""


SITE_CSS = """:root {
  --primary: #2f7a3a;
  --primary-dark: #1f5527;
  --bg: #fafbfa;
  --bg-card: #fff;
  --text: #1a1f1c;
  --muted: #6b7670;
  --border: #d9dfdb;
}
* { box-sizing: border-box; }
body { margin: 0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; color: var(--text); background: var(--bg); line-height: 1.5; }
a { color: var(--primary-dark); text-decoration: none; }
a:hover { text-decoration: underline; }
.site-header { background: var(--primary); color: #fff; padding: 14px 20px; display: flex; align-items: center; justify-content: space-between; }
.site-header a, .site-header .site-brand { color: #fff; text-decoration: none; font-weight: 600; }
.site-header nav a { margin-left: 16px; font-size: 14px; }
.hero { flex-direction: column; align-items: flex-start; padding: 32px 24px; }
.hero h1 { margin: 0 0 6px; font-size: 28px; }
.hero p { margin: 4px 0; opacity: 0.95; }
.locations-bar { font-size: 14px; }
.home { padding: 20px; max-width: 900px; margin: 0 auto; }
.home .intro { color: var(--muted); margin-bottom: 24px; }
.home section { background: var(--bg-card); border: 1px solid var(--border); border-radius: 10px; padding: 16px 20px; margin-bottom: 16px; }
.home section h2 { margin: 0 0 10px; color: var(--primary-dark); font-size: 18px; }
.home section .count { color: var(--muted); font-weight: 400; font-size: 13px; }
.home section ul { margin: 0; padding-left: 18px; }
.home section li { margin: 4px 0; font-size: 14.5px; }
.page { padding: 20px; max-width: 900px; margin: 0 auto; }
.page h1 { color: var(--primary-dark); margin-top: 8px; }
.page .body { background: var(--bg-card); border: 1px solid var(--border); border-radius: 10px; padding: 20px; }
.page .body p { margin: 0 0 12px; }
.image-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(180px, 1fr)); gap: 8px; margin: 16px 0; }
.page-image { width: 100%; height: 140px; object-fit: cover; border-radius: 8px; background: #eee; }
.source { color: var(--muted); font-size: 13px; margin-top: 20px; }
"""


def main() -> int:
    pages_path = BUNDLE / "pages.json"
    image_map_path = BUNDLE / "image_map.json"
    if not pages_path.exists():
        print(f"missing {pages_path} - run scrape_full.py first", file=sys.stderr)
        return 1

    pages: list[dict] = json.loads(pages_path.read_text(encoding="utf-8"))
    image_map: dict[str, str] = (
        json.loads(image_map_path.read_text(encoding="utf-8"))
        if image_map_path.exists()
        else {}
    )

    PAGES_DIR.mkdir(parents=True, exist_ok=True)
    ASSETS_DIR.mkdir(parents=True, exist_ok=True)

    # Per-page HTML
    for p in pages:
        out = PAGES_DIR / slug_for(p["url"])
        out.write_text(render_page_html(p, image_map), encoding="utf-8")

    # Index
    cats = categorize(pages)
    (BUNDLE / "index.html").write_text(render_index_html(cats), encoding="utf-8")

    # Copy + adapt widget assets (canned URL is now a static JSON file, no /api/)
    widget_src = ROOT / "widget"
    shutil.copy(widget_src / "widget.css", ASSETS_DIR / "widget.css")
    widget_js = (widget_src / "widget.js").read_text(encoding="utf-8")
    (ASSETS_DIR / "widget.js").write_text(widget_js, encoding="utf-8")
    (ASSETS_DIR / "site.css").write_text(SITE_CSS, encoding="utf-8")

    # Bundle canned answers so chips work fully offline
    canned = json.loads((ROOT / "backend" / "canned.json").read_text(encoding="utf-8"))
    (ASSETS_DIR / "canned.json").write_text(
        json.dumps(canned, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    # PWA manifest
    manifest = {
        "name": "Middletown Tractor Sales",
        "short_name": "MTS",
        "start_url": "./index.html",
        "display": "standalone",
        "background_color": "#fafbfa",
        "theme_color": "#2f7a3a",
        "icons": [
            {"src": "assets/icon-192.png", "sizes": "192x192", "type": "image/png"},
            {"src": "assets/icon-512.png", "sizes": "512x512", "type": "image/png"},
        ],
    }
    (BUNDLE / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    print(f"Wrote {len(pages)} pages into {PAGES_DIR}")
    print(f"Wrote index.html with {len(cats)} categories")
    print(f"Bundled {len(canned)} canned answers into assets/canned.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
