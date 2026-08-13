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

  function normalizedCategory(value) {
    var category = String(value || "").trim();
    return ["agent", "platform", "bi", "product", "insight"].indexOf(category) >= 0 ? category : "";
  }

  var INSIGHT_TOPICS = ["组织人才", "财务经营", "销售增长", "客户运营", "供应链", "风险管理"];

  function filterStateAfterSelection(state, selection) {
    var next = {
      q: String(state.q || ""),
      topic: String(state.topic || "all"),
      category: normalizedCategory(state.category),
      page: 1
    };
    if (selection.all) {
      next.topic = "all"; next.category = "";
    } else if (selection.category) {
      next.category = selection.category === next.category ? "" : normalizedCategory(selection.category);
      if (next.category === "insight" && INSIGHT_TOPICS.indexOf(next.topic) < 0) next.topic = "all";
    } else if (selection.topic) {
      next.topic = selection.topic === next.topic ? "all" : selection.topic;
      if (next.category === "insight" && next.topic !== "all" && INSIGHT_TOPICS.indexOf(next.topic) < 0) {
        next.category = "";
      }
    }
    return next;
  }

  function stateFromSearch(search) {
    var params = new URLSearchParams(String(search || "").replace(/^\?/, ""));
    return {
      q: String(params.get("q") || "").trim(),
      topic: String(params.get("topic") || "all").trim() || "all",
      category: normalizedCategory(params.get("category")),
      page: normalizedPage(params.get("page"))
    };
  }

  function searchForState(state) {
    var params = new URLSearchParams();
    if (state.q) params.set("q", state.q);
    if (state.topic && state.topic !== "all") params.set("topic", state.topic);
    if (normalizedCategory(state.category)) params.set("category", normalizedCategory(state.category));
    if (normalizedPage(state.page) > 1) params.set("page", String(normalizedPage(state.page)));
    var query = params.toString();
    return query ? "?" + query : "";
  }

  var HOME_HISTORY_KEY = "datahotHome";

  function historyStateWithSnapshot(currentHistoryState, state, position) {
    var next = currentHistoryState && typeof currentHistoryState === "object"
      ? Object.assign({}, currentHistoryState) : {};
    next[HOME_HISTORY_KEY] = {
      version: 1,
      search: searchForState(state),
      page: normalizedPage(state.page),
      y: Math.max(0, Number(position && position.y) || 0),
      anchor: String(position && position.anchor || ""),
      anchorOffset: Number(position && position.anchorOffset) || 0
    };
    return next;
  }

  function snapshotFromHistory(historyState, state) {
    if (!historyState || typeof historyState !== "object") return null;
    var snapshot = historyState[HOME_HISTORY_KEY];
    if (!snapshot || snapshot.version !== 1) return null;
    if (snapshot.search !== searchForState(state)) return null;
    return {
      version: 1,
      search: snapshot.search,
      page: normalizedPage(snapshot.page),
      y: Math.max(0, Number(snapshot.y) || 0),
      anchor: String(snapshot.anchor || ""),
      anchorOffset: Number(snapshot.anchorOffset) || 0
    };
  }

  function orderedEvents(payload) {
    var map = new Map((payload.events || []).map(function (event) { return [event.event_id, event]; }));
    return (payload.home_event_ids || []).map(function (id) { return map.get(id); }).filter(Boolean);
  }

  function filterEvents(events, state) {
    var topic = state.topic && state.topic !== "all" ? state.topic : "";
    var category = normalizedCategory(state.category);
    var q = String(state.q || "").toLocaleLowerCase("zh-CN");
    return (events || []).filter(function (event) {
      if (category && event.category !== category) return false;
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
    groups.sort(function (left, right) { return right.parts.key.localeCompare(left.parts.key); });
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
    var restoredSnapshot = false;

    if ("scrollRestoration" in win.history) win.history.scrollRestoration = "manual";

    function persistUrl() {
      var query = searchForState(state);
      var historyState = win.history.state && typeof win.history.state === "object"
        ? Object.assign({}, win.history.state) : {};
      if (historyState[HOME_HISTORY_KEY] && historyState[HOME_HISTORY_KEY].search !== query) {
        delete historyState[HOME_HISTORY_KEY];
      }
      win.history.replaceState(historyState, "", win.location.pathname + query + win.location.hash);
    }
    function positionForCard(card) {
      var anchorCard = card;
      if (!anchorCard) {
        var cards = Array.from(root.querySelectorAll("[data-event-id]"));
        anchorCard = cards.find(function (candidate) {
          return candidate.getBoundingClientRect().bottom > 0;
        }) || cards[0] || null;
      }
      var rect = anchorCard ? anchorCard.getBoundingClientRect() : null;
      return {
        y: win.scrollY || 0,
        anchor: anchorCard ? String(anchorCard.dataset.eventId || "") : "",
        anchorOffset: rect ? rect.top : 0
      };
    }
    function saveHomePosition(card) {
      var historyState = historyStateWithSnapshot(win.history.state, state, positionForCard(card));
      win.history.replaceState(
        historyState, "", win.location.pathname + searchForState(state) + win.location.hash
      );
    }
    function restoreHomePosition(snapshot) {
      if (!snapshot || restoredSnapshot) return;
      var apply = function () {
        var y = snapshot.y;
        if (snapshot.anchor && /^[a-z0-9_-]+$/i.test(snapshot.anchor)) {
          var anchor = root.querySelector('[data-event-id="' + snapshot.anchor + '"]');
          if (anchor) {
            y = (win.scrollY || 0) + anchor.getBoundingClientRect().top - snapshot.anchorOffset;
          }
        }
        win.scrollTo(0, Math.max(0, y));
        restoredSnapshot = true;
      };
      win.requestAnimationFrame(function () { win.requestAnimationFrame(apply); });
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
    function syncChips() {
      doc.querySelectorAll("#chiprow .fchip").forEach(function (chip) {
        var isAll = chip.dataset.topic === "all";
        var selected = isAll
          ? (!state.category && state.topic === "all")
          : (chip.dataset.category
            ? chip.dataset.category === state.category
            : chip.dataset.topic === state.topic);
        chip.classList.toggle("on", selected);
        chip.setAttribute("aria-pressed", selected ? "true" : "false");
      });
    }
    doc.querySelectorAll("#chiprow .fchip").forEach(function (chip) {
      chip.addEventListener("click", function () {
        state = filterStateAfterSelection(state, {
          all: chip.dataset.topic === "all",
          category: chip.dataset.category || "",
          topic: chip.dataset.category ? "" : (chip.dataset.topic || "")
        });
        syncChips();
        refresh();
      });
    });
    syncChips();
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
      var detailLink = event.target.closest && event.target.closest('a[href^="e/"]');
      var cardNavigation = !event.target.closest("a,button") && card.dataset.link;
      if (card.classList.contains("item") && (detailLink || cardNavigation)) saveHomePosition(card);
      if (cardNavigation) win.location.href = card.dataset.link;
    });

    var initialSnapshot = snapshotFromHistory(win.history.state, state);
    var initialRender = null;
    if (state.q || state.topic !== "all" || state.category || state.page > 1) initialRender = refresh();
    else {
      var prefetch = function () { fetchEvents().catch(function () {}); };
      if (typeof win.requestIdleCallback === "function") win.requestIdleCallback(prefetch, { timeout: 1500 });
      else win.setTimeout(prefetch, 500);
    }
    if (initialSnapshot) {
      if (initialRender) initialRender.then(function () { restoreHomePosition(initialSnapshot); });
      else restoreHomePosition(initialSnapshot);
    }
    win.addEventListener("pageshow", function (event) {
      if (!event.persisted) return;
      restoredSnapshot = false;
      var snapshot = snapshotFromHistory(win.history.state, state);
      if (snapshot) restoreHomePosition(snapshot);
    });
  }

  return {
    escapeHtml: escapeHtml,
    stateFromSearch: stateFromSearch,
    searchForState: searchForState,
    historyStateWithSnapshot: historyStateWithSnapshot,
    snapshotFromHistory: snapshotFromHistory,
    filterStateAfterSelection: filterStateAfterSelection,
    orderedEvents: orderedEvents,
    filterEvents: filterEvents,
    visibleEvents: visibleEvents,
    renderTimeline: renderTimeline,
    boot: boot
  };
});
