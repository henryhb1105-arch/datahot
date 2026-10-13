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
  function boot(win) {
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
  return { boot: boot, isNavigation: isNavigation };
});
