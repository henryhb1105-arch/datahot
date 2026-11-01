(function (root, factory) {
  "use strict";
  var api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  if (root && root.document) api.boot(root);
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  "use strict";
  function isNavigation(event, link, location) {
    if (!link || event.defaultPrevented || (event.button != null && event.button !== 0) ||
        event.metaKey || event.ctrlKey || event.shiftKey || event.altKey ||
        link.hasAttribute("download") || link.target === "_blank") return false;
    var target = new URL(link.href, location.href), current = new URL(location.href);
    return target.origin === current.origin &&
      (target.pathname !== current.pathname || target.search !== current.search);
  }
  // Anchor to the current visible screen, not a fixed-bottom containing block
  // that an embedded browser may retain while a foldable display is expanding.
  function syncViewport(win) {
    var viewport = win.visualViewport, doc = win.document;
    var bar = doc.querySelector && doc.querySelector(".tabbar");
    if (!viewport || !bar) return;
    var frame = null, settle = null;
    function update() {
      frame = null;
      var width = viewport.width, height = viewport.height;
      if (!(width > 0 && height > 0) || !Number.isFinite(width + height) ||
          Math.abs((viewport.scale || 1) - 1) > 0.01) {
        bar.classList.remove("viewport-anchored");
        return;
      }
      bar.style.setProperty("--nav-viewport-bottom", (viewport.offsetTop + height) + "px");
      bar.style.setProperty("--nav-viewport-left", viewport.offsetLeft + "px");
      bar.style.setProperty("--nav-viewport-width", width + "px");
      bar.classList.add("viewport-anchored");
    }
    function schedule() {
      if (frame === null) frame = win.requestAnimationFrame(update);
    }
    function resized() {
      schedule();
      // Some hosts deliver orientation/resize before the new viewport metrics.
      if (settle !== null) win.clearTimeout(settle);
      settle = win.setTimeout(function () { settle = null; schedule(); }, 250);
    }
    viewport.addEventListener("resize", schedule, { passive: true });
    viewport.addEventListener("scroll", schedule, { passive: true });
    win.addEventListener("resize", resized, { passive: true });
    win.addEventListener("orientationchange", resized, { passive: true });
    win.addEventListener("pageshow", resized);
    update();
  }
  function boot(win) {
    syncViewport(win);
    var doc = win.document, pending = null, timer = null;
    var status = doc.createElement("div");
    status.className = "nav-status";
    status.setAttribute("role", "status");
    status.hidden = true;
    doc.body.appendChild(status);
    function reset() {
      if (pending) { pending.classList.remove("is-pending"); pending.removeAttribute("aria-busy"); }
      pending = null; status.hidden = true;
      if (timer) win.clearTimeout(timer);
    }
    doc.addEventListener("click", function (event) {
      var link = event.target.closest(".tabbar a, .more-sheet a, .sidebar a");
      if (!isNavigation(event, link, win.location)) return;
      reset(); pending = link;
      link.classList.add("is-pending"); link.setAttribute("aria-busy", "true");
      status.textContent = "正在打开「" + link.textContent.trim() + "」…";
      status.hidden = false;
      timer = win.setTimeout(reset, 8000);
    });
    win.addEventListener("pageshow", reset);
  }
  return { boot: boot, isNavigation: isNavigation, syncViewport: syncViewport };
});
