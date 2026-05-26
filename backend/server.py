"""
FastAPI backend for the Middletown Tractor chatbot.

- Loads scraped chunks from chunks.json
- Indexes them with BM25 for keyword retrieval
- /api/chat streams an Ollama (local LLM) response grounded in retrieved chunks
- Serves the widget demo at /

Run:
    uvicorn backend.server:app --reload --port 8000
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import AsyncIterator, Optional

import requests
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, EmailStr, Field
from rank_bm25 import BM25Okapi

load_dotenv()

ROOT = Path(__file__).resolve().parent.parent
CHUNKS_PATH = ROOT / "backend" / "chunks.json"
SUPPLEMENTAL_PATH = ROOT / "backend" / "supplemental.json"
CANNED_PATH = ROOT / "backend" / "canned.json"
WIDGET_DIR = ROOT / "widget"

OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "gemma2:2b")
OLLAMA_KEEP_ALIVE = os.getenv("OLLAMA_KEEP_ALIVE", "30m")
TOP_K = 3
MAX_OUTPUT_TOKENS = 400

# Service-request notifier (ntfy.sh).
# Pick a hard-to-guess topic name (e.g. "mts-service-7f2k9q1x") and subscribe to
# it from the ntfy mobile app. Set NTFY_TOPIC in your environment / .env file.
NTFY_URL = os.getenv("NTFY_URL", "https://ntfy.sh").rstrip("/")
NTFY_TOPIC = os.getenv("NTFY_TOPIC", "").strip()

SERVICE_DB_PATH = ROOT / "backend" / "service_requests.db"

SYSTEM_PROMPT = """You are the helpful chatbot for Middletown Tractor Sales, a John Deere dealer with four locations in WV and PA: Fairmont WV, Buckhannon WV, Uniontown PA, and Washington PA.

Your job: answer customer questions about products, brands, services, parts, financing, hours, and locations using ONLY the website context provided in each message. Be friendly, concise, and direct - like a knowledgeable salesperson.

Rules:
- Ground every factual claim in the provided context. If the context doesn't cover the specific fact asked for, say so and suggest the customer call the relevant location.
- NEVER mix up information between locations. If the customer asks about Buckhannon, only use the Buckhannon source. If they ask about Fairmont, only use the Fairmont source. Each location has its own address and phone number - never substitute one for another.
- Never invent prices, model availability, hours, phone numbers, or addresses.
- When a customer wants to buy, get a quote, schedule service, or check inventory, point them to the relevant page and recommend calling the dealership.
- Keep answers short (2-4 sentences) unless the customer asks for detail.
- Don't mention "the context", "the sources", or "the documents" - speak as the dealership.
"""

# ---------- Retrieval ----------

_word_re = re.compile(r"[a-z0-9]+")


def tokenize(text: str) -> list[str]:
    return _word_re.findall(text.lower())


LOCATION_NAMES = ("fairmont", "buckhannon", "uniontown", "washington")


class Retriever:
    def __init__(self, chunks: list[dict]):
        self.chunks = chunks
        corpus = [tokenize(f"{c['title']} {c['text']}") for c in chunks]
        self.bm25 = BM25Okapi(corpus) if corpus else None
        # Pre-compute which location each chunk belongs to (by title).
        self.chunk_locations: list[str | None] = []
        for c in chunks:
            title_l = c["title"].lower()
            loc = next((n for n in LOCATION_NAMES if n in title_l), None)
            self.chunk_locations.append(loc)

    def search(self, query: str, k: int = TOP_K) -> list[dict]:
        if not self.bm25 or not query.strip():
            return []
        q_lower = query.lower()
        mentioned = [n for n in LOCATION_NAMES if n in q_lower]
        scores = self.bm25.get_scores(tokenize(query))

        # Boost chunks whose location matches a city mentioned in the query;
        # demote chunks that belong to OTHER named locations so the model
        # doesn't have to disambiguate between them.
        if mentioned:
            for i, loc in enumerate(self.chunk_locations):
                if loc in mentioned:
                    scores[i] += 50.0
                elif loc is not None:
                    scores[i] -= 50.0

        ranked = sorted(
            zip(scores, self.chunks), key=lambda x: x[0], reverse=True
        )
        results = []
        for score, chunk in ranked[:k]:
            if score <= 0:
                break
            results.append({**chunk, "score": float(score)})
        return results


def load_retriever() -> Retriever:
    chunks: list[dict] = []
    if CHUNKS_PATH.exists():
        scraped = json.loads(CHUNKS_PATH.read_text(encoding="utf-8"))
        chunks.extend(scraped)
        print(f"[ok] Loaded {len(scraped)} chunks from {CHUNKS_PATH.name}")
    else:
        print(f"[warn] {CHUNKS_PATH} not found. Run `python scraper/scrape.py` first.")

    if SUPPLEMENTAL_PATH.exists():
        extra = json.loads(SUPPLEMENTAL_PATH.read_text(encoding="utf-8"))
        chunks.extend(extra)
        print(f"[ok] Loaded {len(extra)} supplemental chunks from {SUPPLEMENTAL_PATH.name}")

    return Retriever(chunks)


retriever = load_retriever()


def ollama_available() -> tuple[bool, str]:
    """Returns (ok, message). Checks the Ollama server and pulled models."""
    try:
        r = requests.get(f"{OLLAMA_HOST}/api/tags", timeout=3)
        r.raise_for_status()
    except requests.RequestException as e:
        return False, f"Ollama not reachable at {OLLAMA_HOST} ({e})"
    models = [m["name"] for m in r.json().get("models", [])]
    if not any(m.startswith(OLLAMA_MODEL.split(":")[0]) for m in models):
        return False, (
            f"Model '{OLLAMA_MODEL}' not pulled. Available: {models or 'none'}. "
            f"Run: ollama pull {OLLAMA_MODEL}"
        )
    return True, f"Ollama OK ({OLLAMA_MODEL})"


# ---------- Service requests ----------

LOCATION_CHOICES = (
    "Fairmont, WV",
    "Buckhannon, WV",
    "Uniontown, PA",
    "Washington, PA",
    "No preference",
)

SERVICE_TYPE_CHOICES = (
    "Routine maintenance",
    "Repair / diagnostic",
    "Mobile / on-site service",
    "Pickup & delivery",
    "Parts inquiry",
    "Other",
)


def init_service_db() -> None:
    """Create the service_requests table if it doesn't exist."""
    with sqlite3.connect(SERVICE_DB_PATH) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS service_requests (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at    TEXT NOT NULL,
                name          TEXT NOT NULL,
                phone         TEXT NOT NULL,
                email         TEXT NOT NULL,
                location      TEXT NOT NULL,
                service_type  TEXT NOT NULL,
                equipment     TEXT,
                preferred_date TEXT,
                notes         TEXT,
                notified      INTEGER NOT NULL DEFAULT 0
            )
            """
        )
        conn.commit()


init_service_db()


class ServiceRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    phone: str = Field(min_length=7, max_length=40)
    email: EmailStr
    location: str
    service_type: str
    equipment: Optional[str] = Field(default=None, max_length=240)
    preferred_date: Optional[str] = Field(default=None, max_length=40)
    notes: Optional[str] = Field(default=None, max_length=2000)


def _notify_ntfy(req: ServiceRequest, request_id: int) -> bool:
    """POST the new request to ntfy.sh; returns True on 2xx."""
    if not NTFY_TOPIC:
        print("[warn] NTFY_TOPIC is not set; skipping push notification")
        return False
    body_lines = [
        f"{req.service_type} @ {req.location}",
        f"From: {req.name}  ({req.phone} / {req.email})",
    ]
    if req.equipment:
        body_lines.append(f"Equipment: {req.equipment}")
    if req.preferred_date:
        body_lines.append(f"Preferred: {req.preferred_date}")
    if req.notes:
        body_lines.append("")
        body_lines.append(req.notes[:500])
    body = "\n".join(body_lines).encode("utf-8")
    headers = {
        "Title": f"New service request #{request_id}",
        "Priority": "high",
        "Tags": "wrench,tractor2,bell",
        "Click": f"tel:{re.sub(r'[^0-9+]', '', req.phone)}",
    }
    try:
        r = requests.post(f"{NTFY_URL}/{NTFY_TOPIC}", data=body, headers=headers, timeout=10)
        return 200 <= r.status_code < 300
    except requests.RequestException as e:
        print(f"[warn] ntfy notify failed: {e}")
        return False


# ---------- API ----------

app = FastAPI(title="Middletown Tractor Chatbot")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class ChatMessage(BaseModel):
    role: str = Field(pattern="^(user|assistant)$")
    content: str


class ChatRequest(BaseModel):
    messages: list[ChatMessage]


def format_context(chunks: list[dict]) -> str:
    if not chunks:
        return "(No relevant website content found for this question.)"
    parts = []
    for i, c in enumerate(chunks, 1):
        parts.append(
            f"[Source {i}] {c['title']} - {c['url']}\n{c['text']}"
        )
    return "\n\n---\n\n".join(parts)


def stream_answer(req: ChatRequest) -> AsyncIterator[bytes]:
    if not req.messages or req.messages[-1].role != "user":
        yield b"data: " + json.dumps({"error": "last message must be from user"}).encode() + b"\n\n"
        return

    last_user = req.messages[-1].content
    hits = retriever.search(last_user, k=TOP_K)
    context = format_context(hits)

    # Build Ollama chat messages. System prompt first, then prior turns,
    # then the latest user turn with retrieved context prepended.
    messages: list[dict] = [{"role": "system", "content": SYSTEM_PROMPT}]
    messages.extend(m.model_dump() for m in req.messages[:-1])
    messages.append(
        {
            "role": "user",
            "content": (
                f"Website context for this question:\n\n{context}\n\n"
                f"---\nCustomer question: {last_user}"
            ),
        }
    )

    sources = [{"title": h["title"], "url": h["url"]} for h in hits]
    yield b"data: " + json.dumps({"type": "sources", "sources": sources}).encode() + b"\n\n"

    payload = {
        "model": OLLAMA_MODEL,
        "messages": messages,
        "stream": True,
        "keep_alive": OLLAMA_KEEP_ALIVE,
        "options": {
            "num_predict": MAX_OUTPUT_TOKENS,
            "temperature": 0.3,
        },
    }

    try:
        with requests.post(
            f"{OLLAMA_HOST}/api/chat",
            json=payload,
            stream=True,
            timeout=(10, 300),
        ) as resp:
            if resp.status_code != 200:
                err = f"Ollama HTTP {resp.status_code}: {resp.text[:200]}"
                yield b"data: " + json.dumps({"type": "error", "error": err}).encode() + b"\n\n"
                return
            for line in resp.iter_lines(decode_unicode=True):
                if not line:
                    continue
                try:
                    evt = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if evt.get("done"):
                    yield b"data: " + json.dumps({"type": "done"}).encode() + b"\n\n"
                    return
                delta = evt.get("message", {}).get("content", "")
                if delta:
                    yield b"data: " + json.dumps({"type": "delta", "text": delta}).encode() + b"\n\n"
    except requests.RequestException as e:
        yield b"data: " + json.dumps({"type": "error", "error": str(e)}).encode() + b"\n\n"


@app.post("/api/chat")
def chat(req: ChatRequest):
    ok, msg = ollama_available()
    if not ok:
        raise HTTPException(503, msg)
    return StreamingResponse(stream_answer(req), media_type="text/event-stream")


@app.get("/api/health")
def health():
    ok, msg = ollama_available()
    return {
        "ok": ok,
        "status": msg,
        "model": OLLAMA_MODEL,
        "host": OLLAMA_HOST,
        "chunks": len(retriever.chunks),
    }


def _load_canned() -> list[dict]:
    if not CANNED_PATH.exists():
        return []
    try:
        return json.loads(CANNED_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []


@app.get("/api/suggestions")
def suggestions():
    """Returns suggestion chips with pre-written answers. The widget renders
    these instantly on click without hitting the LLM, so they're fast and
    accurate. Edit canned.json to change them.
    """
    return _load_canned()


@app.post("/api/service-request")
def submit_service_request(req: ServiceRequest):
    """Store a new service / maintenance request and push-notify the dealer."""
    if req.location not in LOCATION_CHOICES:
        raise HTTPException(400, f"location must be one of: {', '.join(LOCATION_CHOICES)}")
    if req.service_type not in SERVICE_TYPE_CHOICES:
        raise HTTPException(400, f"service_type must be one of: {', '.join(SERVICE_TYPE_CHOICES)}")

    created = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with sqlite3.connect(SERVICE_DB_PATH) as conn:
        cur = conn.execute(
            """INSERT INTO service_requests
               (created_at, name, phone, email, location, service_type,
                equipment, preferred_date, notes, notified)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0)""",
            (created, req.name, req.phone, req.email, req.location, req.service_type,
             req.equipment, req.preferred_date, req.notes),
        )
        request_id = cur.lastrowid
        conn.commit()

    notified = _notify_ntfy(req, request_id)
    if notified:
        with sqlite3.connect(SERVICE_DB_PATH) as conn:
            conn.execute("UPDATE service_requests SET notified=1 WHERE id=?", (request_id,))
            conn.commit()

    return {
        "ok": True,
        "id": request_id,
        "created_at": created,
        "notified": notified,
        "message": "Thanks - we'll be in touch shortly to confirm.",
    }


@app.get("/api/service-request/options")
def service_request_options():
    """Returns the allowed values so the form can render the same choices the
    backend will validate against."""
    return {"locations": list(LOCATION_CHOICES), "service_types": list(SERVICE_TYPE_CHOICES)}


@app.get("/api/service-requests/recent")
def service_requests_recent(limit: int = 50):
    """Admin / debug: list the most recent requests. Protect with a reverse
    proxy auth header in production if exposed publicly."""
    limit = max(1, min(limit, 500))
    with sqlite3.connect(SERVICE_DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM service_requests ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
    return [dict(r) for r in rows]


@app.middleware("http")
async def no_cache_widget_assets(request, call_next):
    """Disable browser caching for widget assets so edits show up immediately
    without users having to hard-refresh."""
    response = await call_next(request)
    path = request.url.path
    if path == "/" or path.endswith((".html", ".js", ".css")):
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response


# Serve the widget demo at /
if WIDGET_DIR.exists():
    app.mount("/", StaticFiles(directory=str(WIDGET_DIR), html=True), name="widget")
