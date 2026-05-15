// app/static/js/main.js — ES Module


// ================== STORAGE KEYS ==================
export const TOKEN_KEY = 'sklio_access_token';
export const USER_KEY  = 'sklio_user';
const LEGACY_TOKEN_KEY = "skl_token";
const LEGACY_ROLE_KEY = "skl_role";
const FEATURE_CACHE_KEY = "sklio_features";
const FEATURE_CACHE_MAX_AGE_MS = 60 * 1000;
const PENDING_TOAST_KEY = "mk_pending_toast";

// ================== TOKEN HELPERS ==================
export function getToken() {
  return localStorage.getItem(TOKEN_KEY) || localStorage.getItem(LEGACY_TOKEN_KEY);
}

export function setToken(token) {
  localStorage.setItem(TOKEN_KEY, token);
  localStorage.setItem(LEGACY_TOKEN_KEY, token);
}

export function setCachedUser(user) {
  if (!user) return;
  localStorage.setItem(USER_KEY, JSON.stringify(user));
  if (user.role) {
    localStorage.setItem(LEGACY_ROLE_KEY, user.role);
  }
}

export function clearToken() {
  localStorage.removeItem(TOKEN_KEY);
  localStorage.removeItem(LEGACY_TOKEN_KEY);
  localStorage.removeItem(USER_KEY);
  localStorage.removeItem(LEGACY_ROLE_KEY);
}

export function logout() {
  clearToken();
  window.location.replace('/demo_login');
}

/** Minimal toast (Task 2+); mk- prefixed host/class in CSS */
export function showMkToast(message, variant = "error") {
  let host = document.getElementById("mk-toast-host");
  if (!host) {
    host = document.createElement("div");
    host.id = "mk-toast-host";
    host.className = "mk-toast-host";
    document.body.appendChild(host);
  }
  const el = document.createElement("div");
  el.className = `mk-toast mk-toast--${variant}`;
  el.setAttribute("role", "status");
  el.textContent = message;
  host.appendChild(el);
  requestAnimationFrame(() => el.classList.add("is-visible"));
  const ms = variant === "error" ? 5000 : 3000;
  setTimeout(() => {
    el.classList.remove("is-visible");
    setTimeout(() => el.remove(), 280);
  }, ms);
}

function queuePendingToast(message, variant = "error") {
  try {
    sessionStorage.setItem(PENDING_TOAST_KEY, JSON.stringify({ message, variant }));
  } catch {
    // Ignore storage failures for non-essential UX polish.
  }
}

function consumePendingToast() {
  try {
    const raw = sessionStorage.getItem(PENDING_TOAST_KEY);
    if (!raw) return;
    sessionStorage.removeItem(PENDING_TOAST_KEY);
    const parsed = JSON.parse(raw);
    if (parsed?.message) {
      requestAnimationFrame(() => showMkToast(parsed.message, parsed.variant || "error"));
    }
  } catch {
    sessionStorage.removeItem(PENDING_TOAST_KEY);
  }
}

function readCachedFeatures() {
  try {
    const cached = JSON.parse(localStorage.getItem(FEATURE_CACHE_KEY) || "null");
    if (!cached?.data || !cached?.fetched_at) return null;
    if ((Date.now() - cached.fetched_at) > FEATURE_CACHE_MAX_AGE_MS) return null;
    return cached.data;
  } catch {
    return null;
  }
}

function writeCachedFeatures(data) {
  try {
    localStorage.setItem(
      FEATURE_CACHE_KEY,
      JSON.stringify({ data, fetched_at: Date.now() })
    );
  } catch {
    // Ignore localStorage errors for non-essential caching.
  }
}

// ================== FETCH HELPERS ==================
export async function authFetch(path, opts = {}) {
  const isFormData = opts.body instanceof FormData;

  // ✅ Only set JSON content type when not sending FormData
  opts.headers = {
    ...(opts.headers || {}),
    ...(isFormData ? {} : { "Content-Type": "application/json" })
  };

  const token = getToken();
  if (token) {
    opts.headers.Authorization = "Bearer " + token;
  }

  let res, data = {};
  try {
    res = await fetch(path, opts);

    // Safely parse JSON (even for empty responses)
    data = await res.json().catch(() => ({}));
  } catch (err) {
    showMkToast("Connection error. Check your internet and try again.", "error");
    return {
      ok: false,
      status: 0,
      data: { error: "Connection error. Check your internet and try again." }
    };
  }

  // 🔒 Auto logout on expired / invalid token
  if (res.status === 401) {
    clearToken();
    queuePendingToast("Session expired. Please log in again.", "error");
    window.location.replace("/demo_login");
  }

  if (res.status >= 500) {
    showMkToast("Something went wrong. We're on it.", "error");
  }

  return {
    ok: res.ok,
    status: res.status,
    data
  };
}



export async function ensureFeaturesLoaded(force = false) {
  if (!force) {
    const cached = readCachedFeatures();
    if (cached) return cached;
  }

  try {
    const res = await fetch("/api/system/features", { method: "GET" });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      return readCachedFeatures() || {};
    }
    writeCachedFeatures(data || {});
    return data || {};
  } catch {
    return readCachedFeatures() || {};
  }
}

export async function useFeature(name) {
  const features = await ensureFeaturesLoaded();
  return Boolean(features?.[name]);
}


// ================== CURRENT USER ==================
export async function getCurrentUser(force = false) {
  if (!force) {
    const cached = localStorage.getItem(USER_KEY);
    if (cached) {
      try {
        return JSON.parse(cached);
      } catch {
        localStorage.removeItem(USER_KEY);
      }
    }
  }

  const token = getToken();
  if (!token) return null;

  const res = await authFetch('/api/auth/me');
  if (res.ok) {
    setCachedUser(res.data);
    return res.data;
  }

  return null;
}


// ================== GEOLOCATION ==================
export function getLocation(timeout = 10000) {
  return new Promise(resolve => {
    if (!navigator.geolocation) return resolve(null);

    navigator.geolocation.getCurrentPosition(
      pos => resolve({
        latitude: pos.coords.latitude,
        longitude: pos.coords.longitude,
      }),
      () => resolve(null),
      { enableHighAccuracy: true, timeout, maximumAge: 0 }
    );
  });
}

async function fetchUnreadChatCount() {
  const token = getToken();
  if (!token) return 0;
  try {
    const res = await authFetch("/api/chat/unread-count", { method: "GET" });
    if (!res.ok) return 0;
    return Number(res.data?.count || 0);
  } catch {
    return 0;
  }
}

// ================== GLOBAL UI HELPERS ==================
function initMobileToggle() {
  const toggle = document.getElementById("mobileToggle");
  const nav = document.getElementById("mainNav");
  if (!toggle || !nav) return;

  // Remove old listeners to avoid multiple fires
  const newToggle = toggle.cloneNode(true);
  toggle.parentNode.replaceChild(newToggle, toggle);

  newToggle.addEventListener("click", (e) => {
    e.stopPropagation();
    nav.classList.toggle("show");
  });

  document.addEventListener("click", (e) => {
    if (nav.classList.contains("show") && !nav.contains(e.target) && !newToggle.contains(e.target)) {
      nav.classList.remove("show");
    }
  });
}

function appendNavLink(nav, href, text, isActive = false) {
  const link = document.createElement("a");
  link.href = href;
  link.textContent = text;
  if (isActive) {
    link.className = "active";
  }
  nav.appendChild(link);
}

function renderMainNav({ nav, user, pathname, jobPostsEnabled }) {
  if (!nav) return;
  nav.innerHTML = "";

  appendNavLink(nav, "/home", "Home", pathname === "/home" || pathname === "/");

  if (jobPostsEnabled) {
    appendNavLink(nav, "/jobs", "Browse Jobs", pathname === "/jobs");
  }

  if (!user) {
    return;
  }

  if (user.role === "PROVIDER") {
    appendNavLink(
      nav,
      "/provider/dashboard",
      "My Dashboard",
      pathname.startsWith("/provider/dashboard")
    );
    if (jobPostsEnabled) {
      appendNavLink(nav, "/provider/job-board", "Job Board", pathname === "/provider/job-board");
    }
    return;
  }

  if (user.role === "SEEKER") {
    appendNavLink(nav, "/my-bookings", "My Bookings", pathname === "/my-bookings");
    if (jobPostsEnabled) {
      appendNavLink(nav, "/my-jobs", "My Job Posts", pathname === "/my-jobs");
    }
  }
}

// ================== PROVIDER VERIFICATION GUARD ==================
document.addEventListener("DOMContentLoaded", async () => {
  consumePendingToast();
  ensureFeaturesLoaded();
  initMobileToggle();
  const path = window.location.pathname;
  const headerActions = document.getElementById("headerActions");
  const mainNav = document.getElementById("mainNav");
  const jobPostsEnabled = document.body.dataset.featureJobPosts === 'true';

  renderMainNav({ nav: mainNav, user: null, pathname: path, jobPostsEnabled });

  const publicPaths = new Set([
    "/",
    "/login",
    "/demo_login",
    "/demo-login",
    "/home",
    "/trust-center",
    "/help",
    "/legal/terms",
    "/legal/privacy",
    "/legal/refund",
    "/legal/provider-terms",
    "/legal/grievance",
  ]);

  const isPublicPath =
    publicPaths.has(path) ||
    path.startsWith("/skill/") ||
    path.startsWith("/booking/");

  const token = getToken();
  if (!token && !isPublicPath) {
    window.location.replace("/demo_login");
    return;
  }

  const user = token ? await getCurrentUser(true) : null;
  if (!user && !isPublicPath) {
    window.location.replace("/demo_login");
    return;
  }

  if (
    !isPublicPath &&
    user &&
    user.role === "PROVIDER" &&
    user.provider_next_route &&
    Array.isArray(user.provider_allowed_paths) &&
    user.provider_allowed_paths.length > 0 &&
    !user.provider_allowed_paths.includes(path)
  ) {
    window.location.replace(user.provider_next_route);
    return;
  }
  if (!headerActions || !mainNav) return;

  if (!user) {
    headerActions.innerHTML = `
      <a href="/demo_login" class="btn secondary small">Demo Login</a>
      <div class="mobile-toggle" id="mobileToggle">
        <i data-lucide="menu"></i>
      </div>
    `;
    if (window.lucide) window.lucide.createIcons();
    initMobileToggle();
    return;
  }

  renderMainNav({ nav: mainNav, user, pathname: path, jobPostsEnabled });

  // --- 2. Update Header Actions (Notifications + User Dropdown) ---
  const initials = user.name.split(' ').map(n => n[0]).join('').toUpperCase().substring(0, 2);
  
  headerActions.innerHTML = `
    <!-- Notifications -->
    <a href="/notifications" class="nav-notif-btn" id="navNotifBtn" title="Notifications">
      <i data-lucide="bell" style="width:20px; height:20px;"></i>
      <span class="nav-badge" id="navNotifBadge" style="display:none;"></span>
    </a>

    <!-- User Menu -->
    <div class="user-menu" id="userMenu">
      <div class="user-trigger" id="userTrigger">
        <div class="user-avatar">${initials}</div>
        <div class="user-info">
          <span class="user-name">${user.name}</span>
          <span class="user-role-badge">${user.role}</span>
        </div>
        <i data-lucide="chevron-down" style="width:14px; height:14px; opacity:0.5;"></i>
      </div>

      <div class="dropdown-menu" id="userDropdown">
        <div style="padding: 10px 12px; border-bottom: 1px solid var(--border); margin-bottom: 4px;">
          <div style="font-size: 14px; font-weight: 600;">${user.name}</div>
          <div style="font-size: 11px; color: var(--muted);">${user.email || ''}</div>
        </div>
        
        <a href="/wallet" class="dropdown-item">
          <i data-lucide="wallet"></i> Wallet
        </a>
        <a href="/messages" class="dropdown-item">
          <i data-lucide="message-square"></i> Messages
          <span id="dropdownChatBadge" style="display:none; margin-left:auto; background:var(--brand-600); color:white; padding:1px 6px; border-radius:10px; font-size:10px;"></span>
        </a>
        <a href="/account" class="dropdown-item">
          <i data-lucide="settings"></i> Settings
        </a>
        
        <div class="dropdown-divider"></div>
        
        <button class="dropdown-item logout" id="logoutBtn" style="width:100%; border:none; background:none; cursor:pointer; font-family:inherit;">
          <i data-lucide="log-out"></i> Logout
        </button>
      </div>
    </div>

    <div class="mobile-toggle" id="mobileToggle">
      <i data-lucide="menu"></i>
    </div>
  `;

  initMobileToggle();
  if (window.lucide) window.lucide.createIcons();

  // --- 3. Interaction Logic ---
  const userTrigger = document.getElementById("userTrigger");
  const userDropdown = document.getElementById("userDropdown");
  const logoutBtn = document.getElementById("logoutBtn");

  if (userTrigger && userDropdown) {
    userTrigger.addEventListener("click", (e) => {
      e.stopPropagation();
      userDropdown.classList.toggle("show");
    });

    document.addEventListener("click", (e) => {
      if (!userDropdown.contains(e.target)) {
        userDropdown.classList.remove("show");
      }
    });
  }

  if (logoutBtn) {
    logoutBtn.addEventListener("click", logout);
  }

  // Notification badge polling
  async function refreshNavBadges() {
    try {
      const [notifRes, chatCount] = await Promise.all([
        fetch('/api/notifications/unread-count', { headers: { Authorization: 'Bearer ' + token } }),
        fetchUnreadChatCount()
      ]);

      if (notifRes.ok) {
        const d = await notifRes.json();
        const badge = document.getElementById('navNotifBadge');
        const cnt = Number(d.count || 0);
        if (badge) {
          badge.style.display = cnt > 0 ? 'flex' : 'none';
          badge.textContent = cnt > 9 ? '9+' : String(cnt);
        }
      }

      const chatBadge = document.getElementById("dropdownChatBadge");
      if (chatBadge) {
        chatBadge.style.display = chatCount > 0 ? 'inline-block' : 'none';
        chatBadge.textContent = chatCount > 99 ? '99+' : String(chatCount);
      }
    } catch(e) {}
  }

  refreshNavBadges();
  setInterval(refreshNavBadges, 30000);

  if (window.lucide) window.lucide.createIcons();

  // Real-time Notification Listener
  if (user && typeof io !== "undefined") {
    try {
      const socket = io({
        auth: { token },
        transports: ["websocket", "polling"],
      });

      socket.on("connect", () => {
        socket.emit("join", { room: `user_${user.id}` });
      });

      socket.on("notification", (data) => {
        // Show live toast for new notification
        showMkToast(data.title || "New notification", "success");
        // Immediately refresh badges
        refreshNavBadges();
      });
    } catch (err) {
      console.warn("Real-time notifications unavailable:", err);
    }
  }
});
