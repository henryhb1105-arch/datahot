(function (root, factory) {
  "use strict";
  var api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  if (root) root.DataHotDetail = api;
  if (root && root.document) api.boot(root);
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  "use strict";

  function shouldUseHistoryBack(referrer, currentHref, historyLength) {
    if (!referrer || Number(historyLength) <= 1) return false;
    try {
      var current = new URL(currentHref);
      var source = new URL(referrer, current);
      if (source.origin !== current.origin) return false;
      var match = current.pathname.match(/^(.*\/)e\/[^/]+\.html$/);
      if (!match) return false;
      var siteRoot = match[1];
      return source.pathname === siteRoot || source.pathname === siteRoot + "index.html";
    } catch (error) {
      return false;
    }
  }

  function boot(win) {
    var links = Array.from(win.document.querySelectorAll("[data-smart-back],[data-smart-home-return]"));
    links.forEach(function (link) {
      link.addEventListener("click", function (event) {
        if (event.defaultPrevented || event.button > 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
        if (!shouldUseHistoryBack(win.document.referrer, win.location.href, win.history.length)) return;
        event.preventDefault();
        win.history.back();
      });
    });
  }

  return {
    shouldUseHistoryBack: shouldUseHistoryBack,
    boot: boot
  };
});
