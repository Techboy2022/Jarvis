/* JARVIS front-end: chat list, streaming, settings, voice input. */
(function () {
  "use strict";

  const $ = (id) => document.getElementById(id);

  const el = {
    sidebar: $("sidebar"),
    chatList: $("chat-list"),
    search: $("search"),
    newChat: $("new-chat"),
    toggleSidebar: $("toggle-sidebar"),
    title: $("chat-title"),
    modelSelect: $("model-select"),
    exportChat: $("export-chat"),
    deleteChat: $("delete-chat"),
    messages: $("messages"),
    empty: $("empty"),
    input: $("input"),
    send: $("send"),
    stop: $("stop"),
    mic: $("mic"),
    meta: $("meta"),
    error: $("composer-error"),
    status: $("status"),
    statusText: $("status-text"),
    settings: $("settings"),
    openSettings: $("open-settings"),
    closeSettings: $("close-settings"),
    saveSettings: $("save-settings"),
    clearAll: $("clear-all"),
    setModel: $("set-model"),
    setSystem: $("set-system"),
    setTemp: $("set-temp"),
    setTopp: $("set-topp"),
    setCtx: $("set-ctx"),
    setPredict: $("set-predict"),
    setThreads: $("set-threads"),
    setKeepAlive: $("set-keepalive"),
    setHistory: $("set-history"),
    setShowThink: $("set-showthink"),
    tempVal: $("temp-val"),
    toppVal: $("topp-val"),
    settingsHint: $("settings-hint"),
  };

  const state = {
    chats: [],
    chatId: null,
    conf: {},
    models: [],
    streaming: false,
    controller: null,
    showThink: localStorage.getItem("jarvis.showThink") !== "0",
  };

  /* ------------------------------------------------------------- helpers */

  async function api(path, options) {
    const response = await fetch(path, Object.assign({
      headers: { "Content-Type": "application/json" },
    }, options || {}));
    if (!response.ok) {
      let detail = "HTTP " + response.status;
      try {
        const body = await response.json();
        if (body.detail) detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
      } catch (_) { /* non-JSON error body */ }
      throw new Error(detail);
    }
    return response.status === 204 ? null : response.json();
  }

  function showError(message) {
    el.error.textContent = message;
    el.error.hidden = !message;
  }

  function timeAgo(seconds) {
    const delta = Date.now() / 1000 - seconds;
    if (delta < 60) return "just now";
    if (delta < 3600) return Math.floor(delta / 60) + "m ago";
    if (delta < 86400) return Math.floor(delta / 3600) + "h ago";
    return Math.floor(delta / 86400) + "d ago";
  }

  function scrollToBottom(force) {
    const box = el.messages;
    const nearBottom = box.scrollHeight - box.scrollTop - box.clientHeight < 160;
    if (force || nearBottom) box.scrollTop = box.scrollHeight;
  }

  /* --------------------------------------------------------- chat list UI */

  async function loadChats(query) {
    if (query) {
      const { results } = await api("/api/search?q=" + encodeURIComponent(query));
      renderChatList(results.map((r) => Object.assign({ message_count: 0, pinned: false }, r)));
      return;
    }
    const { chats } = await api("/api/chats");
    state.chats = chats;
    renderChatList(chats);
    const current = chats.find((chat) => chat.id === state.chatId);
    if (current) el.title.textContent = current.title;
  }

  function renderChatList(chats) {
    el.chatList.textContent = "";
    chats.forEach((chat) => {
      const item = document.createElement("div");
      item.className = "chat-item" + (chat.id === state.chatId ? " active" : "");
      item.title = chat.title + " — " + timeAgo(chat.updated_at);

      const pin = document.createElement("span");
      pin.className = "pin" + (chat.pinned ? " on" : "");
      pin.textContent = chat.pinned ? "★" : "☆";
      pin.onclick = async (event) => {
        event.stopPropagation();
        await api("/api/chats/" + chat.id, {
          method: "PATCH",
          body: JSON.stringify({ pinned: !chat.pinned }),
        });
        loadChats(el.search.value.trim());
      };

      const name = document.createElement("span");
      name.className = "name";
      name.textContent = chat.title;

      item.append(pin, name);
      item.onclick = () => openChat(chat.id);
      el.chatList.appendChild(item);
    });
  }

  /* ---------------------------------------------------------- message DOM */

  function messageNode(role) {
    const wrapper = document.createElement("div");
    wrapper.className = "msg " + role;

    const who = document.createElement("div");
    who.className = "who";
    who.textContent = role === "user" ? "YOU" : "J";

    const bubble = document.createElement("div");
    bubble.className = "bubble";

    const think = document.createElement("details");
    think.className = "think";
    think.hidden = true;
    const summary = document.createElement("summary");
    summary.textContent = "Reasoning";
    const thinkBody = document.createElement("div");
    thinkBody.className = "think-body";
    think.append(summary, thinkBody);

    const body = document.createElement("div");
    body.className = "body";

    const stats = document.createElement("div");
    stats.className = "stats";

    const tools = document.createElement("div");
    tools.className = "tools";

    bubble.append(think, body, stats, tools);
    wrapper.append(who, bubble);
    wrapper._parts = { body, think, thinkBody, stats, tools };
    return wrapper;
  }

  function toolButton(label, handler) {
    const button = document.createElement("button");
    button.className = "copy-btn";
    button.type = "button";
    button.textContent = label;
    button.onclick = handler;
    return button;
  }

  function paintMessage(node, message) {
    const { body, think, thinkBody, stats, tools } = node._parts;
    if (message.role === "user") {
      body.textContent = message.content;
      body.style.whiteSpace = "pre-wrap";
    } else {
      body.innerHTML = MD.render(message.content);
      wireCopyButtons(body);
    }

    if (message.thinking) {
      thinkBody.textContent = message.thinking;
      think.hidden = !state.showThink;
    }

    if (message.stats && message.stats.tokens) {
      const bits = [message.stats.tokens + " tok"];
      if (message.stats.tokens_per_second) bits.push(message.stats.tokens_per_second + " tok/s");
      if (message.stats.first_token_seconds) bits.push(message.stats.first_token_seconds + "s to first token");
      stats.textContent = bits.join(" · ");
    } else if (message.stats && message.stats.stopped) {
      stats.textContent = "stopped";
    }

    tools.textContent = "";
    tools.appendChild(toolButton("copy", () => navigator.clipboard.writeText(message.content)));
    if (message.role === "assistant") {
      tools.appendChild(toolButton("regenerate", () => regenerate()));
    }
  }

  function wireCopyButtons(scope) {
    scope.querySelectorAll(".codeblock .copy-btn").forEach((button) => {
      button.onclick = () => {
        const code = button.closest(".codeblock").querySelector("code").textContent;
        navigator.clipboard.writeText(code);
        button.textContent = "copied";
        setTimeout(() => { button.textContent = "copy"; }, 1200);
      };
    });
  }

  /* --------------------------------------------------------------- chats */

  async function openChat(chatId) {
    if (state.streaming) stopStream();
    const chat = await api("/api/chats/" + chatId);
    state.chatId = chat.id;
    localStorage.setItem("jarvis.chat", chat.id);
    el.title.textContent = chat.title;
    el.messages.textContent = "";
    chat.messages.forEach((message) => {
      const node = messageNode(message.role);
      paintMessage(node, message);
      el.messages.appendChild(node);
    });
    if (!chat.messages.length) el.messages.appendChild(el.empty);
    renderChatList(state.chats);
    scrollToBottom(true);
    el.input.focus();
  }

  async function newChat() {
    const chat = await api("/api/chats", { method: "POST", body: JSON.stringify({}) });
    await loadChats();
    await openChat(chat.id);
  }

  async function ensureChat() {
    if (state.chatId) return state.chatId;
    const chat = await api("/api/chats", { method: "POST", body: JSON.stringify({}) });
    state.chatId = chat.id;
    await loadChats();
    return chat.id;
  }

  /* ------------------------------------------------------------ streaming */

  function setStreaming(on) {
    state.streaming = on;
    el.send.hidden = on;
    el.stop.hidden = !on;
    el.input.disabled = false;
  }

  function stopStream() {
    if (state.controller) state.controller.abort();
  }

  async function streamTurn(url, payload) {
    showError("");
    const node = messageNode("assistant");
    el.messages.appendChild(node);
    const { body, think, thinkBody, stats } = node._parts;
    body.classList.add("cursor");
    scrollToBottom(true);

    let answer = "";
    let reasoning = "";
    let dirty = false;
    let finalMessage = null;

    const paint = () => {
      if (!dirty) return;
      dirty = false;
      body.innerHTML = MD.render(answer);
      wireCopyButtons(body);
      if (reasoning) {
        thinkBody.textContent = reasoning;
        thinkBody.scrollTop = thinkBody.scrollHeight;
        think.hidden = !state.showThink;
        if (!answer && state.showThink) think.open = true;
      }
      scrollToBottom(false);
    };
    // Repaint on a timer instead of per token: re-rendering markdown for every
    // token pins the CPU that the model needs.
    const timer = setInterval(paint, 70);

    state.controller = new AbortController();
    setStreaming(true);
    el.meta.textContent = "thinking…";

    try {
      const response = await fetch(url, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
        signal: state.controller.signal,
      });
      if (!response.ok) {
        let detail = "HTTP " + response.status;
        try { detail = (await response.json()).detail || detail; } catch (_) {}
        throw new Error(detail);
      }

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";

      while (true) {
        const { value, done } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const frames = buffer.split("\n\n");
        buffer = frames.pop();
        for (const frame of frames) {
          const line = frame.trim();
          if (!line.startsWith("data:")) continue;
          let event;
          try { event = JSON.parse(line.slice(5).trim()); } catch (_) { continue; }

          if (event.type === "token") {
            answer += event.content;
            dirty = true;
          } else if (event.type === "think") {
            reasoning += event.content;
            dirty = true;
            el.meta.textContent = "reasoning…";
          } else if (event.type === "start") {
            el.meta.textContent = "generating with " + event.model + "…";
          } else if (event.type === "error") {
            throw new Error(event.error);
          } else if (event.type === "done") {
            finalMessage = event.message;
          }
        }
      }
    } catch (error) {
      if (error.name === "AbortError") {
        el.meta.textContent = "stopped";
      } else {
        showError(error.message);
        el.meta.textContent = "";
      }
    } finally {
      clearInterval(timer);
      dirty = true;
      paint();
      body.classList.remove("cursor");
      setStreaming(false);
      state.controller = null;
    }

    if (finalMessage) {
      paintMessage(node, finalMessage);
      const s = finalMessage.stats;
      el.meta.textContent = s && s.tokens_per_second ? s.tokens_per_second + " tok/s · " + s.tokens + " tokens" : "";
    } else if (!answer) {
      node.remove();
    } else {
      // Aborted mid-stream: the server persisted the partial reply, so pull
      // the canonical copy back in.
      openChat(state.chatId);
    }
    loadChats(el.search.value.trim());
  }

  async function send() {
    const text = el.input.value.trim();
    if (!text || state.streaming) return;
    const chatId = await ensureChat();

    el.input.value = "";
    el.input.style.height = "auto";
    if (el.empty.parentElement) el.empty.remove();

    const node = messageNode("user");
    paintMessage(node, { role: "user", content: text });
    el.messages.appendChild(node);
    scrollToBottom(true);

    await streamTurn("/api/chats/" + chatId + "/messages", {
      message: text,
      model: el.modelSelect.value || null,
    });
    el.input.focus();
  }

  async function regenerate() {
    if (state.streaming || !state.chatId) return;
    const bubbles = el.messages.querySelectorAll(".msg");
    if (bubbles.length) bubbles[bubbles.length - 1].remove();
    await streamTurn("/api/chats/" + state.chatId + "/regenerate", {});
  }

  /* -------------------------------------------------------------- system */

  async function refreshHealth() {
    try {
      const health = await api("/api/health");
      if (health.ok) {
        el.status.className = "status ok";
        el.statusText.textContent = "online · " + health.model + (health.model_loaded ? " (loaded)" : "");
      } else {
        el.status.className = "status bad";
        el.statusText.textContent = "Ollama offline";
        showError(health.error);
      }
    } catch (error) {
      el.status.className = "status bad";
      el.statusText.textContent = "server unreachable";
    }
  }

  async function loadModels() {
    try {
      const { models } = await api("/api/models");
      state.models = models;
      [el.modelSelect, el.setModel].forEach((select) => {
        select.textContent = "";
        models.forEach((model) => {
          const option = document.createElement("option");
          option.value = model.name;
          option.textContent = model.parameter_size
            ? model.name + " · " + model.parameter_size + " " + (model.quantization || "")
            : model.name;
          select.appendChild(option);
        });
        select.value = state.conf.model || (models[0] && models[0].name) || "";
      });
      if (!models.length) el.settingsHint.textContent = "No models installed. Run: ollama pull qwen3:4b";
    } catch (error) {
      el.settingsHint.textContent = error.message;
    }
  }

  async function loadSettings() {
    state.conf = await api("/api/settings");
    el.setSystem.value = state.conf.system_prompt;
    el.setTemp.value = state.conf.temperature;
    el.setTopp.value = state.conf.top_p;
    el.setCtx.value = state.conf.num_ctx;
    el.setPredict.value = state.conf.num_predict;
    el.setThreads.value = state.conf.num_thread;
    el.setKeepAlive.value = state.conf.keep_alive;
    el.setHistory.value = state.conf.history_limit;
    el.setShowThink.checked = state.showThink;
    el.tempVal.textContent = Number(state.conf.temperature).toFixed(2);
    el.toppVal.textContent = Number(state.conf.top_p).toFixed(2);
  }

  async function saveSettings() {
    state.showThink = el.setShowThink.checked;
    localStorage.setItem("jarvis.showThink", state.showThink ? "1" : "0");
    try {
      state.conf = await api("/api/settings", {
        method: "PUT",
        body: JSON.stringify({
          model: el.setModel.value || null,
          system_prompt: el.setSystem.value,
          temperature: Number(el.setTemp.value),
          top_p: Number(el.setTopp.value),
          num_ctx: Number(el.setCtx.value),
          num_predict: Number(el.setPredict.value),
          num_thread: Number(el.setThreads.value),
          keep_alive: el.setKeepAlive.value,
          history_limit: Number(el.setHistory.value),
        }),
      });
      el.modelSelect.value = state.conf.model;
      el.settings.hidden = true;
      refreshHealth();
      if (state.chatId) openChat(state.chatId);
    } catch (error) {
      el.settingsHint.textContent = error.message;
    }
  }

  /* --------------------------------------------------------- voice input */

  function setupVoice() {
    const Recognition = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!Recognition) {
      el.mic.title = "Speech recognition is not supported in this browser";
      el.mic.disabled = true;
      el.mic.style.opacity = 0.4;
      return;
    }
    const recognition = new Recognition();
    recognition.lang = navigator.language || "en-US";
    recognition.interimResults = true;
    recognition.continuous = false;
    let base = "";
    let active = false;

    recognition.onresult = (event) => {
      let text = "";
      for (let i = event.resultIndex; i < event.results.length; i++) {
        text += event.results[i][0].transcript;
      }
      el.input.value = (base + " " + text).trim();
      autosize();
    };
    recognition.onend = () => {
      active = false;
      el.mic.classList.remove("rec");
    };
    recognition.onerror = () => {
      active = false;
      el.mic.classList.remove("rec");
    };

    el.mic.onclick = () => {
      if (active) { recognition.stop(); return; }
      base = el.input.value.trim();
      active = true;
      el.mic.classList.add("rec");
      recognition.start();
    };
  }

  /* --------------------------------------------------------------- wiring */

  function autosize() {
    el.input.style.height = "auto";
    el.input.style.height = Math.min(el.input.scrollHeight, 220) + "px";
  }

  el.input.addEventListener("input", autosize);
  el.input.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      send();
    }
  });

  el.send.onclick = send;
  el.stop.onclick = stopStream;
  el.newChat.onclick = newChat;
  el.toggleSidebar.onclick = () => el.sidebar.classList.toggle("open");

  el.title.onclick = async () => {
    if (!state.chatId) return;
    const title = prompt("Rename chat", el.title.textContent);
    if (!title) return;
    await api("/api/chats/" + state.chatId, { method: "PATCH", body: JSON.stringify({ title }) });
    el.title.textContent = title;
    loadChats();
  };

  el.deleteChat.onclick = async () => {
    if (!state.chatId || !confirm("Delete this chat?")) return;
    await api("/api/chats/" + state.chatId, { method: "DELETE" });
    state.chatId = null;
    await loadChats();
    if (state.chats.length) openChat(state.chats[0].id); else newChat();
  };

  el.exportChat.onclick = () => {
    if (state.chatId) window.location.href = "/api/chats/" + state.chatId + "/export";
  };

  el.modelSelect.onchange = () => {
    fetch("/api/warmup", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ model: el.modelSelect.value }),
    });
    if (state.chatId) {
      api("/api/chats/" + state.chatId, {
        method: "PATCH",
        body: JSON.stringify({ model: el.modelSelect.value }),
      });
    }
  };

  let searchTimer = null;
  el.search.addEventListener("input", () => {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(() => loadChats(el.search.value.trim()), 180);
  });

  el.openSettings.onclick = async () => {
    await loadSettings();
    await loadModels();
    el.settings.hidden = false;
  };
  el.closeSettings.onclick = () => { el.settings.hidden = true; };
  el.saveSettings.onclick = saveSettings;
  el.settings.addEventListener("click", (event) => {
    if (event.target === el.settings) el.settings.hidden = true;
  });
  el.setTemp.addEventListener("input", () => { el.tempVal.textContent = Number(el.setTemp.value).toFixed(2); });
  el.setTopp.addEventListener("input", () => { el.toppVal.textContent = Number(el.setTopp.value).toFixed(2); });

  el.clearAll.onclick = async () => {
    if (!confirm("Delete every conversation? This cannot be undone.")) return;
    await api("/api/chats", { method: "DELETE" });
    state.chatId = null;
    el.settings.hidden = true;
    await loadChats();
    newChat();
  };

  document.querySelectorAll(".chip").forEach((chip) => {
    chip.onclick = () => {
      el.input.value = chip.textContent + " ";
      autosize();
      el.input.focus();
    };
  });

  document.addEventListener("keydown", (event) => {
    if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") {
      event.preventDefault();
      newChat();
    }
    if (event.key === "Escape") {
      if (!el.settings.hidden) el.settings.hidden = true;
      else if (state.streaming) stopStream();
    }
  });

  /* ----------------------------------------------------------------- boot */

  (async function boot() {
    setupVoice();
    await loadSettings();
    await loadModels();
    await loadChats();
    refreshHealth();
    setInterval(refreshHealth, 15000);

    const remembered = localStorage.getItem("jarvis.chat");
    const known = state.chats.some((chat) => chat.id === remembered);
    if (known) await openChat(remembered);
    else if (state.chats.length) await openChat(state.chats[0].id);
    else await newChat();
  })();
})();
