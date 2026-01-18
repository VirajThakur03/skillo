// // app/static/js/main.js

// const TOKEN_KEY = 'sklio_access_token';
// const USER_KEY  = 'sklio_user'; // cached /me response

// export function getToken() {
//   return localStorage.getItem(TOKEN_KEY);
// }

// export function setToken(token) {
//   localStorage.setItem(TOKEN_KEY, token);
// }

// export function clearToken() {
//   localStorage.removeItem(TOKEN_KEY);
//   localStorage.removeItem(USER_KEY);
// }

// export function logout() {
//   clearToken();
//   window.location.href = '/demo_login';
// }

// // Basic fetch
// export async function apiFetch(path, opts = {}) {
//   opts.headers = opts.headers || {};
//   const base = '';
//   opts.headers['Content-Type'] = opts.headers['Content-Type'] || 'application/json';
//   const res = await fetch(base + path, opts);
//   const data = await res.json().catch(() => ({}));
//   return { ok: res.ok, status: res.status, data };
// }

// // Auth fetch (adds Authorization header)
// export async function authFetch(path, opts = {}) {
//   opts.headers = opts.headers || {};
//   const token = getToken();
//   if (token) {
//     opts.headers['Authorization'] = 'Bearer ' + token;
//   }
//   opts.headers['Content-Type'] = opts.headers['Content-Type'] || 'application/json';
//   const res = await fetch(path, opts);
//   const data = await res.json().catch(() => ({}));

//   // Auto-logout on 401
//   if (res.status === 401) {
//     clearToken();
//     // optional: redirect to login
//   }

//   return { ok: res.ok, status: res.status, data };
// }

// // Get cached user; fetch /me if missing
// export async function getCurrentUser(force = false) {
//   if (!force) {
//     const cached = localStorage.getItem(USER_KEY);
//     if (cached) {
//       try { return JSON.parse(cached); } catch(e){}
//     }
//   }
//   const token = getToken();
//   if (!token) return null;
//   const res = await authFetch('/api/auth/me', { method: 'GET' });
//   if (res.ok) {
//     localStorage.setItem(USER_KEY, JSON.stringify(res.data));
//     return res.data;
//   }
//   return null;
// }

// // Simple geolocation helper
// export function getLocation(timeout=10000) {
//   return new Promise((resolve) => {
//     if (!navigator.geolocation) {
//       resolve(null);
//       return;
//     }
//     navigator.geolocation.getCurrentPosition(
//       pos => resolve({ latitude: pos.coords.latitude, longitude: pos.coords.longitude }),
//       err => resolve(null),
//       { enableHighAccuracy: true, timeout, maximumAge: 0 }
//     );
//   });
// }

// // On every page: update header state (login/logout)
// document.addEventListener('DOMContentLoaded', async () => {
//   const token = getToken();
//   const authBar = document.querySelector('[data-auth-bar]');
//   if (!authBar) return;

//   if (token) {
//     const user = await getCurrentUser();
//     authBar.innerHTML = `
//       <span class="muted">Hi, ${user ? user.name : 'user'} (${user ? user.role : ''})</span>
//       <button class="btn ghost small" id="logoutBtn">Logout</button>
//     `;
//     const btn = document.getElementById('logoutBtn');
//     if (btn) btn.addEventListener('click', logout);
//   } else {
//     authBar.innerHTML = `
//       <a href="/demo_login" class="btn ghost small">Login</a>
//     `;
//   }
// });

// app/static/js/main.js
// ES MODULE VERSION (works with <script type="module">)

// ================== STORAGE KEYS ==================
export const TOKEN_KEY = 'sklio_access_token';
export const USER_KEY  = 'sklio_user';

// ================== TOKEN HELPERS ==================
export function getToken() {
  return localStorage.getItem(TOKEN_KEY);
}

export function setToken(token) {
  localStorage.setItem(TOKEN_KEY, token);
}

export function clearToken() {
  localStorage.removeItem(TOKEN_KEY);
  localStorage.removeItem(USER_KEY);
}

export function logout() {
  clearToken();
  window.location.replace('/demo_login');
}

// ================== FETCH HELPERS ==================
export async function authFetch(path, opts = {}) {
  opts.headers = opts.headers || {};
  const token = getToken();

  if (token) {
    opts.headers['Authorization'] = 'Bearer ' + token;
  }

  let res, data = {};
  try {
    res = await fetch(path, opts);
    data = await res.json().catch(() => ({}));
  } catch (err) {
    console.error('Network error:', err);
    return { ok: false, data: { error: 'Network error' } };
  }

  if (res.status === 401) {
    clearToken();
    window.location.replace('/demo_login');
  }

  return { ok: res.ok, data };
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
    localStorage.setItem(USER_KEY, JSON.stringify(res.data));
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

// ================== PROVIDER VERIFICATION GUARD ==================
document.addEventListener('DOMContentLoaded', async () => {
  const token = getToken();
  if (!token) return;

  const user = await getCurrentUser(true);
  if (!user) return;

  const path = window.location.pathname;
  const status = user.verification_status;
  const role = user.role;

  /*
    ✅ SINGLE SOURCE OF TRUTH (BACKEND → FRONTEND)
    status values:
    - pending
    - document_verified
    - face_verified
    - completed
    - rejected (allowed retry)
  */

  if (role === 'PROVIDER') {

    // 🚫 HARD BLOCK: rejected → retry document
    if (
      status === 'rejected' &&
      path !== '/provider_verification'
    ) {
      window.location.replace('/provider_verification');
      return;
    }

    // STEP 1 → DOCUMENT
    if (
      status === 'pending' &&
      path !== '/provider_verification'
    ) {
      window.location.replace('/provider_verification');
      return;
    }

    // STEP 2 → FACE VIDEO
    if (
      status === 'document_verified' &&
      path !== '/provider_verification_video'
    ) {
      window.location.replace('/provider_verification_video');
      return;
    }

    // STEP 3 → LOCATION
    if (
      status === 'face_verified' &&
      path !== '/confirm_location'
    ) {
      window.location.replace('/confirm_location');
      return;
    }

    // STEP 4 → COMPLETED
    // completed → allow everywhere
  }

  // ================== AUTH BAR ==================
  const authBar = document.querySelector('[data-auth-bar]');
  if (!authBar) return;

  authBar.innerHTML = `
    <span class="muted">
      Hi, ${user.name} (${user.role})
    </span>
    <button class="btn ghost small" id="logoutBtn">Logout</button>
  `;

  document
    .getElementById('logoutBtn')
    ?.addEventListener('click', logout);
});
