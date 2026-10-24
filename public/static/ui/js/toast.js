/**
 * Toast notifications — lightweight, auto-dismissing messages.
 *
 * Usage:
 *   1. Include CSS (already in components.css)
 *   2. Include this file before </body>:
 *      <script src="/ui/js/toast.js"></script>
 *
 *   3. Show a toast:
 *      window.__toast("Link copied to clipboard");
 *      window.__toast("Saved!", { variant: "success" });
 *      window.__toast("Something went wrong", { variant: "error", duration: 5000 });
 *
 * Options:
 *   - variant: "success" | "error" | "warning" | "info" (default: none)
 *   - duration: milliseconds before auto-dismiss (default: 2000)
 */

(function () {
  "use strict";

  var CONTAINER_CLASS = "toast-container";
  var DEFAULT_DURATION = 2000;

  function getContainer() {
    var el = document.querySelector("." + CONTAINER_CLASS);
    if (!el) {
      el = document.createElement("div");
      el.className = CONTAINER_CLASS;
      document.body.appendChild(el);
    }
    return el;
  }

  function toast(message, opts) {
    opts = opts || {};
    var duration = opts.duration || DEFAULT_DURATION;
    var variant = opts.variant || null;

    var container = getContainer();
    var el = document.createElement("div");
    el.className = "toast" + (variant ? " toast--" + variant : "");
    el.textContent = message;
    container.appendChild(el);

    // Trigger reflow so the transition plays
    el.offsetHeight; // eslint-disable-line no-unused-expressions

    el.classList.add("toast--visible");

    setTimeout(function () {
      el.classList.remove("toast--visible");
      el.addEventListener("transitionend", function () {
        el.remove();
      });
    }, duration);
  }

  window.__toast = toast;
})();
