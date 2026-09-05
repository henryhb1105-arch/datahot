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

  function questionsFor(record) {
    var value = record && record.designQuestions;
    if (Array.isArray(value)) return value.map(String).filter(Boolean);
    return String(value || "").split("|").filter(Boolean);
  }

  function matchesCase(record, state) {
    record = record || {};
    state = state || {};
    var query = normalized(state.query);
    var product = String(state.product || "");
    var task = String(state.task || "");
    var question = String(state.question || "");
    if (product && String(record.productType || "") !== product) return false;
    if (task && String(record.taskType || "") !== task) return false;
    if (question && questionsFor(record).indexOf(question) === -1) return false;
    return !query || normalized(record.searchText).indexOf(query) !== -1;
  }

  function filterCases(records, state) {
    return (records || []).filter(function (record) { return matchesCase(record, state); });
  }

  function selectedAfterToggle(current, id, maximum) {
    var values = (current || []).slice();
    var index = values.indexOf(id);
    if (index !== -1) {
      values.splice(index, 1);
      return values;
    }
    if (values.length >= (maximum || 3)) return values;
    values.push(id);
    return values;
  }

  function clearNode(node) {
    while (node && node.firstChild) node.removeChild(node.firstChild);
  }

  function boot(win) {
    var doc = win && win.document;
    if (!doc || typeof doc.querySelector !== "function") return;
    var page = doc.querySelector("[data-cases-page]");
    if (!page) return;
    var cards = Array.from(page.querySelectorAll("[data-case-card]"));
    var search = page.querySelector("[data-case-search]");
    var counts = Array.from(page.querySelectorAll("[data-case-count]"));
    var empty = page.querySelector("[data-case-empty]");
    var reset = page.querySelector("[data-case-reset]");
    var buttons = Array.from(page.querySelectorAll("[data-case-filter-kind]"));
    var moreFilters = page.querySelector("[data-case-more-filters]");
    var moreSummary = moreFilters && moreFilters.querySelector("summary");
    var compareBar = doc.querySelector("[data-case-compare-bar]");
    var compareStatus = doc.querySelector("[data-case-compare-status]");
    var compareClear = doc.querySelector("[data-case-compare-clear]");
    var compareOpen = doc.querySelector("[data-case-compare-open]");
    var compareDialog = doc.querySelector("[data-case-compare-dialog]");
    var compareClose = doc.querySelector("[data-case-compare-close]");
    var compareContent = doc.querySelector("[data-case-compare-content]");
    var state = { query: "", product: "", task: "", question: "" };
    var selectedIds = [];
    var limitMessage = "";

    function recordFor(card) {
      return {
        element: card,
        id: card.getAttribute("data-case-id") || "",
        productType: card.getAttribute("data-product-type") || "",
        taskType: card.getAttribute("data-task-type") || "",
        designQuestions: card.getAttribute("data-design-questions") || "",
        searchText: card.getAttribute("data-search") || "",
        product: card.getAttribute("data-compare-product") || "",
        problem: card.getAttribute("data-compare-problem") || "",
        pattern: card.getAttribute("data-compare-pattern") || "",
        modules: card.getAttribute("data-compare-modules") || "",
        takeaway: card.getAttribute("data-compare-takeaway") || "",
        tradeoff: card.getAttribute("data-compare-tradeoff") || "",
        url: card.getAttribute("data-compare-url") || ""
      };
    }

    function syncFilterButtons(kind) {
      buttons.forEach(function (button) {
        if (button.getAttribute("data-case-filter-kind") !== kind) return;
        var on = (button.getAttribute("data-case-filter-value") || "") === state[kind];
        button.classList.toggle("on", on);
        button.setAttribute("aria-pressed", on ? "true" : "false");
      });
    }

    function updateQuestionUrl() {
      if (!win.history || typeof win.history.replaceState !== "function" || !win.location) return;
      try {
        var url = new URL(win.location.href);
        if (state.question) url.searchParams.set("question", state.question);
        else url.searchParams.delete("question");
        win.history.replaceState(null, "", url.pathname + url.search + url.hash);
      } catch (error) {
        // Filtering still works in older or local-file browsers without URL support.
      }
    }

    function render() {
      var visible = 0;
      cards.forEach(function (card) {
        var show = matchesCase(recordFor(card), state);
        card.hidden = !show;
        if (show) visible += 1;
      });
      counts.forEach(function (count) { count.textContent = String(visible); });
      if (empty) empty.classList.toggle("show", visible === 0);
      var active = Boolean(state.query || state.product || state.task || state.question);
      if (reset) reset.hidden = !active;
      if (moreSummary) {
        var secondaryCount = Number(Boolean(state.product)) + Number(Boolean(state.task));
        moreSummary.textContent = secondaryCount ? "更多筛选 · " + secondaryCount : "更多筛选";
      }
    }

    function updateCompareBar() {
      cards.forEach(function (card) {
        var record = recordFor(card);
        var selected = selectedIds.indexOf(record.id) !== -1;
        var toggle = card.querySelector("[data-case-compare-toggle]");
        if (!toggle) return;
        toggle.setAttribute("aria-pressed", selected ? "true" : "false");
        toggle.textContent = selected ? "已加入" : "加入对比";
      });
      if (compareBar) compareBar.hidden = selectedIds.length === 0;
      if (compareOpen) compareOpen.disabled = selectedIds.length < 2;
      if (compareStatus) {
        clearNode(compareStatus);
        var bold = doc.createElement("b");
        bold.textContent = "已选 " + selectedIds.length + " / 3";
        compareStatus.appendChild(bold);
        compareStatus.appendChild(doc.createTextNode(
          limitMessage || (selectedIds.length < 2 ? "至少选择 2 个案例" : "可以开始比较")
        ));
      }
    }

    function selectedRecords() {
      return selectedIds.map(function (id) {
        var card = cards.find(function (candidate) {
          return (candidate.getAttribute("data-case-id") || "") === id;
        });
        return card ? recordFor(card) : null;
      }).filter(Boolean);
    }

    function appendCell(row, tagName, value) {
      var cell = doc.createElement(tagName);
      cell.textContent = value || "—";
      row.appendChild(cell);
      return cell;
    }

    function renderComparison() {
      if (!compareContent) return;
      clearNode(compareContent);
      var records = selectedRecords();
      var table = doc.createElement("table");
      table.className = "case-compare-table";
      var head = doc.createElement("thead");
      var headRow = doc.createElement("tr");
      appendCell(headRow, "th", "比较维度");
      records.forEach(function (record) {
        var cell = appendCell(headRow, "th", "");
        clearNode(cell);
        var link = doc.createElement("a");
        link.href = record.url;
        link.textContent = record.product;
        cell.appendChild(link);
      });
      head.appendChild(headRow);
      table.appendChild(head);
      var body = doc.createElement("tbody");
      [
        ["要解决的问题", "problem"],
        ["核心设计模式", "pattern"],
        ["关键模块", "modules"],
        ["可以借鉴", "takeaway"],
        ["代价与边界", "tradeoff"]
      ].forEach(function (definition) {
        var row = doc.createElement("tr");
        appendCell(row, "th", definition[0]);
        records.forEach(function (record) {
          var cell = appendCell(row, "td", "");
          clearNode(cell);
          var productLink = doc.createElement("a");
          productLink.className = "case-compare-product";
          productLink.href = record.url;
          productLink.textContent = record.product;
          cell.appendChild(productLink);
          var content = doc.createElement("p");
          content.textContent = record[definition[1]] || "—";
          cell.appendChild(content);
        });
        body.appendChild(row);
      });
      table.appendChild(body);
      compareContent.appendChild(table);
    }

    function closeComparison() {
      if (!compareDialog) return;
      if (typeof compareDialog.close === "function") compareDialog.close();
      else compareDialog.removeAttribute("open");
    }

    if (win.location) {
      try {
        var requestedQuestion = new URL(win.location.href).searchParams.get("question") || "";
        var validQuestion = buttons.some(function (button) {
          return button.getAttribute("data-case-filter-kind") === "question" &&
            button.getAttribute("data-case-filter-value") === requestedQuestion;
        });
        if (validQuestion) state.question = requestedQuestion;
      } catch (error) {
        // Ignore malformed local URLs.
      }
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
        if (["product", "task", "question"].indexOf(kind) === -1) return;
        state[kind] = value;
        syncFilterButtons(kind);
        if (kind === "question") updateQuestionUrl();
        if (kind !== "question" && moreFilters) moreFilters.open = false;
        render();
      });
    });
    if (reset) {
      reset.addEventListener("click", function () {
        state = { query: "", product: "", task: "", question: "" };
        if (search) search.value = "";
        ["product", "task", "question"].forEach(syncFilterButtons);
        if (moreFilters) moreFilters.open = false;
        updateQuestionUrl();
        render();
      });
    }
    cards.forEach(function (card) {
      var toggle = card.querySelector("[data-case-compare-toggle]");
      if (!toggle) return;
      toggle.addEventListener("click", function () {
        var id = card.getAttribute("data-case-id") || "";
        var wasSelected = selectedIds.indexOf(id) !== -1;
        var next = selectedAfterToggle(selectedIds, id, 3);
        limitMessage = !wasSelected && next.length === selectedIds.length
          ? "最多选择 3 个案例，请先移除一个"
          : "";
        selectedIds = next;
        updateCompareBar();
      });
    });
    if (compareClear) {
      compareClear.addEventListener("click", function () {
        selectedIds = [];
        limitMessage = "";
        updateCompareBar();
      });
    }
    if (compareOpen) {
      compareOpen.addEventListener("click", function () {
        if (selectedIds.length < 2 || !compareDialog) return;
        renderComparison();
        if (typeof compareDialog.showModal === "function") compareDialog.showModal();
        else compareDialog.setAttribute("open", "");
      });
    }
    if (compareClose) compareClose.addEventListener("click", closeComparison);
    if (compareDialog) {
      compareDialog.addEventListener("click", function (event) {
        if (event.target === compareDialog) closeComparison();
      });
    }

    ["product", "task", "question"].forEach(syncFilterButtons);
    render();
    updateCompareBar();
  }

  return {
    normalized: normalized,
    questionsFor: questionsFor,
    matchesCase: matchesCase,
    filterCases: filterCases,
    selectedAfterToggle: selectedAfterToggle,
    boot: boot
  };
});
