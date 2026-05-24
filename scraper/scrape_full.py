"""
Deep crawl of middletowntractor.com:
- visits up to MAX_PAGES, prioritizing non-inventory content first
- dedupes inventory-image-variant URLs (?img=N) and other near-duplicate URLs
- extracts every image URL referenced on each page
- writes:
    backend/chunks.json   (text chunks for the chatbot)
    site_bundle/pages.json (structured page list for the static site generator)
    site_bundle/images.json (unique image URL list for the downloader)

Run:
    python scraper/scrape_full.py
"""
from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path
from urllib.parse import urljoin, urlparse, urlunparse, parse_qsl, urlencode

import requests
from bs4 import BeautifulSoup

BASE = "https://www.middletowntractor.com"
ALLOWED_HOST = urlparse(BASE).netloc

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

MAX_PAGES = 500
REQUEST_DELAY_SEC = 0.3
CHUNK_TARGET_CHARS = 1800
CHUNK_OVERLAP_CHARS = 200

# Path-segment substrings whose URLs we drop entirely.
DROP_PATTERNS = [
    re.compile(r"\.(jpg|jpeg|png|gif|svg|webp|pdf|zip|mp4|mp3)$", re.I),
    re.compile(r"/cart", re.I),
    re.compile(r"/checkout", re.I),
    re.compile(r"/account", re.I),
]

# Query keys that are irrelevant to page identity (image gallery indices, etc).
STRIP_QUERY_KEYS = {"img", "format"}

# URLs with these path patterns are deprioritized to last in the queue so the
# main content pages (about, service, parts, brand listings) are crawled first.
LOW_PRIORITY_PATTERNS = [
    re.compile(r"page=xInquiry", re.I),
    re.compile(r"page=xContact", re.I),
]


def normalize(url: str) -> str:
    p = urlparse(url)
    # Drop fragment, strip irrelevant query keys
    qs = [(k, v) for (k, v) in parse_qsl(p.query, keep_blank_values=True) if k not in STRIP_QUERY_KEYS]
    qs.sort()
    new_query = urlencode(qs)
    path = p.path.rstrip("/") or "/"
    return urlunparse((p.scheme or "https", p.netloc or ALLOWED_HOST, path, "", new_query, ""))


def is_same_site(url: str) -> bool:
    try:
        return urlparse(url).netloc in ("", ALLOWED_HOST)
    except Exception:
        return False


def should_drop(url: str) -> bool:
    return any(p.search(url) for p in DROP_PATTERNS)


def is_low_priority(url: str) -> bool:
    return any(p.search(url) for p in LOW_PRIORITY_PATTERNS)


def extract_text(soup: BeautifulSoup) -> tuple[str, str]:
    for tag in soup(["script", "style", "noscript", "nav", "footer", "header", "form"]):
        tag.decompose()

    title = (soup.title.string.strip() if soup.title and soup.title.string else "").strip()

    main = soup.find("main") or soup.find("article") or soup.body or soup
    text = main.get_text(separator="\n", strip=True)
    text = re.sub(r"\n{2,}", "\n\n", text)
    text = re.sub(r"[ \t]+", " ", text)
    return title, text.strip()


IMAGE_HOST_ALLOWLIST = (
    "middletowntractor.com",
    "dealerspike.com",  # their inventory CDN - product photos live here
)


def extract_images(soup: BeautifulSoup, base_url: str) -> list[str]:
    urls: list[str] = []
    seen: set[str] = set()
    for img in soup.find_all("img"):
        src = img.get("src") or img.get("data-src") or img.get("data-lazy-src")
        if not src:
            continue
        full = urljoin(base_url, src)
        host = urlparse(full).netloc.lower()
        if not any(allowed in host for allowed in IMAGE_HOST_ALLOWLIST):
            continue
        if full in seen:
            continue
        if re.search(r"(spacer|pixel|blank|1x1|favicon)", full, re.I):
            continue
        seen.add(full)
        urls.append(full)
    return urls


def chunk_text(text: str) -> list[str]:
    if len(text) <= CHUNK_TARGET_CHARS:
        return [text] if text else []
    chunks = []
    start = 0
    while start < len(text):
        end = min(start + CHUNK_TARGET_CHARS, len(text))
        if end < len(text):
            nl = text.rfind("\n\n", start, end)
            if nl > start + CHUNK_TARGET_CHARS // 2:
                end = nl
        chunks.append(text[start:end].strip())
        if end >= len(text):
            break
        start = max(end - CHUNK_OVERLAP_CHARS, start + 1)
    return [c for c in chunks if c]


def crawl() -> tuple[list[dict], set[str]]:
    seen: set[str] = set()
    high_q: list[str] = [BASE]
    low_q: list[str] = []
    pages: list[dict] = []
    images: set[str] = set()
    session = requests.Session()
    session.headers.update(HEADERS)

    while (high_q or low_q) and len(pages) < MAX_PAGES:
        url = high_q.pop(0) if high_q else low_q.pop(0)
        url = normalize(url)
        if url in seen or should_drop(url) or not is_same_site(url):
            continue
        seen.add(url)

        try:
            r = session.get(url, timeout=15)
        except requests.RequestException as e:
            print(f"[skip] {url}: {e}", file=sys.stderr)
            continue
        if r.status_code != 200 or "text/html" not in r.headers.get("Content-Type", ""):
            print(f"[skip] {url}: HTTP {r.status_code}", file=sys.stderr)
            continue

        soup = BeautifulSoup(r.text, "html.parser")
        title, text = extract_text(soup)
        page_images = extract_images(soup, url)
        images.update(page_images)

        if len(text) > 200:
            pages.append({
                "url": url,
                "title": title,
                "text": text,
                "images": page_images,
            })
            print(f"[ok] {len(pages):3d}/{MAX_PAGES}  {url}  ({len(text)}c, {len(page_images)} imgs)")

        for a in soup.find_all("a", href=True):
            link = normalize(urljoin(url, a["href"]))
            if not is_same_site(link) or should_drop(link) or link in seen:
                continue
            if is_low_priority(link):
                low_q.append(link)
            else:
                high_q.append(link)

        time.sleep(REQUEST_DELAY_SEC)

    return pages, images


def build_chunks(pages: list[dict]) -> list[dict]:
    chunks: list[dict] = []
    for page in pages:
        for i, body in enumerate(chunk_text(page["text"])):
            chunks.append({
                "id": f"{page['url']}#chunk-{i}",
                "url": page["url"],
                "title": page["title"],
                "text": body,
            })
    return chunks


def main() -> int:
    print(f"Crawling {BASE} (max {MAX_PAGES} pages, low-priority URLs deferred)...")
    pages, images = crawl()
    print(f"\nDone. {len(pages)} pages, {len(images)} unique images.")

    root = Path(__file__).resolve().parent.parent
    chunks = build_chunks(pages)
    (root / "backend" / "chunks.json").write_text(
        json.dumps(chunks, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(f"  -> backend/chunks.json  ({len(chunks)} chunks)")

    site_bundle = root / "site_bundle"
    site_bundle.mkdir(exist_ok=True)
    (site_bundle / "pages.json").write_text(
        json.dumps(pages, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(f"  -> site_bundle/pages.json  ({len(pages)} pages)")

    (site_bundle / "images.json").write_text(
        json.dumps(sorted(images), indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(f"  -> site_bundle/images.json  ({len(images)} image URLs)")

    return 0


if __name__ == "__main__":
    sys.exit(main())
