(function (root, factory) {
  "use strict";
  var api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  if (root) root.DataHotAnalytics = api;
  if (root && root.document) api.boot(root);
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  "use strict";

  var EVENT_NAMES = [
    "session_start", "list_exposure", "detail_click", "outbound_click",
    "favorite_toggle", "content_feedback", "search", "filter",
    "weekly_brief_click", "daily_brief_click"
  ];
  var ALLOWED_FIELDS = [
    "schema_version", "event_uuid", "name", "ts", "environment", "site_id",
    "page", "event_id", "category", "source", "session_id", "device_id",
    "sequence", "viewport", "referrer", "action", "filter", "query_bucket",
    "result_count", "feedback_reason"
  ];
  var PAGES = ["home", "for-me", "weekly", "daily", "topics", "topic", "hot", "favorites", "sources", "detail", "privacy", "other"];
  var CATEGORIES = ["agent", "platform", "bi", "product", "insight", ""];
  var DEVICE_KEY = "dh_analytics_device_v1";
  var SESSION_KEY = "dh_analytics_session_v1";
  var SESSION_STARTED_KEY = "dh_analytics_session_started_v1";
  var SEQUENCE_KEY = "dh_analytics_sequence_v1";
  var OPTOUT_KEY = "dh_analytics_optout_v1";
  var DEVICE_TTL_MS = 30 * 24 * 60 * 60 * 1000;

  function includes(list, value) { return list.indexOf(value) >= 0; }

  function cleanText(value, maximum) {
    var text = String(value || "").replace(/[\u0000-\u001f\u007f]/g, " ").trim();
    return text.slice(0, maximum);
  }

  function sanitizeEvent(input) {
    if (!input || typeof input !== "object" || !includes(EVENT_NAMES, input.name)) return null;
    var output = {};
    ALLOWED_FIELDS.forEach(function (field) {
      if (Object.prototype.hasOwnProperty.call(input, field)) output[field] = input[field];
    });
    output.schema_version = 1;
    output.site_id = cleanText(output.site_id, 40).toLowerCase().replace(/[^a-z0-9_-]/g, "");
    output.page = includes(PAGES, output.page) ? output.page : "other";
    output.event_id = /^[a-f0-9]{12}$/.test(String(output.event_id || "")) ? output.event_id : "";
    output.category = includes(CATEGORIES, String(output.category || "")) ? String(output.category || "") : "";
    output.source = cleanText(output.source, 80);
    output.filter = cleanText(output.filter, 40);
    output.action = includes(["add", "remove", "useful", "not_useful"], output.action) ? output.action : "";
    output.feedback_reason = includes([
      "solid", "relevant", "novel", "source_discovery", "irrelevant",
      "shallow", "marketing", "duplicate", "body_quality"
    ], output.feedback_reason) ? output.feedback_reason : "";
    output.query_bucket = includes(["1-3", "4-8", "9+"], output.query_bucket) ? output.query_bucket : "";
    if (Object.prototype.hasOwnProperty.call(output, "result_count")) {
      output.result_count = Math.max(0, Math.min(100000, Number(output.result_count) || 0));
    }
    ["event_id", "category", "source", "filter", "action", "query_bucket", "feedback_reason"].forEach(function (field) {
      if (!output[field]) delete output[field];
    });
    return output;
  }

  function queryBucket(value) {
    var length = String(value || "").trim().length;
    if (!length) return "";
    if (length <= 3) return "1-3";
    if (length <= 8) return "4-8";
    return "9+";
  }

  function pageFromPath(pathname) {
    var path = String(pathname || "").replace(/\/+$/, "");
    if (!path || /\/datahot$/.test(path)) return "home";
    if (/\/e\/[a-f0-9]{12}\.html$/.test(path)) return "detail";
    if (/\/topics\/[^/]+\.html$/.test(path)) return "topic";
    if (/\/weekly\/\d{4}-W\d{2}\.html$/.test(path)) return "weekly";
    var filename = path.split("/").pop() || "index.html";
    var pages = {
      "index.html": "home", "for-me.html": "for-me", "weekly.html": "weekly", "daily.html": "weekly", "topics.html": "topics",
      "hot.html": "hot", "favorites.html": "favorites", "sources.html": "sources",
      "privacy.html": "privacy"
    };
    return pages[filename] || "other";
  }

  function boot(win) {
    var doc = win.document;
    var meta = doc.querySelector('meta[name="datahot-analytics"]');
    if (!meta) return;
    var config = {
      enabled: meta.getAttribute("data-enabled") === "true",
      endpoint: meta.getAttribute("data-endpoint") || "",
      siteId: meta.getAttribute("data-site-id") || "datahot",
      environment: meta.getAttribute("data-environment") || "",
      productionHost: meta.getAttribute("data-production-host") || "datahot.xiahongbin.com"
    };
    var queue = [];
    var flushTimer = null;
    var active = false;
    var local = null;
    var session = null;
    try { local = win.localStorage; session = win.sessionStorage; } catch (_error) {}

    function storageGet(storage, key) {
      if (!storage) return null;
      try { return storage.getItem(key); } catch (_error) { return null; }
    }
    function storageSet(storage, key, value) {
      if (!storage) return false;
      try { storage.setItem(key, value); return true; } catch (_error) { return false; }
    }
    function storageRemove(storage, key) {
      if (!storage) return;
      try { storage.removeItem(key); } catch (_error) {}
    }
    function uuid() {
      if (win.crypto && typeof win.crypto.randomUUID === "function") return win.crypto.randomUUID();
      if (!win.crypto || typeof win.crypto.getRandomValues !== "function") return "";
      var bytes = new Uint8Array(16);
      win.crypto.getRandomValues(bytes);
      bytes[6] = (bytes[6] & 15) | 64;
      bytes[8] = (bytes[8] & 63) | 128;
      var hex = Array.prototype.map.call(bytes, function (value) { return value.toString(16).padStart(2, "0"); }).join("");
      return [hex.slice(0, 8), hex.slice(8, 12), hex.slice(12, 16), hex.slice(16, 20), hex.slice(20)].join("-");
    }
    function privacySignal() {
      return Boolean(
        win.navigator && (
          win.navigator.globalPrivacyControl === true ||
          win.navigator.doNotTrack === "1" ||
          win.doNotTrack === "1"
        )
      );
    }
    function validEndpoint(value) {
      try {
        var parsed = new URL(value);
        return parsed.protocol === "https:" && !parsed.username && !parsed.password;
      } catch (_error) { return false; }
    }
    function updatePrivacyStatus() {
      var message = active
        ? "匿名统计已启用（30 天随机设备 ID，不采集正文或完整搜索词）"
        : "匿名统计已关闭，不会发送行为事件";
      doc.querySelectorAll("[data-analytics-status]").forEach(function (node) { node.textContent = message; });
    }
    function disable() {
      storageSet(local, OPTOUT_KEY, "1");
      storageRemove(local, DEVICE_KEY);
      storageRemove(session, SESSION_KEY);
      storageRemove(session, SESSION_STARTED_KEY);
      storageRemove(session, SEQUENCE_KEY);
      queue.length = 0;
      active = false;
      updatePrivacyStatus();
    }
    function enable() {
      storageRemove(local, OPTOUT_KEY);
      if (win.location && typeof win.location.reload === "function") win.location.reload();
    }
    doc.addEventListener("click", function (event) {
      if (event.target.closest("[data-analytics-opt-out]")) { event.preventDefault(); disable(); }
      if (event.target.closest("[data-analytics-opt-in]")) { event.preventDefault(); enable(); }
    }, true);

    active = Boolean(
      config.enabled && config.environment === "production" &&
      win.location.hostname === config.productionHost && validEndpoint(config.endpoint) &&
      storageGet(local, OPTOUT_KEY) !== "1" && !privacySignal()
    );
    updatePrivacyStatus();
    if (!active) {
      api.disable = disable;
      api.enable = enable;
      return;
    }

    var now = Date.now();
    var deviceRecord = null;
    try { deviceRecord = JSON.parse(storageGet(local, DEVICE_KEY) || "null"); } catch (_error) {}
    if (!deviceRecord || !deviceRecord.id || !deviceRecord.created || now - deviceRecord.created > DEVICE_TTL_MS) {
      deviceRecord = { id: uuid(), created: now, last_seen: now };
    } else {
      deviceRecord.last_seen = now;
    }
    if (!deviceRecord.id || !storageSet(local, DEVICE_KEY, JSON.stringify(deviceRecord))) {
      active = false; updatePrivacyStatus(); return;
    }
    var sessionId = storageGet(session, SESSION_KEY) || uuid();
    if (!sessionId || !storageSet(session, SESSION_KEY, sessionId)) {
      active = false; updatePrivacyStatus(); return;
    }
    var page = pageFromPath(win.location.pathname);
    var body = doc.body;
    var lastSent = new Map();

    function nextSequence() {
      var value = Number(storageGet(session, SEQUENCE_KEY) || 0) + 1;
      storageSet(session, SEQUENCE_KEY, String(value));
      return value;
    }
    function viewportBucket() {
      var width = Number(win.innerWidth || 0);
      return width < 600 ? "small" : (width < 1024 ? "medium" : "large");
    }
    function referrerBucket() {
      if (!doc.referrer) return "direct";
      try {
        var ref = new URL(doc.referrer);
        if (ref.hostname === win.location.hostname) return "internal";
        if (/(google|bing|baidu|duckduckgo|sogou)\./i.test(ref.hostname)) return "search";
        if (/(weibo|weixin|twitter|x\.com|linkedin|facebook|bsky)\./i.test(ref.hostname)) return "social";
      } catch (_error) {}
      return "other";
    }
    function context(node) {
      var target = node || body;
      return {
        event_id: (target.dataset && target.dataset.eventId) || body.dataset.eventId || "",
        category: (target.dataset && target.dataset.category) || body.dataset.category || "",
        source: (target.dataset && target.dataset.source) || body.dataset.source || ""
      };
    }
    function flush() {
      if (!queue.length || !active) return;
      var events = queue.splice(0, queue.length);
      if (flushTimer) { win.clearTimeout(flushTimer); flushTimer = null; }
      var payload = JSON.stringify({ schema_version: 1, site_id: config.siteId, events: events });
      var sent = false;
      try {
        if (win.navigator && typeof win.navigator.sendBeacon === "function") {
          sent = win.navigator.sendBeacon(config.endpoint, new win.Blob([payload], { type: "text/plain;charset=UTF-8" }));
        }
      } catch (_error) {}
      if (!sent && typeof win.fetch === "function") {
        try {
          win.fetch(config.endpoint, {
            method: "POST", body: payload, keepalive: true, credentials: "omit",
            mode: "cors", cache: "no-store", referrerPolicy: "no-referrer",
            headers: { "Content-Type": "text/plain;charset=UTF-8" }
          }).catch(function () {});
        } catch (_error) {}
      }
    }
    function emit(name, properties, dedupeWindow) {
      if (!active || !includes(EVENT_NAMES, name)) return;
      var props = properties || {};
      var dedupeKey = [name, props.event_id || "", props.action || "", props.feedback_reason || "", props.filter || "", props.query_bucket || ""].join("|");
      var at = Date.now();
      if (lastSent.has(dedupeKey) && at - lastSent.get(dedupeKey) < (dedupeWindow || 750)) return;
      lastSent.set(dedupeKey, at);
      var raw = Object.assign({
        schema_version: 1, event_uuid: uuid(), name: name, ts: new Date().toISOString(),
        environment: "production", site_id: config.siteId, page: page,
        session_id: sessionId, device_id: deviceRecord.id, sequence: nextSequence(),
        viewport: viewportBucket(), referrer: referrerBucket()
      }, props);
      var clean = sanitizeEvent(raw);
      if (!clean || !clean.event_uuid) return;
      queue.push(clean);
      if (queue.length >= 5) flush();
      else if (!flushTimer) flushTimer = win.setTimeout(flush, 5000);
    }

    api.disable = disable;
    api.enable = enable;
    api.flush = flush;
    api.track = function (name, properties) { emit(name, properties || {}, 750); };

    if (storageGet(session, SESSION_STARTED_KEY) !== "1") {
      emit("session_start", {}, 0);
      storageSet(session, SESSION_STARTED_KEY, "1");
    }

    var exposed = new Set();
    var observer = null;
    function expose(node) {
      var props = context(node);
      if (!props.event_id || exposed.has(props.event_id)) return;
      exposed.add(props.event_id);
      emit("list_exposure", props, 0);
    }
    if ("IntersectionObserver" in win) {
      observer = new win.IntersectionObserver(function (entries) {
        entries.forEach(function (entry) {
          if (entry.isIntersecting && entry.intersectionRatio >= 0.4) {
            expose(entry.target); observer.unobserve(entry.target);
          }
        });
      }, { threshold: [0.4] });
    }
    function observeList(container) {
      var scope = container && container.querySelectorAll ? container : doc;
      var nodes = Array.prototype.slice.call(scope.querySelectorAll("[data-analytics-list][data-event-id]"));
      nodes.forEach(function (node) { if (observer) observer.observe(node); else expose(node); });
    }
    api.observeList = observeList;
    observeList(doc);

    doc.addEventListener("click", function (event) {
      var favorite = event.target.closest("[data-fav]");
      if (favorite) {
        emit("favorite_toggle", Object.assign(context(favorite.closest("[data-event-id]") || body), {
          event_id: favorite.getAttribute("data-fav") || "",
          action: favorite.classList.contains("on") ? "remove" : "add"
        }), 750);
        return;
      }
      var filter = event.target.closest("[data-topic],[data-category]");
      if (filter && filter.classList.contains("fchip")) {
        emit("filter", {
          filter: filter.getAttribute("data-category")
            ? "category:" + filter.getAttribute("data-category")
            : (filter.getAttribute("data-topic") || "")
        }, 750);
        return;
      }
      var brief = event.target.closest('[data-analytics="weekly_brief"]');
      if (brief) emit("weekly_brief_click", context(brief.closest("[data-event-id]") || body), 750);

      var anchor = event.target.closest("a[href]");
      if (anchor) {
        try {
          var destination = new URL(anchor.href, win.location.href);
          var detailMatch = destination.pathname.match(/\/e\/([a-f0-9]{12})\.html$/);
          if (detailMatch && destination.origin === win.location.origin) {
            emit("detail_click", Object.assign(context(anchor.closest("[data-event-id]") || body), {
              event_id: detailMatch[1]
            }), 750);
            return;
          }
          var outboundArea = anchor.getAttribute("data-analytics") === "outbound" ||
            (page === "detail" && !anchor.closest("footer") && Boolean(anchor.closest(".fulltext,.vendor-row,.topbar")));
          if (outboundArea && destination.origin !== win.location.origin) {
            emit("outbound_click", context(anchor), 750);
          }
        } catch (_error) {}
        return;
      }
      var card = event.target.closest("[data-analytics-list][data-event-id]");
      if (card && !event.target.closest("button")) emit("detail_click", context(card), 750);
    }, true);

    var search = doc.getElementById("q");
    if (search) {
      var searchTimer = null;
      search.addEventListener("input", function () {
        if (searchTimer) win.clearTimeout(searchTimer);
        searchTimer = win.setTimeout(function () {
          var bucket = queryBucket(search.value);
          if (!bucket) return;
          var visible = Array.prototype.filter.call(doc.querySelectorAll(".item"), function (item) {
            return item.style.display !== "none";
          }).length;
          emit("search", { query_bucket: bucket, result_count: visible }, 3000);
        }, 600);
      });
    }
    doc.addEventListener("visibilitychange", function () { if (doc.visibilityState === "hidden") flush(); });
    win.addEventListener("pagehide", flush);
  }

  var api = {
    allowedFields: ALLOWED_FIELDS.slice(),
    eventNames: EVENT_NAMES.slice(),
    sanitizeEvent: sanitizeEvent,
    queryBucket: queryBucket,
    pageFromPath: pageFromPath,
    boot: boot,
    track: function () {}, flush: function () {}, disable: function () {}, enable: function () {},
    observeList: function () {}
  };
  return api;
});
