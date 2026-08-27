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

  function readingProgress(scrollY, sectionTop, sectionHeight, viewportHeight) {
    var start = Number(sectionTop) || 0;
    var end = start + Math.max(0, Number(sectionHeight) || 0) - Math.max(0, Number(viewportHeight) || 0);
    if (end <= start) return Number(scrollY) >= start ? 1 : 0;
    return Math.max(0, Math.min(1, (Number(scrollY) - start) / (end - start)));
  }

  function tableScrollState(scrollLeft, clientWidth, scrollWidth) {
    var overflow = Number(scrollWidth) > Number(clientWidth) + 2;
    return {
      overflow: overflow,
      scrolled: overflow && Number(scrollLeft) > 4,
      atEnd: !overflow || Number(scrollLeft) + Number(clientWidth) >= Number(scrollWidth) - 2
    };
  }

  function setupReadingNavigation(win) {
    var doc = win.document;
    if (!doc || typeof doc.querySelector !== "function") return;
    var progress = doc.querySelector("[data-reading-progress]");
    var section = doc.querySelector(".content-section");
    var headings = Array.from(doc.querySelectorAll("[data-article-heading]"));
    var links = Array.from(doc.querySelectorAll("[data-toc-link]"));
    if (!progress || !section || !headings.length) return;

    var queued = false;
    function update() {
      queued = false;
      var scrollY = Number(win.scrollY || win.pageYOffset || 0);
      var sectionTop = section.getBoundingClientRect().top + scrollY;
      var ratio = readingProgress(scrollY, sectionTop, section.offsetHeight, win.innerHeight);
      progress.style.transform = "scaleX(" + ratio.toFixed(4) + ")";

      var topbar = doc.querySelector(".detail-context");
      var threshold = (topbar ? topbar.getBoundingClientRect().height : 0) + 24;
      var activeId = headings[0].id;
      headings.forEach(function (heading) {
        if (heading.getBoundingClientRect().top <= threshold) activeId = heading.id;
      });
      links.forEach(function (link) {
        if (link.getAttribute("data-toc-target") === activeId) {
          link.setAttribute("aria-current", "location");
        } else {
          link.removeAttribute("aria-current");
        }
      });
    }
    function queueUpdate() {
      if (queued) return;
      queued = true;
      if (typeof win.requestAnimationFrame === "function") win.requestAnimationFrame(update);
      else update();
    }
    win.addEventListener("scroll", queueUpdate, { passive: true });
    win.addEventListener("resize", queueUpdate);
    update();
  }

  function setupScrollableTables(win) {
    var doc = win.document;
    if (!doc || typeof doc.querySelector !== "function") return;
    var shells = Array.from(doc.querySelectorAll("[data-table-shell]"));
    if (!shells.length) return;
    var updaters = [];
    shells.forEach(function (shell) {
      var table = shell.querySelector("[data-scroll-table]");
      if (!table) return;
      function update() {
        var state = tableScrollState(table.scrollLeft, table.clientWidth, table.scrollWidth);
        shell.classList.toggle("is-overflowing", state.overflow);
        shell.classList.toggle("at-end", state.atEnd);
        if (state.scrolled) shell.classList.add("has-scrolled");
      }
      table.addEventListener("scroll", update, { passive: true });
      updaters.push(update);
      update();
    });
    if (updaters.length) {
      win.addEventListener("resize", function () { updaters.forEach(function (update) { update(); }); });
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
    setupReadingNavigation(win);
    setupScrollableTables(win);
  }

  return {
    shouldUseHistoryBack: shouldUseHistoryBack,
    readingProgress: readingProgress,
    tableScrollState: tableScrollState,
    setupReadingNavigation: setupReadingNavigation,
    setupScrollableTables: setupScrollableTables,
    boot: boot
  };
});
