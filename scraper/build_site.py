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
    # Fallback: trim the long title
    t = p["title"].split("|")[0].strip()
    return t[:50] if t else "Product"


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
  <meta name="theme-color" content="#2f7a3a">
  <link rel="icon" href="{prefix}assets/icon-192.png" type="image/png">
</head>"""


def topbar(depth: int) -> str:
    prefix = "../" if depth else ""
    return f"""<header class="topbar">
  <a class="brand" href="{prefix}index.html">
    <span class="brand-mark">MT</span>
    <span class="brand-text">
      <strong>Middletown Tractor Sales</strong>
      <small>John Deere &middot; STIHL &middot; Honda Power &middot; Ventrac</small>
    </span>
  </a>
  <nav class="topnav">
    <a href="{prefix}index.html">Home</a>
    <a href="#" onclick="document.querySelector('.mt-launcher')?.click();return false;">Chat</a>
  </nav>
</header>"""


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
    prefix = "/" if not depth else "/"  # absolute path works in Capacitor WebView
    return f"""<div id="mt-chat-root"></div>
<script>window.MT_CHAT_CONFIG = {{ apiUrl: window.MT_BACKEND_URL || '', suggestionsUrl: '/assets/canned.json' }};</script>
<script src="/assets/widget.js" defer></script>"""


# ---------- Product card ----------

def product_card(p: dict, image_map: dict[str, str], depth: int = 0) -> str:
    """depth=0 from index.html, depth=1 from pages/*.html."""
    thumb = page_thumb(p, image_map)
    img_prefix = "../" if depth else ""
    href_prefix = "" if depth else "pages/"
    img_html = (
        f'<div class="card-img"><img loading="lazy" src="{img_prefix}{H(thumb)}" alt=""></div>'
        if thumb else
        '<div class="card-img card-img-empty"></div>'
    )
    name = product_name(p)
    brand = brand_of(p) or ""
    return f"""<a class="card product-card" href="{href_prefix}{H(slug_for(p["url"]))}">
  {img_html}
  <div class="card-body">
    <div class="card-brand">{H(brand)}</div>
    <div class="card-title">{H(name)}</div>
  </div>
</a>"""


def brand_card(brand: str, count: int, thumb: str | None) -> str:
    img_html = (
        f'<div class="card-img"><img loading="lazy" src="{H(thumb)}" alt=""></div>'
        if thumb else
        '<div class="card-img card-img-empty"></div>'
    )
    return f"""<a class="card brand-card" href="pages/{H(brand_slug(brand))}">
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

    hero_html = (
        f'<div class="product-hero"><img src="../{H(hero)}" alt=""></div>'
        if hero else
        '<div class="product-hero product-hero-empty"></div>'
    )

    thumb_html = ""
    if thumbs:
        items = "".join(
            f'<button class="thumb" onclick="document.querySelector(\'.product-hero img\').src=\'../{H(t)}\'">'
            f'<img src="../{H(t)}" alt=""></button>'
            for t in thumbs
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
        items = "".join(f'<img class="info-img" loading="lazy" src="../{H(i)}" alt="">' for i in images[:8])
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
        f'<div class="loc-pill"><strong>{H(l["city"])}</strong><small>{H(l["phone"])}</small></div>'
        for l in LOCATIONS
    )

    return f"""{head("Middletown Tractor Sales - WV & PA", depth=0)}
<body>
{topbar(depth=0)}

<section class="hero">
  <div class="hero-inner">
    <h1>Equipment for the way you work.</h1>
    <p class="lede">John Deere &middot; STIHL &middot; Honda Power &middot; Ventrac. Serving West Virginia and Pennsylvania since 1955.</p>
    <div class="locations-strip">{loc_summary}</div>
    <div class="hero-cta">
      <a class="btn btn-primary btn-lg" href="#brands">Browse inventory</a>
      <a class="btn btn-ghost btn-lg" href="#" onclick="document.querySelector('.mt-launcher')?.click();return false;">Ask the chatbot</a>
    </div>
  </div>
</section>

<main class="home">

  <section class="featured">
    <div class="section-head">
      <h2>Featured inventory</h2>
      <p class="muted">A taste of what we have. <a href="pages/all-inventory.html">See all units &rarr;</a></p>
    </div>
    <div class="card-grid">{featured_html}</div>
  </section>

  <section class="brands" id="brands">
    <div class="section-head">
      <h2>Browse by brand</h2>
    </div>
    <div class="card-grid">{brand_html}</div>
  </section>

  <section class="info">
    <div class="section-head">
      <h2>Service, parts &amp; about us</h2>
    </div>
    <div class="info-links">{info_links}</div>
  </section>

</main>

{footer(depth=0)}
{chat_root(depth=0)}
</body></html>
"""


# ---------- CSS ----------

SITE_CSS = """:root {
  --primary: #2f7a3a;
  --primary-dark: #1f5527;
  --accent: #f5c84f;
  --bg: #f7f8f6;
  --bg-card: #fff;
  --text: #1a1f1c;
  --muted: #6b7670;
  --border: #dde1dd;
  --shadow: 0 2px 8px rgba(0,0,0,0.06);
  --shadow-hover: 0 6px 18px rgba(0,0,0,0.12);
}
* { box-sizing: border-box; }
html, body { margin: 0; padding: 0; }
body {
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
  color: var(--text);
  background: var(--bg);
  line-height: 1.5;
  font-size: 15px;
}
a { color: var(--primary-dark); text-decoration: none; }
a:hover { text-decoration: underline; }
img { max-width: 100%; display: block; }
h1, h2, h3, h4 { color: var(--text); }

/* ---------- Topbar ---------- */
.topbar {
  position: sticky; top: 0; z-index: 100;
  background: #fff;
  border-bottom: 1px solid var(--border);
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 10px 16px;
}
.brand { display: flex; align-items: center; gap: 10px; color: var(--text); }
.brand-mark {
  width: 36px; height: 36px;
  background: var(--primary); color: #fff;
  border-radius: 50%;
  display: flex; align-items: center; justify-content: center;
  font-weight: 700; font-size: 14px;
  letter-spacing: 0.05em;
}
.brand-text strong { display: block; line-height: 1.1; font-size: 15px; }
.brand-text small { display: block; color: var(--muted); font-size: 11px; }
.topnav a { margin-left: 16px; font-size: 14px; font-weight: 500; color: var(--text); }

/* ---------- Hero ---------- */
.hero {
  background: linear-gradient(135deg, var(--primary-dark) 0%, var(--primary) 100%);
  color: #fff;
  padding: 40px 20px 32px;
}
.hero-inner { max-width: 1000px; margin: 0 auto; }
.hero h1 { font-size: 30px; margin: 0 0 8px; color: #fff; line-height: 1.15; }
.hero .lede { font-size: 15px; opacity: 0.95; margin: 0 0 16px; }
.locations-strip {
  display: flex; flex-wrap: wrap; gap: 10px; margin: 18px 0 22px;
}
.loc-pill {
  background: rgba(255,255,255,0.13);
  border: 1px solid rgba(255,255,255,0.2);
  border-radius: 8px;
  padding: 8px 12px;
  font-size: 13px;
}
.loc-pill strong { display: block; }
.loc-pill small { opacity: 0.85; }
.hero-cta { display: flex; gap: 10px; flex-wrap: wrap; }

/* ---------- Buttons ---------- */
.btn {
  display: inline-block;
  padding: 9px 16px;
  border-radius: 8px;
  font-weight: 600;
  font-size: 14px;
  text-decoration: none;
  border: 1px solid transparent;
  cursor: pointer;
}
.btn:hover { text-decoration: none; }
.btn-primary { background: var(--accent); color: #1a1f1c; }
.btn-primary:hover { background: #f0bc34; }
.btn-secondary { background: #fff; color: var(--primary-dark); border-color: var(--border); }
.btn-secondary:hover { background: var(--bg); }
.btn-ghost { background: rgba(255,255,255,0.15); color: #fff; border-color: rgba(255,255,255,0.4); }
.btn-ghost:hover { background: rgba(255,255,255,0.25); }
.btn-lg { padding: 11px 22px; font-size: 15px; }

/* ---------- Main / sections ---------- */
.home { max-width: 1100px; margin: 0 auto; padding: 8px 16px 40px; }
section { margin: 32px 0; }
.section-head { margin-bottom: 14px; }
.section-head h2 { margin: 0 0 4px; font-size: 22px; color: var(--primary-dark); }
.section-head .muted { color: var(--muted); margin: 0; font-size: 13.5px; }
.muted { color: var(--muted); }

/* ---------- Card grid ---------- */
.card-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(180px, 1fr));
  gap: 14px;
}
.card {
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: 10px;
  overflow: hidden;
  text-decoration: none;
  color: var(--text);
  display: flex; flex-direction: column;
  box-shadow: var(--shadow);
  transition: box-shadow 0.15s ease, transform 0.15s ease;
}
.card:hover { box-shadow: var(--shadow-hover); transform: translateY(-2px); text-decoration: none; }
.card-img {
  width: 100%; aspect-ratio: 4/3;
  background: #eee;
  overflow: hidden;
  display: flex; align-items: center; justify-content: center;
}
.card-img img { width: 100%; height: 100%; object-fit: cover; }
.card-img-empty { background: linear-gradient(135deg, #e8eee8, #d9e3da); }
.card-body { padding: 10px 12px 12px; }
.card-brand { font-size: 11px; color: var(--muted); text-transform: uppercase; letter-spacing: 0.04em; font-weight: 600; }
.card-title { font-weight: 600; font-size: 14px; margin-top: 2px; line-height: 1.3; color: var(--text); }
.card-meta { color: var(--muted); font-size: 12.5px; margin-top: 4px; }

/* ---------- Info links ---------- */
.info-links { display: grid; grid-template-columns: repeat(auto-fill, minmax(220px, 1fr)); gap: 8px; }
.info-link {
  display: block;
  padding: 12px 14px;
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: 8px;
  font-weight: 500;
  font-size: 14px;
  color: var(--primary-dark);
  text-decoration: none;
}
.info-link:hover { background: #fff; border-color: var(--primary); text-decoration: none; }

/* ---------- Product detail ---------- */
.product-page, .listing-page, .info-page { max-width: 1100px; margin: 0 auto; padding: 16px; }
.back { display: inline-block; color: var(--muted); margin-bottom: 12px; font-size: 13.5px; }
.product-grid { display: grid; grid-template-columns: 1fr; gap: 20px; }
@media (min-width: 768px) { .product-grid { grid-template-columns: minmax(0,1.2fr) minmax(0,1fr); } }
.product-hero {
  width: 100%; aspect-ratio: 4/3;
  background: #eee;
  border-radius: 12px;
  overflow: hidden;
}
.product-hero img { width: 100%; height: 100%; object-fit: cover; }
.product-hero-empty { background: linear-gradient(135deg, #e8eee8, #d9e3da); }
.thumb-row { display: flex; gap: 8px; margin-top: 10px; flex-wrap: wrap; }
.thumb { width: 70px; height: 56px; border: 1px solid var(--border); border-radius: 6px; background: #fff; padding: 0; cursor: pointer; overflow: hidden; }
.thumb img { width: 100%; height: 100%; object-fit: cover; }
.product-info .product-brand { font-size: 12px; color: var(--muted); text-transform: uppercase; letter-spacing: 0.05em; font-weight: 600; }
.product-info h1 { margin: 4px 0 14px; font-size: 24px; color: var(--primary-dark); }
.product-cta { display: flex; gap: 8px; flex-wrap: wrap; margin-bottom: 18px; }
.product-body p { margin: 0 0 10px; font-size: 14.5px; }
.source-link { margin-top: 18px; font-size: 13px; color: var(--muted); }

/* ---------- Info page ---------- */
.info-page article { background: var(--bg-card); border: 1px solid var(--border); border-radius: 10px; padding: 22px; }
.info-page h1 { margin-top: 0; color: var(--primary-dark); }
.info-images { display: grid; grid-template-columns: repeat(auto-fill, minmax(160px,1fr)); gap: 8px; margin: 14px 0; }
.info-img { width: 100%; height: 140px; object-fit: cover; border-radius: 8px; }

/* ---------- Listing page ---------- */
.listing-page h1 { color: var(--primary-dark); margin: 6px 0 4px; }
.listing-meta { color: var(--muted); margin: 0 0 16px; font-size: 13.5px; }

/* ---------- Footer ---------- */
.site-footer { background: #1a1f1c; color: #c9d1cb; padding: 30px 20px 14px; margin-top: 40px; }
.footer-cols { max-width: 1100px; margin: 0 auto; display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 24px; }
.footer-cols h4 { color: #fff; margin: 0 0 10px; font-size: 14px; text-transform: uppercase; letter-spacing: 0.04em; }
.footer-cols ul { list-style: none; padding: 0; margin: 0; }
.footer-cols ul li { margin: 6px 0; font-size: 13.5px; line-height: 1.45; }
.footer-cols a { color: #d9e3da; }
.footer-cols .loc-list li { margin-bottom: 12px; }
.footer-bottom { max-width: 1100px; margin: 22px auto 0; padding-top: 14px; border-top: 1px solid #2a312c; font-size: 12px; color: #8a948c; }
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
    for p in products:
        if not page_thumb(p, image_map):
            continue
        b = brand_of(p) or "Other"
        if by_brand_seen[b] >= 3:
            continue
        featured.append(p)
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

    canned = json.loads((ROOT / "backend" / "canned.json").read_text(encoding="utf-8"))
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
        "background_color": "#f7f8f6",
        "theme_color": "#2f7a3a",
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
