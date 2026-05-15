// app/static/js/favorites.js — seeker saved providers (heart + batch check)
import { authFetch, getToken, getCurrentUser, showMkToast } from "/static/js/main.js";

export async function applyFavoriteSavedState(root = document) {
  const buttons = root.querySelectorAll("[data-mk-favorite-for]");
  if (!buttons.length || !getToken()) return;
  const user = await getCurrentUser();
  if (!user || user.role !== "SEEKER") return;
  const ids = [
    ...new Set(
      [...buttons].map((b) => b.getAttribute("data-mk-favorite-for")).filter(Boolean)
    ),
  ];
  if (!ids.length) return;
  const res = await authFetch(
    `/api/favorites/check?provider_ids=${encodeURIComponent(ids.join(","))}`
  );
  if (!res.ok) return;
  const saved = new Set((res.data.saved_provider_ids || []).map(Number));
  buttons.forEach((btn) => {
    const id = Number(btn.getAttribute("data-mk-favorite-for"));
    const on = saved.has(id);
    setFavoriteButtonState(btn, on);
  });
}

export function setFavoriteButtonState(btn, on) {
  btn.classList.toggle("is-saved", on);
  btn.setAttribute("aria-pressed", String(on));
}

export function bindFavoriteButtons(root = document) {
  root.querySelectorAll("[data-mk-favorite-for]").forEach((btn) => {
    if (btn.dataset.mkFavoriteBound === "true") return;
    btn.dataset.mkFavoriteBound = "true";
    btn.addEventListener("click", async (e) => {
      e.preventDefault();
      e.stopPropagation();
      const pid = btn.getAttribute("data-mk-favorite-for");
      if (!pid) return;
      if (!getToken()) {
        showMkToast("Sign in to save providers.", "error");
        setTimeout(() => window.location.assign("/demo_login"), 600);
        return;
      }
      const user = await getCurrentUser();
      if (!user || user.role !== "SEEKER") {
        showMkToast("Only seekers can save providers.", "error");
        return;
      }
      const was = btn.classList.contains("is-saved");
      setFavoriteButtonState(btn, !was);
      const res = was
        ? await authFetch(`/api/favorites/${encodeURIComponent(pid)}`, {
            method: "DELETE",
          })
        : await authFetch("/api/favorites", {
            method: "POST",
            body: JSON.stringify({ provider_id: Number(pid) }),
          });
      if (!res.ok) {
        setFavoriteButtonState(btn, was);
        showMkToast("Couldn't save. Try again.", "error");
        return;
      }
      root.dispatchEvent(
        new CustomEvent("mk:favorite-toggled", {
          bubbles: true,
          detail: {
            providerId: Number(pid),
            saved: !was,
          },
        })
      );
    });
  });
}
