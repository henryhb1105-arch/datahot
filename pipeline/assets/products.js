(function (root, factory) {
  "use strict";
  var api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  if (root && root.document) api.boot(root);
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  "use strict";
  var STORAGE_KEY = "dh_for_me_v1";
  function readFollowing(storage) {
    try {
      var state = JSON.parse(storage.getItem(STORAGE_KEY) || "{}");
      return Array.isArray(state && state.products) ? state.products.filter(function (id) {
        return typeof id === "string" && /^[a-z][a-z0-9-]{1,63}$/.test(id);
      }).slice(0, 50) : [];
    } catch (_) { return []; }
  }
  function boot(win) {
    var page = win.document.querySelector("[data-product-radar]");
    if (!page) return;
    var mode = "all";
    var cards = Array.from(page.querySelectorAll("[data-radar-product]"));
    var buttons = Array.from(page.querySelectorAll("[data-radar-filter]"));
    function render() {
      var following = [];
      try { following = readFollowing(win.localStorage); } catch (_) {}
      var count = 0;
      cards.forEach(function (card) {
        var followed = following.indexOf(card.dataset.radarProduct) >= 0;
        card.hidden = mode === "following" && !followed;
        if (!card.hidden) count += 1;
        var link = card.querySelector("[data-radar-follow]");
        if (link) {
          link.textContent = followed ? "已关注 →" : "关注产品";
          link.setAttribute("aria-label", (followed ? "查看已关注的 " : "关注 ") + link.dataset.productName);
        }
      });
      buttons.forEach(function (button) { button.setAttribute("aria-pressed", String(button.dataset.radarFilter === mode)); });
      page.querySelector("[data-radar-count]").textContent = count + " 个产品";
      page.querySelector("[data-radar-empty]").hidden = count !== 0;
    }
    buttons.forEach(function (button) {
      button.addEventListener("click", function () { mode = button.dataset.radarFilter; render(); });
    });
    page.querySelector("[data-radar-reset]").addEventListener("click", function () { mode = "all"; render(); });
    win.addEventListener("storage", function (event) { if (!event.key || event.key === STORAGE_KEY) render(); });
    win.addEventListener("pageshow", render);
    page.querySelector("[data-radar-controls]").hidden = false;
    render();
  }
  return { readFollowing: readFollowing, boot: boot };
});
