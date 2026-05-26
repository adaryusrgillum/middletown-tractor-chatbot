"""
Download every image URL listed in site_bundle/images.json into
site_bundle/images/, with safe filenames derived from the URL path.

Writes site_bundle/image_map.json mapping original URL -> local relative path
(e.g., "https://www.middletowntractor.com/foo/bar.jpg" -> "images/bar_abc123.jpg").

Skips files that already exist on disk.

Run:
    python scraper/download_images.py
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
import time
from pathlib import Path
from urllib.parse import urlparse
from concurrent.futures import ThreadPoolExecutor
import threading

import requests

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Referer": "https://www.middletowntractor.com/",
}

TIMEOUT = 20
SAFE_NAME_RE = re.compile(r"[^A-Za-z0-9._-]+")


def safe_filename(url: str) -> str:
    """Build a stable, filesystem-safe filename for an image URL.
    Format: <basename>_<hash8>.<ext>  (hash makes it collision-free)
    """
    parsed = urlparse(url)
    path_part = parsed.path.rsplit("/", 1)[-1] or "image"
    name, _, ext = path_part.rpartition(".")
    if not name:
        name, ext = path_part, "jpg"
    ext = (ext or "jpg").lower()
    if ext not in {"jpg", "jpeg", "png", "gif", "svg", "webp"}:
        ext = "jpg"
    name = SAFE_NAME_RE.sub("_", name)[:60].strip("_") or "image"
    h = hashlib.sha1(url.encode("utf-8")).hexdigest()[:8]
    return f"{name}_{h}.{ext}"


def download_one(url: str, out_dir: Path, session: requests.Session) -> tuple[str, str | None]:
    fname = safe_filename(url)
    dest = out_dir / fname
    rel = f"images/{fname}"
    if dest.exists() and dest.stat().st_size > 0:
        return url, rel
    try:
        r = session.get(url, timeout=TIMEOUT)
        if r.status_code != 200 or len(r.content) < 100:
            return url, None
        dest.write_bytes(r.content)
        return url, rel
    except Exception:
        return url, None


def main() -> int:
    root = Path(__file__).resolve().parent.parent
    images_path = root / "site_bundle" / "images.json"
    if not images_path.exists():
        print("site_bundle/images.json not found - run scrape_full.py first", file=sys.stderr)
        return 1

    urls: list[str] = json.loads(images_path.read_text(encoding="utf-8"))
    out_dir = root / "site_bundle" / "images"
    out_dir.mkdir(parents=True, exist_ok=True)

    image_map: dict[str, str] = {}
    thread_local = threading.local()

    def get_session():
        if not hasattr(thread_local, "session"):
            thread_local.session = requests.Session()
            thread_local.session.headers.update(HEADERS)
        return thread_local.session

    def worker(url: str):
        return download_one(url, out_dir, get_session())

    print(f"Starting concurrent download of {len(urls)} images...")
    n_ok = n_fail = 0

    with ThreadPoolExecutor(max_workers=32) as executor:
        results = executor.map(worker, urls)
        for idx, (url, rel) in enumerate(results, 1):
            if rel:
                image_map[url] = rel
                n_ok += 1
            else:
                n_fail += 1
            if idx % 100 == 0 or idx == len(urls):
                print(f"Progress: {idx}/{len(urls)} processed...")

    (root / "site_bundle" / "image_map.json").write_text(
        json.dumps(image_map, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(f"\nDone. Wrote site_bundle/image_map.json with {len(image_map)} entries (success={n_ok}, fail={n_fail}).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
