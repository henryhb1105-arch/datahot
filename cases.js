(function (root, factory) {
  "use strict";
  var api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  if (root) root.DataHotCases = api;
  if (root && root.document) api.boot(root);
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  "use strict";

  function normalized(value) {
    return String(value == null ? "" : value).trim().toLocaleLowerCase();
  }

  function matchesCase(record, state) {
    record = record || {};
    state = state || {};
    var query = normalized(state.query);
    var product = String(state.product || "");
    var task = String(state.task || "");
    if (product && String(record.productType || "") !== product) return false;
    if (task && String(record.taskType || "") !== task) return false;
    return !query || normalized(record.searchText).indexOf(query) !== -1;
  }

  function filterCases(records, state) {
    return (records || []).filter(function (record) { return matchesCase(record, state); });
  }

  function boot(win) {
    var doc = win && win.document;
    if (!doc || typeof doc.querySelector !== "function") return;
    var page = doc.querySelector("[data-cases-page]");
    if (!page) return;
    var cards = Array.from(page.querySelectorAll("[data-case-card]"));
    var search = page.querySelector("[data-case-search]");
    var count = page.querySelector("[data-case-count]");
    var empty = page.querySelector("[data-case-empty]");
    var buttons = Array.from(page.querySelectorAll("[data-case-filter-kind]"));
    var state = { query: "", product: "", task: "" };

    function recordFor(card) {
      return {
        element: card,
        productType: card.getAttribute("data-product-type") || "",
        taskType: card.getAttribute("data-task-type") || "",
        searchText: card.getAttribute("data-search") || ""
      };
    }

    function render() {
      var visible = 0;
      cards.forEach(function (card) {
        var show = matchesCase(recordFor(card), state);
        card.hidden = !show;
        if (show) visible += 1;
      });
      if (count) count.textContent = String(visible);
      if (empty) empty.classList.toggle("show", visible === 0);
    }

    if (search) {
      search.addEventListener("input", function () {
        state.query = search.value || "";
        render();
      });
    }
    buttons.forEach(function (button) {
      button.addEventListener("click", function () {
        var kind = button.getAttribute("data-case-filter-kind");
        var value = button.getAttribute("data-case-filter-value") || "";
        if (kind !== "product" && kind !== "task") return;
        state[kind] = value;
        buttons.forEach(function (candidate) {
          if (candidate.getAttribute("data-case-filter-kind") !== kind) return;
          var on = candidate === button;
          candidate.classList.toggle("on", on);
          candidate.setAttribute("aria-pressed", on ? "true" : "false");
        });
        render();
      });
    });
    render();
  }

  return {
    normalized: normalized,
    matchesCase: matchesCase,
    filterCases: filterCases,
    boot: boot
  };
});
