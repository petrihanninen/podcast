/**
 * Theme toggle — dark/light mode with system preference detection.
 *
 * Usage:
 *   1. Add FOUC-prevention script in <head> (inline, before CSS):
 *      <script>
 *        (function(){var t=localStorage.getItem('theme');if(t){document.documentElement.setAttribute('data-theme',t)}else if(window.matchMedia('(prefers-color-scheme:light)').matches){document.documentElement.setAttribute('data-theme','light')}else{document.documentElement.setAttribute('data-theme','dark')}})();
 *      </script>
 *
 *   2. Include this file at end of <body>:
 *      <script src="/ui/js/theme.js"></script>
 *
 *   3. Add a toggle button anywhere:
 *      <button class="theme-toggle" aria-label="Toggle theme">
 *        <span class="theme-toggle__icon"></span>
 *      </button>
 */

(function () {
  "use strict";

  const STORAGE_KEY = "theme";
  const DARK = "dark";
  const LIGHT = "light";

  function getSystemTheme() {
    return window.matchMedia("(prefers-color-scheme: light)").matches
      ? LIGHT
      : DARK;
  }

  function getStoredTheme() {
    try {
      return localStorage.getItem(STORAGE_KEY);
    } catch {
      return null;
    }
  }

  function setTheme(theme) {
    document.documentElement.setAttribute("data-theme", theme);
    try {
      localStorage.setItem(STORAGE_KEY, theme);
    } catch {
      // localStorage unavailable
    }
    updateToggles(theme);
  }

  function toggleTheme() {
    const current = document.documentElement.getAttribute("data-theme");
    setTheme(current === DARK ? LIGHT : DARK);
  }

  function updateToggles(theme) {
    document.querySelectorAll(".theme-toggle").forEach(function (btn) {
      const icon = btn.querySelector(".theme-toggle__icon");
      if (icon) {
        icon.textContent = theme === DARK ? "\u2600" : "\u263E"; // ☀ or ☾
      }
      btn.setAttribute(
        "aria-label",
        theme === DARK ? "Switch to light mode" : "Switch to dark mode"
      );
    });
  }

  // Initialize
  var current =
    document.documentElement.getAttribute("data-theme") ||
    getStoredTheme() ||
    getSystemTheme();
  setTheme(current);

  // Bind toggle buttons
  document.addEventListener("click", function (e) {
    var toggle = e.target.closest(".theme-toggle");
    if (toggle) {
      toggleTheme();
    }
  });

  // Listen for system preference changes
  window
    .matchMedia("(prefers-color-scheme: dark)")
    .addEventListener("change", function (e) {
      if (!getStoredTheme()) {
        setTheme(e.matches ? DARK : LIGHT);
      }
    });

  // Expose for programmatic use
  window.__theme = { toggle: toggleTheme, set: setTheme };
})();
