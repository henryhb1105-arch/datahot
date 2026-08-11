(function (root, factory) {
  "use strict";
  var api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  if (root) root.DataHotHome = api;
  if (root && root.document) api.boot(root);
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  "use strict";

  function escapeHtml(value) {
    return String(value == null ? "" : value).replace(/[&<>"']/g, function (char) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[char];
    });
  }

  function normalizedPage(value) {
    var page = parseInt(value || "1", 10);
    return Number.isFinite(page) && page > 0 ? page : 1;
  }

  function stateFromSearch(search) {
    var params = new URLSearchParams(String(search || "").replace(/^\?/, ""));
    return {
      q: String(params.get("q") || "").trim(),
      topic: String(params.get("topic") || "all").trim() || "all",
      page: normalizedPage(params.get("page"))
    };
  }

  function searchForState(state) {
    var params = new URLSearchParams();
    if (state.q) params.set("q", state.q);
    if (state.topic && state.topic !== "all") params.set("topic", state.topic);
    if (normalizedPage(state.page) > 1) params.set("page", String(normalizedPage(state.page)));
    var query = params.toString();
    return query ? "?" + query : "";
  }

  function orderedEvents(payload) {
    var map = new Map((payload.events || []).map(function (event) { return [event.event_id, event]; }));
    return (payload.home_event_ids || []).map(function (id) { return map.get(id); }).filter(Boolean);
  }

  function filterEvents(events, state) {
    var topic = state.topic && state.topic !== "all" ? state.topic : "";
    var q = String(state.q || "").toLocaleLowerCase("zh-CN");
    return (events || []).filter(function (event) {
      if (topic && (event.topics || []).indexOf(topic) < 0) return false;
      if (!q) return true;
      var text = [event.zh_title, event.zh_summary, event.reason, event.category_label]
        .concat(event.topics || [], event.vendors || [], (event.items || []).map(function (item) { return item.source; }))
        .join(" ").toLocaleLowerCase("zh-CN");
      return text.indexOf(q) >= 0;
    });
  }

  function visibleEvents(events, state, pageSize) {
    var filtered = filterEvents(events, state);
    return {
      filtered: filtered,
      visible: filtered.slice(0, normalizedPage(state.page) * pageSize)
    };
  }

  function dateParts(value) {
    var date = new Date(value || 0);
    if (Number.isNaN(date.getTime())) return { key: "unknown", head: "未知日期", label: "" };
    var parts = new Intl.DateTimeFormat("zh-CN", {
      timeZone: "Asia/Shanghai", month: "numeric", day: "numeric", weekday: "short"
    }).formatToParts(date).reduce(function (acc, part) { acc[part.type] = part.value; return acc; }, {});
    var key = new Intl.DateTimeFormat("en-CA", {
      timeZone: "Asia/Shanghai", year: "numeric", month: "2-digit", day: "2-digit"
    }).format(date);
    return { key: key, head: parts.month + "月" + parts.day + "日", label: parts.weekday || "" };
  }

  function cardTime(event) {
    var value = event.published || event.first_seen;
    if (!value) return "";
    var date = new Date(value);
    if (Number.isNaN(date.getTime())) return "";
    return new Intl.DateTimeFormat("zh-CN", {
      timeZone: "Asia/Shanghai", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit",
      hour12: false
    }).format(date).replace(/\//g, "-");
  }

  function cleanReason(value) {
    return String(value || "").replace(/^\s*推荐理由\s*[:：]\s*/, "");
  }

  function renderCard(event) {
    var source = event.items && event.items[0] ? event.items[0].source : "";
    var topics = (event.topics || []).map(function (topic) {
      return '<span class="chip">' + escapeHtml(topic) + "</span>";
    }).join("");
    var vendors = (event.vendors || []).map(function (vendor) {
      return '<span class="vtag">' + escapeHtml(vendor) + "</span>";
    }).join("");
    var reason = event.reason ? '<div class="why"><span><span class="w">推荐理由：</span>' +
      escapeHtml(cleanReason(event.reason)) + "</span></div>" : "";
    var also = (event.items || []).length > 1 ? '<div class="also">另有 <b>' +
      ((event.items || []).length - 1) + " 家信源</b>报道</div>" : "";
    var star = event.star ? '<span class="star">精选</span>' : "";
    var url = "e/" + encodeURIComponent(event.event_id) + ".html";
    return '<div class="item" data-cat="' + escapeHtml(event.category) + '" data-topics="' +
      escapeHtml((event.topics || []).join("|")) + '" data-link="' + url +
      '" data-analytics-list="1" data-event-id="' + escapeHtml(event.event_id) +
      '" data-category="' + escapeHtml(event.category) + '" data-source="' + escapeHtml(source) + '">' +
      '<div class="top"><span class="srcbadge">信源</span><span style="font-weight:600;color:var(--txt3)">' +
      escapeHtml(source) + "</span><span>" + escapeHtml(cardTime(event)) + "</span>" + star +
      '<button class="favbtn" data-fav="' + escapeHtml(event.event_id) + '" title="收藏">☆</button>' +
      '<span class="heatnum">热 ' + Number(event.heat || 0) + "</span></div>" +
      '<h3><a href="' + url + '">' + escapeHtml(event.zh_title) + "</a></h3>" +
      '<p class="sum">' + escapeHtml(event.zh_summary) + "</p>" + also + reason +
      ((topics || vendors) ? '<div class="vendors">' + topics + vendors + "</div>" : "") + "</div>";
  }

  function renderTimeline(events) {
    var groups = [], byKey = new Map();
    events.forEach(function (event) {
      var parts = dateParts(event.first_seen || event.published);
      if (!byKey.has(parts.key)) {
        var group = { parts: parts, events: [] };
        byKey.set(parts.key, group); groups.push(group);
      }
      byKey.get(parts.key).events.push(event);
    });
    return groups.map(function (group) {
      return '<div class="day"><div class="day-head"><span class="date">' + escapeHtml(group.parts.head) +
        '</span><span class="info">' + escapeHtml(group.parts.label) + " · " + group.events.length +
        " 个事件</span></div>" + group.events.map(renderCard).join("") + "</div>";
    }).join("");
  }

  function boot(win) {
    var doc = win.document;
    var config = doc.getElementById("homeDataConfig");
    if (!config) return;
    var root = doc.getElementById("timeline");
    var more = doc.getElementById("loadMore");
    var count = doc.getElementById("rCount");
    var qInput = doc.getElementById("q");
    var qClear = doc.getElementById("qClear");
    var pageSize = Math.max(1, parseInt(config.dataset.pageSize || "20", 10));
    var total = Math.max(0, parseInt(config.dataset.total || "0", 10));
    var state = stateFromSearch(win.location.search);
    var payloadPromise = null;
    var allEvents = null;
    var scrollKey = "datahot-home-scroll-v1";

    function persistUrl() {
      win.history.replaceState(null, "", win.location.pathname + searchForState(state) + win.location.hash);
    }
    function fetchEvents() {
      if (!payloadPromise) {
        payloadPromise = win.fetch(config.dataset.liteUrl, { cache: "no-store", credentials: "omit" })
          .then(function (response) { if (!response.ok) throw new Error("lite payload " + response.status); return response.json(); })
          .then(function (payload) { allEvents = orderedEvents(payload); return allEvents; });
      }
      return payloadPromise;
    }
    function refresh() {
      return fetchEvents().then(function (events) {
        var result = visibleEvents(events, state, pageSize);
        root.innerHTML = renderTimeline(result.visible) || '<div class="scard" style="color:var(--sub)">没有匹配的事件</div>';
        count.textContent = String(result.filtered.length);
        if (qClear) qClear.style.display = state.q ? "" : "none";
        if (more) {
          more.hidden = result.visible.length >= result.filtered.length;
          more.textContent = "加载更多（" + result.visible.length + "/" + result.filtered.length + "）";
        }
        if (typeof win.dhInitFav === "function") win.dhInitFav();
        if (win.DataHotAnalytics && typeof win.DataHotAnalytics.observeList === "function") {
          win.DataHotAnalytics.observeList(root);
        }
        persistUrl();
        return result;
      }).catch(function () {
        if (more) { more.hidden = false; more.disabled = true; more.textContent = "加载失败，请稍后重试"; }
      });
    }

    if (count) count.textContent = String(total);
    if (qInput) qInput.value = state.q;
    doc.querySelectorAll("#chiprow .fchip").forEach(function (chip) {
      chip.classList.toggle("on", chip.dataset.topic === state.topic || (state.topic === "all" && chip.dataset.topic === "all"));
      chip.addEventListener("click", function () {
        state.topic = chip.dataset.topic === state.topic ? "all" : chip.dataset.topic;
        state.page = 1;
        doc.querySelectorAll("#chiprow .fchip").forEach(function (item) {
          item.classList.toggle("on", item.dataset.topic === state.topic || (state.topic === "all" && item.dataset.topic === "all"));
        });
        refresh();
      });
    });
    var timer = null;
    if (qInput) qInput.addEventListener("input", function () {
      if (timer) win.clearTimeout(timer);
      timer = win.setTimeout(function () { state.q = qInput.value.trim(); state.page = 1; refresh(); }, 160);
    });
    if (qClear) qClear.addEventListener("click", function () {
      qInput.value = ""; state.q = ""; state.page = 1; refresh(); qInput.focus();
    });
    if (more) more.addEventListener("click", function () { state.page += 1; refresh(); });

    doc.addEventListener("click", function (event) {
      var card = event.target.closest && event.target.closest(".item,.hot");
      if (!card) return;
      if (card.classList.contains("item")) {
        try { win.sessionStorage.setItem(scrollKey, JSON.stringify({ href: win.location.href, y: win.scrollY, at: Date.now() })); } catch (_error) {}
      }
      if (!event.target.closest("a,button") && card.dataset.link) win.location.href = card.dataset.link;
    });

    if (state.q || state.topic !== "all" || state.page > 1) refresh();
    try {
      var saved = JSON.parse(win.sessionStorage.getItem(scrollKey) || "null");
      if (saved && saved.href === win.location.href && Date.now() - saved.at < 30 * 60 * 1000) {
        var restore = function () { win.requestAnimationFrame(function () { win.scrollTo(0, saved.y || 0); }); };
        if (state.q || state.topic !== "all" || state.page > 1) fetchEvents().then(refresh).then(restore);
        else restore();
      }
    } catch (_error) {}
  }

  return {
    escapeHtml: escapeHtml,
    stateFromSearch: stateFromSearch,
    searchForState: searchForState,
    orderedEvents: orderedEvents,
    filterEvents: filterEvents,
    visibleEvents: visibleEvents,
    renderTimeline: renderTimeline,
    boot: boot
  };
});
