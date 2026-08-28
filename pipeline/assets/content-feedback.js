(function (root, factory) {
  "use strict";
  var api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  if (root) root.DataHotContentFeedback = api;
  if (root && root.document) api.boot(root);
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  "use strict";

  var STORAGE_KEY = "dh_content_feedback_v1";
  var VALUES = ["useful", "not_useful"];
  var REASONS = [
    "solid", "relevant", "novel", "source_discovery",
    "irrelevant", "shallow", "marketing", "duplicate", "body_quality"
  ];

  function uniqueStrings(values, maximum) {
    var seen = Object.create(null);
    return (Array.isArray(values) ? values : []).reduce(function (output, value) {
      var clean = String(value || "").trim().slice(0, 80);
      if (!clean || seen[clean] || output.length >= maximum) return output;
      seen[clean] = true; output.push(clean); return output;
    }, []);
  }

  function normalizeStore(raw) {
    var source = raw && typeof raw === "object" ? raw : {};
    var entries = {};
    Object.keys(source.entries && typeof source.entries === "object" ? source.entries : {}).slice(-300).forEach(function (id) {
      var row = source.entries[id];
      if (!/^[a-f0-9]{12}$/.test(id) || !row || VALUES.indexOf(row.value) < 0) return;
      entries[id] = {
        value: row.value,
        reason: REASONS.indexOf(row.reason) >= 0 ? row.reason : "",
        topics: uniqueStrings(row.topics, 8), vendors: uniqueStrings(row.vendors, 8),
        source: String(row.source || "").trim().slice(0, 80),
        ts: /^\d{4}-\d{2}-\d{2}T/.test(String(row.ts || "")) ? String(row.ts) : ""
      };
    });
    return { version: 1, entries: entries };
  }

  function load(storage) {
    if (!storage) return normalizeStore({});
    try { return normalizeStore(JSON.parse(storage.getItem(STORAGE_KEY) || "null")); }
    catch (_error) { return normalizeStore({}); }
  }

  function save(storage, state) {
    var clean = normalizeStore(state);
    if (storage) {
      try { storage.setItem(STORAGE_KEY, JSON.stringify(clean)); } catch (_error) {}
    }
    return clean;
  }

  function record(state, event, value, reason, timestamp) {
    var clean = normalizeStore(state);
    var id = String(event && event.event_id || "");
    if (!/^[a-f0-9]{12}$/.test(id) || VALUES.indexOf(value) < 0) return clean;
    clean.entries[id] = {
      value: value,
      reason: REASONS.indexOf(reason) >= 0 ? reason : "",
      topics: uniqueStrings(event.topics, 8), vendors: uniqueStrings(event.vendors, 8),
      source: String(event.source || "").trim().slice(0, 80),
      ts: timestamp || new Date().toISOString()
    };
    return normalizeStore(clean);
  }

  function boot(win) {
    var doc = win.document;
    var boxes = Array.from(doc.querySelectorAll("[data-content-feedback]"));
    if (!boxes.length) return;
    var storage = null;
    try { storage = win.localStorage; } catch (_error) {}
    var state = load(storage);

    function context(box) {
      var payload = {};
      try { payload = JSON.parse(box.getAttribute("data-feedback-context") || "{}"); }
      catch (_error) {}
      return {
        event_id: String(box.getAttribute("data-event-id") || ""),
        topics: uniqueStrings(payload.topics, 8), vendors: uniqueStrings(payload.vendors, 8),
        source: String(payload.source || "").slice(0, 80)
      };
    }
    function render(box) {
      var item = state.entries[String(box.getAttribute("data-event-id") || "")] || null;
      box.querySelectorAll("[data-feedback-value]").forEach(function (button) {
        var selected = Boolean(item && item.value === button.getAttribute("data-feedback-value"));
        button.classList.toggle("on", selected);
        button.setAttribute("aria-pressed", selected ? "true" : "false");
      });
      box.querySelectorAll("[data-feedback-reasons]").forEach(function (group) {
        group.hidden = !item || group.getAttribute("data-feedback-reasons") !== item.value;
      });
      box.querySelectorAll("[data-feedback-reason]").forEach(function (button) {
        button.classList.toggle("on", Boolean(item && item.reason === button.getAttribute("data-feedback-reason")));
      });
      var status = box.querySelector("[data-feedback-status]");
      if (status) status.textContent = item ? "已记录，当前设备的关注排序会立即调整" : "反馈只用于改善内容筛选，不等同于收藏";
    }
    function emit(box, item) {
      if (!win.DataHotAnalytics || typeof win.DataHotAnalytics.track !== "function") return;
      win.DataHotAnalytics.track("content_feedback", {
        event_id: box.getAttribute("data-event-id") || "",
        action: item.value,
        feedback_reason: item.reason || ""
      });
    }

    boxes.forEach(function (box) {
      box.addEventListener("click", function (event) {
        var valueButton = event.target.closest("[data-feedback-value]");
        var reasonButton = event.target.closest("[data-feedback-reason]");
        var itemContext = context(box);
        if (valueButton) {
          state = record(state, itemContext, valueButton.getAttribute("data-feedback-value"), "");
        } else if (reasonButton) {
          var current = state.entries[itemContext.event_id];
          if (!current) return;
          state = record(state, itemContext, current.value, reasonButton.getAttribute("data-feedback-reason"));
        } else {
          return;
        }
        state = save(storage, state);
        render(box);
        emit(box, state.entries[itemContext.event_id]);
        try { win.dispatchEvent(new win.CustomEvent("datahot:feedback")); } catch (_error) {}
      });
      render(box);
    });
  }

  return {
    storageKey: STORAGE_KEY,
    normalizeStore: normalizeStore,
    load: load,
    save: save,
    record: record,
    boot: boot
  };
});
