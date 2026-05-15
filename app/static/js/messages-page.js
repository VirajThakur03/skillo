import { authFetch } from "/static/js/main.js";

export function initMessagesPage() {
  const roomsEl = document.getElementById("rooms");
  const searchInput = document.getElementById("roomSearch");
  const retryBtn = document.getElementById("retryRoomsBtn");
  const loadMoreBtn = document.getElementById("loadMoreRoomsBtn");

  let offset = 0;
  let hasMore = false;
  let query = "";

  function timeAgo(dateString) {
    if (!dateString) return "";
    const date = new Date(dateString);
    const seconds = Math.floor((new Date() - date) / 1000);
    let interval = seconds / 31536000;
    if (interval > 1) return `${Math.floor(interval)}y ago`;
    interval = seconds / 2592000;
    if (interval > 1) return `${Math.floor(interval)}mo ago`;
    interval = seconds / 86400;
    if (interval > 1) return `${Math.floor(interval)}d ago`;
    interval = seconds / 3600;
    if (interval > 1) return `${Math.floor(interval)}h ago`;
    interval = seconds / 60;
    if (interval > 1) return `${Math.floor(interval)}m ago`;
    return "Just now";
  }

  function latestPreview(item) {
    const msg = item.latest_message;
    if (!msg) return "No messages yet";
    if (item.latest_message_type === "image") return "[Image attached]";
    if (item.latest_message_type === "file") return "[PDF attached]";
    return msg.length > 80 ? `${msg.slice(0, 80)}...` : msg;
  }

  function presenceMarkup(isOnline) {
    return `<span style="display:inline-flex;align-items:center;gap:6px;color:${isOnline ? "var(--success-600, #0f9d58)" : "var(--gray-500)"};">
      <span style="width:8px;height:8px;border-radius:9999px;background:${isOnline ? "var(--success-600, #0f9d58)" : "var(--gray-400)"};"></span>
      ${isOnline ? "Online" : "Offline"}
    </span>`;
  }

  function renderItems(items, append = false) {
    const html = items.map((item) => `
      <article class="mk-card mk-card-booking mk-booking-accent" data-state="confirmed" style="margin-bottom:12px;">
        <div style="display:flex;justify-content:space-between;gap:12px;align-items:flex-start;">
          <div>
            <div class="mk-heading">${item.other_party_name || "Conversation"}</div>
            <div class="mk-body-sm">${presenceMarkup(Boolean(item.other_party_online))}</div>
          </div>
          <div style="display:flex;gap:8px;align-items:center;">
            ${item.latest_at ? `<span class="mk-body-sm" style="color:var(--gray-500);font-size:12px;">${timeAgo(item.latest_at)}</span>` : ""}
            ${item.unread_count ? `<span style="min-width:16px;height:16px;padding:0 6px;border-radius:9999px;background:var(--danger-600);color:white;font-size:11px;display:inline-flex;align-items:center;justify-content:center;">${item.unread_count > 9 ? "9+" : item.unread_count}</span>` : ""}
          </div>
        </div>
        <div class="mk-body-sm">${item.skill || "Service inquiry"} ${item.booking_id ? `• #${item.booking_id}` : "• Pre-booking"}</div>
        <div class="mk-body-sm" style="margin-top:6px;color:var(--gray-500);">
          ${latestPreview(item)}
          ${item.latest_status ? `<span style="margin-left:8px;">• ${item.latest_status}</span>` : ""}
        </div>
        <div class="actions" style="margin-top:10px;">
          <a class="btn primary" href="/chat/${item.room}">Open chat</a>
          ${item.booking_id ? `<a class="btn ghost" href="/track/${item.booking_id}">Track</a>` : ""}
        </div>
      </article>
    `).join("");

    if (append) {
      roomsEl.insertAdjacentHTML("beforeend", html);
    } else {
      roomsEl.innerHTML = html;
    }
  }

  async function loadRooms({ append = false } = {}) {
    if (!append) {
      roomsEl.innerHTML = `
        <div class="mk-loading-stack">
          <div class="mk-card"><div class="mk-skeleton" style="height:68px;"></div></div>
          <div class="mk-card"><div class="mk-skeleton" style="height:68px;"></div></div>
        </div>
      `;
      offset = 0;
    }

    const params = new URLSearchParams({
      limit: "20",
      offset: String(offset),
    });
    if (query) params.set("q", query);

    const res = await authFetch(`/api/chat/rooms?${params.toString()}`);
    if (!res.ok) {
      roomsEl.innerHTML = `<div class="mk-card mk-empty-state"><p class="mk-body-sm">${res.data?.error || "Unable to load conversations."}</p></div>`;
      loadMoreBtn.style.display = "none";
      return;
    }

    const items = res.data.items || [];
    if (!items.length && !append) {
      roomsEl.innerHTML = `<div class="mk-card mk-empty-state"><p class="mk-body-sm">${query ? "No conversations matched your search." : "No conversations yet."}</p><a class="btn ghost" href="/home">Find services</a></div>`;
      loadMoreBtn.style.display = "none";
      return;
    }

    renderItems(items, append);
    hasMore = Boolean(res.data.has_more);
    offset = res.data.next_offset || 0;
    loadMoreBtn.style.display = hasMore ? "inline-flex" : "none";
  }

  retryBtn.addEventListener("click", () => loadRooms({ append: false }));
  loadMoreBtn.addEventListener("click", () => loadRooms({ append: true }));
  searchInput.addEventListener("keydown", (event) => {
    if (event.key !== "Enter") return;
    query = searchInput.value.trim();
    loadRooms({ append: false });
  });

  loadRooms({ append: false });
  setInterval(() => {
    loadRooms({ append: false });
  }, 30000);
}
