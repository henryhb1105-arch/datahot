(function (root, factory) {
  "use strict";
  var api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  if (root && root.document) api.boot(root);
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  "use strict";
  function stepFromHash(hash, count) {
    var match = /^#step-([1-9][0-9]*)$/.exec(String(hash || ""));
    var step = match ? Number(match[1]) : 1;
    return step <= count ? step : 1;
  }
  function safeImage(url, base) {
    try {
      var resolved = new URL(url, base);
      var origin = new URL(base).origin;
      return resolved.origin === origin && /^\/(?:case-media|media)\/[a-zA-Z0-9_-]+\/[a-zA-Z0-9_-]+\.(png|jpe?g|webp|svg)$/.test(resolved.pathname) ? resolved.href : "";
    } catch (_) { return ""; }
  }
  function boot(win) {
    var doc = win.document;
    var study = doc.querySelector("[data-study-page]");
    if (study && study.querySelector("[data-study-step]")) {
      var panels = Array.from(study.querySelectorAll("[data-study-step]"));
      var selectors = Array.from(study.querySelectorAll("[data-step-select]"));
      var current = stepFromHash(win.location.hash, panels.length);
      var previous = study.querySelector("[data-step-prev]");
      var next = study.querySelector("[data-step-next]");
      var stepLabel = study.getAttribute("data-step-label") || "操作";
      function selectStep(number, updateUrl, reveal) {
        current = Math.min(panels.length, Math.max(1, number));
        panels.forEach(function (panel, i) { panel.hidden = i + 1 !== current; });
        selectors.forEach(function (button, i) { button.setAttribute("aria-pressed", i + 1 === current ? "true" : "false"); });
        previous.disabled = current === 1;
        next.disabled = current === panels.length;
        study.querySelector("[data-step-status]").textContent = stepLabel + " " + current + " / " + panels.length;
        var selectedButton = selectors[current - 1];
        var nav = study.querySelector("[data-step-nav]");
        if (selectedButton) {
          var left = selectedButton.offsetLeft - nav.offsetLeft;
          if (left < nav.scrollLeft) nav.scrollLeft = left;
          else if (left + selectedButton.offsetWidth > nav.scrollLeft + nav.clientWidth) nav.scrollLeft = left + selectedButton.offsetWidth - nav.clientWidth;
        }
        if (updateUrl && win.history && win.history.replaceState) {
          win.history.replaceState(null, "", win.location.pathname + win.location.search + "#step-" + current);
        }
        if (reveal && win.innerWidth <= 900) panels[current - 1].scrollIntoView({ block: "start", behavior: "auto" });
      }
      selectors.forEach(function (button) {
        button.addEventListener("click", function () { selectStep(Number(button.getAttribute("data-step-select")), true); });
      });
      previous.addEventListener("click", function () { selectStep(current - 1, true, true); });
      next.addEventListener("click", function () { selectStep(current + 1, true, true); });
      win.addEventListener("hashchange", function () {
        selectStep(stepFromHash(win.location.hash, panels.length), false);
        if (/^#step-/.test(win.location.hash)) panels[current - 1].scrollIntoView({ block: "start" });
      });
      study.querySelector("[data-step-nav]").hidden = false;
      study.querySelector("[data-step-controls]").hidden = false;
      selectStep(current, false);
    }

    var dialog = doc.querySelector("[data-image-dialog]");
    if (!dialog || typeof dialog.showModal !== "function") return;
    var links = Array.from(doc.querySelectorAll("[data-case-image]"));
    var selected = [], index = 0, opener = null, scrollOverflow = "";
    var full = dialog.querySelector("[data-image-full]");
    var canvas = dialog.querySelector("[data-image-canvas]");
    var zoom = dialog.querySelector("[data-image-zoom]");
    function renderImage() {
      var link = selected[index];
      var image = link.querySelector("img");
      full.src = safeImage(link.href, win.location.href);
      full.alt = image ? image.alt : "产品界面";
      dialog.querySelector("[data-image-title]").textContent = link.getAttribute("data-image-caption") || full.alt;
      dialog.querySelector("[data-image-count]").textContent = (index + 1) + " / " + selected.length;
      dialog.querySelector("[data-image-prev]").disabled = index === 0;
      dialog.querySelector("[data-image-next]").disabled = index === selected.length - 1;
      canvas.classList.remove("is-zoomed");
      canvas.scrollTop = canvas.scrollLeft = 0;
      zoom.setAttribute("aria-pressed", "false");
      zoom.textContent = "原尺寸";
      var caseLink = dialog.querySelector("[data-image-case]");
      var target = link.getAttribute("data-case-target") || "";
      caseLink.hidden = !/^(?:cases\/[a-z0-9-]+|e\/[a-f0-9]{12})\.html$/.test(target);
      if (!caseLink.hidden) caseLink.href = target;
    }
    function move(delta) {
      index = Math.max(0, Math.min(selected.length - 1, index + delta));
      renderImage();
    }
    links.forEach(function (link) {
      link.addEventListener("click", function (event) {
        if (event.defaultPrevented || event.button > 0 || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey || !safeImage(link.href, win.location.href)) return;
        event.preventDefault();
        opener = link;
        selected = links.filter(function (candidate) { return candidate.getAttribute("data-image-group") === link.getAttribute("data-image-group"); });
        index = selected.indexOf(link);
        renderImage();
        scrollOverflow = doc.body.style.overflow;
        doc.body.style.overflow = "hidden";
        dialog.showModal();
      });
    });
    dialog.querySelector("[data-image-close]").addEventListener("click", function () { dialog.close(); });
    dialog.querySelector("[data-image-prev]").addEventListener("click", function () { move(-1); });
    dialog.querySelector("[data-image-next]").addEventListener("click", function () { move(1); });
    zoom.addEventListener("click", function () {
      var on = !canvas.classList.contains("is-zoomed");
      canvas.classList.toggle("is-zoomed", on);
      zoom.setAttribute("aria-pressed", String(on));
      zoom.textContent = on ? "适应屏幕" : "原尺寸";
    });
    dialog.addEventListener("keydown", function (event) {
      if (canvas.classList.contains("is-zoomed")) return;
      if (event.key === "ArrowLeft" || event.key === "ArrowRight") { event.preventDefault(); move(event.key === "ArrowLeft" ? -1 : 1); }
    });
    dialog.addEventListener("close", function () {
      doc.body.style.overflow = scrollOverflow;
      if (opener) opener.focus({ preventScroll: true });
    });
  }
  return { stepFromHash: stepFromHash, safeImage: safeImage, boot: boot };
});
