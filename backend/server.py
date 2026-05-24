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
from pathlib import Path
from typing import AsyncIterator

import requests
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
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
