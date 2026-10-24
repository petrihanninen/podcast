/**
 * Swipeable — touch-swipe to reveal action panels behind content.
 *
 * Markup:
 *   <div class="swipeable" data-swipeable>
 *     <div class="swipeable__action swipeable__action--start">Retry</div>
 *     <div class="swipeable__content">…</div>
 *     <div class="swipeable__action swipeable__action--end">Delete</div>
 *   </div>
 *
 * Either action panel is optional — if missing, swipe in that direction
 * is disabled.
 *
 * Events (dispatched on the .swipeable element, bubbles):
 *   swipe:action  detail: { direction: "start" | "end" }
 *
 * Desktop:
 *   Use .swipeable__buttons inside the content for inline action buttons;
 *   they are shown only on hover-capable / fine-pointer devices via CSS.
 */
(function () {
  var THRESHOLD = 80;
  var MAX_TRANSLATE = 100;

  function Swipeable(el) {
    this.el = el;
    this.content = el.querySelector('.swipeable__content');
    if (!this.content) return;

    this.hasStart = !!el.querySelector('.swipeable__action--start');
    this.hasEnd = !!el.querySelector('.swipeable__action--end');

    this.startX = 0;
    this.startY = 0;
    this.dx = 0;
    this.locked = null; // null | "h" | "v"

    this.content.addEventListener('touchstart', this._onStart.bind(this), { passive: true });
    this.content.addEventListener('touchmove', this._onMove.bind(this), { passive: false });
    this.content.addEventListener('touchend', this._onEnd.bind(this));
  }

  Swipeable.prototype._onStart = function (e) {
    this.startX = e.touches[0].clientX;
    this.startY = e.touches[0].clientY;
    this.dx = 0;
    this.locked = null;
  };

  Swipeable.prototype._onMove = function (e) {
    var x = e.touches[0].clientX;
    var y = e.touches[0].clientY;
    var dx = x - this.startX;
    var dy = y - this.startY;

    // Lock scroll direction after 5 px of movement
    if (!this.locked) {
      if (Math.abs(dx) > Math.abs(dy) && Math.abs(dx) > 5) {
        this.locked = 'h';
        this.content.classList.add('is-dragging');
      } else if (Math.abs(dy) > 5) {
        this.locked = 'v';
      }
      return;
    }

    if (this.locked !== 'h') return;

    e.preventDefault(); // stop page scroll while swiping horizontally

    var clamped = dx;
    if (clamped > 0 && !this.hasStart) clamped = 0;
    if (clamped < 0 && !this.hasEnd) clamped = 0;
    clamped = Math.max(-MAX_TRANSLATE, Math.min(MAX_TRANSLATE, clamped));

    this.dx = clamped;
    this.content.style.transform = 'translateX(' + clamped + 'px)';
  };

  Swipeable.prototype._onEnd = function () {
    var wasH = this.locked === 'h';
    this.content.classList.remove('is-dragging');
    this.content.style.transform = '';

    if (wasH) {
      // Swallow the click that fires after touchend so links don't navigate
      this.content.addEventListener('click', function block(e) {
        e.preventDefault();
        e.stopPropagation();
      }, { capture: true, once: true });
    }

    if (Math.abs(this.dx) >= THRESHOLD) {
      var direction = this.dx > 0 ? 'start' : 'end';
      this.el.dispatchEvent(new CustomEvent('swipe:action', {
        bubbles: true,
        detail: { direction: direction },
      }));
    }

    this.dx = 0;
    this.locked = null;
  };

  // --- public ---------------------------------------------------------

  function init() {
    var els = document.querySelectorAll('[data-swipeable]');
    for (var i = 0; i < els.length; i++) {
      if (!els[i]._swipeable) {
        els[i]._swipeable = new Swipeable(els[i]);
      }
    }
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }

  window.Swipeable = { init: init };
})();
