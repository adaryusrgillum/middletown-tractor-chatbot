"""
Crawl middletowntractor.com, extract clean text from each page,
chunk it, and save to backend/chunks.json for retrieval at chat time.

Run once (or whenever the site changes):
    python scraper/scrape.py
"""
from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path
from urllib.parse import urljoin, urlparse

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

MAX_PAGES = 200
REQUEST_DELAY_SEC = 0.5
CHUNK_TARGET_CHARS = 1800  # roughly ~400-500 tokens
CHUNK_OVERLAP_CHARS = 200

# Skip URLs that obviously aren't useful content.
SKIP_PATTERNS = [
    re.compile(r"\.(jpg|jpeg|png|gif|svg|webp|pdf|zip|mp4|mp3)$", re.I),
    re.compile(r"/cart", re.I),
    re.compile(r"/checkout", re.I),
    re.compile(r"/account", re.I),
    re.compile(r"#"),
]


def is_same_site(url: str) -> bool:
    try:
        return urlparse(url).netloc in ("", ALLOWED_HOST)
    except Exception:
        return False


def should_skip(url: str) -> bool:
    return any(p.search(url) for p in SKIP_PATTERNS)


def normalize(url: str) -> str:
    url = url.split("#")[0]
    return url.rstrip("/") or BASE


def extract_text(soup: BeautifulSoup) -> tuple[str, str]:
    for tag in soup(["script", "style", "noscript", "nav", "footer", "header", "form"]):
        tag.decompose()

    title = (soup.title.string.strip() if soup.title and soup.title.string else "").strip()

    main = soup.find("main") or soup.find("article") or soup.body or soup
    text = main.get_text(separator="\n", strip=True)
    text = re.sub(r"\n{2,}", "\n\n", text)
    text = re.sub(r"[ \t]+", " ", text)
    return title, text.strip()


def chunk_text(text: str) -> list[str]:
    if len(text) <= CHUNK_TARGET_CHARS:
        return [text] if text else []

    chunks = []
    start = 0
    while start < len(text):
        end = min(start + CHUNK_TARGET_CHARS, len(text))
        # Try to break on a paragraph boundary
        if end < len(text):
            nl = text.rfind("\n\n", start, end)
            if nl > start + CHUNK_TARGET_CHARS // 2:
                end = nl
        chunks.append(text[start:end].strip())
        if end >= len(text):
            break
        start = max(end - CHUNK_OVERLAP_CHARS, start + 1)
    return [c for c in chunks if c]


def crawl() -> list[dict]:
    seen: set[str] = set()
    queue: list[str] = [BASE]
    pages: list[dict] = []
    session = requests.Session()
    session.headers.update(HEADERS)

    while queue and len(pages) < MAX_PAGES:
        url = normalize(queue.pop(0))
        if url in seen or should_skip(url) or not is_same_site(url):
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
        if len(text) > 200:  # ignore near-empty pages
            pages.append({"url": url, "title": title, "text": text})
            print(f"[ok]   {url}  ({len(text)} chars)")

        for a in soup.find_all("a", href=True):
            link = urljoin(url, a["href"])
            link = normalize(link)
            if is_same_site(link) and not should_skip(link) and link not in seen:
                queue.append(link)

        time.sleep(REQUEST_DELAY_SEC)

    return pages


def build_chunks(pages: list[dict]) -> list[dict]:
    chunks: list[dict] = []
    for page in pages:
        for i, body in enumerate(chunk_text(page["text"])):
            chunks.append(
                {
                    "id": f"{page['url']}#chunk-{i}",
                    "url": page["url"],
                    "title": page["title"],
                    "text": body,
                }
            )
    return chunks


def main() -> int:
    print(f"Crawling {BASE} (max {MAX_PAGES} pages)...")
    pages = crawl()
    print(f"\nCrawled {len(pages)} pages.")

    chunks = build_chunks(pages)
    print(f"Built {len(chunks)} chunks.")

    out_path = Path(__file__).resolve().parent.parent / "backend" / "chunks.json"
    out_path.write_text(json.dumps(chunks, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Wrote {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
