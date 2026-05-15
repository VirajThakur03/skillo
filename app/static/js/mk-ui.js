// app/static/js/mk-ui.js
// Non-breaking UI helpers for mk-* design system.

function initFadeInObserver() {
  const items = document.querySelectorAll(".mk-fade-in");
  if (!items.length || typeof IntersectionObserver === "undefined") return;
  const observer = new IntersectionObserver((entries) => {
    entries.forEach((entry) => {
      if (entry.isIntersecting) {
        entry.target.classList.add("mk-visible");
      }
    });
  }, { threshold: 0.1 });
  items.forEach((item) => observer.observe(item));
}

function initTooltips() {
  const wraps = document.querySelectorAll(".mk-tooltip-wrap");
  wraps.forEach((wrap) => {
    const trigger = wrap.querySelector(".mk-tooltip-trigger");
    if (!trigger) return;
    trigger.addEventListener("click", (event) => {
      event.preventDefault();
      wraps.forEach((other) => {
        if (other !== wrap) other.classList.remove("is-open");
      });
      wrap.classList.toggle("is-open");
    });
  });
  document.addEventListener("click", (event) => {
    if (!(event.target instanceof Element)) return;
    if (!event.target.closest(".mk-tooltip-wrap")) {
      wraps.forEach((wrap) => wrap.classList.remove("is-open"));
    }
  });
}

function initInputValidation() {
  const fields = document.querySelectorAll("[data-mk-validate]");
  fields.forEach((field) => {
    const type = field.getAttribute("data-mk-validate");
    const errId = field.getAttribute("data-mk-error-id");
    const errorEl = errId ? document.getElementById(errId) : null;
    const required = field.hasAttribute("required");

    const validate = () => {
      const value = (field.value || "").trim();
      let error = "";
      if (required && !value) {
        error = `${field.getAttribute("data-mk-label") || "Field"} is required`;
      } else if (value && type === "phone" && !/^\d{10}$/.test(value)) {
        error = "Please enter a valid 10-digit mobile number";
      } else if (value && type === "address" && value.length < 10) {
        error = "Please enter a full address with area or landmark";
      }
      if (error) {
        field.classList.add("mk-input-error");
        field.classList.remove("mk-input-success");
        if (errorEl) errorEl.textContent = error;
        return false;
      }
      field.classList.remove("mk-input-error");
      if (value && (type === "phone" || type === "address")) {
        field.classList.add("mk-input-success");
      } else {
        field.classList.remove("mk-input-success");
      }
      if (errorEl) errorEl.textContent = "";
      return true;
    };

    field.addEventListener("blur", validate);
    field.addEventListener("input", () => {
      if (field.classList.contains("mk-input-error")) validate();
    });
  });
}

document.addEventListener("DOMContentLoaded", () => {
  initFadeInObserver();
  initTooltips();
  initInputValidation();
  if (window.lucide && typeof window.lucide.createIcons === "function") {
    window.lucide.createIcons();
  }
});
