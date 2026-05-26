"""
Generate a polished, dealership-style static site from the scraped pages.

Layout:
  index.html              - Hero, featured inventory, brand & category cards, locations footer
  pages/brand-<slug>.html - Listing of products under a brand (cards w/ thumbnails)
  pages/<slug>.html       - Product detail (image gallery + description) or info page
  assets/                 - widget files, canned.json, brand-themed CSS, icons

Reads:
  site_bundle/pages.json
  site_bundle/image_map.json
  backend/canned.json
  widget/widget.js, widget.css
"""
from __future__ import annotations

import hashlib
import html
import json
import re
import shutil
import sys
from collections import defaultdict
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent.parent
BUNDLE = ROOT / "site_bundle"
PAGES_DIR = BUNDLE / "pages"
ASSETS_DIR = BUNDLE / "assets"

# Populated in main() from image_map: paths (relative to bundle root) for the
# real John Deere and Middletown Tractor brand marks shown in the topbar.
TOPBAR_LOGOS: dict[str, str] = {}

LOCATIONS = [
    {"city": "Fairmont, WV",   "address": "2050 Boyers Drive, Fairmont, WV 26554",     "phone": "(304) 366-4690"},
    {"city": "Buckhannon, WV", "address": "136 Billingsley Dr, Buckhannon, WV 26201",  "phone": "(304) 473-4400"},
    {"city": "Uniontown, PA",  "address": "655 Pittsburgh Road, Uniontown, PA 15401",  "phone": "(724) 439-1234"},
    {"city": "Washington, PA", "address": "910 Henderson Avenue, Washington, PA 15301", "phone": "(724) 229-0191"},
]

# ---------- Classification ----------

PRODUCT_URL_RE = re.compile(r"--(?:[A-Za-z]+-)+(?:West-Virginia|Pennsylvania)---\d+", re.I)


def page_kind(p: dict) -> str:
    url = p["url"].lower()
    if PRODUCT_URL_RE.search(p["url"]):
        return "product"
    if "/inventory/v1/current/" in url and url.count("/") <= 9:
        return "category"
    if "/inventory/v1/2019/" in url:
        return "category"
    if "hours" in url or "map-and-directions" in url or "map-directions" in url:
        return "location"
    if "review" in url or "testimonial" in url:
        return "reviews"
    return "info"


def brand_of(p: dict) -> str | None:
    m = re.search(r"/Current/([^/?]+)", p["url"])
    if m:
        return m.group(1).replace("-", " ")
    if "deere" in p["title"].lower():
        return "John Deere"
    return None


def category_of(p: dict) -> str | None:
    m = re.search(r"/Current/[^/]+/([^/?]+)", p["url"])
    return m.group(1).replace("-", " ") if m else None


def product_name(p: dict) -> str:
    """Try to extract a clean product name from URL or title."""
    m = re.search(r"/Current/[^/]+(?:/[^/]+){2,}/([A-Z0-9-]+)(?:--|--)", p["url"])
    if m:
        return m.group(1).replace("-", " ")
    # Try to pull a model from the URL even when the captured segment lives
    # one level deeper (e.g. /Turf-Maintenance/HQ680/Base--...).
    m = re.search(r"/Current/[^/]+(?:/[^/]+){1,}/([A-Z][A-Z0-9-]{1,})/[^/]+--", p["url"])
    if m:
        return m.group(1).replace("-", " ")
    # Fallback: trim the long title
    t = p["title"].split("|")[0].strip()
    return t[:50] if t else "Product"


def is_generic_showroom(p: dict) -> bool:
    """True when this product page lacks an identifiable model name and would
    render as a duplicate 'Inventory Showroom' card with the same stock photo."""
    name = product_name(p)
    if not name or name.lower() in ("inventory showroom", "product"):
        return True
    title = (p.get("title") or "").split("|")[0].strip().lower()
    return title.startswith("inventory showroom") and name.lower() == title


def slug_for(url: str) -> str:
    h = hashlib.sha1(url.encode("utf-8")).hexdigest()[:8]
    path = urlparse(url).path.strip("/")
    base = re.sub(r"[^A-Za-z0-9._-]+", "-", path)[:50].strip("-") or "home"
    return f"{base}_{h}.html"


def brand_slug(brand: str) -> str:
    return "brand-" + re.sub(r"[^a-z0-9]+", "-", brand.lower()).strip("-") + ".html"


# ---------- Image helpers ----------

def page_thumb(p: dict, image_map: dict[str, str]) -> str | None:
    """Return the first usable local image path for a page, or None."""
    for img_url in p.get("images", []):
        if img_url in image_map:
            return image_map[img_url]
    return None


def is_product_image(local_path: str) -> bool:
    return "/images/" in local_path or local_path.startswith("images/")


# ---------- HTML helpers ----------

def H(s: str) -> str:
    return html.escape(s or "")


def head(title: str, depth: int) -> str:
    """`depth` = how many ../ to prefix paths (0 for index, 1 for pages/)."""
    prefix = "../" if depth else ""
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
  <title>{H(title)}</title>
  <script>
    (function(){{
      try {{
        var s = localStorage.getItem('mt-theme');
        var t = s || (matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light');
        document.documentElement.setAttribute('data-theme', t);
      }} catch(e) {{
        document.documentElement.setAttribute('data-theme', 'light');
      }}
    }})();
  </script>
  <link rel="stylesheet" href="{prefix}assets/site.css">
  <link rel="stylesheet" href="{prefix}assets/widget.css">
  <link rel="manifest" href="{prefix}manifest.json">
  <meta name="theme-color" content="#ffffff" media="(prefers-color-scheme: light)">
  <meta name="theme-color" content="#0a0e0c" media="(prefers-color-scheme: dark)">
  <meta name="color-scheme" content="light dark">
  <link rel="icon" href="{prefix}assets/icon-192.png" type="image/png">
  <script src="{prefix}assets/theme.js" defer></script>
</head>"""


def topbar(depth: int) -> str:
    prefix = "../" if depth else ""
    # Curated mark image paths (resolved from image_map by build_site.py).
    # Falls back to hand-drawn SVG when missing.
    jd_path = TOPBAR_LOGOS.get("jd")
    mts_path = TOPBAR_LOGOS.get("mts")
    jd_html = (f'<img src="{prefix}{H(jd_path)}" alt="John Deere" class="jd-mark-img">'
               if jd_path else
               '<svg viewBox="0 0 70 50" width="42" height="30" fill="currentColor" aria-hidden="true">'
               '<path d="M11 38c-2-7 1-14 6-19 5-4 11-5 17-4 1 0 1 1 0 1-5 1-9 4-13 8-3 4-5 9-4 14 1 4 4 7 8 7 1 0 1 1 0 1-6 1-12-2-14-8zm22-26c-7 0-13 5-15 12 0 1 1 1 1 0 3-4 8-7 13-7s9 2 11 6c0 1 1 1 1 0 0-7-5-11-11-11zm15 16c-2-6-8-10-15-10-1 0-1 1 0 1 6 1 11 4 13 10 1 5-1 10-5 13 0 1 0 1 1 1 5-3 8-9 6-15z"/></svg>')
    mts_html = (f'<img src="{prefix}{H(mts_path)}" alt="MTS" class="brand-logo-img">'
                if mts_path else
                '<span class="brand-mark" aria-hidden="true">MTS</span>'
                '<span class="brand-text"><strong>Middletown</strong><small>Tractor Sales</small></span>')
    return f"""<header class="topbar">
  <span class="jd-mark" aria-label="John Deere">{jd_html}</span>
  <span class="topbar-divider" aria-hidden="true"></span>
  <a class="brand" href="{prefix}index.html" aria-label="Middletown Tractor Sales home">{mts_html}</a>
  <nav class="topnav">
    <button class="theme-toggle" type="button" aria-label="Toggle light/dark theme" title="Toggle theme">
      <svg class="icon-sun" viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
        <circle cx="12" cy="12" r="4"></circle>
        <path d="M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M2 12h2M20 12h2M4.93 19.07l1.41-1.41M17.66 6.34l1.41-1.41"></path>
      </svg>
      <svg class="icon-moon" viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
        <path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"></path>
      </svg>
    </button>
    <button class="icon-btn" type="button" onclick="document.querySelector('.mt-launcher')?.click();return false;" aria-label="Search / ask chatbot" title="Ask">
      <svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
        <circle cx="11" cy="11" r="7"></circle><path d="m20 20-3.5-3.5"></path>
      </svg>
    </button>
  </nav>
</header>"""


def bottom_nav(depth: int, active: str = "home") -> str:
    """`active` ∈ {'home', 'inventory', 'specials', 'parts', 'more'}."""
    prefix = "../" if depth else ""
    def cls(name: str) -> str:
        return ' class="active"' if active == name else ""

    icon_home = ('<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" '
                 'stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'
                 '<path d="M3 11 12 4l9 7"/><path d="M5 10v10h14V10"/></svg>')
    icon_inv = ('<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" '
                'stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'
                '<rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/>'
                '<rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/></svg>')
    icon_spec = ('<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" '
                 'stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'
                 '<path d="M20.59 13.41 11 22.83l-9-9V3h10.83l9 9.41a2 2 0 0 1 0 1Z"/><circle cx="7" cy="7" r="1.5" fill="currentColor"/></svg>')
    icon_parts = ('<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" '
                  'stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'
                  '<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1Z"/></svg>')
    icon_more = ('<svg viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">'
                 '<circle cx="5" cy="12" r="1.8"/><circle cx="12" cy="12" r="1.8"/><circle cx="19" cy="12" r="1.8"/></svg>')

    return f"""<nav class="nav-bottom" aria-label="Primary">
  <a href="{prefix}index.html"{cls("home")}>
    <span class="nav-icon">{icon_home}</span>
    <span>Home</span>
  </a>
  <a href="{prefix}pages/all-inventory.html"{cls("inventory")}>
    <span class="nav-icon">{icon_inv}</span>
    <span>Inventory</span>
  </a>
  <a href="{prefix}index.html#specials"{cls("specials")}>
    <span class="nav-icon">{icon_spec}</span>
    <span>Specials</span>
  </a>
  <a href="{prefix}index.html#parts"{cls("parts")}>
    <span class="nav-icon">{icon_parts}</span>
    <span>Parts</span>
  </a>
  <button type="button" onclick="document.querySelector('.mt-launcher')?.click();return false;" aria-label="Open chatbot"{(' class="active"' if active == "more" else "")}>
    <span class="nav-icon">{icon_more}</span>
    <span>More</span>
  </button>
</nav>"""


def footer(depth: int) -> str:
    prefix = "../" if depth else ""
    loc_html = "".join(
        f'<li><strong>{H(l["city"])}</strong><br>{H(l["address"])}<br><a href="tel:{re.sub(r"[^0-9]","",l["phone"])}">{H(l["phone"])}</a></li>'
        for l in LOCATIONS
    )
    return f"""<footer class="site-footer">
  <div class="footer-cols">
    <div>
      <h4>Visit Us</h4>
      <ul class="loc-list">{loc_html}</ul>
    </div>
    <div>
      <h4>Brands</h4>
      <ul>
        <li>John Deere</li>
        <li>STIHL</li>
        <li>Honda Power</li>
        <li>Ventrac</li>
        <li>Frontier</li>
        <li>Alamo Industrial</li>
        <li>Kuhn (Washington PA)</li>
      </ul>
    </div>
    <div>
      <h4>Departments</h4>
      <ul>
        <li><a href="#" onclick="document.querySelector('.mt-launcher')?.click();return false;">Sales chat</a></li>
        <li>Parts</li>
        <li>Service &amp; Repair</li>
        <li>Mobile / On-site service</li>
        <li>Financing &amp; quotes</li>
      </ul>
    </div>
  </div>
  <div class="footer-bottom">
    &copy; Middletown Tractor Sales &middot; Serving WV &amp; PA since 1955
  </div>
</footer>"""


def chat_root(depth: int) -> str:
    # Absolute paths resolve from the Capacitor bundle root in both the
    # index page and pages/*.html, so we don't need to adjust by depth.
    return """<div id="mt-chat-root"></div>
<script>window.MT_CHAT_CONFIG = {
  apiUrl: window.MT_BACKEND_URL || '',
  suggestionsUrl: '/assets/canned.json',
  urlMapUrl: '/assets/url_map.json'
};</script>
<script src="/assets/widget.js" defer></script>"""


# ---------- Product card ----------

def product_card(p: dict, image_map: dict[str, str], depth: int = 0) -> str:
    """depth=0 from index.html, depth=1 from pages/*.html."""
    thumb = page_thumb(p, image_map)
    img_prefix = "../" if depth else ""
    href_prefix = "" if depth else "pages/"
    name = product_name(p)
    brand = brand_of(p) or ""
    alt = (f"{brand} {name}".strip() or "Product photo")
    img_html = (
        f'<div class="card-img">'
        f'<img loading="lazy" src="{img_prefix}{H(thumb)}" alt="{H(alt)}">'
        f'</div>'
        if thumb else
        f'<div class="card-img card-img-empty" aria-label="{H(alt)}">'
        f'<span class="card-img-fallback">{H(brand or "Middletown Tractor")}</span>'
        f'</div>'
    )
    return f"""<a class="card product-card" href="{href_prefix}{H(slug_for(p["url"]))}" aria-label="{H(alt)}">
  {img_html}
  <div class="card-body">
    <div class="card-brand">{H(brand)}</div>
    <div class="card-title">{H(name)}</div>
  </div>
</a>"""


def brand_card(brand: str, count: int, thumb: str | None) -> str:
    alt = f"{brand} inventory"
    img_html = (
        f'<div class="card-img"><img loading="lazy" src="{H(thumb)}" alt="{H(alt)}"></div>'
        if thumb else
        f'<div class="card-img card-img-empty" aria-label="{H(alt)}">'
        f'<span class="card-img-fallback">{H(brand)}</span>'
        f'</div>'
    )
    return f"""<a class="card brand-card" href="pages/{H(brand_slug(brand))}" aria-label="{H(alt)}">
  {img_html}
  <div class="card-body">
    <div class="card-title">{H(brand)}</div>
    <div class="card-meta">{count} item{'s' if count != 1 else ''}</div>
  </div>
</a>"""


# ---------- Page builders ----------

def render_product_page(p: dict, image_map: dict[str, str]) -> str:
    title = product_name(p) or p["title"]
    images = [image_map[u] for u in p.get("images", []) if u in image_map]
    hero = images[0] if images else None
    thumbs = images[1:] if len(images) > 1 else []

    alt = f"{brand_of(p) or ''} {title}".strip() or "Product photo"
    hero_html = (
        f'<div class="product-hero"><img src="../{H(hero)}" alt="{H(alt)}"></div>'
        if hero else
        f'<div class="product-hero product-hero-empty" aria-label="{H(alt)}">'
        f'<span class="hero-fallback">{H(alt)}</span></div>'
    )

    thumb_html = ""
    if thumbs:
        items = "".join(
            f'<button class="thumb" type="button" aria-label="View photo {i+2} of {H(title)}" '
            f'onclick="document.querySelector(\'.product-hero img\').src=\'../{H(t)}\'">'
            f'<img src="../{H(t)}" alt="{H(title)} photo {i+2}"></button>'
            for i, t in enumerate(thumbs)
        )
        thumb_html = f'<div class="thumb-row">{items}</div>'

    paras = [f"<p>{H(para.strip())}</p>" for para in (p["text"] or "").split("\n\n") if para.strip()]
    body_html = "\n".join(paras) or "<p>Contact us for details on this unit.</p>"

    return f"""{head(title + " | Middletown Tractor", depth=1)}
<body>
{topbar(depth=1)}
<main class="product-page">
  <a class="back" href="../index.html">&larr; Back</a>
  <div class="product-grid">
    <div class="product-images">
      {hero_html}
      {thumb_html}
    </div>
    <div class="product-info">
      <div class="product-brand">{H(brand_of(p) or "")}</div>
      <h1>{H(title)}</h1>
      <div class="product-cta">
        <a class="btn btn-primary" href="#" onclick="document.querySelector('.mt-launcher')?.click();return false;">Ask about this unit</a>
        <a class="btn btn-secondary" href="tel:3043664690">Call Fairmont</a>
      </div>
      <div class="product-body">{body_html}</div>
      <p class="source-link"><a href="{H(p['url'])}">View on middletowntractor.com</a></p>
    </div>
  </div>
</main>
{footer(depth=1)}
{bottom_nav(depth=1, active="inventory")}
{chat_root(depth=1)}
</body></html>
"""


def render_info_page(p: dict, image_map: dict[str, str]) -> str:
    title = (p["title"].split("|")[0]).strip() or p["url"]
    paras = [f"<p>{H(para.strip())}</p>" for para in (p["text"] or "").split("\n\n") if para.strip()]
    body_html = "\n".join(paras)

    images = [image_map[u] for u in p.get("images", []) if u in image_map]
    img_html = ""
    if images:
        items = "".join(
            f'<img class="info-img" loading="lazy" src="../{H(i)}" alt="{H(title)} photo {idx+1}">'
            for idx, i in enumerate(images[:8])
        )
        img_html = f'<div class="info-images">{items}</div>'

    return f"""{head(title + " | Middletown Tractor", depth=1)}
<body>
{topbar(depth=1)}
<main class="info-page">
  <a class="back" href="../index.html">&larr; Back</a>
  <article>
    <h1>{H(title)}</h1>
    {img_html}
    <div class="info-body">{body_html}</div>
    <p class="source-link"><a href="{H(p['url'])}">View on middletowntractor.com</a></p>
  </article>
</main>
{footer(depth=1)}
{bottom_nav(depth=1, active="home")}
{chat_root(depth=1)}
</body></html>
"""


def render_brand_listing(brand: str, products: list[dict], image_map: dict[str, str]) -> str:
    cards = "\n".join(product_card(p, image_map, depth=1) for p in products)
    return f"""{head(brand + " Inventory | Middletown Tractor", depth=1)}
<body>
{topbar(depth=1)}
<main class="listing-page">
  <a class="back" href="../index.html">&larr; Back to home</a>
  <h1>{H(brand)} Inventory</h1>
  <p class="listing-meta">{len(products)} items currently listed across our 4 locations</p>
  <div class="card-grid">{cards}</div>
</main>
{footer(depth=1)}
{bottom_nav(depth=1, active="inventory")}
{chat_root(depth=1)}
</body></html>
"""


def render_all_inventory(products_by_brand: dict[str, list[dict]], image_map: dict[str, str]) -> str:
    """Single page listing every product, grouped by brand so navigation stays sane."""
    sections = []
    total = 0
    for brand, prods in sorted(products_by_brand.items(), key=lambda kv: -len(kv[1])):
        if not prods:
            continue
        cards = "\n".join(product_card(p, image_map, depth=1) for p in prods)
        sections.append(
            f'<section class="brand-section">'
            f'<h2 id="{H(re.sub(r"[^a-z0-9]+", "-", brand.lower()))}">{H(brand)}'
            f' <span class="muted">({len(prods)})</span></h2>'
            f'<div class="card-grid">{cards}</div>'
            f'</section>'
        )
        total += len(prods)

    nav = " &middot; ".join(
        f'<a href="#{H(re.sub(r"[^a-z0-9]+", "-", b.lower()))}">{H(b)}</a>'
        for b, _ in sorted(products_by_brand.items(), key=lambda kv: -len(kv[1]))
    )

    return f"""{head("All Inventory | Middletown Tractor", depth=1)}
<body>
{topbar(depth=1)}
<main class="listing-page">
  <a class="back" href="../index.html">&larr; Back to home</a>
  <h1>All Inventory</h1>
  <p class="listing-meta">{total} units across 4 locations &middot; jump to: {nav}</p>
  {"".join(sections)}
</main>
{footer(depth=1)}
{bottom_nav(depth=1, active="inventory")}
{chat_root(depth=1)}
</body></html>
"""


def render_schedule_page() -> str:
    """Schedule Service / Maintenance form. Posts to the backend's
    /api/service-request endpoint and pushes a notification to the dealer."""
    location_opts = "\n".join(
        f'        <label class="form-radio"><input type="radio" name="location" value="{H(l["city"])}" required><span>{H(l["city"])}</span></label>'
        for l in LOCATIONS
    ) + '\n        <label class="form-radio"><input type="radio" name="location" value="No preference"><span>No preference</span></label>'

    service_opts = "\n".join(
        f'        <label class="form-radio"><input type="radio" name="service_type" value="{v}" required><span>{v}</span></label>'
        for v in ("Routine maintenance", "Repair / diagnostic",
                  "Mobile / on-site service", "Pickup & delivery",
                  "Parts inquiry", "Other")
    )

    return f"""{head("Schedule Service | Middletown Tractor", depth=1)}
<body>
{topbar(depth=1)}
<main class="info-page schedule-page">
  <a class="back" href="../index.html">&larr; Back to home</a>
  <article>
    <h1>Schedule Service or Maintenance</h1>
    <p class="muted">Fill this out and we'll ring your nearest store - a tech will reach back within one business day to confirm timing.</p>

    <form id="service-form" novalidate>
      <fieldset>
        <label class="form-row">
          <span class="form-label">Your name</span>
          <input type="text" name="name" required autocomplete="name" maxlength="120">
        </label>
        <div class="form-grid-2">
          <label class="form-row">
            <span class="form-label">Phone</span>
            <input type="tel" name="phone" required autocomplete="tel" inputmode="tel" maxlength="40" placeholder="(304) 555-0100">
          </label>
          <label class="form-row">
            <span class="form-label">Email</span>
            <input type="email" name="email" required autocomplete="email" maxlength="120" placeholder="you@example.com">
          </label>
        </div>
      </fieldset>

      <fieldset>
        <legend class="form-legend">Which location?</legend>
        <div class="form-radio-grid">
{location_opts}
        </div>
      </fieldset>

      <fieldset>
        <legend class="form-legend">What kind of service?</legend>
        <div class="form-radio-grid">
{service_opts}
        </div>
      </fieldset>

      <fieldset>
        <label class="form-row">
          <span class="form-label">Equipment (make / model / year)</span>
          <input type="text" name="equipment" maxlength="240" placeholder="John Deere 1025R, 2022">
        </label>
        <label class="form-row">
          <span class="form-label">Preferred date or week</span>
          <input type="text" name="preferred_date" maxlength="40" placeholder="Week of June 9, or any Tuesday morning">
        </label>
        <label class="form-row">
          <span class="form-label">Anything we should know?</span>
          <textarea name="notes" rows="4" maxlength="2000" placeholder="What's the symptom, last service date, anything fragile..."></textarea>
        </label>
      </fieldset>

      <div class="form-actions">
        <button type="submit" class="btn btn-primary btn-lg" id="service-submit">Send request</button>
        <span class="form-status" id="service-status" aria-live="polite"></span>
      </div>
    </form>

    <p class="muted small-print">Submitted requests are forwarded to the service desk instantly via push notification. You can also <a href="tel:3043664690">call Fairmont</a> or <a href="#" onclick="document.querySelector('.mt-launcher')?.click();return false;">ask the chatbot</a>.</p>
  </article>
</main>

<script>
(function(){{
  var form = document.getElementById('service-form');
  var status = document.getElementById('service-status');
  var btn = document.getElementById('service-submit');
  var BACKEND = window.MT_BACKEND_URL || '';
  form.addEventListener('submit', async function(e){{
    e.preventDefault();
    if (!BACKEND) {{
      status.textContent = 'No backend URL configured. Set window.MT_BACKEND_URL.';
      status.className = 'form-status err';
      return;
    }}
    if (!form.checkValidity()) {{ form.reportValidity(); return; }}
    var data = Object.fromEntries(new FormData(form).entries());
    btn.disabled = true; status.textContent = 'Sending…'; status.className = 'form-status';
    try {{
      var r = await fetch(BACKEND.replace(/\\/$/,'') + '/api/service-request', {{
        method: 'POST',
        headers: {{ 'Content-Type': 'application/json' }},
        body: JSON.stringify(data),
      }});
      var body = await r.json().catch(function(){{ return {{}}; }});
      if (!r.ok) throw new Error(body.detail || ('HTTP ' + r.status));
      status.textContent = body.message || 'Thanks - request received.';
      status.className = 'form-status ok';
      form.reset();
    }} catch (err) {{
      status.textContent = 'Could not send (' + err.message + '). Please call us.';
      status.className = 'form-status err';
    }} finally {{
      btn.disabled = false;
    }}
  }});
}})();
</script>

{footer(depth=1)}
{bottom_nav(depth=1, active="more")}
{chat_root(depth=1)}
</body></html>
"""


def render_index(featured: list[dict], brands: list[tuple[str, int, str | None]],
                 info_pages: list[dict], image_map: dict[str, str]) -> str:
    featured_html = "\n".join(product_card(p, image_map, depth=0) for p in featured)
    brand_html = "\n".join(brand_card(b, c, t) for b, c, t in brands)

    info_links = "\n".join(
        f'<a class="info-link" href="pages/{H(slug_for(p["url"]))}">{H((p["title"].split("|")[0]).strip()[:60])}</a>'
        for p in info_pages[:8]
    )

    loc_summary = "".join(
        f'<a class="loc-pill" href="tel:{re.sub(r"[^0-9]","",l["phone"])}">'
        f'<strong>{H(l["city"])}</strong><small>{H(l["phone"])}</small></a>'
        for l in LOCATIONS
    )

    # Canonical promo image URLs scraped from the live site - mapped to the
    # specific slots they were authored for.
    PROMO_URLS = {
        "memorial":   "https://www.middletowntractor.com/images/slideshow/Main-SlideShow/Memorial%20Day%20Hours1.jpg",
        "deal1":      "https://www.middletowntractor.com/fckimages/Deal%201%20As%20Low%20As%20Mar%202026%20copy.jpg",
        "earthquaker":"https://www.middletowntractor.com/fckimages/EQ%20Pkg%200%25%20WS%20Mar%202026%20copy.jpg",
        "stihl_save": "https://www.middletowntractor.com/fckimages/Deal%203%20Stihl%203%202026%20copy.jpg",
        "promo_new":  "https://www.middletowntractor.com/images/middletowntractor-promo3.jpg",   # Hot Fall Deals / 0%
        "promo_used": "https://www.middletowntractor.com/fckimages/headers/john-deere5.jpg",
        "specials":   "https://www.middletowntractor.com/images/slideshow/Main-SlideShow/Website%20specials%203%202026%20copy.jpg",
        "parts":      "https://www.middletowntractor.com/images/middletowntractor-promo1.jpg",  # Parts-A-Thon
        "service":    "https://www.middletowntractor.com/images/middletowntractor-promo2.jpg",  # Service banner
        # Brand tiles
        "logo_jd":      "https://www.middletowntractor.com/images/middletowntractor-deer.png",
        "logo_stihl":   "https://cdn.dealerspike.com/imglib/InventoryPages/Makes/Stihl-logo.png",
        "logo_frontier":"https://cdn.dealerspike.com/imglib/InventoryPages/makes/Frontier-logo.png",
        "logo_ventrac": "https://cdn.dealerspike.com/imglib/InventoryPages/Makes/Ventrac-logo.png",
        "logo_honda":   "https://cdn.dealerspike.com/imglib/InventoryPages/Makes/Honda-Power-logo.png",
        "logo_kuhn":    "https://cdn.dealerspike.com/imglib/InventoryPages/Makes/Kuhn-logo.png",
        "logo_alamo":   "https://cdn.dealerspike.com/imglib/InventoryPages/Makes/Alamo-Industrial-logo.png",
        # Topbar marks
        "topbar_jd":   "https://www.middletowntractor.com/images/middletowntractor-deer.png",
        "topbar_mts":  "https://www.middletowntractor.com/images/middletowntractor-logo.png",
    }

    def promo_img(slot: str) -> str | None:
        url = PROMO_URLS.get(slot)
        if url and url in image_map:
            return image_map[url]
        return None

    # Inventory-thumb fallbacks for cat-cards (when the curated promo is missing)
    def first_thumb(brand_name: str) -> str | None:
        for prod in brands_pages.get(brand_name, []):
            t = page_thumb(prod, image_map)
            if t:
                return t
        return None

    brands_pages: dict[str, list[dict]] = {}
    for p in featured:
        brands_pages.setdefault(brand_of(p) or "Other", []).append(p)

    jd_thumb = first_thumb("John Deere")
    stihl_thumb = first_thumb("STIHL")
    other_thumb = first_thumb("Ventrac") or first_thumb("Honda Power") or first_thumb("Other")

    def card_bg(thumb: str | None) -> str:
        if thumb:
            return f'<span class="bg" style="background-image:url(\'{H(thumb)}\')"></span>'
        return '<span class="bg-fallback"></span>'

    # Pick the best image for each slot: curated promo first, then inventory fallback.
    img_riding    = promo_img("deal1")        or jd_thumb
    img_earthq    = promo_img("earthquaker")  or other_thumb or jd_thumb
    img_stihl_save= promo_img("stihl_save")   or stihl_thumb
    img_new       = promo_img("promo_new")    or jd_thumb
    img_used      = promo_img("promo_used")   or other_thumb or jd_thumb
    img_specials  = promo_img("specials")     or jd_thumb
    img_parts     = promo_img("parts")        or jd_thumb
    img_service   = promo_img("service")      or other_thumb
    img_memorial  = promo_img("memorial")

    return f"""{head("Middletown Tractor Sales - WV & PA", depth=0)}
<body>
{topbar(depth=0)}

<main class="home">

  <!-- Featured promotional banner: real Memorial Day art when present -->
  <section class="promo-hero" aria-label="Memorial Day weekend hours">
    {('<img class="promo-hero-art" src="' + H(img_memorial) + '" alt="Memorial Day Weekend special store hours">') if img_memorial else '<div class="promo-hero-img"></div><div class="promo-hero-body"><h2>MEMORIAL DAY<br>WEEKEND</h2><p class="sub">Special Store Hours</p><span class="row">Saturday &mdash; 8:30 AM &ndash; 1:00 PM</span><span class="row">Monday &mdash; CLOSED</span></div>'}
    <div class="promo-dots" aria-hidden="true">
      <span class="dot on"></span><span class="dot"></span>
    </div>
  </section>

  <!-- Two side-by-side promo cards -->
  <section class="promo-duo">
    <a class="promo-card promo-card-art" href="pages/brand-john-deere.html" aria-label="Riding lawn equipment">
      {card_bg(img_riding)}
    </a>
    <a class="promo-card promo-card-art" href="pages/brand-john-deere.html" aria-label="The EARTHQUAKER tractor package">
      {card_bg(img_earthq)}
    </a>
  </section>

  <!-- Wide STIHL-style promo banner -->
  <a class="promo-wide promo-wide-art" href="pages/brand-stihl.html" aria-label="STIHL savings">
    {('<img src="' + H(img_stihl_save) + '" alt="STIHL Save $30">') if img_stihl_save else card_bg(stihl_thumb) + '<span class="label">SAVE $30</span><span class="small">On Select STIHL</span>'}
  </a>

  <!-- 3-up category strip: NEW EQUIP / USED EQUIP / SPECIALS -->
  <section class="cat-strip" id="specials">
    <a class="cat-card" href="pages/all-inventory.html" aria-label="New equipment">
      {card_bg(img_new)}
      <div class="inner">
        <span class="cat-title">New Equip</span>
        <span class="cat-cta">View Inventory &rsaquo;</span>
      </div>
    </a>
    <a class="cat-card" href="pages/all-inventory.html" aria-label="Used equipment">
      {card_bg(img_used)}
      <div class="inner">
        <span class="cat-title">Used Equip</span>
        <span class="cat-cta">View Inventory &rsaquo;</span>
      </div>
    </a>
    <a class="cat-card" href="pages/all-inventory.html" aria-label="Specials">
      {card_bg(img_specials)}
      <div class="inner">
        <span class="cat-title">Specials</span>
        <span class="cat-cta">See More &rsaquo;</span>
      </div>
    </a>
  </section>

  <!-- 2-up: Parts / Service -->
  <section class="cat-strip duo" id="parts">
    <a class="cat-card" href="#" onclick="document.querySelector('.mt-launcher')?.click();return false;" aria-label="Parts">
      {card_bg(img_parts)}
      <div class="inner">
        <span class="cat-title">Parts</span>
        <span class="cat-cta">Learn More &rsaquo;</span>
      </div>
    </a>
    <a class="cat-card" href="pages/schedule-service.html" aria-label="Schedule service">
      {card_bg(img_service)}
      <div class="inner">
        <span class="cat-title">Service</span>
        <span class="cat-cta">Schedule Now &rsaquo;</span>
      </div>
    </a>
  </section>

  <!-- Shop by brands - real logos pulled from middletowntractor.com / dealerspike -->
  <section class="brands-row" id="brands">
    <h3 class="brands-row-title">Shop by Brands</h3>
    <div class="brands-tiles">
      <a class="brand-tile" href="pages/brand-john-deere.html" aria-label="John Deere">
        {('<img src="' + H(promo_img("logo_jd") or "") + '" alt="John Deere" class="brand-logo">') if promo_img("logo_jd") else '<span class="brand-tile-name"><span class="jd">John Deere</span></span>'}
      </a>
      <a class="brand-tile" href="pages/brand-stihl.html" aria-label="STIHL">
        {('<img src="' + H(promo_img("logo_stihl") or "") + '" alt="STIHL" class="brand-logo">') if promo_img("logo_stihl") else '<span class="brand-tile-name"><span class="stihl">STIHL</span></span>'}
      </a>
      <a class="brand-tile" href="pages/brand-other-inventory.html" aria-label="Frontier">
        {('<img src="' + H(promo_img("logo_frontier") or "") + '" alt="Frontier" class="brand-logo brand-logo-light">') if promo_img("logo_frontier") else '<span class="brand-tile-name"><span class="frontier">Frontier</span><small class="brand-tile-sub">Rugged. Reliable.</small></span>'}
      </a>
    </div>
  </section>

  <!-- Locations -->
  <section class="locations-section" id="locations">
    <div class="section-head">
      <h2>Our Locations</h2>
      <p class="muted">Tap to call any of our four WV &amp; PA stores.</p>
    </div>
    <div class="locations-strip">{loc_summary}</div>
  </section>

  <!-- Featured inventory cards -->
  <section class="featured">
    <div class="section-head">
      <h2>Featured Inventory</h2>
      <p class="muted">A taste of what we carry. <a href="pages/all-inventory.html">See all units &rarr;</a></p>
    </div>
    <div class="card-grid">{featured_html}</div>
  </section>

  <!-- Browse all brands grid -->
  <section class="brands">
    <div class="section-head">
      <h2>Browse by Brand</h2>
      <p class="muted">Pick a brand to see every unit we carry.</p>
    </div>
    <div class="card-grid">{brand_html}</div>
  </section>

  <!-- Service / about info -->
  <section class="info">
    <div class="section-head">
      <h2>Service, Parts &amp; About</h2>
    </div>
    <div class="info-links">{info_links}</div>
  </section>

</main>

{footer(depth=0)}
{bottom_nav(depth=0, active="home")}
{chat_root(depth=0)}
</body></html>
"""


# ---------- CSS ----------

SITE_CSS = """:root {
  /* Brand constants - matched to middletowntractor.com (John Deere palette) */
  --primary: #367C2B;             /* John Deere green */
  --primary-dark: #1f5527;
  --jd-yellow: #FFDE00;           /* John Deere yellow - the iconic accent */
  --jd-yellow-bright: #FFE63D;
  --jd-yellow-dark: #E5C700;
  --brand-red: #d92024;           /* Promo / sale urgency */
  --on-primary: #ffffff;

  --radius-sm: 10px;
  --radius: 16px;
  --radius-lg: 22px;
  --topbar-h: 56px;
  --nav-h: 64px;
}

[data-theme="light"] {
  color-scheme: light;
  --bg: #ffffff;
  --bg-elev: #f7f7f4;
  --surface: #ffffff;
  --surface-2: #f4f5f1;
  --surface-3: #e9ebe5;

  --text: #1a1f1c;
  --text-strong: #0a0e0c;
  --text-muted: #6b7670;
  --text-dim: #8a948c;

  --border: #e1e5e1;
  --border-strong: #c4cbc6;

  --topbar-bg: rgba(0, 0, 0, 1);          /* Top bar stays black even in light mode (matches website branding) */
  --topbar-on: #ffffff;
  --topbar-muted: rgba(255, 255, 255, 0.65);
  --nav-bg: rgba(255, 255, 255, 0.94);
  --nav-bg-solid: #ffffff;
  --nav-border: #e1e5e1;
  --nav-fg: #6b7670;
  --nav-fg-active: var(--primary);

  --shadow: 0 2px 8px rgba(0, 0, 0, 0.06);
  --shadow-lg: 0 12px 32px rgba(0, 0, 0, 0.12);
  --shadow-glow: 0 6px 22px rgba(47, 122, 58, 0.22);

  /* Accent on light: keep brand green for readability on white */
  --accent: var(--primary);
  --card-empty-1: #eef2ed;
  --card-empty-2: #e1e8e1;
  --ink-on-yellow: #0a0e0c;
}

[data-theme="dark"] {
  color-scheme: dark;
  --bg: #000000;                          /* Pure black, matches the screenshot */
  --bg-elev: #0a0e0c;
  --surface: #0d1311;
  --surface-2: #141c19;
  --surface-3: #1c2723;

  --text: #ecf2ee;
  --text-strong: #ffffff;
  --text-muted: #98a59c;
  --text-dim: #6b7670;

  --border: rgba(255, 255, 255, 0.08);
  --border-strong: rgba(255, 255, 255, 0.18);

  --topbar-bg: #000000;
  --topbar-on: #ffffff;
  --topbar-muted: rgba(255, 255, 255, 0.55);
  --nav-bg: rgba(0, 0, 0, 0.92);
  --nav-bg-solid: #000000;
  --nav-border: rgba(255, 255, 255, 0.08);
  --nav-fg: #98a59c;
  --nav-fg-active: var(--jd-yellow);

  --shadow: 0 4px 16px rgba(0, 0, 0, 0.5);
  --shadow-lg: 0 12px 32px rgba(0, 0, 0, 0.6);
  --shadow-glow: 0 6px 26px rgba(255, 222, 0, 0.18);

  /* Accent on dark: John Deere yellow (matches screenshot) */
  --accent: var(--jd-yellow);
  --card-empty-1: #0f1714;
  --card-empty-2: #060a08;
  --ink-on-yellow: #0a0e0c;
}

* { box-sizing: border-box; min-width: 0; }

html {
  background: var(--bg);
  -webkit-tap-highlight-color: transparent;
}

html, body {
  margin: 0;
  padding: 0;
  overflow-x: hidden;
  max-width: 100vw;
  min-height: 100vh;
  min-height: 100dvh;
}

body {
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "Samsung One UI", Roboto, Helvetica, Arial, sans-serif;
  color: var(--text);
  background: var(--bg);
  line-height: 1.5;
  font-size: 15px;
  -webkit-text-size-adjust: 100%;
  -webkit-font-smoothing: antialiased;
  padding-bottom: calc(var(--nav-h) + env(safe-area-inset-bottom));
}

a { color: var(--accent); text-decoration: none; }
a:hover { text-decoration: underline; }
img { max-width: 100%; height: auto; display: block; }
h1, h2, h3, h4 { color: var(--text-strong); overflow-wrap: anywhere; letter-spacing: -0.01em; }
p, li, .card-title, .card-meta, .card-brand { overflow-wrap: anywhere; word-wrap: break-word; }

/* ---------- Topbar (always-black like the screenshot) ---------- */
.topbar {
  position: sticky; top: 0; z-index: 100;
  background: var(--topbar-bg);
  color: var(--topbar-on);
  border-bottom: 1px solid rgba(255, 255, 255, 0.08);
  display: flex;
  align-items: center;
  gap: 8px;
  padding: max(10px, env(safe-area-inset-top)) 12px 10px;
  min-height: var(--topbar-h);
}
.topbar .jd-mark {
  flex: 0 0 auto;
  height: 32px;
  display: flex; align-items: center;
  color: var(--primary);
}
.topbar .jd-mark svg { display: block; }
.topbar .jd-mark-img {
  height: 32px; width: auto; display: block;
  /* Keep deer green on the always-black topbar */
  filter: drop-shadow(0 0 0 transparent);
}
.brand-logo-img {
  height: 30px; width: auto; display: block;
  /* The logo has green + yellow brand marks - leave colors intact on black topbar. */
}
.topbar-divider {
  width: 1px; height: 28px;
  background: rgba(255, 255, 255, 0.16);
  margin: 0 4px;
  flex: 0 0 auto;
}
.brand { display: flex; align-items: center; gap: 10px; color: var(--topbar-on); min-width: 0; flex: 1 1 auto; text-decoration: none; }
.brand:hover { text-decoration: none; }
.brand-mark {
  flex: 0 0 auto;
  width: 36px; height: 36px;
  background: linear-gradient(135deg, var(--jd-yellow) 0%, var(--primary) 100%);
  color: #0a0e0c;
  border-radius: 8px;
  display: flex; align-items: center; justify-content: center;
  font-weight: 900; font-size: 12px;
  letter-spacing: 0.04em;
}
.brand-text { min-width: 0; line-height: 1.05; }
.brand-text strong { display: block; font-size: 14px; font-weight: 800; color: var(--topbar-on); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; letter-spacing: 0.02em; }
.brand-text small { display: block; color: var(--topbar-muted); font-size: 9.5px; font-weight: 600; letter-spacing: 0.16em; text-transform: uppercase; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.topnav { display: flex; gap: 4px; flex-shrink: 0; align-items: center; }
.icon-btn {
  display: inline-flex; align-items: center; justify-content: center;
  width: 38px; height: 38px;
  background: transparent; border: none;
  color: var(--topbar-on);
  border-radius: 10px;
  cursor: pointer; font-family: inherit;
  position: relative;
}
.icon-btn:hover { background: rgba(255, 255, 255, 0.08); }
.icon-btn.cart-btn { color: var(--jd-yellow); }
.cart-badge {
  position: absolute;
  top: 4px; right: 4px;
  min-width: 16px; height: 16px;
  background: var(--brand-red);
  color: #fff;
  font-size: 10px; font-weight: 800;
  border-radius: 999px;
  display: flex; align-items: center; justify-content: center;
  padding: 0 4px;
  box-shadow: 0 0 0 2px var(--topbar-bg);
}
.theme-toggle {
  display: inline-flex; align-items: center; justify-content: center;
  width: 38px; height: 38px;
  background: transparent; border: none;
  color: var(--topbar-on);
  border-radius: 10px;
  cursor: pointer; font-family: inherit;
}
.theme-toggle:hover { background: rgba(255, 255, 255, 0.08); }
.theme-toggle .icon-sun { display: none; }
.theme-toggle .icon-moon { display: block; }
[data-theme="dark"] .theme-toggle .icon-sun { display: block; }
[data-theme="dark"] .theme-toggle .icon-moon { display: none; }
.chat-btn {
  background: var(--jd-yellow);
  color: var(--ink-on-yellow);
  border: none;
  padding: 9px 14px; border-radius: 10px;
  font-family: inherit; font-weight: 800; font-size: 13px;
  letter-spacing: 0.04em; text-transform: uppercase;
  cursor: pointer;
}
.chat-btn:hover { background: var(--jd-yellow-bright); }

/* ---------- Hero promo banner (Memorial-Day-style featured card) ---------- */
.home { max-width: 1100px; margin: 0 auto; padding: 14px clamp(10px, 3vw, 18px) 24px; }

.promo-hero {
  position: relative;
  border-radius: var(--radius);
  overflow: hidden;
  border: 1px solid var(--border);
  background: var(--surface);
  margin-bottom: 12px;
}
.promo-hero-img {
  width: 100%; aspect-ratio: 16/10;
  background: linear-gradient(180deg, #1c4f8c 0%, #c41e3a 100%);
  display: block;
  position: relative;
}
.promo-hero-img::before {
  /* Flag-like striping effect when no real image is available */
  content: "";
  position: absolute; inset: 0;
  background-image:
    repeating-linear-gradient(180deg, transparent 0, transparent 22px, rgba(255,255,255,0.08) 22px, rgba(255,255,255,0.08) 24px);
  pointer-events: none;
}
.promo-hero-img img {
  width: 100%; height: 100%; object-fit: cover;
  display: block;
  position: relative;
  z-index: 1;
}
.promo-hero-body {
  background: #ffffff;
  color: #0a0e0c;
  padding: 18px 16px 22px;
  text-align: center;
}
.promo-hero-body h2 {
  margin: 0;
  font-size: clamp(22px, 6.5vw, 36px);
  line-height: 1;
  font-weight: 900;
  letter-spacing: -0.01em;
  color: #1c4f8c;
}
.promo-hero-body .sub {
  margin: 10px 0 0;
  font-size: clamp(12px, 3vw, 14px);
  letter-spacing: 0.32em;
  font-weight: 700;
  color: #1a1f1c;
  text-transform: uppercase;
}
.promo-hero-body .row {
  display: block;
  margin-top: 14px;
  font-size: clamp(13px, 3.4vw, 15px);
  font-weight: 700;
  color: var(--brand-red);
  letter-spacing: 0.02em;
}
.promo-dots {
  display: flex; gap: 6px; justify-content: center;
  padding: 10px 0;
  background: #ffffff;
}
.promo-dots .dot { width: 6px; height: 6px; border-radius: 50%; background: #c4cbc6; }
.promo-dots .dot.on { background: var(--primary); }

/* Promo hero - full-bleed banner image (replaces the gradient fallback) */
.promo-hero-art {
  display: block; width: 100%; height: auto;
  background: #ffffff;
}

/* Promo cards: when a full art image is supplied, hide the text overlay and let the
   designed graphic do all the work (these banners are pre-composed with their own
   typography, prices, and brand marks). */
.promo-card-art { aspect-ratio: 16/9; }
.promo-card-art .inner { display: none; }
.promo-card-art::after { display: none; }
.promo-card-art .bg {
  background-image: none;          /* inline style="background-image:url(...)" wins */
  background-color: #0a0e0c;
  background-size: contain;
  background-color: #0d1311;
}

/* Wide promo: when an art image is supplied, render it directly inside the
   anchor at intrinsic aspect ratio. */
.promo-wide-art {
  background: transparent;
  aspect-ratio: auto;
  display: block;
  padding: 0;
}
.promo-wide-art img { display: block; width: 100%; height: auto; border-radius: inherit; }
.promo-wide-art .bg, .promo-wide-art .label, .promo-wide-art .small { display: none; }

/* Brand tile logos */
.brand-logo {
  max-height: 36px;
  max-width: 90%;
  width: auto;
  height: auto;
  object-fit: contain;
}
[data-theme="dark"] .brand-logo-light {
  /* Frontier logo is white-on-transparent. In light mode we tint it dark so it shows. */
}
[data-theme="light"] .brand-logo-light {
  filter: invert(1) brightness(0.5);
}

/* ---------- Duo promo (two cards side by side) ---------- */
.promo-duo {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 10px;
  margin-bottom: 12px;
}
.promo-card {
  position: relative;
  border-radius: var(--radius);
  overflow: hidden;
  background: var(--surface-2);
  border: 1px solid var(--border);
  aspect-ratio: 1/1;
  display: flex; align-items: flex-end;
  color: #fff;
  text-decoration: none;
}
.promo-card .bg, .promo-card .bg-fallback {
  position: absolute; inset: 0;
  background-color: #0d1311;
  background-image: linear-gradient(135deg, #2c4521 0%, #0d1311 100%);
  background-position: center; background-size: cover; background-repeat: no-repeat;
  z-index: 0;
}
/* When a real image URL is supplied via inline style, it overlays the fallback gradient */
.promo-card .bg[style*="url("] {
  background-image: var(--bg-img, none), linear-gradient(135deg, #2c4521 0%, #0d1311 100%);
}
.promo-card::after {
  content: "";
  position: absolute; inset: 0;
  background: linear-gradient(180deg, rgba(0,0,0,0) 35%, rgba(0,0,0,0.6) 100%);
  z-index: 1;
  pointer-events: none;
}
.promo-card .inner {
  position: relative; z-index: 2;
  padding: 12px 14px 14px;
  width: 100%;
}
.promo-card .kicker {
  display: block;
  font-size: 14px;
  font-weight: 900;
  color: var(--jd-yellow);
  line-height: 1.05;
  text-shadow: 0 1px 4px rgba(0,0,0,0.6);
  letter-spacing: 0.01em;
}
.promo-card .price {
  display: block;
  font-size: 22px;
  font-weight: 900;
  color: var(--jd-yellow);
  margin-top: 4px;
  text-shadow: 0 1px 4px rgba(0,0,0,0.6);
}
.promo-card .note {
  display: block; margin-top: 4px;
  font-size: 11.5px; font-weight: 600; color: #fff;
  text-shadow: 0 1px 4px rgba(0,0,0,0.55);
}

/* Wide promo banner (STIHL Save $30 style) */
.promo-wide {
  position: relative;
  border-radius: var(--radius);
  overflow: hidden;
  margin-bottom: 12px;
  background: #e8580f;
  aspect-ratio: 16/7;
  display: flex; align-items: center; justify-content: center;
  text-decoration: none;
  color: #fff;
}
.promo-wide .bg {
  position: absolute; inset: 0;
  background-size: cover; background-position: center;
  opacity: 0.55;
}
.promo-wide .label {
  position: relative;
  font-size: clamp(28px, 9vw, 48px);
  font-weight: 900;
  color: #ffffff;
  letter-spacing: -0.01em;
  text-shadow: 0 2px 6px rgba(0,0,0,0.55);
  z-index: 1;
}
.promo-wide .small {
  position: relative; z-index: 1;
  margin-left: 14px;
  font-size: 11px;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.12em;
  opacity: 0.95;
}

/* ---------- Category strip (NEW EQUIP / USED EQUIP / SPECIALS) ---------- */
.cat-strip {
  display: grid;
  grid-template-columns: 1fr 1fr 1fr;
  gap: 8px;
  margin-bottom: 12px;
}
.cat-strip.duo { grid-template-columns: 1fr 1fr; }

.cat-card {
  position: relative;
  border-radius: var(--radius);
  overflow: hidden;
  aspect-ratio: 5/4;
  background: var(--surface-2);
  border: 1px solid var(--border);
  display: flex; align-items: flex-end;
  text-decoration: none;
  color: #fff;
}
.cat-card .bg, .cat-card .bg-fallback {
  position: absolute; inset: 0;
  background-color: #0d1311;
  background-image: linear-gradient(135deg, #0d1311 0%, #2c4521 100%);
  background-position: center; background-size: cover; background-repeat: no-repeat;
  z-index: 0;
}
.promo-wide .bg, .promo-wide .bg-fallback {
  position: absolute; inset: 0;
  background-color: #e8580f;
  background-position: center; background-size: cover; background-repeat: no-repeat;
  z-index: 0;
  opacity: 0.55;
}
.cat-card::after {
  content: "";
  position: absolute; inset: 0;
  background: linear-gradient(180deg, rgba(0,0,0,0) 30%, rgba(0,0,0,0.7) 100%);
  z-index: 1;
}
.cat-card .inner {
  position: relative; z-index: 2;
  padding: 10px 12px 12px;
  width: 100%;
}
.cat-card .cat-title {
  display: block;
  font-size: 13px;
  font-weight: 900;
  color: var(--jd-yellow);
  letter-spacing: 0.06em;
  text-transform: uppercase;
  text-shadow: 0 1px 3px rgba(0,0,0,0.55);
}
.cat-card .cat-cta {
  display: block; margin-top: 2px;
  font-size: 11.5px; font-weight: 600;
  color: #fff;
  text-shadow: 0 1px 3px rgba(0,0,0,0.55);
}

/* ---------- Brands strip ---------- */
.brands-row {
  margin: 12px 0;
}
.brands-row-title {
  text-align: center;
  font-size: 13px;
  font-weight: 800;
  letter-spacing: 0.16em;
  text-transform: uppercase;
  color: var(--text-strong);
  margin: 18px 0 12px;
}
.brands-tiles {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 8px;
}
.brand-tile {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  aspect-ratio: 16/8;
  display: flex; align-items: center; justify-content: center;
  text-decoration: none;
  color: var(--text-strong);
  padding: 8px;
  text-align: center;
}
.brand-tile:hover { border-color: var(--accent); text-decoration: none; }
.brand-tile-name {
  font-weight: 900;
  font-size: 13px;
  letter-spacing: 0.06em;
  text-transform: uppercase;
}
.brand-tile-name .jd { color: var(--primary); }
.brand-tile-name .stihl { color: #f76707; }
.brand-tile-name .ventrac { color: var(--jd-yellow); }
.brand-tile-name .honda { color: var(--brand-red); }
.brand-tile-name .frontier { color: var(--text-strong); font-size: 11.5px; }
.brand-tile-name .other { color: var(--text-muted); font-size: 11.5px; }
.brand-tile-sub { display: block; font-size: 9.5px; font-weight: 600; color: var(--text-muted); margin-top: 2px; letter-spacing: 0.04em; }

/* ---------- Buttons ---------- */
.btn {
  display: inline-flex;
  align-items: center; justify-content: center;
  gap: 6px;
  padding: 12px 18px;
  border-radius: 10px;
  font-weight: 800;
  font-size: 14px;
  text-decoration: none;
  border: 1px solid transparent;
  cursor: pointer;
  min-height: 44px;
  line-height: 1.2;
  transition: transform 0.12s ease, background 0.15s ease, box-shadow 0.15s ease;
  font-family: inherit;
  letter-spacing: 0.02em;
}
.btn:hover { text-decoration: none; transform: translateY(-1px); }
.btn:active { transform: translateY(0); }
.btn-primary {
  background: var(--jd-yellow);
  color: var(--ink-on-yellow);
  box-shadow: var(--shadow-glow);
}
.btn-primary:hover { background: var(--jd-yellow-bright); }
.btn-secondary { background: var(--surface-2); color: var(--text-strong); border-color: var(--border-strong); }
.btn-secondary:hover { background: var(--surface-3); }
.btn-ghost { background: transparent; color: var(--text-strong); border-color: var(--border-strong); }
.btn-ghost:hover { background: var(--surface); }
.btn-lg { padding: 14px 22px; font-size: 14px; min-height: 50px; }

/* ---------- Sections ---------- */
section { margin: clamp(20px, 4vw, 32px) 0; }
.section-head { margin-bottom: 14px; }
.section-head h2 { margin: 0 0 4px; font-size: clamp(18px, 4.4vw, 22px); color: var(--text-strong); font-weight: 800; letter-spacing: -0.01em; }
.section-head .muted { color: var(--text-muted); margin: 0; font-size: 13.5px; }
.section-head .muted a { color: var(--accent); font-weight: 700; }
.muted { color: var(--text-muted); }

/* ---------- Locations strip ---------- */
.locations-strip {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(150px, 1fr));
  gap: 10px;
}
.loc-pill {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  padding: 12px 14px;
  font-size: 13px;
  min-width: 0;
  transition: border-color 0.15s ease, transform 0.15s ease;
  text-decoration: none;
  color: var(--text);
  display: block;
}
.loc-pill:hover { border-color: var(--accent); transform: translateY(-1px); text-decoration: none; }
.loc-pill strong { display: block; color: var(--text-strong); font-weight: 800; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.loc-pill small { color: var(--accent); display: block; margin-top: 2px; font-weight: 700; }

/* ---------- Card grid ---------- */
.card-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(150px, 1fr));
  gap: clamp(10px, 2.4vw, 14px);
}
@media (min-width: 600px) {
  .card-grid { grid-template-columns: repeat(auto-fill, minmax(190px, 1fr)); }
}
.card {
  position: relative;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  overflow: hidden;
  text-decoration: none;
  color: var(--text);
  display: flex; flex-direction: column;
  transition: border-color 0.18s ease, transform 0.18s ease, box-shadow 0.18s ease;
  min-width: 0;
}
.card:hover, .card:focus-visible {
  transform: translateY(-3px);
  border-color: var(--accent);
  box-shadow: var(--shadow-lg);
  text-decoration: none;
  outline: none;
}
.card-img {
  width: 100%; aspect-ratio: 4/3;
  background: var(--card-empty-1);
  overflow: hidden;
  display: flex; align-items: center; justify-content: center;
  position: relative;
}
.card-img img { width: 100%; height: 100%; object-fit: cover; transition: transform 0.4s ease; }
.card:hover .card-img img { transform: scale(1.04); }
.card-img-empty {
  background: linear-gradient(135deg, var(--card-empty-1) 0%, var(--card-empty-2) 100%);
  color: var(--accent);
}
.card-img-fallback {
  font-size: 12px; font-weight: 800; letter-spacing: 0.06em;
  text-transform: uppercase; text-align: center;
  padding: 0 10px; color: var(--accent);
}
.card-body { padding: 12px 14px 14px; min-width: 0; }
.card-brand { font-size: 10.5px; color: var(--accent); text-transform: uppercase; letter-spacing: 0.08em; font-weight: 800; }
.card-title { font-weight: 700; font-size: 14px; margin-top: 4px; line-height: 1.3; color: var(--text-strong); }
.card-meta { color: var(--text-muted); font-size: 12.5px; margin-top: 4px; }

/* Brand cards: square-ish with overlay gradient */
.brand-card .card-img { aspect-ratio: 1/1; }
.brand-card .card-img::after {
  content: "";
  position: absolute; inset: 0;
  background: linear-gradient(180deg, transparent 45%, rgba(0,0,0,0.65) 100%);
  pointer-events: none;
}

/* ---------- Info links ---------- */
.info-links { display: grid; grid-template-columns: repeat(auto-fill, minmax(200px, 1fr)); gap: 10px; }
.info-link {
  display: flex; align-items: center; gap: 10px;
  padding: 14px 16px;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  font-weight: 600;
  font-size: 14px;
  color: var(--text-strong);
  text-decoration: none;
  overflow-wrap: anywhere;
  transition: border-color 0.15s ease, background 0.15s ease, transform 0.15s ease;
}
.info-link::after {
  content: "›";
  margin-left: auto;
  color: var(--accent);
  font-size: 20px;
  line-height: 1;
}
.info-link:hover {
  background: var(--surface-2);
  border-color: var(--accent);
  text-decoration: none;
  transform: translateX(2px);
}

/* ---------- Product detail ---------- */
.product-page, .listing-page, .info-page {
  max-width: 1100px; margin: 0 auto;
  padding: 20px clamp(12px, 3vw, 20px) 32px;
}
.back {
  display: inline-flex; align-items: center; gap: 6px;
  color: var(--text-muted); margin: 0 0 16px -12px;
  font-size: 14px; font-weight: 500;
  padding: 8px 12px; border-radius: 8px;
}
.back:hover { background: var(--surface); color: var(--text-strong); text-decoration: none; }
.product-grid { display: grid; grid-template-columns: 1fr; gap: 24px; }
@media (min-width: 768px) { .product-grid { grid-template-columns: minmax(0,1.2fr) minmax(0,1fr); gap: 32px; } }
.product-hero {
  width: 100%; aspect-ratio: 4/3;
  background: var(--card-empty-1);
  border-radius: var(--radius-lg);
  overflow: hidden;
  position: relative;
  border: 1px solid var(--border);
}
.product-hero img { width: 100%; height: 100%; object-fit: cover; }
.product-hero-empty {
  background: linear-gradient(135deg, var(--card-empty-1) 0%, var(--card-empty-2) 100%);
  display: flex; align-items: center; justify-content: center;
}
.hero-fallback {
  color: var(--accent);
  font-weight: 800;
  font-size: clamp(15px, 3.4vw, 20px);
  text-align: center; padding: 0 16px;
  letter-spacing: 0.04em;
}
.thumb-row { display: flex; gap: 10px; margin-top: 12px; flex-wrap: wrap; }
.thumb {
  width: 78px; height: 60px;
  border: 1px solid var(--border); border-radius: 10px;
  background: var(--surface); padding: 0; cursor: pointer; overflow: hidden;
  flex: 0 0 auto;
  transition: border-color 0.15s ease, transform 0.15s ease;
}
.thumb img { width: 100%; height: 100%; object-fit: cover; }
.thumb:hover, .thumb:focus-visible { border-color: var(--accent); outline: none; transform: translateY(-2px); }
.product-info { min-width: 0; }
.product-info .product-brand { font-size: 11.5px; color: var(--accent); text-transform: uppercase; letter-spacing: 0.08em; font-weight: 800; }
.product-info h1 { margin: 6px 0 18px; font-size: clamp(22px, 5vw, 32px); color: var(--text-strong); font-weight: 800; line-height: 1.15; letter-spacing: -0.015em; }
.product-cta { display: flex; gap: 10px; flex-wrap: wrap; margin-bottom: 22px; }
.product-body { min-width: 0; }
.product-body p {
  margin: 0 0 12px;
  font-size: 14.5px;
  color: var(--text);
  line-height: 1.65;
  overflow-wrap: anywhere;
  word-break: break-word;
}
.source-link {
  margin-top: 22px; font-size: 13px; color: var(--text-muted);
  overflow-wrap: anywhere; padding-top: 16px; border-top: 1px solid var(--border);
}

/* ---------- Info page ---------- */
.info-page article {
  background: var(--surface); border: 1px solid var(--border);
  border-radius: var(--radius-lg); padding: clamp(18px, 4vw, 28px);
  min-width: 0;
}
.info-page h1 { margin-top: 0; color: var(--text-strong); font-size: clamp(22px, 5vw, 30px); font-weight: 800; letter-spacing: -0.015em; }
.info-body { overflow-wrap: anywhere; word-break: break-word; }
.info-body p { margin: 0 0 12px; line-height: 1.65; color: var(--text); }
.info-images {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(130px,1fr));
  gap: 10px; margin: 16px 0;
}
.info-img { width: 100%; height: 130px; object-fit: cover; border-radius: 12px; border: 1px solid var(--border); }
@media (min-width: 600px) {
  .info-images { grid-template-columns: repeat(auto-fill, minmax(170px,1fr)); }
  .info-img { height: 150px; }
}

/* ---------- Schedule Service form ---------- */
.schedule-page .small-print { font-size: 12.5px; margin-top: 18px; }
.schedule-page form { margin-top: 12px; display: flex; flex-direction: column; gap: 18px; }
.schedule-page fieldset {
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 14px 16px 16px;
  background: var(--surface-2);
  margin: 0;
  min-width: 0;
}
.schedule-page .form-legend {
  font-size: 12px; font-weight: 800;
  letter-spacing: 0.08em; text-transform: uppercase;
  color: var(--accent); padding: 0 4px;
}
.schedule-page .form-row { display: flex; flex-direction: column; gap: 6px; margin-bottom: 12px; }
.schedule-page .form-row:last-child { margin-bottom: 0; }
.schedule-page .form-label { font-size: 12.5px; font-weight: 700; color: var(--text-muted); text-transform: uppercase; letter-spacing: 0.04em; }
.schedule-page input[type="text"],
.schedule-page input[type="tel"],
.schedule-page input[type="email"],
.schedule-page textarea {
  background: var(--bg);
  color: var(--text-strong);
  border: 1px solid var(--border-strong);
  border-radius: var(--radius-sm);
  padding: 12px 14px;
  font-size: 15px; font-family: inherit;
  width: 100%; min-width: 0; box-sizing: border-box;
  transition: border-color 0.15s ease, box-shadow 0.15s ease;
}
.schedule-page textarea { resize: vertical; min-height: 100px; }
.schedule-page input:focus,
.schedule-page textarea:focus {
  outline: none;
  border-color: var(--accent);
  box-shadow: 0 0 0 3px rgba(54, 124, 43, 0.18);
}
.schedule-page .form-grid-2 { display: grid; grid-template-columns: 1fr; gap: 12px; }
@media (min-width: 520px) { .schedule-page .form-grid-2 { grid-template-columns: 1fr 1fr; } }
.schedule-page .form-radio-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 8px;
  margin-top: 4px;
}
@media (min-width: 640px) { .schedule-page .form-radio-grid { grid-template-columns: 1fr 1fr 1fr; } }
.schedule-page .form-radio {
  display: flex; align-items: center; gap: 8px;
  background: var(--bg);
  border: 1px solid var(--border-strong);
  border-radius: var(--radius-sm);
  padding: 10px 12px;
  cursor: pointer;
  font-size: 13.5px; font-weight: 600;
  color: var(--text);
  transition: border-color 0.15s ease, background 0.15s ease;
  min-width: 0;
}
.schedule-page .form-radio:hover { border-color: var(--accent); }
.schedule-page .form-radio input { accent-color: var(--accent); flex: 0 0 auto; }
.schedule-page .form-radio span { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.schedule-page .form-radio:has(input:checked) {
  border-color: var(--accent);
  background: rgba(54, 124, 43, 0.10);
  color: var(--text-strong);
}
[data-theme="dark"] .schedule-page .form-radio:has(input:checked) {
  background: rgba(255, 222, 0, 0.10);
}
.schedule-page .form-actions { display: flex; align-items: center; gap: 14px; flex-wrap: wrap; margin-top: 4px; }
.schedule-page .form-status { font-size: 13.5px; color: var(--text-muted); }
.schedule-page .form-status.ok { color: var(--accent); font-weight: 700; }
.schedule-page .form-status.err { color: var(--brand-red); font-weight: 700; }

/* ---------- Listing page ---------- */
.listing-page h1 { color: var(--text-strong); margin: 8px 0 6px; font-size: clamp(24px, 5.4vw, 34px); font-weight: 800; letter-spacing: -0.02em; }
.listing-meta { color: var(--text-muted); margin: 0 0 20px; font-size: 14px; }
.listing-meta a { color: var(--accent); font-weight: 700; }
.brand-section { margin: 36px 0; }
.brand-section h2 {
  color: var(--text-strong); margin: 0 0 14px;
  font-size: clamp(20px, 4.4vw, 24px);
  font-weight: 800;
  display: flex; align-items: baseline; gap: 10px;
}
.brand-section h2 .muted { font-weight: 500; font-size: 0.7em; }

/* ---------- Bottom nav (5 tabs, yellow active on dark / green active on light) ---------- */
.nav-bottom {
  position: fixed; left: 0; right: 0; bottom: 0;
  z-index: 90;
  display: flex;
  background: var(--nav-bg);
  backdrop-filter: saturate(180%) blur(24px);
  -webkit-backdrop-filter: saturate(180%) blur(24px);
  border-top: 1px solid var(--nav-border);
  padding: 4px 0 calc(4px + env(safe-area-inset-bottom));
}
.nav-bottom a, .nav-bottom button {
  flex: 1;
  display: flex; flex-direction: column;
  align-items: center; justify-content: center;
  gap: 3px;
  padding: 6px 2px;
  background: transparent; border: none;
  color: var(--nav-fg);
  font-family: inherit; font-size: 11px; font-weight: 600;
  cursor: pointer; text-decoration: none; text-align: center;
  min-height: 52px;
  border-radius: 12px;
  transition: color 0.15s ease;
}
.nav-bottom a:hover, .nav-bottom button:hover { color: var(--text-strong); text-decoration: none; }
.nav-bottom a.active, .nav-bottom button.active { color: var(--nav-fg-active); }
.nav-bottom .nav-icon {
  width: 24px; height: 24px;
  display: flex; align-items: center; justify-content: center;
  line-height: 1;
}
.nav-bottom .nav-icon svg { display: block; width: 22px; height: 22px; }

/* ---------- Footer ---------- */
.site-footer {
  background: var(--bg-elev);
  color: var(--text-muted);
  padding: 28px clamp(16px, 4vw, 24px) 20px;
  margin-top: 28px;
  border-top: 1px solid var(--border);
}
.footer-cols { max-width: 1100px; margin: 0 auto; display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 24px; }
.footer-cols h4 { color: var(--text-strong); margin: 0 0 12px; font-size: 13px; text-transform: uppercase; letter-spacing: 0.08em; font-weight: 800; }
.footer-cols ul { list-style: none; padding: 0; margin: 0; }
.footer-cols ul li { margin: 6px 0; font-size: 13.5px; line-height: 1.5; color: var(--text-muted); overflow-wrap: anywhere; }
.footer-cols a { color: var(--text); }
.footer-cols a:hover { color: var(--accent); }
.footer-cols .loc-list li { margin-bottom: 12px; }
.footer-cols .loc-list strong { color: var(--text-strong); font-weight: 800; }
.footer-bottom { max-width: 1100px; margin: 22px auto 0; padding-top: 16px; border-top: 1px solid var(--border); font-size: 12px; color: var(--text-dim); }

/* ---------- Chat launcher: sit above the bottom nav ---------- */
.mt-launcher {
  bottom: calc(var(--nav-h) + 14px + env(safe-area-inset-bottom)) !important;
}

/* ---------- Very small screens ---------- */
@media (max-width: 380px) {
  .brand-text small { display: none; }
  .icon-btn, .theme-toggle { width: 34px; height: 34px; }
  .chat-btn { padding: 8px 10px; font-size: 12px; }
  .card-grid { grid-template-columns: repeat(auto-fill, minmax(140px, 1fr)); gap: 10px; }
  .nav-bottom a, .nav-bottom button { font-size: 10px; }
  .nav-bottom .nav-icon svg { width: 20px; height: 20px; }
}

/* ---------- Reduce motion ---------- */
@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after {
    animation-duration: 0.01ms !important;
    transition-duration: 0.01ms !important;
  }
}
"""


THEME_JS = """(function(){
  'use strict';
  var html = document.documentElement;
  var META_LIGHT = '#ffffff';
  var META_DARK  = '#0a0e0c';

  function applyMetaThemeColor(theme){
    // Replace the dual media-scoped meta tags with a single explicit tag so
    // Android picks up the manually-toggled choice instead of the system one.
    var head = document.head;
    head.querySelectorAll('meta[name="theme-color"]').forEach(function(m){ m.remove(); });
    var m = document.createElement('meta');
    m.setAttribute('name', 'theme-color');
    m.setAttribute('content', theme === 'dark' ? META_DARK : META_LIGHT);
    head.appendChild(m);
  }

  function setTheme(theme){
    html.setAttribute('data-theme', theme);
    try { localStorage.setItem('mt-theme', theme); } catch(e) {}
    applyMetaThemeColor(theme);
  }

  // Sync meta-color on initial load (the pre-paint script set data-theme).
  applyMetaThemeColor(html.getAttribute('data-theme') || 'light');

  // Wire up every theme toggle on the page.
  document.addEventListener('click', function(e){
    var btn = e.target.closest('.theme-toggle');
    if (!btn) return;
    var current = html.getAttribute('data-theme') || 'light';
    setTheme(current === 'dark' ? 'light' : 'dark');
  });
})();
"""


# ---------- Main ----------

def main() -> int:
    pages_path = BUNDLE / "pages.json"
    image_map_path = BUNDLE / "image_map.json"
    if not pages_path.exists():
        print(f"missing {pages_path}", file=sys.stderr)
        return 1

    pages = json.loads(pages_path.read_text(encoding="utf-8"))
    image_map = json.loads(image_map_path.read_text(encoding="utf-8")) if image_map_path.exists() else {}

    # Wire the real JD/MTS marks into the topbar if we've scraped them.
    JD_URL = "https://www.middletowntractor.com/images/middletowntractor-deer.png"
    MTS_URL = "https://www.middletowntractor.com/images/middletowntractor-logo.png"
    if JD_URL in image_map:  TOPBAR_LOGOS["jd"] = image_map[JD_URL]
    if MTS_URL in image_map: TOPBAR_LOGOS["mts"] = image_map[MTS_URL]

    # Wipe + recreate output dirs
    if PAGES_DIR.exists():
        shutil.rmtree(PAGES_DIR)
    PAGES_DIR.mkdir(parents=True, exist_ok=True)
    ASSETS_DIR.mkdir(parents=True, exist_ok=True)

    # Classify
    classified: dict[str, list[dict]] = defaultdict(list)
    for p in pages:
        classified[page_kind(p)].append(p)

    products = classified["product"]
    categories = classified["category"]
    info_pages = classified["info"] + classified["reviews"] + classified["location"]

    # Group products by brand; uncategorized go to "Other"
    # Strip generic "Inventory Showroom" pages — they all share the same
    # category stock photo and clutter every grid they appear in.
    products = [p for p in products if not is_generic_showroom(p)]

    brand_groups: dict[str, list[dict]] = defaultdict(list)
    for p in products:
        b = brand_of(p) or "Other Inventory"
        brand_groups[b].append(p)

    # Build brand cards (name, count, thumbnail)
    brand_cards_data: list[tuple[str, int, str | None]] = []
    for brand, prods in sorted(brand_groups.items(), key=lambda kv: -len(kv[1])):
        thumb = None
        for prod in prods:
            t = page_thumb(prod, image_map)
            if t:
                thumb = t
                break
        brand_cards_data.append((brand, len(prods), thumb))

    # Featured: 12 random-ish products with images, prefer diverse brands
    featured: list[dict] = []
    by_brand_seen: dict[str, int] = defaultdict(int)
    seen_thumbs: set[str] = set()
    for p in products:
        if is_generic_showroom(p):
            continue
        thumb = page_thumb(p, image_map)
        if not thumb or thumb in seen_thumbs:
            continue
        b = brand_of(p) or "Other"
        if by_brand_seen[b] >= 3:
            continue
        featured.append(p)
        seen_thumbs.add(thumb)
        by_brand_seen[b] += 1
        if len(featured) >= 12:
            break

    # Render per-product detail pages
    for p in products:
        (PAGES_DIR / slug_for(p["url"])).write_text(
            render_product_page(p, image_map), encoding="utf-8"
        )

    # Render per-brand listing pages (show every product, photo'd ones first)
    for brand, prods in brand_groups.items():
        ordered = sorted(prods, key=lambda p: 0 if page_thumb(p, image_map) else 1)
        (PAGES_DIR / brand_slug(brand)).write_text(
            render_brand_listing(brand, ordered, image_map), encoding="utf-8"
        )

    # Render the catch-all "All Inventory" page so every product is reachable
    (PAGES_DIR / "all-inventory.html").write_text(
        render_all_inventory(
            {brand: sorted(prods, key=lambda p: 0 if page_thumb(p, image_map) else 1)
             for brand, prods in brand_groups.items()},
            image_map,
        ),
        encoding="utf-8",
    )

    # Schedule-service form page
    (PAGES_DIR / "schedule-service.html").write_text(
        render_schedule_page(), encoding="utf-8",
    )

    # Render info / category / location / reviews pages
    for p in info_pages + categories:
        (PAGES_DIR / slug_for(p["url"])).write_text(
            render_info_page(p, image_map), encoding="utf-8"
        )

    # Render index
    (BUNDLE / "index.html").write_text(
        render_index(featured, brand_cards_data, info_pages, image_map),
        encoding="utf-8",
    )

    # Assets
    widget_src = ROOT / "widget"
    shutil.copy(widget_src / "widget.css", ASSETS_DIR / "widget.css")
    shutil.copy(widget_src / "widget.js", ASSETS_DIR / "widget.js")
    (ASSETS_DIR / "site.css").write_text(SITE_CSS, encoding="utf-8")
    (ASSETS_DIR / "theme.js").write_text(THEME_JS, encoding="utf-8")

    # ---- URL map: remote URL -> in-app relative path ----
    # Every scraped page we render locally is reachable; the widget uses this
    # to translate source links so they navigate to the bundled copy.
    url_map: dict[str, str] = {}
    for p in pages:
        if is_generic_showroom(p):
            continue
        kind = page_kind(p)
        if kind in ("product", "category", "info", "location", "reviews"):
            url_map[p["url"]] = f"pages/{slug_for(p['url'])}"
    # Hand-curated mappings for canned-answer URLs that aren't direct page hits.
    extra_map = {
        "https://www.middletowntractor.com/inventory/v1/Current": "pages/all-inventory.html",
        "https://www.middletowntractor.com/inventory/v1/Current/John-Deere": "pages/brand-john-deere.html",
        "https://www.middletowntractor.com/inventory/v1/Current/John-Deere/Tractor": "pages/brand-john-deere.html",
    }
    url_map.update(extra_map)
    (ASSETS_DIR / "url_map.json").write_text(
        json.dumps(url_map, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    # ---- Canned answers enriched with app_path + brand navigation cards ----
    canned = json.loads((ROOT / "backend" / "canned.json").read_text(encoding="utf-8"))

    # Pick one thumb per brand for nav cards
    brand_thumb: dict[str, str | None] = {}
    for brand, prods in brand_groups.items():
        thumb = None
        for prod in prods:
            t = page_thumb(prod, image_map)
            if t:
                thumb = t
                break
        brand_thumb[brand] = thumb

    def card(title: str, sub: str, app_path: str, image: str | None) -> dict:
        c = {"title": title, "sub": sub, "app_path": app_path}
        if image:
            c["image"] = image
        return c

    nav_cards_by_question = {
        "What brands do you carry besides John Deere?": [
            card(b, f"{c} item{'s' if c != 1 else ''}", f"pages/{brand_slug(b)}", brand_thumb.get(b))
            for b, c in sorted(
                ((b, len(p)) for b, p in brand_groups.items() if b != "John Deere"),
                key=lambda kv: -kv[1],
            )[:6]
        ],
        "What John Deere tractors do you sell?": [
            card("John Deere",
                 f"{len(brand_groups.get('John Deere', []))} units in stock",
                 "pages/brand-john-deere.html",
                 brand_thumb.get("John Deere")),
            card("All inventory", "Browse every brand", "pages/all-inventory.html", None),
        ],
        "Do you sell used equipment?": [
            card("All inventory", "Browse current stock", "pages/all-inventory.html", None),
        ],
        "How do I get a quote?": [
            card("All inventory", "Pick a unit first", "pages/all-inventory.html", None),
        ],
    }

    for entry in canned:
        # Translate every source to an in-app path where possible
        for s in entry.get("sources", []):
            ap = url_map.get(s.get("url", ""))
            if ap:
                s["app_path"] = ap
        # Attach nav cards if we curated some
        cards = nav_cards_by_question.get(entry["question"])
        if cards:
            entry["cards"] = cards

    (ASSETS_DIR / "canned.json").write_text(
        json.dumps(canned, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    # Re-copy icons if they exist
    for sz in (192, 512, 1024):
        src = ASSETS_DIR / f"icon-{sz}.png"
        if not src.exists():
            print(f"warn: missing {src}, run make_icons.py", file=sys.stderr)

    # PWA manifest
    manifest = {
        "name": "Middletown Tractor Sales",
        "short_name": "MTS",
        "start_url": "./index.html",
        "display": "standalone",
        "background_color": "#0a0e0c",
        "theme_color": "#0a0e0c",
        "icons": [
            {"src": "assets/icon-192.png", "sizes": "192x192", "type": "image/png"},
            {"src": "assets/icon-512.png", "sizes": "512x512", "type": "image/png"},
        ],
    }
    (BUNDLE / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    print(f"Wrote index.html")
    print(f"  Featured products: {len(featured)}")
    print(f"  Brand listings:    {len(brand_cards_data)} ({sum(c for _, c, _ in brand_cards_data)} products total)")
    print(f"  Info pages:        {len(info_pages)}")
    print(f"  Category pages:    {len(categories)}")
    print(f"  Total HTML files in pages/: {len(list(PAGES_DIR.glob('*.html')))}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
