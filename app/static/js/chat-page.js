import { authFetch, getToken, showMkToast } from "/static/js/main.js";
import { createChatSocket, sendHeartbeat, sendTyping } from "/static/js/chat.js";

export function initChatPage({ room }) {
  const token = getToken() || null;
  const messagesEl = document.getElementById("messages");
  const statusEl = document.getElementById("chatStatus");
  const titleEl = document.getElementById("roomTitle");
  const presenceEl = document.getElementById("roomPresence");
  const inputEl = document.getElementById("msg");
  const sendBtn = document.getElementById("sendBtn");
  const attachBtn = document.getElementById("attachBtn");
  const attachInput = document.getElementById("attachInput");
  const loadOlderBtn = document.getElementById("loadOlderBtn");
  const searchInput = document.getElementById("searchMessages");
  const clearSearchBtn = document.getElementById("clearSearchBtn");

  let currentUserId = null;
  let currentUserRole = null;
  let otherPartyId = null;
  let renderedMessageIds = new Set();
  let renderedClientIds = new Set();
  let pollingInterval = null;
  let heartbeatInterval = null;
  let currentQuery = "";
  let nextBeforeId = null;
  let hasMoreHistory = false;
  let socket = null;
  let isJoined = false;
  let joinTimeout = null;
  let typingDebounceTimeout = null;
  let hideTypingTimeout = null;
  let diagnosticsEl = null;
  let lastHistoryRefreshAt = null;
  let lastAckAt = null;

  function escapeHtml(value) {
    return String(value ?? "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function isDiagnosticsEnabled() {
    return document.body?.dataset?.env === "development";
  }

  function ensureDiagnosticsPanel() {
    if (!isDiagnosticsEnabled()) return null;
    if (diagnosticsEl) return diagnosticsEl;
    diagnosticsEl = document.createElement("div");
    diagnosticsEl.id = "chatDiagnostics";
    diagnosticsEl.className = "mk-card";
    diagnosticsEl.style.cssText = "margin-top:12px;padding:12px;background:var(--gray-50);border-style:dashed;";
    const chatCard = document.querySelector(".chat-card");
    if (chatCard) {
      chatCard.appendChild(diagnosticsEl);
      refreshDiagnostics();
    }
    return diagnosticsEl;
  }

  function refreshDiagnostics() {
    const panel = ensureDiagnosticsPanel();
    if (!panel) return;
    panel.innerHTML = `
      <div class="mk-label-upper" style="margin-bottom:8px;">Chat diagnostics</div>
      <div class="mk-body-sm">socket connected: ${socket?.connected ? "yes" : "no"}</div>
      <div class="mk-body-sm">room joined: ${isJoined ? "yes" : "no"}</div>
      <div class="mk-body-sm">last history refresh: ${escapeHtml(lastHistoryRefreshAt || "never")}</div>
      <div class="mk-body-sm">last message ack: ${escapeHtml(lastAckAt || "never")}</div>
      <div class="mk-body-sm">transport mode: ${escapeHtml(socket?.io?.engine?.transport?.name || "rest-only")}</div>
    `;
  }

  function formatTime(timestamp) {
    return new Intl.DateTimeFormat("en-IN", {
      hour: "numeric",
      minute: "2-digit",
    }).format(new Date(timestamp));
  }

  function messageStatusIcon(status) {
    if (status === "read") return `<span data-testid="message-status" data-message-status="read" style="color:var(--brand-600);font-size:12px;">&#10003;&#10003;</span>`;
    if (status === "delivered") return `<span data-testid="message-status" data-message-status="delivered" style="color:var(--gray-500);font-size:12px;">&#10003;&#10003;</span>`;
    if (status === "sending") return `<span data-testid="message-status" data-message-status="sending" style="color:var(--gray-500);font-size:12px;">...</span>`;
    if (status === "failed") return `<span data-testid="message-status" data-message-status="failed" style="color:var(--danger-600, #d93025);font-size:12px;">!</span>`;
    return `<span data-testid="message-status" data-message-status="sent" style="color:var(--gray-500);font-size:12px;">&#10003;</span>`;
  }

  function attachmentHtml(message) {
    const safeUrl = escapeHtml(message.content);
    const label = escapeHtml(message.attachment_name || "Download attachment");
    if (message.message_type === "image") {
      return `<img src="${safeUrl}" alt="attachment" style="max-width:220px;max-height:200px;border-radius:8px;display:block;cursor:pointer;" onclick="window.open('${safeUrl}','_blank')" loading="lazy" />`;
    }
    if (message.message_type === "file") {
      return `<a href="${safeUrl}${message.content.includes("?") ? "&" : "?"}download=1" target="_blank" rel="noopener" class="btn ghost" style="display:inline-flex;align-items:center;gap:8px;">${label}</a>`;
    }
    if (typeof message.content === "string" && message.content.startsWith("/api/system/upload")) {
      return `<a href="${safeUrl}" target="_blank" rel="noopener" class="btn ghost" style="display:inline-flex;align-items:center;gap:8px;">${label}</a>`;
    }
    return `<div>${escapeHtml(message.content)}</div>`;
  }

  function createMessageHTML(message) {
    const outgoing = currentUserId != null && Number(message.sender_id) === Number(currentUserId);
    const bubbleId = message.client_id ? `msg-client-${message.client_id}` : `msg-${message.id}`;
    const messageId = message.id ?? "";
    const clientId = message.client_id ?? "";

    return `
      <div
        id="${bubbleId}"
        class="message"
        data-testid="message-bubble"
        data-message-id="${escapeHtml(messageId)}"
        data-client-id="${escapeHtml(clientId)}"
        style="margin-bottom:12px;display:flex;justify-content:${outgoing ? "flex-end" : "flex-start"};"
      >
        <div
          style="
            max-width:min(85%, 420px);
            padding:10px 12px;
            border-radius:16px;
            background:${outgoing ? "var(--brand-600)" : "var(--gray-100)"};
            color:${outgoing ? "white" : "var(--gray-900)"};
          "
        >
          ${!outgoing && message.sender_name ? `<div class="mk-label-upper" style="margin-bottom:4px;color:inherit;opacity:.8;">${escapeHtml(message.sender_name)}</div>` : ""}
          ${attachmentHtml(message)}
          <div style="display:flex;justify-content:flex-end;gap:6px;align-items:center;margin-top:6px;font-size:12px;opacity:.85;">
            <span>${escapeHtml(formatTime(message.created_at || new Date().toISOString()))}</span>
            ${outgoing ? messageStatusIcon(message.status) : ""}
          </div>
        </div>
      </div>
    `;
  }

  function updateRenderedMessageStatus(messageId, status, readAt) {
    const bubble = messagesEl.querySelector(`[data-message-id='${messageId}']`);
    if (!bubble) return;
    const statusNode = bubble.querySelector("[data-message-status]");
    if (!statusNode) return;

    statusNode.setAttribute("data-message-status", status);
    if (status === "read") {
      statusNode.style.color = "var(--brand-600)";
      statusNode.innerHTML = "&#10003;&#10003;";
    } else if (status === "delivered") {
      statusNode.style.color = "var(--gray-500)";
      statusNode.innerHTML = "&#10003;&#10003;";
    } else if (status === "sending") {
      statusNode.style.color = "var(--gray-500)";
      statusNode.textContent = "...";
    } else if (status === "failed") {
      statusNode.style.color = "var(--danger-600, #d93025)";
      statusNode.textContent = "!";
    } else {
      statusNode.style.color = "var(--gray-500)";
      statusNode.innerHTML = "&#10003;";
    }

    if (readAt) {
      bubble.dataset.readAt = readAt;
    }
  }

  function updateRenderedClientStatus(clientId, status, messageId = null, readAt = null) {
    if (!clientId) return;
    const bubble = messagesEl.querySelector(`[data-client-id='${clientId}']`);
    if (!bubble) return;
    if (messageId != null) {
      bubble.dataset.messageId = String(messageId);
      renderedMessageIds.add(Number(messageId));
    }
    updateRenderedMessageStatus(bubble.dataset.messageId || clientId, status, readAt);
  }

  function ensureEmptyState() {
    const emptyState = document.getElementById("chatEmptyState");
    if (messagesEl.children.length > 0 && emptyState) {
      emptyState.remove();
    } else if (messagesEl.children.length === 0 && !emptyState) {
      messagesEl.innerHTML = `<div id="chatEmptyState" class="mk-card mk-empty-state" style="border:none;background:transparent;"><p class="mk-body-sm" style="color:var(--gray-500);">No messages found yet.</p></div>`;
    }
  }

  function prependMessages(items) {
    if (!items.length) {
      ensureEmptyState();
      return;
    }

    const previousHeight = messagesEl.scrollHeight;
    const htmlContent = items.map((message) => createMessageHTML(message)).join("");
    messagesEl.insertAdjacentHTML("afterbegin", htmlContent);
    const newHeight = messagesEl.scrollHeight;
    messagesEl.scrollTop = newHeight - previousHeight;
    ensureEmptyState();
  }

  function appendMessages(items, { prepend = false } = {}) {
    const toInsert = [];
    const toPrepend = [];

    for (const message of items) {
      if (message.client_id && renderedClientIds.has(message.client_id)) {
        const bubble = document.getElementById(`msg-client-${message.client_id}`);
        if (bubble) {
          bubble.outerHTML = createMessageHTML(message);
          if (message.id != null) renderedMessageIds.add(message.id);
          renderedClientIds.add(message.client_id);
          continue;
        }
      }

      if (message.id != null && renderedMessageIds.has(message.id)) {
        updateRenderedMessageStatus(message.id, message.status || "sent", message.read_at || null);
        continue;
      }

      if (message.id != null) renderedMessageIds.add(message.id);
      if (message.client_id) renderedClientIds.add(message.client_id);
      (prepend ? toPrepend : toInsert).push(message);
    }

    if (toPrepend.length) {
      console.log("chat.history_refresh", { room, isJoined });
      prependMessages(toPrepend);
    }

    if (toInsert.length) {
      const isAtBottom = messagesEl.scrollHeight - messagesEl.scrollTop <= messagesEl.clientHeight + 100;
      messagesEl.insertAdjacentHTML("beforeend", toInsert.map((message) => createMessageHTML(message)).join(""));
      if (isAtBottom) {
        messagesEl.scrollTop = messagesEl.scrollHeight;
      }
    }

    ensureEmptyState();
  }

  function resetRenderedMessages() {
    renderedMessageIds = new Set();
    renderedClientIds = new Set();
    messagesEl.innerHTML = "";
    nextBeforeId = null;
    hasMoreHistory = false;
  }

  function updateLoadOlderState() {
    loadOlderBtn.style.display = hasMoreHistory ? "inline-flex" : "none";
    loadOlderBtn.disabled = !hasMoreHistory;
  }

  function setPresenceState(meta) {
    otherPartyId = meta?.other_party_id || null;
    titleEl.textContent = meta?.other_party_name || "Conversation";
    if (meta?.skill) {
      titleEl.textContent = `${meta.other_party_name || "Conversation"} • ${meta.skill}`;
    }
    presenceEl.textContent = meta?.other_party_online ? "Online now" : "Offline";
    presenceEl.style.color = meta?.other_party_online ? "var(--success-600, #0f9d58)" : "var(--gray-500)";
  }

  async function loadMe() {
    if (!token) return;
    const res = await fetch("/api/auth/me", {
      headers: { Authorization: "Bearer " + token },
    });
    if (!res.ok) return;
    const data = await res.json();
    currentUserId = data.id;
    currentUserRole = data.role;
  }

  async function loadRoomMeta() {
    const res = await authFetch(`/api/chat/room/${room}/meta`);
    if (!res.ok) {
      statusEl.innerText = res.data?.error || "Unable to load conversation.";
      return null;
    }
    setPresenceState(res.data);
    return res.data;
  }

  async function fetchHistory({ beforeId = null, query = currentQuery, replace = false } = {}) {
    const params = new URLSearchParams();
    params.set("format", "paginated");
    params.set("limit", "40");
    if (beforeId) params.set("before_id", String(beforeId));
    if (query) params.set("q", query);

    const res = await authFetch(`/api/chat/room/${room}?${params.toString()}`);
    if (!res.ok) {
      if (res.status === 403) {
        statusEl.innerText = "This conversation is private.";
        messagesEl.innerHTML = `<div class="mk-card mk-empty-state"><p class="mk-body-sm">You do not have access to this room.</p></div>`;
        return;
      }
      statusEl.innerText = res.data?.error || "Unable to load chat history.";
      return;
    }

    const payload = res.data || {};
    const items = payload.items || [];
    if (replace) {
      resetRenderedMessages();
    }

    hasMoreHistory = Boolean(payload.has_more);
    nextBeforeId = payload.next_before_id || null;
    updateLoadOlderState();

    appendMessages(items, { prepend: Boolean(beforeId) });
    lastHistoryRefreshAt = new Date().toISOString();
    refreshDiagnostics();
    statusEl.innerText = query ? `Showing results for "${query}"` : "Connected to chat";
  }

  async function loadOlderHistory() {
    if (!hasMoreHistory || !nextBeforeId) return;
    loadOlderBtn.disabled = true;
    await fetchHistory({ beforeId: nextBeforeId, replace: false });
    loadOlderBtn.disabled = false;
  }

  function startPolling() {
    if (!pollingInterval) {
      pollingInterval = setInterval(() => {
        loadRoomMeta();
        fetchHistory({ replace: true }).catch(() => {});
      }, 15000);
    }
  }

  function stopPolling() {
    if (pollingInterval) {
      clearInterval(pollingInterval);
      pollingInterval = null;
    }
  }

  function startHeartbeat() {
    if (heartbeatInterval) return;
    heartbeatInterval = setInterval(() => {
      if (socket?.connected) {
        sendHeartbeat();
      }
    }, 15000);
  }

  function stopHeartbeat() {
    if (heartbeatInterval) {
      clearInterval(heartbeatInterval);
      heartbeatInterval = null;
    }
  }

  function flushOfflineQueue() {
    const queueKey = `chat_queue_${room}`;
    const queued = JSON.parse(localStorage.getItem(queueKey) || "[]");
    if (queued.length === 0) return;

    statusEl.innerText = "Flushing pending messages...";
    const remaining = [];

    (async function processQueue() {
      for (const message of queued) {
        const res = await authFetch(`/api/chat/room/${room}`, {
          method: "POST",
          body: JSON.stringify({ content: message.content, client_id: message.client_id }),
        });
        if (res.ok) {
          appendMessages([res.data]);
        } else {
          remaining.push(message);
        }
      }
      if (remaining.length === 0) {
        localStorage.removeItem(queueKey);
        statusEl.innerText = "Live chat connected";
      } else {
        localStorage.setItem(queueKey, JSON.stringify(remaining));
        statusEl.innerText = "Some messages could not be sent yet.";
      }
    })();
  }

  function ensureTypingIndicator() {
    let typingIndicatorEl = document.getElementById("typingIndicator");
    if (!typingIndicatorEl) {
      typingIndicatorEl = document.createElement("div");
      typingIndicatorEl.id = "typingIndicator";
      typingIndicatorEl.style.display = "none";
      typingIndicatorEl.style.marginBottom = "8px";
      typingIndicatorEl.style.marginLeft = "12px";
      typingIndicatorEl.innerHTML = `<span class="mk-body-sm" style="color:var(--gray-500);font-style:italic;">Someone is typing...</span>`;
      document.querySelector(".chat-composer").parentNode.insertBefore(typingIndicatorEl, document.querySelector(".chat-composer"));
    }
    return typingIndicatorEl;
  }

  function handlePresenceUpdate(data) {
    if (!data || data.room !== room) return;
    if (otherPartyId && Number(data.user_id) !== Number(otherPartyId)) return;
    presenceEl.textContent = data.online ? "Online now" : "Offline";
    presenceEl.style.color = data.online ? "var(--success-600, #0f9d58)" : "var(--gray-500)";
  }

  function bindSocketHandlers() {
    socket = createChatSocket(token, { forceNew: true });
    if (!socket) {
      statusEl.innerText = "Live chat unavailable. Refreshing messages automatically.";
      startPolling();
      return false;
    }

    const typingIndicatorEl = ensureTypingIndicator();

    socket.on("connect", () => {
      isJoined = false;
      statusEl.innerText = "Joining room...";
      socket.emit("join", { room });
      startHeartbeat();
      flushOfflineQueue();
      loadRoomMeta();
      refreshDiagnostics();
      clearTimeout(joinTimeout);
      joinTimeout = setTimeout(() => {
        if (!isJoined) {
          statusEl.innerText = "Live chat is syncing. Refreshing messages automatically.";
          startPolling();
        }
      }, 3000);
    });

    socket.on("disconnect", () => {
      statusEl.innerText = "Live chat reconnecting...";
      isJoined = false;
      clearTimeout(joinTimeout);
      stopHeartbeat();
      startPolling();
      refreshDiagnostics();
    });

    socket.on("connect_error", () => {
      isJoined = false;
      clearTimeout(joinTimeout);
      statusEl.innerText = "Live chat unavailable; retrying...";
      startPolling();
      refreshDiagnostics();
    });

    socket.on("message", (data) => {
      if (!data || data.room !== room) return;
      appendMessages([data]);
    });

    socket.on("joined", (data) => {
      if (!data || data.room !== room) return;
      isJoined = true;
      clearTimeout(joinTimeout);
      stopPolling();
      statusEl.innerText = "Live chat connected";
      if (data.meta) setPresenceState(data.meta);
      refreshDiagnostics();
    });

    socket.on("message_ack", (data) => {
      if (!data || data.room !== room || !data.client_id) return;
      lastAckAt = new Date().toISOString();
      updateRenderedClientStatus(
        data.client_id,
        data.status || "sent",
        data.message_id || null,
        data.read_at || null
      );
      refreshDiagnostics();
    });

    socket.on("messages_read", (data) => {
      if (!data || data.room !== room || !Array.isArray(data.message_ids)) return;
      for (const messageId of data.message_ids) {
        updateRenderedMessageStatus(messageId, "read", data.read_at || null);
      }
    });

    socket.on("typing", (data) => {
      if (!data || data.room !== room) return;
      if (data.is_typing === false) {
        typingIndicatorEl.style.display = "none";
        return;
      }
      const sender = data.sender_name || "Someone";
      typingIndicatorEl.innerHTML = `<span class="mk-body-sm" style="color:var(--gray-500);font-style:italic;">${sender} is typing...</span>`;
      typingIndicatorEl.style.display = "block";
      clearTimeout(hideTypingTimeout);
      hideTypingTimeout = setTimeout(() => {
        typingIndicatorEl.style.display = "none";
      }, 3000);
    });

    socket.on("presence_update", handlePresenceUpdate);
    socket.on("room_error", (data) => {
      clearTimeout(joinTimeout);
      statusEl.innerText = data.error || "Room error";
      showMkToast(data.error || "Room error", "error");
      refreshDiagnostics();
    });
    return true;
  }

  async function sendCurrentMessage() {
    const text = inputEl.value.trim();
    if (!text) return;

    sendBtn.disabled = true;
    inputEl.disabled = true;
    sendTyping(room, false);

    const clientId = `tmp_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`;
    const optimisticMessage = {
      id: clientId,
      client_id: clientId,
      room,
      sender_id: currentUserId,
      content: text,
      message_type: "text",
      created_at: new Date().toISOString(),
      status: "sending",
    };
    appendMessages([optimisticMessage]);
    messagesEl.scrollTop = messagesEl.scrollHeight;
    inputEl.value = "";

    try {
      if (!navigator.onLine) {
        throw new Error("offline");
      }
      const res = await authFetch(`/api/chat/room/${room}`, {
        method: "POST",
        body: JSON.stringify({ content: text, client_id: clientId }),
      });
      if (!res.ok) {
        if (res.status === 0) {
          throw new Error("offline");
        }
        updateRenderedClientStatus(clientId, "failed");
        statusEl.innerText = res.data?.error || "Unable to send message.";
        return;
      }
      appendMessages([res.data]);
      if (!isJoined) {
        await fetchHistory({ replace: true });
      }
      if (currentQuery && !text.toLowerCase().includes(currentQuery.toLowerCase())) {
        statusEl.innerText = `Showing results for "${currentQuery}"`;
      } else {
        statusEl.innerText = isJoined ? "Live chat connected" : "Message sent (socket offline)";
      }
    } catch {
      statusEl.innerText = "Offline. Message queued for later.";
      const queueKey = `chat_queue_${room}`;
      const queued = JSON.parse(localStorage.getItem(queueKey) || "[]");
      queued.push({ content: text, client_id: clientId });
      localStorage.setItem(queueKey, JSON.stringify(queued));
    } finally {
      sendBtn.disabled = false;
      inputEl.disabled = false;
      inputEl.focus();
    }
  }

  async function uploadAttachment(file) {
    if (!file) return;
    const isPdf = file.type === "application/pdf" || file.name.toLowerCase().endsWith(".pdf");
    const maxBytes = isPdf ? 10 * 1024 * 1024 : 5 * 1024 * 1024;
    if (file.size > maxBytes) {
      statusEl.innerText = isPdf ? "PDF too large (max 10 MB)" : "Image too large (max 5 MB)";
      return;
    }

    attachBtn.disabled = true;
    statusEl.innerText = isPdf ? "Uploading PDF..." : "Uploading image...";
    const formData = new FormData();
    formData.append("file", file);

    const res = await authFetch(`/api/chat/room/${room}/upload`, {
      method: "POST",
      body: formData,
    });
    if (res.ok) {
      appendMessages([res.data]);
      messagesEl.scrollTop = messagesEl.scrollHeight;
      statusEl.innerText = "Live chat connected";
    } else {
      statusEl.innerText = res.data?.error || "Upload failed";
      showMkToast(res.data?.error || "Upload failed", "error");
    }
    attachBtn.disabled = false;
    attachInput.value = "";
  }

  function bindDomEvents() {
    sendBtn.addEventListener("click", sendCurrentMessage);
    loadOlderBtn.addEventListener("click", loadOlderHistory);

    inputEl.addEventListener("keydown", (event) => {
      if (event.key === "Enter") {
        event.preventDefault();
        sendCurrentMessage();
      }
    });

    inputEl.addEventListener("input", () => {
      if (typingDebounceTimeout) {
        clearTimeout(typingDebounceTimeout);
      } else {
        sendTyping(room, true);
      }
      typingDebounceTimeout = setTimeout(() => {
        sendTyping(room, false);
        typingDebounceTimeout = null;
      }, 1200);
    });

    attachBtn.addEventListener("click", () => attachInput.click());
    attachInput.addEventListener("change", async (event) => {
      await uploadAttachment(event.target.files[0]);
    });

    searchInput.addEventListener("keydown", async (event) => {
      if (event.key !== "Enter") return;
      currentQuery = searchInput.value.trim();
      await fetchHistory({ replace: true, query: currentQuery });
    });

    clearSearchBtn.addEventListener("click", async () => {
      searchInput.value = "";
      currentQuery = "";
      await fetchHistory({ replace: true, query: "" });
    });
  }

  async function boot() {
    if (!token) {
      messagesEl.innerHTML = `<div class="mk-card mk-empty-state"><p class="mk-body-sm">Please login again to use chat.</p></div>`;
      statusEl.innerText = "Authentication required";
      sendBtn.disabled = true;
      inputEl.disabled = true;
      return;
    }

    await loadMe();
    ensureDiagnosticsPanel();

    const roomParts = room.split("_");
    const shouldRedirectToCanonicalInquiry =
      roomParts.length === 2 &&
      roomParts[0] === "skill" &&
      currentUserId != null &&
      currentUserRole === "SEEKER";

    if (shouldRedirectToCanonicalInquiry) {
      window.location.replace(`/chat/skill_${roomParts[1]}_${currentUserId}`);
      return;
    }

    bindDomEvents();
    await loadRoomMeta();
    await fetchHistory({ replace: true, query: "" });
    bindSocketHandlers();
    refreshDiagnostics();
  }

  boot();
}
