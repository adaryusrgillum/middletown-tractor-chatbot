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
  <link rel="stylesheet" href="{prefix}assets/site.css">
  <link rel="stylesheet" href="{prefix}assets/widget.css">
  <link rel="manifest" href="{prefix}manifest.json">
  <meta name="theme-color" content="#0a0e0c">
  <meta name="color-scheme" content="dark">
  <link rel="icon" href="{prefix}assets/icon-192.png" type="image/png">
</head>"""


def topbar(depth: int) -> str:
    prefix = "../" if depth else ""
    return f"""<header class="topbar">
  <a class="brand" href="{prefix}index.html" aria-label="Middletown Tractor Sales home">
    <span class="brand-mark" aria-hidden="true">MT</span>
    <span class="brand-text">
      <strong>Middletown Tractor</strong>
      <small>John Deere &middot; STIHL &middot; Honda &middot; Ventrac</small>
    </span>
  </a>
  <nav class="topnav">
    <button class="chat-btn" type="button" onclick="document.querySelector('.mt-launcher')?.click();return false;" aria-label="Open chatbot">Ask</button>
  </nav>
</header>"""


def bottom_nav(depth: int, active: str = "home") -> str:
    """`active` ∈ {'home', 'inventory', 'locations', 'chat'}."""
    prefix = "../" if depth else ""
    def cls(name: str) -> str:
        return ' class="active"' if active == name else ""
    return f"""<nav class="nav-bottom" aria-label="Primary">
  <a href="{prefix}index.html"{cls("home")}>
    <span class="nav-icon" aria-hidden="true">⌂</span>
    <span>Home</span>
  </a>
  <a href="{prefix}pages/all-inventory.html"{cls("inventory")}>
    <span class="nav-icon" aria-hidden="true">▦</span>
    <span>Inventory</span>
  </a>
  <a href="{prefix}index.html#locations"{cls("locations")}>
    <span class="nav-icon" aria-hidden="true">◉</span>
    <span>Locations</span>
  </a>
  <button type="button" onclick="document.querySelector('.mt-launcher')?.click();return false;" aria-label="Open chatbot">
    <span class="nav-icon" aria-hidden="true">✦</span>
    <span>Chat</span>
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

    return f"""{head("Middletown Tractor Sales - WV & PA", depth=0)}
<body>
{topbar(depth=0)}

<section class="hero">
  <div class="hero-inner">
    <span class="hero-badge">Serving WV &amp; PA since 1955</span>
    <h1>Equipment for the way <span class="accent">you work.</span></h1>
    <p class="lede">John Deere &middot; STIHL &middot; Honda Power &middot; Ventrac. Four locations across West Virginia and Pennsylvania.</p>
    <div class="hero-cta">
      <a class="btn btn-primary btn-lg" href="#brands">Browse inventory</a>
      <a class="btn btn-ghost btn-lg" href="#" onclick="document.querySelector('.mt-launcher')?.click();return false;">Ask the chatbot</a>
    </div>
  </div>
</section>

<main class="home">

  <section class="locations-section" id="locations">
    <div class="section-head">
      <h2>Our locations</h2>
      <p class="muted">Tap a location to call. Same crew, same quality across all four stores.</p>
    </div>
    <div class="locations-strip">{loc_summary}</div>
  </section>

  <section class="brands" id="brands">
    <div class="section-head">
      <h2>Browse by brand</h2>
      <p class="muted">Pick a brand to see every unit we carry.</p>
    </div>
    <div class="card-grid">{brand_html}</div>
  </section>

  <section class="featured">
    <div class="section-head">
      <h2>Featured inventory</h2>
      <p class="muted">A taste of what we have. <a href="pages/all-inventory.html">See all units &rarr;</a></p>
    </div>
    <div class="card-grid">{featured_html}</div>
  </section>

  <section class="info">
    <div class="section-head">
      <h2>Service, parts &amp; about us</h2>
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
  /* Dark palette - One UI 7 inspired */
  --bg: #0a0e0c;
  --bg-elev: #11171a;
  --surface: #161e1c;
  --surface-2: #1f2a26;
  --surface-3: #2a3833;

  --primary: #52c168;
  --primary-dark: #2f7a3a;
  --primary-glow: rgba(82, 193, 104, 0.28);
  --accent: #f5c84f;

  --text: #ecf2ee;
  --text-strong: #ffffff;
  --text-muted: #8b988f;
  --text-dim: #6b7670;

  --border: rgba(255, 255, 255, 0.06);
  --border-strong: rgba(255, 255, 255, 0.14);

  --shadow: 0 4px 16px rgba(0, 0, 0, 0.5);
  --shadow-lg: 0 12px 32px rgba(0, 0, 0, 0.6);
  --shadow-glow: 0 4px 20px var(--primary-glow);

  --radius-sm: 10px;
  --radius: 16px;
  --radius-lg: 22px;

  --topbar-h: 56px;
  --nav-h: 64px;
}

* { box-sizing: border-box; min-width: 0; }

html {
  background: var(--bg);
  color-scheme: dark;
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
  background:
    radial-gradient(1200px 600px at 50% -240px, rgba(82, 193, 104, 0.08), transparent 70%),
    radial-gradient(800px 400px at 100% 200px, rgba(82, 193, 104, 0.04), transparent 60%),
    var(--bg);
  background-attachment: fixed;
  line-height: 1.5;
  font-size: 15px;
  -webkit-text-size-adjust: 100%;
  -webkit-font-smoothing: antialiased;
  padding-bottom: calc(var(--nav-h) + env(safe-area-inset-bottom));
}

a { color: var(--primary); text-decoration: none; }
a:hover { text-decoration: underline; }
img { max-width: 100%; height: auto; display: block; }
h1, h2, h3, h4 { color: var(--text-strong); overflow-wrap: anywhere; letter-spacing: -0.01em; }
p, li, .card-title, .card-meta, .card-brand { overflow-wrap: anywhere; word-wrap: break-word; }

/* ---------- Topbar ---------- */
.topbar {
  position: sticky; top: 0; z-index: 100;
  background: rgba(10, 14, 12, 0.72);
  backdrop-filter: saturate(180%) blur(20px);
  -webkit-backdrop-filter: saturate(180%) blur(20px);
  border-bottom: 1px solid var(--border);
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: max(10px, env(safe-area-inset-top)) 16px 10px;
  min-height: var(--topbar-h);
}
.brand { display: flex; align-items: center; gap: 12px; color: var(--text-strong); min-width: 0; flex: 1 1 auto; }
.brand-mark {
  flex: 0 0 auto;
  width: 38px; height: 38px;
  background: linear-gradient(135deg, var(--primary) 0%, var(--primary-dark) 100%);
  color: #061008;
  border-radius: 12px;
  display: flex; align-items: center; justify-content: center;
  font-weight: 900; font-size: 13px;
  letter-spacing: 0.04em;
  box-shadow: var(--shadow-glow);
}
.brand-text { min-width: 0; }
.brand-text strong { display: block; line-height: 1.15; font-size: 15px; font-weight: 700; color: var(--text-strong); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.brand-text small { display: block; color: var(--text-muted); font-size: 11px; font-weight: 500; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.topnav { display: flex; gap: 6px; flex-shrink: 0; align-items: center; }
.topnav a, .topnav button {
  display: inline-flex; align-items: center; justify-content: center;
  font-size: 14px; font-weight: 600; color: var(--text);
  background: transparent; border: none;
  padding: 9px 14px; border-radius: 10px;
  cursor: pointer; font-family: inherit;
}
.topnav a:hover, .topnav button:hover { background: var(--surface); text-decoration: none; color: var(--text-strong); }
.topnav .chat-btn {
  background: linear-gradient(135deg, var(--primary) 0%, #45a356 100%);
  color: #061008; font-weight: 800;
  box-shadow: var(--shadow-glow);
}
.topnav .chat-btn:hover { filter: brightness(1.08); background: linear-gradient(135deg, var(--primary) 0%, #45a356 100%); }

/* ---------- Hero ---------- */
.hero {
  position: relative;
  overflow: hidden;
  padding: clamp(36px, 9vw, 64px) clamp(16px, 4vw, 24px) clamp(32px, 8vw, 52px);
  background:
    radial-gradient(ellipse 80% 60% at 50% 0%, rgba(82, 193, 104, 0.18), transparent 60%),
    linear-gradient(180deg, var(--bg-elev) 0%, var(--bg) 100%);
  border-bottom: 1px solid var(--border);
}
.hero::before {
  content: "";
  position: absolute; inset: 0;
  background-image:
    radial-gradient(circle at 20% 30%, rgba(82, 193, 104, 0.08) 0, transparent 40%),
    radial-gradient(circle at 80% 70%, rgba(245, 200, 79, 0.05) 0, transparent 35%);
  pointer-events: none;
}
.hero-inner { position: relative; max-width: 1000px; margin: 0 auto; z-index: 1; }
.hero-badge {
  display: inline-block;
  font-size: 11.5px; font-weight: 700;
  letter-spacing: 0.08em; text-transform: uppercase;
  color: var(--primary);
  background: rgba(82, 193, 104, 0.1);
  border: 1px solid rgba(82, 193, 104, 0.25);
  padding: 6px 12px; border-radius: 999px;
  margin-bottom: 16px;
}
.hero h1 {
  font-size: clamp(28px, 7.5vw, 46px);
  margin: 0 0 14px;
  color: var(--text-strong);
  line-height: 1.04;
  font-weight: 800;
  letter-spacing: -0.025em;
  overflow-wrap: anywhere;
}
.hero h1 .accent {
  background: linear-gradient(120deg, var(--primary) 0%, var(--accent) 100%);
  -webkit-background-clip: text; background-clip: text;
  -webkit-text-fill-color: transparent;
}
.hero .lede { font-size: clamp(15px, 3.6vw, 17px); color: var(--text-muted); margin: 0 0 24px; max-width: 540px; line-height: 1.55; }
.hero-cta { display: flex; gap: 10px; flex-wrap: wrap; margin-top: 4px; }

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
.loc-pill:hover { border-color: var(--primary); transform: translateY(-1px); text-decoration: none; }
.loc-pill strong { display: block; color: var(--text-strong); font-weight: 700; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.loc-pill small { color: var(--text-muted); display: block; margin-top: 2px; }

/* ---------- Buttons ---------- */
.btn {
  display: inline-flex;
  align-items: center; justify-content: center;
  gap: 6px;
  padding: 12px 18px;
  border-radius: 12px;
  font-weight: 700;
  font-size: 14px;
  text-decoration: none;
  border: 1px solid transparent;
  cursor: pointer;
  min-height: 44px;
  line-height: 1.2;
  transition: transform 0.12s ease, background 0.15s ease, box-shadow 0.15s ease;
  font-family: inherit;
}
.btn:hover { text-decoration: none; transform: translateY(-1px); }
.btn:active { transform: translateY(0); }
.btn-primary {
  background: linear-gradient(135deg, var(--primary) 0%, #45a356 100%);
  color: #061008;
  box-shadow: var(--shadow-glow);
}
.btn-primary:hover { box-shadow: 0 6px 24px var(--primary-glow), 0 2px 8px rgba(0,0,0,0.4); }
.btn-secondary { background: var(--surface-2); color: var(--text-strong); border-color: var(--border-strong); }
.btn-secondary:hover { background: var(--surface-3); }
.btn-ghost { background: rgba(255,255,255,0.04); color: var(--text-strong); border-color: var(--border-strong); }
.btn-ghost:hover { background: rgba(255,255,255,0.08); }
.btn-lg { padding: 14px 24px; font-size: 15px; min-height: 50px; }

/* ---------- Main / sections ---------- */
.home { max-width: 1100px; margin: 0 auto; padding: 0 clamp(12px, 3vw, 20px) 40px; }
section { margin: clamp(28px, 6vw, 44px) 0; }
.section-head { margin-bottom: 16px; }
.section-head h2 { margin: 0 0 4px; font-size: clamp(20px, 4.8vw, 26px); color: var(--text-strong); font-weight: 700; letter-spacing: -0.01em; }
.section-head .muted { color: var(--text-muted); margin: 0; font-size: 14px; }
.section-head .muted a { color: var(--primary); font-weight: 600; }
.muted { color: var(--text-muted); }

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
  border-color: rgba(82, 193, 104, 0.32);
  box-shadow: var(--shadow-lg);
  text-decoration: none;
  outline: none;
}
.card-img {
  width: 100%; aspect-ratio: 4/3;
  background: #1a2220;
  overflow: hidden;
  display: flex; align-items: center; justify-content: center;
  position: relative;
}
.card-img img { width: 100%; height: 100%; object-fit: cover; transition: transform 0.4s ease; }
.card:hover .card-img img { transform: scale(1.04); }
.card-img-empty {
  background: linear-gradient(135deg, #1c2723 0%, #0f1714 100%);
  color: var(--primary);
}
.card-img-fallback {
  font-size: 12px; font-weight: 800; letter-spacing: 0.06em;
  text-transform: uppercase; text-align: center;
  padding: 0 10px; color: var(--primary);
}
.card-body { padding: 12px 14px 14px; min-width: 0; }
.card-brand { font-size: 10.5px; color: var(--primary); text-transform: uppercase; letter-spacing: 0.08em; font-weight: 800; }
.card-title { font-weight: 700; font-size: 14px; margin-top: 4px; line-height: 1.3; color: var(--text-strong); }
.card-meta { color: var(--text-muted); font-size: 12.5px; margin-top: 4px; }

/* Brand cards: square-ish with overlay gradient */
.brand-card .card-img { aspect-ratio: 1/1; }
.brand-card .card-img::after {
  content: "";
  position: absolute; inset: 0;
  background: linear-gradient(180deg, transparent 45%, rgba(0,0,0,0.55) 100%);
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
  color: var(--primary);
  font-size: 20px;
  line-height: 1;
}
.info-link:hover {
  background: var(--surface-2);
  border-color: var(--primary);
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
  background: #1a2220;
  border-radius: var(--radius-lg);
  overflow: hidden;
  position: relative;
  border: 1px solid var(--border);
}
.product-hero img { width: 100%; height: 100%; object-fit: cover; }
.product-hero-empty {
  background: linear-gradient(135deg, #1c2723 0%, #0f1714 100%);
  display: flex; align-items: center; justify-content: center;
}
.hero-fallback {
  color: var(--primary);
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
.thumb:hover, .thumb:focus-visible { border-color: var(--primary); outline: none; transform: translateY(-2px); }
.product-info { min-width: 0; }
.product-info .product-brand { font-size: 11.5px; color: var(--primary); text-transform: uppercase; letter-spacing: 0.08em; font-weight: 800; }
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

/* ---------- Listing page ---------- */
.listing-page h1 { color: var(--text-strong); margin: 8px 0 6px; font-size: clamp(24px, 5.4vw, 34px); font-weight: 800; letter-spacing: -0.02em; }
.listing-meta { color: var(--text-muted); margin: 0 0 20px; font-size: 14px; }
.listing-meta a { color: var(--primary); font-weight: 600; }
.brand-section { margin: 36px 0; }
.brand-section h2 {
  color: var(--text-strong); margin: 0 0 14px;
  font-size: clamp(20px, 4.4vw, 24px);
  font-weight: 800;
  display: flex; align-items: baseline; gap: 10px;
}
.brand-section h2 .muted { font-weight: 500; font-size: 0.7em; }

/* ---------- Bottom nav ---------- */
.nav-bottom {
  position: fixed; left: 0; right: 0; bottom: 0;
  z-index: 90;
  display: flex;
  background: rgba(10, 14, 12, 0.88);
  backdrop-filter: saturate(180%) blur(24px);
  -webkit-backdrop-filter: saturate(180%) blur(24px);
  border-top: 1px solid var(--border);
  padding: 6px 4px calc(6px + env(safe-area-inset-bottom));
}
.nav-bottom a, .nav-bottom button {
  flex: 1;
  display: flex; flex-direction: column;
  align-items: center; justify-content: center;
  gap: 3px;
  padding: 6px 4px;
  background: transparent; border: none;
  color: var(--text-muted);
  font-family: inherit; font-size: 11px; font-weight: 600;
  cursor: pointer; text-decoration: none; text-align: center;
  min-height: 52px;
  border-radius: 12px;
  transition: color 0.15s ease, background 0.15s ease;
}
.nav-bottom a:hover, .nav-bottom button:hover { color: var(--text); text-decoration: none; }
.nav-bottom a.active, .nav-bottom button.active { color: var(--primary); }
.nav-bottom .nav-icon {
  width: 26px; height: 26px;
  display: flex; align-items: center; justify-content: center;
  font-size: 20px; line-height: 1;
}
.nav-bottom a.active .nav-icon,
.nav-bottom button.active .nav-icon {
  filter: drop-shadow(0 0 8px var(--primary-glow));
}

/* ---------- Footer ---------- */
.site-footer {
  background: var(--bg-elev);
  color: var(--text-muted);
  padding: 36px clamp(16px, 4vw, 24px) 24px;
  margin-top: 48px;
  border-top: 1px solid var(--border);
}
.footer-cols { max-width: 1100px; margin: 0 auto; display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 28px; }
.footer-cols h4 { color: var(--text-strong); margin: 0 0 12px; font-size: 13px; text-transform: uppercase; letter-spacing: 0.08em; font-weight: 700; }
.footer-cols ul { list-style: none; padding: 0; margin: 0; }
.footer-cols ul li { margin: 8px 0; font-size: 14px; line-height: 1.55; color: var(--text-muted); overflow-wrap: anywhere; }
.footer-cols a { color: var(--text); }
.footer-cols a:hover { color: var(--primary); }
.footer-cols .loc-list li { margin-bottom: 14px; }
.footer-cols .loc-list strong { color: var(--text-strong); font-weight: 700; }
.footer-bottom { max-width: 1100px; margin: 28px auto 0; padding-top: 18px; border-top: 1px solid var(--border); font-size: 12px; color: var(--text-dim); }

/* ---------- Chat launcher: sit above the bottom nav ---------- */
.mt-launcher {
  bottom: calc(var(--nav-h) + 14px + env(safe-area-inset-bottom)) !important;
}

/* ---------- Very small screens ---------- */
@media (max-width: 380px) {
  .brand-text small { display: none; }
  .topnav a, .topnav button { padding: 8px 11px; font-size: 13px; }
  .card-grid { grid-template-columns: repeat(auto-fill, minmax(140px, 1fr)); gap: 10px; }
  .nav-bottom a, .nav-bottom button { font-size: 10px; }
  .nav-bottom .nav-icon { width: 22px; height: 22px; font-size: 18px; }
  .hero { padding-left: 16px; padding-right: 16px; }
}

/* ---------- Tall narrow phones (S25 Ultra: ~19.5:9) ---------- */
@media (min-aspect-ratio: 9/19) and (max-width: 480px) {
  .hero { padding-top: clamp(40px, 11vw, 72px); padding-bottom: clamp(36px, 9vw, 56px); }
  .hero h1 { font-size: clamp(30px, 8.2vw, 44px); }
}

/* ---------- Reduce motion ---------- */
@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after {
    animation-duration: 0.01ms !important;
    transition-duration: 0.01ms !important;
  }
}
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
