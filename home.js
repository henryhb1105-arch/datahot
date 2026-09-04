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
      editorial: Boolean(state.editorial),
      page: 1
    };
    if (selection.all) {
      next.topic = "all"; next.category = ""; next.editorial = false;
    } else if (selection.editorial) {
      next.editorial = !next.editorial;
      next.topic = "all"; next.category = "";
    } else if (selection.category) {
      next.editorial = false;
      next.category = selection.category === next.category ? "" : normalizedCategory(selection.category);
      if (next.category === "insight" && INSIGHT_TOPICS.indexOf(next.topic) < 0) next.topic = "all";
    } else if (selection.topic) {
      next.editorial = false;
      next.topic = selection.topic === next.topic ? "all" : selection.topic;
      if (next.category === "insight" && next.topic !== "all" && INSIGHT_TOPICS.indexOf(next.topic) < 0) {
        next.category = "";
      }
    }
    return next;
  }

  function stateFromSearch(search) {
    var params = new URLSearchParams(String(search || "").replace(/^\?/, ""));
    var editorial = params.get("view") === "editor";
    return {
      q: String(params.get("q") || "").trim(),
      topic: editorial ? "all" : (String(params.get("topic") || "all").trim() || "all"),
      category: editorial ? "" : normalizedCategory(params.get("category")),
      editorial: editorial,
      page: normalizedPage(params.get("page"))
    };
  }

  function searchForState(state) {
    var params = new URLSearchParams();
    if (state.q) params.set("q", state.q);
    if (state.editorial) params.set("view", "editor");
    if (!state.editorial && state.topic && state.topic !== "all") params.set("topic", state.topic);
    if (!state.editorial && normalizedCategory(state.category)) params.set("category", normalizedCategory(state.category));
    if (normalizedPage(state.page) > 1) params.set("page", String(normalizedPage(state.page)));
    var query = params.toString();
    return query ? "?" + query : "";
  }

  var HOME_HISTORY_KEY = "datahotHome";
  var HOME_TOP_SESSION_KEY = "datahotForceHomeTop";
  var WEEKLY_DISMISS_KEY = "datahotWeeklyDismissedWeek";

  function storageValue(win, storageName, key) {
    try {
      var storage = win && win[storageName];
      return storage && typeof storage.getItem === "function" ? storage.getItem(key) : null;
    } catch (error) {
      return null;
    }
  }

  function weeklyDismissed(win, weekId) {
    var current = String(weekId || "");
    if (!current) return false;
    return storageValue(win, "localStorage", WEEKLY_DISMISS_KEY) === current ||
      storageValue(win, "sessionStorage", WEEKLY_DISMISS_KEY) === current;
  }

  function rememberWeeklyDismissal(win, weekId) {
    var current = String(weekId || "");
    if (!current) return false;
    for (var index = 0; index < 2; index += 1) {
      var storageName = index === 0 ? "localStorage" : "sessionStorage";
      try {
        var storage = win && win[storageName];
        if (!storage || typeof storage.setItem !== "function") continue;
        storage.setItem(WEEKLY_DISMISS_KEY, current);
        return true;
      } catch (error) {}
    }
    return false;
  }

  function initWeeklyTeaser(win) {
    var doc = win && win.document;
    if (!doc || typeof doc.getElementById !== "function") return false;
    var teaser = doc.getElementById("weeklyTeaser");
    if (!teaser) return false;
    var weekId = String(teaser.dataset && teaser.dataset.weekId || "");
    if (weeklyDismissed(win, weekId)) {
      teaser.hidden = true;
      return true;
    }
    var dismiss = doc.getElementById("weeklyDismiss");
    if (!dismiss || typeof dismiss.addEventListener !== "function") return true;
    dismiss.addEventListener("click", function (event) {
      if (event && typeof event.preventDefault === "function") event.preventDefault();
      if (event && typeof event.stopPropagation === "function") event.stopPropagation();
      rememberWeeklyDismissal(win, weekId);
      teaser.hidden = true;
    });
    return true;
  }

  function consumeHomeTopRequest(win) {
    try {
      var storage = win && win.sessionStorage;
      if (!storage || storage.getItem(HOME_TOP_SESSION_KEY) !== "1") return false;
      storage.removeItem(HOME_TOP_SESSION_KEY);
      return true;
    } catch (error) {
      return false;
    }
  }

  function shouldShowBackToTop(scrollY, viewportHeight) {
    var height = Math.max(1, Number(viewportHeight) || 0);
    return Math.max(0, Number(scrollY) || 0) > Math.max(720, height * 1.5);
  }

  function preferredScrollBehavior(win) {
    try {
      return win.matchMedia && win.matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth";
    } catch (error) {
      return "auto";
    }
  }

  function isPlainPrimaryClick(event) {
    if (!event || event.defaultPrevented) return false;
    var button = event.button == null ? 0 : event.button;
    return button === 0 && !event.metaKey && !event.ctrlKey && !event.shiftKey && !event.altKey;
  }

  function navigationType(win) {
    try {
      var entries = win.performance && typeof win.performance.getEntriesByType === "function"
        ? win.performance.getEntriesByType("navigation") : [];
      if (entries && entries[0] && entries[0].type) return entries[0].type;
      if (win.performance && win.performance.navigation && win.performance.navigation.type === 2) {
        return "back_forward";
      }
    } catch (error) {}
    return "navigate";
  }

  function shouldRestoreInitialSnapshot(win) {
    return navigationType(win) === "back_forward";
  }

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
    var editorial = Boolean(state.editorial);
    var q = String(state.q || "").toLocaleLowerCase("zh-CN");
    var filtered = (events || []).filter(function (event) {
      if (editorial && !event.editorial_pick) return false;
      if (category && event.category !== category) return false;
      if (topic && (event.topics || []).indexOf(topic) < 0) return false;
      if (!q) return true;
      var text = [event.zh_title, event.zh_summary, event.reason, event.category_label]
        .concat(event.topics || [], event.vendors || [], (event.items || []).map(function (item) { return item.source; }))
        .join(" ").toLocaleLowerCase("zh-CN");
      return text.indexOf(q) >= 0;
    });
    if (editorial) {
      filtered.sort(function (left, right) {
        var byCurated = String(right.curated_at || "").localeCompare(String(left.curated_at || ""));
        return byCurated || String(right.event_id || "").localeCompare(String(left.event_id || ""));
      });
    }
    return filtered;
  }

  function visibleEvents(events, state, pageSize) {
    var filtered = filterEvents(events, state);
    return {
      filtered: filtered,
      visible: filtered.slice(0, normalizedPage(state.page) * pageSize)
    };
  }

  function hasActiveFilter(state) {
    return Boolean(
      String(state && state.q || "") ||
      Boolean(state && state.editorial) ||
      String(state && state.topic || "all") !== "all" ||
      normalizedCategory(state && state.category)
    );
  }

  function renderLoadFailure() {
    return '<div class="scard filter-error" role="status">' +
      '<b>筛选结果加载失败</b><p>当前没有展示未筛选的旧内容，请重试或清除筛选。</p>' +
      '<div class="filter-error-actions"><button type="button" data-filter-retry>重试</button>' +
      '<button type="button" data-filter-clear>清除筛选</button></div></div>';
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
    if (event.editorial_pick && event.curated_at) {
      var curated = monthDay(event.curated_at);
      var published = monthDay(event.published);
      return published ? curated + " 收录 · 原文 " + published : curated + " 收录";
    }
    if (!value) return "";
    var date = new Date(value);
    if (Number.isNaN(date.getTime())) return "";
    return new Intl.DateTimeFormat("zh-CN", {
      timeZone: "Asia/Shanghai", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit",
      hour12: false
    }).format(date).replace(/\//g, "-");
  }

  function monthDay(value) {
    if (!value) return "";
    var date = new Date(value);
    if (Number.isNaN(date.getTime())) return "";
    return new Intl.DateTimeFormat("zh-CN", {
      timeZone: "Asia/Shanghai", month: "2-digit", day: "2-digit"
    }).format(date).replace(/\//g, "-");
  }

  function cleanReason(value) {
    return String(value || "").replace(/^\s*推荐理由\s*[:：]\s*/, "");
  }

  function topRanksFromIds(value) {
    var ranks = {};
    String(value || "").split(",").filter(Boolean).forEach(function (eventId, index) {
      ranks[eventId] = index + 1;
    });
    return ranks;
  }

  function renderCard(event, topRanks) {
    var source = event.items && event.items[0] ? event.items[0].source : "";
    var sourceBadge = event.source_badge || "RSS";
    var topics = (event.topics || []).map(function (topic) {
      return '<span class="chip">' + escapeHtml(topic) + "</span>";
    }).join("");
    var vendors = (event.vendors || []).map(function (vendor) {
      return '<span class="vtag">' + escapeHtml(vendor) + "</span>";
    }).join("");
    var reason = event.reason ? '<div class="why"><span><span class="w">推荐理由：</span>' +
      escapeHtml(cleanReason(event.reason)) + "</span></div>" : "";
    var additionalSources = (event.items || []).slice(1).map(function (item) {
      return escapeHtml(item.source || "");
    }).filter(Boolean);
    var also = additionalSources.length ? '<div class="also">另有 <b>' +
      additionalSources.length + " 家信源</b>报道：" + additionalSources.join(" · ") + "</div>" : "";
    var status = event.editorial_pick ? "编辑精选" : "";
    var heat = Number(event.heat || 0);
    var heatLabel = status ? status + " " + heat : String(heat);
    var topRank = topRanks && topRanks[event.event_id];
    var topRankHtml = topRank ? '<span class="top-rank" aria-label="热点第 ' + topRank +
      ' 名">TOP ' + topRank + "</span>" : "";
    var flameIcon = '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 22c4.4 0 8-3.5 8-7.8 0-3.9-2.9-6-4.6-9.1C14.9 3.6 13.4 2.4 12 2c-.4 2.9-1.9 4.4-3.4 6C6.6 9.6 4 11.6 4 15.1 4 19 7.6 22 12 22z"></path></svg>';
    var bookmarkIcon = '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M19 21l-7-4.5L5 21V4a2 2 0 0 1 2-2h10a2 2 0 0 1 2 2v17z"></path></svg>';
    var url = "e/" + encodeURIComponent(event.event_id) + ".html";
    var favoriteRecord = {
      event_id: event.event_id,
      title: event.zh_title || "",
      summary: event.zh_summary || "",
      source: source,
      category: event.category || "",
      topics: event.topics || [],
      published: event.published || event.first_seen || "",
      original_url: ""
    };
    return '<div class="item" data-cat="' + escapeHtml(event.category) + '" data-topics="' +
      escapeHtml((event.topics || []).join("|")) + '" data-editorial="' +
      (event.editorial_pick ? "true" : "false") + '" data-link="' + url +
      '" data-analytics-list="1" data-event-id="' + escapeHtml(event.event_id) +
      '" data-category="' + escapeHtml(event.category) + '" data-source="' + escapeHtml(source) + '">' +
      '<div class="top card-meta"><span class="card-source"><span class="srcbadge">' + escapeHtml(sourceBadge) +
      '</span><span class="card-source-name">' + escapeHtml(source) + '</span><span class="card-time">' +
      escapeHtml(cardTime(event)) + '</span></span>' + topRankHtml + '<span class="heatnum' + (status ? ' is-featured' : '') +
      '" title="热度分">' + flameIcon + ' ' + escapeHtml(heatLabel) + '</span><button class="favbtn" data-fav="' +
      escapeHtml(event.event_id) + '" data-fav-record="' + escapeHtml(JSON.stringify(favoriteRecord)) +
      '" type="button" title="收藏" aria-label="收藏" aria-pressed="false">' + bookmarkIcon + '</button></div>' +
      '<h3><a href="' + url + '">' + escapeHtml(event.zh_title) + "</a></h3>" +
      '<p class="sum">' + escapeHtml(event.zh_summary) + "</p>" + also + reason +
      ((topics || vendors) ? '<div class="vendors">' + topics + vendors + "</div>" : "") + "</div>";
  }

  function renderTimeline(events, topRanks, editorialView) {
    var groups = [], byKey = new Map();
    events.forEach(function (event) {
      var parts = dateParts(
        editorialView && event.editorial_pick ? event.curated_at : (event.published || event.first_seen)
      );
      if (!byKey.has(parts.key)) {
        var group = { parts: parts, events: [] };
        byKey.set(parts.key, group); groups.push(group);
      }
      byKey.get(parts.key).events.push(event);
    });
    groups.sort(function (left, right) { return right.parts.key.localeCompare(left.parts.key); });
    return groups.map(function (group) {
      return '<div class="day" data-day-key="' + escapeHtml(group.parts.key) +
        '"><div class="day-head"><span class="date" data-date-base="' + escapeHtml(group.parts.head) + '">' + escapeHtml(group.parts.head) +
        '</span><span class="info">' + escapeHtml(group.parts.label) + " · " + group.events.length +
        " 个事件</span></div>" + group.events.map(function (event) {
          return renderCard(event, topRanks);
        }).join("") + "</div>";
    }).join("");
  }

  function boot(win) {
    var doc = win.document;
    initWeeklyTeaser(win);
    var config = doc.getElementById("homeDataConfig");
    if (!config) return;
    var root = doc.getElementById("timeline");
    var more = doc.getElementById("loadMore");
    var count = doc.getElementById("rCount");
    var qInput = doc.getElementById("q");
    var qClear = doc.getElementById("qClear");
    var timelineTitle = doc.querySelector && doc.querySelector("[data-timeline-title]");
    var backToTop = doc.getElementById("backToTop");
    var pageSize = Math.max(1, parseInt(config.dataset.pageSize || "20", 10));
    var total = Math.max(0, parseInt(config.dataset.total || "0", 10));
    var topRanks = topRanksFromIds(config.dataset.topIds || "");
    var state = stateFromSearch(win.location.search);
    var payloadPromise = null;
    var allEvents = null;
    var restoredSnapshot = false;
    var initialTimeline = root.innerHTML;
    var initialMoreText = more ? more.textContent : "";
    var initialMoreHidden = more ? more.hidden : true;
    var forceTopAtBoot = consumeHomeTopRequest(win);
    var restoreInitialSnapshot = shouldRestoreInitialSnapshot(win);

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
    function syncTodayLabels() {
      if (!root || typeof root.querySelectorAll !== "function") return;
      var todayKey = dateParts(new Date()).key;
      root.querySelectorAll(".day[data-day-key]").forEach(function (day) {
        var date = day.querySelector && day.querySelector(".date");
        if (!date) return;
        var base = String(date.dataset.dateBase || date.textContent || "").replace(/^今天\s*·\s*/, "");
        date.dataset.dateBase = base;
        date.textContent = (day.dataset.dayKey === todayKey ? "今天 · " : "") + base;
      });
    }
    function setBackToTopVisible(visible) {
      if (!backToTop) return;
      backToTop.classList.toggle("show", visible);
      backToTop.setAttribute("aria-hidden", visible ? "false" : "true");
      backToTop.tabIndex = visible ? 0 : -1;
    }
    function syncBackToTop() {
      var mobile = true;
      try { if (win.matchMedia) mobile = win.matchMedia("(max-width: 600px)").matches; } catch (error) {}
      setBackToTopVisible(mobile && shouldShowBackToTop(win.scrollY, win.innerHeight));
    }
    var backToTopFramePending = false;
    function queueBackToTopSync() {
      if (backToTopFramePending) return;
      backToTopFramePending = true;
      win.requestAnimationFrame(function () {
        backToTopFramePending = false;
        syncBackToTop();
      });
    }
    function scrollHomeToTop(behavior) {
      var historyState = historyStateWithSnapshot(
        win.history.state, state, { y: 0, anchor: "", anchorOffset: 0 }
      );
      win.history.replaceState(
        historyState, "", win.location.pathname + searchForState(state) + win.location.hash
      );
      try {
        win.scrollTo({ top: 0, left: 0, behavior: behavior || preferredScrollBehavior(win) });
      } catch (error) {
        win.scrollTo(0, 0);
      }
      setBackToTopVisible(false);
      if (backToTop && doc.activeElement === backToTop && typeof backToTop.blur === "function") backToTop.blur();
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
        syncBackToTop();
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
    function restoreInitialTimeline() {
      state = { q: "", topic: "all", category: "", editorial: false, page: 1 };
      if (qInput) qInput.value = "";
      if (qClear) qClear.style.display = "none";
      root.innerHTML = initialTimeline;
      syncTodayLabels();
      if (count) count.textContent = String(total);
      if (more) {
        more.disabled = false;
        more.hidden = initialMoreHidden;
        more.textContent = initialMoreText;
      }
      syncChips();
      persistUrl();
      if (typeof win.dhInitFav === "function") win.dhInitFav();
    }
    function refresh() {
      var filteredRequest = hasActiveFilter(state);
      if (!allEvents && filteredRequest) {
        root.innerHTML = '<div class="scard" role="status" style="color:var(--sub)">正在加载筛选结果…</div>';
        if (more) more.hidden = true;
      }
      return fetchEvents().then(function (events) {
        var result = visibleEvents(events, state, pageSize);
        root.innerHTML = renderTimeline(result.visible, topRanks, state.editorial) || '<div class="scard" style="color:var(--sub)">没有匹配的事件</div>';
        syncTodayLabels();
        count.textContent = String(result.filtered.length);
        if (qClear) qClear.style.display = state.q ? "" : "none";
        if (more) {
          more.disabled = false;
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
        payloadPromise = null;
        allEvents = null;
        if (hasActiveFilter(state)) {
          root.innerHTML = renderLoadFailure();
          if (count) count.textContent = "—";
          if (more) more.hidden = true;
          persistUrl();
        } else if (more) {
          more.hidden = false; more.disabled = true; more.textContent = "加载失败，请稍后重试";
        }
        return null;
      });
    }

    if (count) count.textContent = String(total);
    if (qInput) qInput.value = state.q;
    function syncChips() {
      doc.querySelectorAll("#chiprow .fchip").forEach(function (chip) {
        var isAll = chip.dataset.topic === "all";
        var isEditorial = chip.dataset.editorial === "true";
        var selected = isAll
          ? (!state.editorial && !state.category && state.topic === "all")
          : (isEditorial ? state.editorial : (chip.dataset.category
            ? chip.dataset.category === state.category
            : chip.dataset.topic === state.topic));
        chip.classList.toggle("on", selected);
        chip.setAttribute("aria-pressed", selected ? "true" : "false");
      });
      if (timelineTitle) timelineTitle.textContent = state.editorial ? "编辑精选" : "时间轴";
    }
    doc.querySelectorAll("#chiprow .fchip").forEach(function (chip) {
      chip.addEventListener("click", function () {
        state = filterStateAfterSelection(state, {
          all: chip.dataset.topic === "all",
          editorial: chip.dataset.editorial === "true",
          category: chip.dataset.category || "",
          topic: (chip.dataset.category || chip.dataset.editorial) ? "" : (chip.dataset.topic || "")
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
    doc.querySelectorAll("[data-home-top]").forEach(function (link) {
      link.addEventListener("click", function (event) {
        if (!isPlainPrimaryClick(event)) return;
        event.preventDefault();
        scrollHomeToTop(preferredScrollBehavior(win));
      });
    });
    if (backToTop) backToTop.addEventListener("click", function () {
      scrollHomeToTop(preferredScrollBehavior(win));
    });
    win.addEventListener("scroll", queueBackToTopSync, { passive: true });
    win.addEventListener("resize", queueBackToTopSync);
    syncTodayLabels();
    syncBackToTop();

    root.addEventListener("click", function (event) {
      if (event.target.closest && event.target.closest("[data-filter-retry]")) {
        refresh();
      } else if (event.target.closest && event.target.closest("[data-filter-clear]")) {
        restoreInitialTimeline();
        if (qInput) qInput.focus();
      }
    });

    doc.addEventListener("click", function (event) {
      var card = event.target.closest && event.target.closest(".item,.hot");
      if (!card) return;
      var detailLink = event.target.closest && event.target.closest('a[href^="e/"]');
      var cardNavigation = !event.target.closest("a,button") && card.dataset.link;
      if (card.classList.contains("item") && (detailLink || cardNavigation)) saveHomePosition(card);
      if (cardNavigation) win.location.href = card.dataset.link;
    });

    var initialSnapshot = restoreInitialSnapshot ? snapshotFromHistory(win.history.state, state) : null;
    if (!restoreInitialSnapshot && win.history.state && win.history.state[HOME_HISTORY_KEY]) {
      var cleanHistoryState = Object.assign({}, win.history.state);
      delete cleanHistoryState[HOME_HISTORY_KEY];
      win.history.replaceState(
        cleanHistoryState, "", win.location.pathname + searchForState(state) + win.location.hash
      );
    }
    var initialRender = null;
    if (state.q || state.topic !== "all" || state.category || state.editorial || state.page > 1) initialRender = refresh();
    else {
      var prefetch = function () { fetchEvents().catch(function () {}); };
      if (typeof win.requestIdleCallback === "function") win.requestIdleCallback(prefetch, { timeout: 1500 });
      else win.setTimeout(prefetch, 500);
    }
    if (forceTopAtBoot) {
      if (initialRender) initialRender.then(function () { scrollHomeToTop("auto"); });
      else scrollHomeToTop("auto");
    } else if (initialSnapshot) {
      if (initialRender) initialRender.then(function () { restoreHomePosition(initialSnapshot); });
      else restoreHomePosition(initialSnapshot);
    }
    win.addEventListener("pageshow", function (event) {
      if (consumeHomeTopRequest(win)) {
        restoredSnapshot = false;
        scrollHomeToTop("auto");
        return;
      }
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
    hasActiveFilter: hasActiveFilter,
    weeklyDismissed: weeklyDismissed,
    rememberWeeklyDismissal: rememberWeeklyDismissal,
    initWeeklyTeaser: initWeeklyTeaser,
    consumeHomeTopRequest: consumeHomeTopRequest,
    shouldShowBackToTop: shouldShowBackToTop,
    preferredScrollBehavior: preferredScrollBehavior,
    isPlainPrimaryClick: isPlainPrimaryClick,
    navigationType: navigationType,
    shouldRestoreInitialSnapshot: shouldRestoreInitialSnapshot,
    renderLoadFailure: renderLoadFailure,
    topRanksFromIds: topRanksFromIds,
    renderTimeline: renderTimeline,
    boot: boot
  };
});
