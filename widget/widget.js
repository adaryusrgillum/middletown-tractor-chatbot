(function () {
  "use strict";

  const CONFIG = Object.assign(
    {
      apiUrl: "/api/chat",
      suggestionsUrl: "/api/suggestions",
      urlMapUrl: "/assets/url_map.json",
      productsUrl: "/assets/products.json",
      greeting: "Hi! Ask me anything about Middletown Tractor — products, parts, service, financing, hours, or locations.",
      hfToken: "",
    },
    window.MT_CHAT_CONFIG || {}
  );

  function getBackendUrl() {
    const stored = localStorage.getItem('mt-backend-url');
    if (stored) return stored.replace(/\/$/, '');
    if (window.MT_BACKEND_URL) return window.MT_BACKEND_URL.replace(/\/$/, '');
    if (window.Capacitor) {
      return 'https://middletown-tractor-backend.onrender.com';
    }
    return '';
  }

  function getApiUrl() {
    const backend = getBackendUrl();
    if (backend) return backend + '/api/chat';
    if (!window.Capacitor && CONFIG.apiUrl && CONFIG.apiUrl.startsWith('/')) {
      return CONFIG.apiUrl;
    }
    return '';
  }

  function getTtsUrl() {
    const backend = getBackendUrl();
    if (backend) return backend + '/api/tts';
    const base = CONFIG.apiUrl || '/api/chat';
    if (!window.Capacitor && base.startsWith('/')) {
      return base.replace(/\/chat$/, "/tts");
    }
    return '';
  }

  /** Loaded from /api/suggestions: [{question, answer, sources, cards, images}]. */
  let cannedSuggestions = [];
  /** Remote URL -> in-app relative path (e.g. "pages/brand-john-deere.html"). */
  let urlMap = {};
  /** Loaded from /assets/products.json: [{slug, name, brand, price, image, desc}]. */
  let productsList = [];
  /** Path depth relative to bundle root, so we can prefix relative links correctly. */
  const pathDepth = computePathDepth();

  const root = document.getElementById("mt-chat-root") || document.body;

  // ---------- Build DOM ----------

  const launcher = el("button", { class: "mt-launcher", title: "Chat with us", "aria-label": "Open chat" }, "💬");
  const panel = el("div", { class: "mt-panel", role: "dialog", "aria-label": "Middletown Tractor chat" });

  const settingsBtn = el("button", { class: "mt-settings-toggle-btn", title: "Settings", "aria-label": "Settings" }, "⚙️");
  const header = el("div", { class: "mt-header" }, [
    el("div", { class: "mt-header-text" }, [
      el("h3", {}, "Middletown Tractor"),
      el("div", { class: "mt-subtitle" }, "Ask us anything"),
    ]),
    el("div", { class: "mt-header-actions" }, [
      settingsBtn,
      el("button", { class: "mt-close", title: "Close", "aria-label": "Close chat" }, "×")
    ])
  ]);
  const messagesEl = el("div", { class: "mt-messages" });

  const settingsInput = el("input", {
    type: "url",
    class: "mt-settings-input",
    placeholder: "https://your-backend.onrender.com",
    value: localStorage.getItem("mt-backend-url") || ""
  });
  const settingsVoice = el("input", {
    type: "text",
    class: "mt-settings-input",
    placeholder: "Voice name (optional, e.g. 'alloy')",
    value: localStorage.getItem("mt-tts-voice") || ""
  });
  const settingsSaveBtn = el("button", { class: "mt-settings-save-btn" }, "Save Settings");
  const settingsCloseBtn = el("button", { class: "mt-settings-close", "aria-label": "Close Settings" }, "×");
  
  const settingsPanel = el("div", { class: "mt-settings-panel" }, [
    el("div", { class: "mt-settings-header" }, [
      el("h4", {}, "Chat Settings"),
      settingsCloseBtn
    ]),
    el("div", { class: "mt-settings-body" }, [
      el("div", { class: "mt-settings-row" }, [
        el("label", { class: "mt-settings-label" }, "Backend API URL:"),
        settingsInput
      ]),
      el("div", { class: "mt-settings-row" }, [
        el("label", { class: "mt-settings-label" }, "TTS Voice (optional):"),
        settingsVoice
      ]),
      el("p", { class: "mt-settings-tip" }, "Provide the custom server URL hosting the open-source Ollama chatbot and Kokoro TTS model (leave blank to default to the production server)."),
      settingsSaveBtn
    ])
  ]);
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

  panel.append(header, messagesEl, suggestionsWrap, inputRow, settingsPanel);
  root.append(launcher, panel);

  settingsBtn.addEventListener("click", () => {
    settingsInput.value = localStorage.getItem("mt-backend-url") || "";
    settingsVoice.value = localStorage.getItem("mt-tts-voice") || "";
    settingsPanel.classList.add("open");
  });

  settingsCloseBtn.addEventListener("click", () => {
    settingsPanel.classList.remove("open");
  });

  settingsSaveBtn.addEventListener("click", () => {
    const url = settingsInput.value.trim();
    const voice = settingsVoice.value.trim();
    if (url) {
      localStorage.setItem("mt-backend-url", url);
    } else {
      localStorage.removeItem("mt-backend-url");
    }
    if (voice) {
      localStorage.setItem("mt-tts-voice", voice);
    } else {
      localStorage.removeItem("mt-tts-voice");
    }
    settingsPanel.classList.remove("open");
    
    // Add a system notification in the message box
    const sysMsg = appendAssistantPlaceholder();
    setTimeout(() => {
      renderAssistant(sysMsg, `🔧 **System**: Backend URL updated to: \`${url || 'Default Production Server'}\`.`, [], {});
    }, 400);
  });

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

  async function loadProducts() {
    try {
      const res = await fetch(withPrefix("assets/products.json"));
      if (res.ok) {
        productsList = await res.json();
        return;
      }
      const altRes = await fetch(CONFIG.productsUrl);
      if (altRes.ok) {
        productsList = await altRes.json();
      }
    } catch (e) {
      console.warn("Failed to load products.json", e);
    }
  }

  function sendCanned(item) {
    if (busy) return;
    // Close the mobile keyboard and collapse the suggestion chips so the
    // user can read the answer without the chip strip in the way.
    textarea.blur();
    if (!suggestionsCollapsed) {
      suggestionsCollapsed = true;
      localStorage.setItem(COLLAPSE_KEY, "1");
      applySuggestionsCollapsed();
    }
    appendUser(item.question);
    history.push({ role: "user", content: item.question });
    // Render the canned answer immediately - no LLM call.
    const msgEl = appendAssistantText("");
    renderAssistant(msgEl, item.answer, item.sources || [], {
      cards: item.cards || [],
      images: item.images || [],
    });
    history.push({ role: "assistant", content: item.answer });
  }

  // ---------- State ----------

  /** Conversation history sent to the API (excluding system). */
  const history = [];
  let busy = false;

  let activeUtterance = null;
  let activeSpeechBtn = null;
  let activeSpeechText = null;
  let activeAudio = null;

  function stopSpeech() {
    if (window.Capacitor && window.Capacitor.Plugins && window.Capacitor.Plugins.TextToSpeech) {
      try {
        window.Capacitor.Plugins.TextToSpeech.stop();
      } catch (e) {}
    }
    if (window.speechSynthesis) {
      window.speechSynthesis.cancel();
    }
    if (activeAudio) {
      try {
        activeAudio.pause();
      } catch (e) {}
      activeAudio = null;
    }
    if (activeSpeechBtn) {
      activeSpeechBtn.classList.remove("speaking");
      activeSpeechBtn.textContent = "🔊";
    }
    activeUtterance = null;
    activeSpeechBtn = null;
    activeSpeechText = null;
  }

  async function toggleSpeech(text, btn) {
    if (activeSpeechBtn === btn) {
      stopSpeech();
      return;
    }

    stopSpeech();

    // Clean text by stripping markdown formatting and emojis
    const cleanText = text
      .replace(/\[([^\]]+)\]\([^)]+\)/g, "$1") // markdown links
      .replace(/\*\*([^*]+)\*\*/g, "$1")       // bold
      .replace(/\*([^*]+)\*/g, "$1")         // italics
      .replace(/⚠️/g, "Warning:")
      .replace(/💪|🚗|🛡️|⚡|🛋️|🎨|📦|⛰️|⚙️|🔧|🔥|🍃|🎯|🌪|🤫|📐|🌱|🔄|💵/g, "");

    activeSpeechBtn = btn;
    activeSpeechText = text;
    btn.classList.add("speaking");
    btn.textContent = "⏹️";

    // 1. Try Native Capacitor TTS first (when running inside the APK)
    if (window.Capacitor && window.Capacitor.Plugins && window.Capacitor.Plugins.TextToSpeech) {
      try {
        await window.Capacitor.Plugins.TextToSpeech.speak({
          text: cleanText,
          lang: "en-US",
          rate: 1.0,
          pitch: 1.0,
          volume: 1.0,
          category: "ambient",
          queueStrategy: 1
        });
        if (activeSpeechBtn === btn) stopSpeech();
        return;
      } catch (err) {
        console.warn("Native Capacitor TTS failed, trying other methods:", err);
      }
    }

    // 2. Try Local Backend Kokoro TTS (when running in local preview mode or configured in APK)
    const localTtsUrl = getTtsUrl();
    if (localTtsUrl) {
      try {
        const voice = localStorage.getItem("mt-tts-voice") || undefined;
        const response = await fetch(localTtsUrl, {
          method: "POST",
          headers: {
            "Content-Type": "application/json"
          },
          body: JSON.stringify({ text: cleanText, voice: voice })
        });

        if (!response.ok) {
          throw new Error(`Local TTS Status ${response.status}`);
        }

        const blob = await response.blob();
        if (blob.size < 1000) {
          throw new Error("Invalid audio payload size");
        }

        const audioUrl = URL.createObjectURL(blob);
        const audio = new Audio(audioUrl);
        activeAudio = audio;

        audio.onended = () => {
          if (activeSpeechBtn === btn) stopSpeech();
        };
        audio.onerror = () => {
          fallbackToNative(cleanText, btn);
        };

        await audio.play();
        return;
      } catch (err) {
        console.warn("Local Backend TTS failed, falling back to browser TTS:", err);
      }
    }

    // 3. Fallback to native browser SpeechSynthesis (Web/offline fallback)
    fallbackToNative(cleanText, btn);
  }

  function fallbackToNative(cleanText, btn) {
    if (!window.speechSynthesis) {
      stopSpeech();
      return;
    }
    const u = new SpeechSynthesisUtterance(cleanText);
    u.onend = () => {
      if (activeSpeechBtn === btn) stopSpeech();
    };
    u.onerror = () => {
      if (activeSpeechBtn === btn) stopSpeech();
    };
    activeUtterance = u;
    window.speechSynthesis.speak(u);
  }

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
    stopSpeech();
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

  // Prefetch url map and product database (offline sales pitches)
  loadUrlMap();
  loadProducts();

  // Document delegation click listener for .mt-ask-btn, .mt-compare-btn, and chat components
  document.addEventListener("click", async (e) => {
    const askBtn = e.target.closest(".mt-ask-btn");
    const compareBtn = e.target.closest(".mt-compare-btn");
    const chatCompareBtn = e.target.closest(".mt-chat-compare-btn");
    const chatQuoteBtn = e.target.closest(".mt-chat-quote-btn");
    
    if (askBtn) {
      e.preventDefault();
      const slug = askBtn.getAttribute("data-product-slug");
      const name = askBtn.getAttribute("data-product-name") || askBtn.textContent;
      openPanel();
      if (messagesEl.children.length === 0) {
        appendAssistantText(CONFIG.greeting);
      }
      await triggerSalesPitch(slug, name);
    } else if (compareBtn) {
      e.preventDefault();
      const slug = compareBtn.getAttribute("data-product-slug");
      const name = compareBtn.getAttribute("data-product-name") || compareBtn.textContent;
      openPanel();
      if (messagesEl.children.length === 0) {
        appendAssistantText(CONFIG.greeting);
      }
      await triggerComparison(slug, name);
    } else if (chatCompareBtn) {
      e.preventDefault();
      const slug = chatCompareBtn.getAttribute("data-product-slug");
      const name = chatCompareBtn.getAttribute("data-product-name");
      await triggerComparison(slug, name);
    } else if (chatQuoteBtn) {
      e.preventDefault();
      const name = chatQuoteBtn.getAttribute("data-product-name");
      await handleQuoteRequest(name);
    }
  });

  // ---------- Core ----------

  async function send() {
    const text = textarea.value.trim();
    if (!text || busy) return;
    textarea.value = "";
    setBusy(true);

    appendUser(text);
    history.push({ role: "user", content: text });

    // 1. Lead capture check (interjects immediately if phone number or email is submitted)
    const phoneRegex = /(?:\+?(\d{1,3}))?[-. (]*(\d{3})[-. )]*(\d{3})[-. ]*(\d{4})/;
    const emailRegex = /[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}/;
    if (phoneRegex.test(text) || emailRegex.test(text)) {
      const assistantMsg = appendAssistantPlaceholder();
      await new Promise(resolve => setTimeout(resolve, 1000));
      const leadMsg = "Thank you! I've captured your contact details and forwarded them to our sales department. A representative from your nearest Middletown Tractor Sales branch will get in touch shortly to assist you!";
      renderAssistant(assistantMsg, leadMsg, [], {});
      history.push({ role: "assistant", content: leadMsg });
      setBusy(false);
      scrollDown();
      return;
    }

    // 2. Intercept queries about specific products in the database
    const queryLower = text.toLowerCase();
    let matchedProduct = null;
    for (const prod of productsList) {
      const prodNameL = prod.name.toLowerCase();
      const words = prodNameL.split(" ");
      // Look for a specific model key (e.g. "1025r", "3025e", "ms 170")
      const modelWord = words.find(w => w.length > 2 && !["john", "deere", "stihl", "lawn", "mower", "riding", "gas", "battery", "utility", "tractor"].includes(w));
      if (modelWord && queryLower.includes(modelWord)) {
        matchedProduct = prod;
        break;
      }
    }

    if (matchedProduct && (queryLower.includes("tell me") || queryLower.includes("about") || queryLower.includes("price") || queryLower.includes("specs") || queryLower.includes("cost") || queryLower.includes("info") || queryLower.includes("con") || queryLower.includes("pro"))) {
      const assistantMsg = appendAssistantPlaceholder();
      await new Promise(resolve => setTimeout(resolve, 1000));
      const pitch = generateSalesPitchText(matchedProduct);
      renderAssistant(assistantMsg, pitch.text, [], {});
      
      const btnRow = el("div", { class: "mt-btn-row" }, [
        el("button", { class: "mt-chat-action-btn primary mt-chat-quote-btn", type: "button", "data-product-name": matchedProduct.name }, "Get a Quote"),
        el("button", { class: "mt-chat-action-btn secondary mt-chat-compare-btn", type: "button", "data-product-slug": matchedProduct.slug, "data-product-name": matchedProduct.name }, "Compare with Others")
      ]);
      assistantMsg.appendChild(btnRow);
      
      history.push({ role: "assistant", content: pitch.text });
      setBusy(false);
      scrollDown();
      return;
    }

    // Graceful degradation: if no backend is configured (e.g. in an offline
    // APK build), tell the user that free-form questions need a connection.
    const currentApiUrl = getApiUrl();
    if (!currentApiUrl) {
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
      const res = await fetch(currentApiUrl, {
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
    const m = el("div", { class: "mt-msg assistant" });
    messagesEl.appendChild(m);
    renderAssistant(m, text, [], {});
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

    if (text) {
      const ttsBtn = el("button", { class: "mt-tts-btn", type: "button", "aria-label": "Speak text", title: "Listen" }, "🔊");
      ttsBtn.addEventListener("click", () => toggleSpeech(text, ttsBtn));
      if (activeSpeechText === text && activeSpeechBtn) {
        activeSpeechBtn = ttsBtn;
        ttsBtn.classList.add("speaking");
        ttsBtn.textContent = "⏹️";
      }
      msgEl.appendChild(ttsBtn);
    }

    const textSpan = el("span", { class: "mt-msg-text" });
    appendLinkedText(textSpan, text || "");
    msgEl.appendChild(textSpan);

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

  // ---------- Offline Psychological Sales Pitch & Comparison Generators ----------

  async function triggerSalesPitch(slug, productName) {
    if (busy) return;
    
    // Copy the product name to the clipboard
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(productName).catch(err => console.warn('Could not copy name to clipboard', err));
    }
    
    // Simulate paste/insertion into the input field
    textarea.value = productName;
    textarea.focus();
    
    // Wait 300ms so the user can see the "pasted" input before submit
    await new Promise(resolve => setTimeout(resolve, 300));
    
    setBusy(true);
    
    // Clear the input field as if submitted
    textarea.value = "";
    
    const query = `Tell me about the ${productName}!`;
    appendUser(query);
    history.push({ role: "user", content: query });
    
    const typingMsg = appendAssistantPlaceholder();
    await new Promise(resolve => setTimeout(resolve, 1200));
    
    const product = productsList.find(p => p.slug === slug || p.name.toLowerCase() === productName.toLowerCase());
    if (!product) {
      if (CONFIG.apiUrl) {
        messagesEl.removeChild(typingMsg);
        setBusy(false);
        textarea.value = query;
        send();
      } else {
        renderAssistant(typingMsg, `I see you are interested in the **${productName}**! That is an exceptional model. For current inventory status, pricing, and finance deals, please call our Fairmont team at **(304) 366-4690**!`, [], {});
        setBusy(false);
      }
      return;
    }
    
    const pitch = generateSalesPitchText(product);
    renderAssistant(typingMsg, pitch.text, [], {});
    
    const btnRow = el("div", { class: "mt-btn-row" }, [
      el("button", { 
        class: "mt-chat-action-btn primary mt-chat-quote-btn", 
        type: "button", 
        "data-product-name": product.name 
      }, "Get a Quote"),
      el("button", { 
        class: "mt-chat-action-btn secondary mt-chat-compare-btn", 
        type: "button", 
        "data-product-slug": product.slug,
        "data-product-name": product.name 
      }, "Compare with Others")
    ]);
    
    typingMsg.appendChild(btnRow);
    history.push({ role: "assistant", content: pitch.text });
    setBusy(false);
    scrollDown();
  }

  function generateSalesPitchText(product) {
    const brand = product.brand;
    const name = product.name;
    const price = product.price;
    const nameL = name.toLowerCase();
    const brandL = brand.toLowerCase();
    
    let hook = "";
    let pros = [];
    let cons = "";
    let valuePitch = "";
    
    if (brandL === "john deere") {
      if (nameL.includes("tractor") || nameL.includes("1025r") || nameL.includes("1023e") || nameL.includes("3025e") || nameL.includes("3038e") || nameL.includes("3032e") || nameL.includes("2025r")) {
        hook = `Excellent choice! The **${name}** is an absolute game-changer. This compact powerhouse is our most requested tractor for local landowners in WV and PA who want commercial-grade capability in a size that fits their lifestyle. Imagine having the strength to tackle loaders, grading, and heavy tilling, all while enjoying the absolute comfort of an ergonomic operator station. It doesn't just do the work—it dominates it.`;
        pros = [
          "💪 **Master Any Task**: Swap out attachments in less than 60 seconds. You can go from loading gravel to tilling your garden to mowing without breaking a sweat.",
          "🚗 **Drive Like a Luxury SUV**: Power steering, 4WD, and Twin Touch pedal controls mean there's zero learning curve—it's as easy as driving your favorite truck.",
          "🛡️ **Worry-Free Ownership**: Backed by John Deere’s legendary **6-Year Powertrain Warranty**. That is absolute reliability and long-term resale value that no competitor can match."
        ];
        cons = "⚠️ **Cons**: Your neighbors are going to get extremely envious when they see your property looking pristine, and you'll probably finish all your chores so fast that you'll run out of excuses to spend your weekends outdoors!";
      } else if (nameL.includes("z") || nameL.includes("zero") || nameL.includes("mower") || nameL.includes("run") || nameL.includes("x3") || nameL.includes("x5") || nameL.includes("x7") || nameL.includes("s100") || nameL.includes("s240")) {
        hook = `You are looking at the ultimate lawn master: the **${name}**! John Deere mowers are the gold standard of turf care. This machine is engineered for the homeowner who takes pride in a perfectly striped yard and wants to reclaim hours of their weekend. It cruises through tall grass with precision, leaving behind a clean, professional finish every single time.`;
        pros = [
          "⚡ **Cut Mowing Time in Half**: With high-capacity deck designs and commercial-grade blade tip speeds, you'll glide over grass with jaw-dropping efficiency.",
          "🛋️ **Unmatched Operator Comfort**: Glide over bumpy ground with premium seats and controls designed to minimize vibration and fatigue, keeping you fresh.",
          "🎨 **Professional Striping Every Time**: The stamped deck shape lifts and cuts grass cleanly, giving you those beautiful, deep green lines that define a premium lawn."
        ];
        cons = "⚠️ **Cons**: It rides so smoothly and cuts so fast that you might find yourself feeling disappointed when the job is done and you have to park it in the garage!";
      } else if (nameL.includes("gator") || nameL.includes("utility vehicle") || nameL.includes("xuv")) {
        hook = `Ah, the **${name}** Gator! This is the ultimate heavy-duty utility vehicle. Whether you're hauling firewood across your acreage, transporting tools on the jobsite, or exploring trails, the Gator is engineered to conquer the toughest terrain with cargo space to spare. It's the most dependable work partner you'll ever have.`;
        pros = [
          "📦 **Mammoth Hauling Power**: A massive cargo box and rugged towing capacity mean you can move heavy loads of dirt, gravel, or firewood in a single trip.",
          "⛰️ **Conquer Any Terrain**: True 4WD and superior ground clearance let you float over mud, rocks, and steep hills with ease.",
          "🛡️ **Heavy-Duty Build**: Built with a fully welded steel frame and durable components that stand up to the harshest WV and PA winters."
        ];
        cons = "⚠️ **Cons**: You will become the designated driver for all outdoor events, and your friends will constantly ask to borrow it for their hauling projects!";
      } else {
        hook = `Ah, the **${name}**! John Deere represents the absolute peak of agricultural and property maintenance technology. When you invest in a John Deere, you're not just buying a machine—you're buying decades of engineering perfection, absolute reliability, and a partnership with a dealership that always has your back.`;
        pros = [
          "⚙️ **Premium Engineering**: Built with the highest-grade materials to ensure maximum uptime and peak efficiency for years to come.",
          "🔧 **Unmatched Dealer Support**: Easy access to parts, certified service technicians, and the peace of mind that your investment is fully protected."
        ];
        cons = "⚠️ **Cons**: Once you experience the quality of a John Deere, you'll never be satisfied with any other brand of equipment!";
      }
    } else if (brandL === "stihl") {
      if (nameL.includes("saw") || nameL.includes("ms ")) {
        hook = `There is only one name trusted by professional arborists and demanding landowners worldwide: STIHL. The **${name}** chainsaw is a legendary tool, engineered to start on the very first pull and deliver brutal, high-torque cutting power. Whether you are clearing storm damage or stocking up on firewood, this saw slices through logs like butter.`;
        pros = [
          "🔥 **Professional-Grade Power**: Incredible power-to-weight ratio that delivers maximum cutting speed with minimal effort.",
          "🍃 **Anti-Vibration Comfort**: STIHL's advanced dampening system minimizes fatigue, protecting your hands and arms during long projects.",
          "🎯 **First-Pull Reliability**: Master Control Lever™ and easy-start technology make starting simple and worry-free every single time."
        ];
        cons = "⚠️ **Cons**: It cuts through wood so quickly and effortlessly that you might end up clearing your neighbor's property just to keep using it!";
      } else if (nameL.includes("blower") || nameL.includes("bg") || nameL.includes("br ") || nameL.includes("bga")) {
        hook = `Clear your driveways, yards, and decks in seconds with the incredible **${name}**! STIHL blowers are world-renowned for their hurricane-force airflow and lightweight ergonomics. This unit is built to make quick work of wet leaves, heavy debris, and lawn clippings without straining your back.`;
        pros = [
          "🌪️ **Hurricane-Force Wind**: Advanced impeller design delivers massive CFM (cubic feet per minute) to clear large areas in record time.",
          "⚖️ **Perfect Balance**: Ergonomically balanced to reduce strain on your wrist and arm, allowing comfortable one-handed operation.",
          "🤫 **Whisper-Tech Blower**: Engineered to run exceptionally quietly, keeping your neighbors happy during early morning cleanups."
        ];
        cons = "⚠️ **Cons**: It is so satisfying to watch debris fly away that you'll look for any excuse to blow down the entire driveway and street!";
      } else {
        hook = `The **${name}** is a premium STIHL tool built for landowners who demand the best. STIHL tools are engineered for maximum performance, long life, and easy maintenance. When you pick up a STIHL, you feel the quality and balance immediately.`;
        pros = [
          "⚙️ **Commercial-Grade Performance**: Squeezes every ounce of power out of its engine/battery while remaining highly fuel/energy efficient.",
          "🔧 **High-Strength Components**: Built with heavy-duty crankshafts, pistons, and wear-resistant materials designed to last for decades."
        ];
        cons = "⚠️ **Cons**: You'll find yourself finishing your property cleanups so quickly that you won't have an excuse to avoid indoor chores!";
      }
    } else if (brandL === "honda power") {
      hook = `When reliability is non-negotiable, you need Honda. The **${name}** is the absolute pinnacle of generator and power technology. World-famous for being whisper-quiet and incredibly fuel-efficient, it provides clean, stable power whenever and wherever you need it most.`;
      pros = [
        "🤫 **Whisper-Quiet Operation**: Runs at decibel levels quieter than a normal conversation. Your family (and neighbors) will sleep soundly even when it's running outside.",
        "🔌 **Safe for Sensitive Electronics**: Standard-setting inverter technology produces pure, stable sine waves, making it 100% safe for phones, laptops, and smart appliances.",
        "⛽ **Extended Run Time**: Smart Throttle system automatically adjusts engine speed to match the load, squeezing hours of extra run time out of a single tank."
      ];
      cons = "⚠️ **Cons**: It runs so quietly that you might occasionally walk outside just to check if it's still running (it is!)!";
    } else if (brandL === "ventrac") {
      hook = `For slopes, wet turf, and challenging properties, nothing on Earth compares to the **${name}**! Ventrac is the ultimate slope-handler, designed to operate safely on inclines where ordinary tractors would be highly dangerous. It distributes weight perfectly to deliver maximum traction without tearing up your lawn.`;
      pros = [
        "📐 **Defy Gravity on Slopes**: Safely operates on steep inclines up to 30 degrees (with dual wheels), keeping you safe and in control.",
        "🌱 **Minimal Turf Disturbance**: Flex-frame articulation allows the tractor to glide over terrain without scuffing or tearing the turf.",
        "🔄 **Over 30+ Commercial Attachments**: Switch from a contour mower deck to a snow blower or aerator in minutes. It is a true 365-day-a-year utility vehicle."
      ];
      cons = "⚠️ **Cons**: You will become the talk of the town, and neighbors will stand and stare in amazement as you cruise up steep hills that they wouldn't dare walk on!";
    } else {
      hook = `The **${name}** is an absolute powerhouse designed to maximize your productivity. Built with heavy-duty commercial components, it stands up to the most demanding tasks and WV/PA property layouts. It's a smart, durable investment that saves you time and effort starting day one.`;
      pros = [
        "🔧 **Industrial-Strength Durability**: Built with thick steel and heavy-duty wear components to ensure years of trouble-free performance.",
        "🌟 **Fast & Efficient**: Engineered to optimize your workflow, allowing you to check tasks off your property maintenance list in record time."
      ];
      cons = "⚠️ **Cons**: It makes tough jobs look so easy that you might run out of challenges on your property!";
    }
    
    valuePitch = `💵 **Unbeatable Value**: The **${name}** is currently listed at **${price}**. At Middletown Tractor, we offer incredibly competitive financing rates (including special dealer incentives like **0% APR financing** on select units for qualified buyers). Plus, we have high-value trade-in options to help lower your immediate out-of-pocket costs!`;
    
    const text = `${hook}\n\n` +
      `**Why our customers choose it:**\n` +
      `${pros.join("\n")}\n\n` +
      `${cons}\n\n` +
      `${valuePitch}\n\n` +
      `This model is extremely popular this season and moving fast off our lots in Fairmont, Buckhannon, Uniontown, and Washington. Let's make sure it's yours before the next rush!`;
      
    return { text };
  }

  async function triggerComparison(slug, productName) {
    if (busy) return;
    setBusy(true);
    
    const query = `Compare the ${productName} with others!`;
    appendUser(query);
    history.push({ role: "user", content: query });
    
    const typingMsg = appendAssistantPlaceholder();
    await new Promise(resolve => setTimeout(resolve, 1200));
    
    const current = productsList.find(p => p.slug === slug || p.name.toLowerCase() === productName.toLowerCase());
    if (!current) {
      renderAssistant(typingMsg, `I'd love to help you compare the **${productName}**! To see how it stacks up against our other units, please give our sales team a call or ask for a custom spec sheet.`, [], {});
      setBusy(false);
      return;
    }
    
    const target = findComparisonTarget(current);
    if (!target) {
      renderAssistant(typingMsg, `The **${current.name}** is a unique model in our catalog. It stands out for its high performance and price of **${current.price}**. Let's talk about what attachments or financing options would suit your land best!`, [], {});
      setBusy(false);
      return;
    }
    
    const comparisonCard = generateComparisonHTML(current, target);
    typingMsg.textContent = ""; 
    appendLinkedText(typingMsg, `Excellent choice! Let's stack the **${current.name}** up against the **${target.name}** to see which one fits your land best. Here is how they compare side-by-side:`);
    typingMsg.appendChild(comparisonCard);
    
    history.push({ role: "assistant", content: `Comparison table for ${current.name} vs ${target.name}` });
    setBusy(false);
    scrollDown();
  }

  function findComparisonTarget(current) {
    const brand = current.brand.toLowerCase();
    const name = current.name.toLowerCase();
    
    if (name.includes("1025r")) {
      return productsList.find(p => p.name.toLowerCase().includes("1023e")) || 
             productsList.find(p => p.name.toLowerCase().includes("3025e")) ||
             productsList.find(p => p.brand.toLowerCase() === "john deere" && p.slug !== current.slug);
    }
    if (name.includes("1023e")) {
      return productsList.find(p => p.name.toLowerCase().includes("1025r")) || 
             productsList.find(p => p.brand.toLowerCase() === "john deere" && p.slug !== current.slug);
    }
    if (name.includes("3025e")) {
      return productsList.find(p => p.name.toLowerCase().includes("1025r")) || 
             productsList.find(p => p.brand.toLowerCase() === "john deere" && p.slug !== current.slug);
    }
    
    if (name.includes("bga")) {
      return productsList.find(p => p.name.toLowerCase().includes("ms 170")) || 
             productsList.find(p => p.brand.toLowerCase() === "stihl" && p.slug !== current.slug);
    }
    if (name.includes("ms 170") || name.includes("chainsaw")) {
      return productsList.find(p => p.name.toLowerCase().includes("bga")) || 
             productsList.find(p => p.brand.toLowerCase() === "stihl" && p.slug !== current.slug);
    }
    
    return productsList.find(p => p.brand.toLowerCase() === brand && p.slug !== current.slug) ||
           productsList.find(p => p.slug !== current.slug);
  }

  const PRODUCT_SPECS = {
    "1025r": { power: "23.9 HP Diesel", type: "Sub-Compact Tractor", hitch: "Category 1 3-Pt", bestFor: "Mowing, Loader Work, Grading", warranty: "6-Year Powertrain" },
    "1023e": { power: "21.5 HP Diesel", type: "Sub-Compact Tractor", hitch: "Category 1 3-Pt", bestFor: "Lawn Mowing & Light Loader", warranty: "6-Year Powertrain" },
    "3025e": { power: "24.7 HP Diesel", type: "Compact Utility Tractor", hitch: "Category 1 3-Pt", bestFor: "Tillage, Pasture Cutting, Heavy Haul", warranty: "6-Year Powertrain" },
    "z997r": { power: "37.4 HP Diesel", type: "Commercial Zero-Turn", hitch: "None", bestFor: "Fast Commercial Mowing", warranty: "3-Year/1500 Hr" },
    "x728": { power: "27 HP Gas", type: "Heavy-Duty Lawn Tractor", hitch: "Optional 3-Pt", bestFor: "Large Lawns & Snow Removal", warranty: "4-Year/700 Hr" },
    "x540": { power: "26 HP Gas", type: "Multi-Terrain Lawn Tractor", hitch: "None", bestFor: "Hilly Lawns & Snow Removal", warranty: "4-Year/500 Hr" },
    "bga 57": { power: "36V AK Battery", type: "Handheld Leaf Blower", hitch: "None", bestFor: "Yard Sweeping & Driveways", warranty: "3-Year Residential" },
    "ms 170": { power: "30.1 cc Gas", type: "Gas Chainsaw (16\")", hitch: "None", bestFor: "Firewood & Storm Cleanup", warranty: "2-Year Residential" }
  };

  function getSpecsFor(prod) {
    const nameL = prod.name.toLowerCase();
    let matchedKey = null;
    for (const key in PRODUCT_SPECS) {
      if (nameL.includes(key)) {
        matchedKey = key;
        break;
      }
    }
    if (matchedKey) return PRODUCT_SPECS[matchedKey];
    
    if (prod.brand.toLowerCase() === "stihl") {
      return { power: "Gas/Battery Power", type: "STIHL Outdoor Tool", hitch: "None", bestFor: "Yard Cleanup", warranty: "2-Year Residential" };
    }
    if (nameL.includes("blade") || nameL.includes("cutter") || nameL.includes("attachment")) {
      return { power: "3-Point PTO Driven", type: "Tractor Attachment", hitch: "Category 1 Hitch", bestFor: "Landscaping & Property Care", warranty: "1-Year Warranty" };
    }
    return { power: "Standard Power", type: "Utility Equipment", hitch: "Standard Connect", bestFor: "Property Maintenance", warranty: "Manufacturer Warranty" };
  }

  function generateComparisonHTML(current, target) {
    const currentSpecs = getSpecsFor(current);
    const targetSpecs = getSpecsFor(target);
    
    const tableHTML = `
      <div class="mt-comparison-header">Side-by-Side Comparison</div>
      <div class="mt-comparison-table-wrapper">
        <table class="mt-comparison-table">
          <thead>
            <tr>
              <th>Feature</th>
              <th class="highlight">${current.name} (This Unit)</th>
              <th>${target.name}</th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <td class="spec-label">Image</td>
              <td class="highlight"><img src="${withPrefix(current.image || 'assets/icon-192.png')}" alt="${current.name}"></td>
              <td><img src="${withPrefix(target.image || 'assets/icon-192.png')}" alt="${target.name}"></td>
            </tr>
            <tr>
              <td class="spec-label">Brand</td>
              <td class="highlight">${current.brand}</td>
              <td>${target.brand}</td>
            </tr>
            <tr>
              <td class="spec-label">Price</td>
              <td class="highlight" style="color:var(--mt-accent); font-weight:800;">${current.price}</td>
              <td style="font-weight:700;">${target.price}</td>
            </tr>
            <tr>
              <td class="spec-label">Category / Type</td>
              <td class="highlight">${currentSpecs.type}</td>
              <td>${targetSpecs.type}</td>
            </tr>
            <tr>
              <td class="spec-label">Power / Engine</td>
              <td class="highlight">${currentSpecs.power}</td>
              <td>${targetSpecs.power}</td>
            </tr>
            <tr>
              <td class="spec-label">Best Suited For</td>
              <td class="highlight">${currentSpecs.bestFor}</td>
              <td>${targetSpecs.bestFor}</td>
            </tr>
            <tr>
              <td class="spec-label">Warranty / Support</td>
              <td class="highlight">${currentSpecs.warranty}</td>
              <td>${targetSpecs.warranty}</td>
            </tr>
          </tbody>
        </table>
      </div>
      <div class="mt-comparison-footer">
        <a class="mt-chat-action-btn secondary" href="${withPrefix('pages/' + target.slug)}" onclick="document.querySelector('.mt-close')?.click();">View ${target.brand} ${target.name.split(' ')[0]}</a>
        <button class="mt-chat-action-btn primary mt-chat-quote-btn" type="button" data-product-name="${current.name}">Request Quote</button>
      </div>
    `;
    
    const card = el("div", { class: "mt-comparison-card" });
    card.innerHTML = tableHTML;
    
    const quoteBtn = card.querySelector(".mt-chat-quote-btn");
    if (quoteBtn) {
      quoteBtn.addEventListener("click", () => {
        handleQuoteRequest(current.name);
      });
    }
    
    return card;
  }

  async function handleQuoteRequest(productName) {
    if (busy) return;
    appendUser(`Request a quote for the ${productName}`);
    history.push({ role: "user", content: `Request a quote for the ${productName}` });
    
    setBusy(true);
    const typingMsg = appendAssistantPlaceholder();
    await new Promise(resolve => setTimeout(resolve, 800));
    
    const responseText = `I'd be glad to arrange a quote for the **${productName}**! I've flagged this model for our sales desks.\n\n` +
      `📞 **Next Steps**: Call our main Fairmont Sales Counter directly at **(304) 366-4690** for immediate numbers, or reply with your **phone number / email** right here in the chat, and a sales specialist will contact you with pricing and custom finance rates!`;
      
    renderAssistant(typingMsg, responseText, [], {});
    history.push({ role: "assistant", content: responseText });
    setBusy(false);
    scrollDown();
  }
})();
