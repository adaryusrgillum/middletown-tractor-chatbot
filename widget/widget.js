(function () {
  "use strict";

  const CONFIG = Object.assign(
    {
      apiUrl: "/api/chat",
      suggestionsUrl: "/api/suggestions",
      urlMapUrl: "/assets/url_map.json",
      greeting: "Hi! Ask me anything about Middletown Tractor — products, parts, service, financing, hours, or locations.",
    },
    window.MT_CHAT_CONFIG || {}
  );

  /** Loaded from /api/suggestions: [{question, answer, sources, cards, images}]. */
  let cannedSuggestions = [];
  /** Remote URL -> in-app relative path (e.g. "pages/brand-john-deere.html"). */
  let urlMap = {};
  /** Path depth relative to bundle root, so we can prefix relative links correctly. */
  const pathDepth = computePathDepth();

  const root = document.getElementById("mt-chat-root") || document.body;

  // ---------- Build DOM ----------

  const launcher = el("button", { class: "mt-launcher", title: "Chat with us", "aria-label": "Open chat" }, "💬");
  const panel = el("div", { class: "mt-panel", role: "dialog", "aria-label": "Middletown Tractor chat" });

  const header = el("div", { class: "mt-header" }, [
    el("div", { class: "mt-header-text" }, [
      el("h3", {}, "Middletown Tractor"),
      el("div", { class: "mt-subtitle" }, "Ask us anything"),
    ]),
    el("button", { class: "mt-close", title: "Close", "aria-label": "Close chat" }, "×"),
  ]);
  const messagesEl = el("div", { class: "mt-messages" });
  const suggestionsToggle = el(
    "button",
    { class: "mt-suggestions-toggle", type: "button" },
    [
      el("span", { class: "mt-suggestions-label" }, "Suggested questions"),
      el("span", { class: "mt-suggestions-chevron" }, "▾"),
    ]
  );
  const suggestionsEl = el("div", { class: "mt-suggestions" });
  const suggestionsWrap = el("div", { class: "mt-suggestions-wrap" }, [
    suggestionsToggle,
    suggestionsEl,
  ]);
  const textarea = el("textarea", {
    class: "mt-input",
    rows: "1",
    placeholder: "Type your question...",
  });
  const sendBtn = el("button", { class: "mt-send" }, "Send");
  const inputRow = el("div", { class: "mt-input-row" }, [textarea, sendBtn]);

  panel.append(header, messagesEl, suggestionsWrap, inputRow);
  root.append(launcher, panel);

  const COLLAPSE_KEY = "mt-chat-suggestions-collapsed";
  let suggestionsCollapsed = localStorage.getItem(COLLAPSE_KEY) === "1";
  applySuggestionsCollapsed();

  function applySuggestionsCollapsed() {
    suggestionsWrap.classList.toggle("collapsed", suggestionsCollapsed);
    suggestionsToggle.setAttribute(
      "aria-expanded",
      suggestionsCollapsed ? "false" : "true"
    );
  }

  suggestionsToggle.addEventListener("click", () => {
    suggestionsCollapsed = !suggestionsCollapsed;
    localStorage.setItem(COLLAPSE_KEY, suggestionsCollapsed ? "1" : "0");
    applySuggestionsCollapsed();
  });

  // ---------- URL handling ----------

  function computePathDepth() {
    const path = location.pathname.replace(/\/+$/, "");
    const segs = path.split("/").filter(Boolean);
    // index.html is at depth 0; pages/*.html is at depth 1.
    return path.endsWith(".html") ? Math.max(0, segs.length - 1) : segs.length;
  }

  function withPrefix(relPath) {
    if (!relPath) return relPath;
    if (/^(?:[a-z]+:)?\/\//i.test(relPath) || relPath.startsWith("#") || relPath.startsWith("mailto:") || relPath.startsWith("tel:")) {
      return relPath;
    }
    return "../".repeat(pathDepth) + relPath;
  }

  /** Resolve a remote URL to an in-app path (or null if no local match). */
  function appPathFor(url) {
    if (!url) return null;
    if (urlMap[url]) return urlMap[url];
    // Try stripping trailing slash / fragment / query.
    const clean = url.split("#")[0].split("?")[0].replace(/\/$/, "");
    return urlMap[clean] || null;
  }

  function renderSuggestions() {
    suggestionsEl.textContent = "";
    if (!cannedSuggestions.length) {
      suggestionsWrap.style.display = "none";
      return;
    }
    suggestionsWrap.style.display = "";
    for (const item of cannedSuggestions) {
      if (item.hidden) continue;
      const chip = el("button", { class: "mt-chip", type: "button" }, item.question);
      chip.addEventListener("click", () => sendCanned(item));
      suggestionsEl.appendChild(chip);
    }
    suggestionsEl.classList.add("visible");
  }

  /** Build list of {keyword, item} triggers from hidden canned entries
   *  (e.g., location details). Sorted longest-first so "Fairmont, WV" matches
   *  before "Fairmont".
   */
  function getLinkTriggers() {
    const triggers = [];
    for (const item of cannedSuggestions) {
      if (!item.hidden || !Array.isArray(item.keywords)) continue;
      for (const kw of item.keywords) triggers.push({ kw, item });
    }
    triggers.sort((a, b) => b.kw.length - a.kw.length);
    return triggers;
  }

  function makeLocLinkEl(label, item) {
    const a = document.createElement("a");
    a.className = "mt-loc-link";
    a.href = "#";
    a.textContent = label;
    a.addEventListener("click", (e) => {
      e.preventDefault();
      sendCanned(item);
    });
    return a;
  }

  /** Render `text` into `container`, turning matched location keywords AND
   *  "[Location Details]" placeholders into clickable links. The placeholder
   *  binds to the most-recently-seen location keyword.
   */
  function appendLinkedText(container, text) {
    const triggers = getLinkTriggers();
    if (!triggers.length) {
      container.appendChild(document.createTextNode(text));
      return;
    }
    const escape = (s) => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
    const re = new RegExp(
      "(" + triggers.map((t) => escape(t.kw)).join("|") + "|\\[Location Details\\])",
      "g"
    );

    let lastIdx = 0;
    let lastItem = null;
    let m;
    while ((m = re.exec(text)) !== null) {
      if (m.index > lastIdx) {
        container.appendChild(document.createTextNode(text.slice(lastIdx, m.index)));
      }
      const matched = m[0];
      if (matched === "[Location Details]") {
        if (lastItem) container.appendChild(makeLocLinkEl(matched, lastItem));
        else container.appendChild(document.createTextNode(matched));
      } else {
        const t = triggers.find((x) => x.kw === matched);
        if (t) {
          lastItem = t.item;
          container.appendChild(makeLocLinkEl(matched, t.item));
        } else {
          container.appendChild(document.createTextNode(matched));
        }
      }
      lastIdx = m.index + matched.length;
    }
    if (lastIdx < text.length) {
      container.appendChild(document.createTextNode(text.slice(lastIdx)));
    }
  }

  async function loadSuggestions() {
    try {
      const res = await fetch(CONFIG.suggestionsUrl);
      if (!res.ok) return;
      cannedSuggestions = await res.json();
    } catch {
      cannedSuggestions = [];
    }
  }

  async function loadUrlMap() {
    try {
      const res = await fetch(CONFIG.urlMapUrl);
      if (!res.ok) return;
      urlMap = await res.json();
    } catch {
      urlMap = {};
    }
  }

  function sendCanned(item) {
    if (busy) return;
    appendUser(item.question);
    history.push({ role: "user", content: item.question });
    // Render the canned answer immediately - no LLM call.
    const msgEl = appendAssistantText("");
    renderAssistant(msgEl, item.answer, item.sources || [], {
      cards: item.cards || [],
      images: item.images || [],
    });
    history.push({ role: "assistant", content: item.answer });
    textarea.focus();
  }

  // ---------- State ----------

  /** Conversation history sent to the API (excluding system). */
  const history = [];
  let busy = false;

  // ---------- Event wiring ----------

  function openPanel() {
    panel.classList.add("open");
    launcher.classList.add("hidden");
    document.body.style.overflow = "hidden";
    textarea.focus();
  }

  function closePanel() {
    panel.classList.remove("open");
    launcher.classList.remove("hidden");
    document.body.style.overflow = "";
  }

  launcher.addEventListener("click", async () => {
    openPanel();
    if (messagesEl.children.length === 0) {
      appendAssistantText(CONFIG.greeting);
      if (!cannedSuggestions.length) await loadSuggestions();
      renderSuggestions();
    }
  });

  header.querySelector(".mt-close").addEventListener("click", closePanel);

  // Close on hardware back / browser back when chat is open
  window.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && panel.classList.contains("open")) closePanel();
  });

  textarea.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      send();
    }
  });

  sendBtn.addEventListener("click", send);

  // Prefetch url map (cheap, ~few KB) so cards/sources render with in-app links
  loadUrlMap();

  // ---------- Core ----------

  async function send() {
    const text = textarea.value.trim();
    if (!text || busy) return;
    textarea.value = "";
    setBusy(true);

    appendUser(text);
    history.push({ role: "user", content: text });

    // Graceful degradation: if no backend is configured (e.g. in an offline
    // APK build), tell the user that free-form questions need a connection.
    if (!CONFIG.apiUrl) {
      const msg = appendAssistantPlaceholder();
      renderAssistant(
        msg,
        "Free-form questions need a connection to our AI service. Please use a suggested question above, or call your nearest location for help.",
        [],
        {}
      );
      setBusy(false);
      textarea.focus();
      return;
    }

    const assistantMsg = appendAssistantPlaceholder();
    let buffer = "";
    let sources = [];
    let extras = {};

    try {
      const res = await fetch(CONFIG.apiUrl, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ messages: history }),
      });
      if (!res.ok || !res.body) {
        throw new Error(`HTTP ${res.status}`);
      }

      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let pending = "";

      while (true) {
        const { value, done } = await reader.read();
        if (done) break;
        pending += decoder.decode(value, { stream: true });

        let idx;
        while ((idx = pending.indexOf("\n\n")) !== -1) {
          const frame = pending.slice(0, idx);
          pending = pending.slice(idx + 2);
          if (!frame.startsWith("data:")) continue;
          const payload = frame.slice(5).trim();
          if (!payload) continue;
          let evt;
          try {
            evt = JSON.parse(payload);
          } catch {
            continue;
          }
          if (evt.type === "delta") {
            buffer += evt.text;
            renderAssistant(assistantMsg, buffer, sources, extras);
          } else if (evt.type === "sources") {
            sources = evt.sources || [];
            renderAssistant(assistantMsg, buffer, sources, extras);
          } else if (evt.type === "cards") {
            extras.cards = evt.cards || [];
            renderAssistant(assistantMsg, buffer, sources, extras);
          } else if (evt.type === "images") {
            extras.images = evt.images || [];
            renderAssistant(assistantMsg, buffer, sources, extras);
          } else if (evt.type === "error") {
            buffer = `⚠️ ${evt.error}`;
            renderAssistant(assistantMsg, buffer, [], {});
          }
        }
      }

      if (buffer) history.push({ role: "assistant", content: buffer });
    } catch (e) {
      renderAssistant(assistantMsg, `⚠️ Couldn't reach the chatbot (${e.message}). Please try again.`, [], {});
    } finally {
      setBusy(false);
      textarea.focus();
    }
  }

  function setBusy(b) {
    busy = b;
    sendBtn.disabled = b;
    textarea.disabled = b;
  }

  // ---------- DOM helpers ----------

  function appendUser(text) {
    const m = el("div", { class: "mt-msg user" }, text);
    messagesEl.appendChild(m);
    scrollDown();
  }

  function appendAssistantText(text) {
    const m = el("div", { class: "mt-msg assistant" }, text);
    messagesEl.appendChild(m);
    scrollDown();
    return m;
  }

  function appendAssistantPlaceholder() {
    const typing = el("div", { class: "mt-typing" }, [
      el("span"), el("span"), el("span"),
    ]);
    const m = el("div", { class: "mt-msg assistant" }, [typing]);
    messagesEl.appendChild(m);
    scrollDown();
    return m;
  }

  function renderCards(cards) {
    const grid = el("div", { class: "mt-cards" });
    for (const c of cards) {
      const href = c.app_path ? withPrefix(c.app_path) : (c.url || "#");
      const card = document.createElement("a");
      card.className = "mt-card";
      card.href = href;
      const imgWrap = document.createElement("div");
      imgWrap.className = "mt-card-img";
      if (c.image) {
        const img = document.createElement("img");
        img.loading = "lazy";
        img.src = withPrefix(c.image);
        img.alt = c.title || "";
        imgWrap.appendChild(img);
      } else {
        const fb = document.createElement("span");
        fb.className = "mt-card-img-fallback";
        fb.textContent = c.title || "Middletown Tractor";
        imgWrap.appendChild(fb);
      }
      const body = document.createElement("div");
      body.className = "mt-card-body";
      const t = document.createElement("div");
      t.className = "mt-card-title";
      t.textContent = c.title || "";
      body.appendChild(t);
      if (c.sub) {
        const s = document.createElement("div");
        s.className = "mt-card-sub";
        s.textContent = c.sub;
        body.appendChild(s);
      }
      card.appendChild(imgWrap);
      card.appendChild(body);
      // Close panel when navigating in-app so the destination page is visible.
      if (c.app_path) {
        card.addEventListener("click", () => closePanel());
      }
      grid.appendChild(card);
    }
    return grid;
  }

  function renderGallery(images) {
    const grid = el("div", { class: "mt-gallery" });
    for (const im of images) {
      const img = document.createElement("img");
      img.loading = "lazy";
      img.src = withPrefix(typeof im === "string" ? im : im.src);
      img.alt = (typeof im === "object" && im.alt) || "";
      grid.appendChild(img);
    }
    return grid;
  }

  function renderAssistant(msgEl, text, sources, extras) {
    msgEl.textContent = ""; // clear typing dots / prior content
    appendLinkedText(msgEl, text || "");

    if (extras && Array.isArray(extras.cards) && extras.cards.length) {
      msgEl.appendChild(renderCards(extras.cards));
    }
    if (extras && Array.isArray(extras.images) && extras.images.length) {
      msgEl.appendChild(renderGallery(extras.images));
    }

    if (sources && sources.length) {
      const seen = new Set();
      const unique = sources.filter((s) => {
        const key = s.app_path || s.url;
        if (seen.has(key)) return false;
        seen.add(key);
        return true;
      });
      const srcEl = el("div", { class: "mt-sources" });
      srcEl.appendChild(document.createTextNode("Sources: "));
      for (const s of unique.slice(0, 4)) {
        const localPath = s.app_path || appPathFor(s.url);
        const a = document.createElement("a");
        if (localPath) {
          a.href = withPrefix(localPath);
          a.addEventListener("click", () => closePanel());
        } else {
          a.href = s.url;
          a.target = "_blank";
          a.rel = "noopener";
        }
        a.textContent = s.title || s.url;
        srcEl.appendChild(a);
      }
      msgEl.appendChild(srcEl);
    }
    scrollDown();
  }

  function scrollDown() {
    messagesEl.scrollTop = messagesEl.scrollHeight;
  }

  function el(tag, attrs, children) {
    const node = document.createElement(tag);
    if (attrs) {
      for (const k in attrs) node.setAttribute(k, attrs[k]);
    }
    if (children == null) return node;
    if (Array.isArray(children)) {
      for (const c of children) node.appendChild(typeof c === "string" ? document.createTextNode(c) : c);
    } else if (typeof children === "string") {
      node.textContent = children;
    } else {
      node.appendChild(children);
    }
    return node;
  }
})();
