(function (root, factory) {
  "use strict";
  var api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  if (root) root.DataHotForMe = api;
  if (root && root.document) api.boot(root);
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  "use strict";

  var STORAGE_KEY = "dh_for_me_v1";
  var SESSION_BASELINE_KEY = "dh_for_me_session_baseline_v1";
  var FAVORITES_KEY = "dh_favs";
  var TOPIC_PRIORITY = [
    "Data Agent", "平台AI化", "语义层", "实时分析", "ChatBI", "湖仓",
    "BI变局", "数据人", "组织人才", "财务经营", "销售增长", "风险管理"
  ];

  function uniqueStrings(values, maximum) {
    var seen = Object.create(null);
    return (Array.isArray(values) ? values : []).reduce(function (output, value) {
      var clean = String(value || "").trim().slice(0, 80);
      if (!clean || seen[clean] || output.length >= maximum) return output;
      seen[clean] = true;
      output.push(clean);
      return output;
    }, []);
  }

  function normalizeState(raw) {
    var source = raw && typeof raw === "object" ? raw : {};
    var read = {};
    Object.keys(source.read && typeof source.read === "object" ? source.read : {}).slice(-500).forEach(function (id) {
      if (/^[A-Za-z0-9_-]{1,64}$/.test(id)) read[id] = String(source.read[id] || "").slice(0, 40);
    });
    return {
      version: 1,
      topics: uniqueStrings(source.topics, 50),
      vendors: uniqueStrings(source.vendors, 50),
      dismissed: uniqueStrings(source.dismissed, 200),
      read: read,
      lastVisit: /^\d{4}-\d{2}-\d{2}T/.test(String(source.lastVisit || "")) ? String(source.lastVisit) : ""
    };
  }

  function follows(state) {
    return state.topics.map(function (value) { return { kind: "topic", value: value }; })
      .concat(state.vendors.map(function (value) { return { kind: "vendor", value: value }; }));
  }

  function eventTime(event, field) {
    var value = field ? event[field] : (event.published || event.first_seen);
    var parsed = Date.parse(String(value || ""));
    return Number.isFinite(parsed) ? parsed : 0;
  }

  function matchReasons(event, state) {
    var topics = Array.isArray(event.topics) ? event.topics : [];
    var vendors = Array.isArray(event.vendors) ? event.vendors : [];
    return state.topics.filter(function (value) { return topics.indexOf(value) >= 0; }).map(function (value) {
      return { kind: "topic", value: value };
    }).concat(state.vendors.filter(function (value) { return vendors.indexOf(value) >= 0; }).map(function (value) {
      return { kind: "vendor", value: value };
    }));
  }

  function scoreEvent(event, state, now) {
    var reasons = matchReasons(event, state);
    var ageDays = Math.max(0, (now - eventTime(event)) / 86400000);
    var freshness = Math.max(0, 18 - ageDays * 1.7);
    var importance = Math.max(0, Math.min(100, Number(event.importance) || 50));
    var heat = Math.max(0, Math.min(100, Number(event.heat) || 0));
    var sourceBonus = Math.min(12, Math.max(0, ((event.items || []).length - 1) * 4));
    var explicit = reasons.length ? 100 + (reasons.length - 1) * 18 : 0;
    var favoriteBonus = state.favorites && state.favorites.indexOf(String(event.event_id || "")) >= 0 ? 10 : 0;
    return explicit + importance * 0.35 + heat * 0.2 + freshness + sourceBonus + favoriteBonus;
  }

  function rankEvents(events, state, now, requireMatch) {
    var dismissed = new Set(state.dismissed || []);
    return (Array.isArray(events) ? events : []).filter(function (event) {
      var id = String(event.event_id || "");
      if (!/^[A-Za-z0-9_-]{1,64}$/.test(id) || dismissed.has(id)) return false;
      return !requireMatch || matchReasons(event, state).length > 0;
    }).slice().sort(function (a, b) {
      var score = scoreEvent(b, state, now) - scoreEvent(a, state, now);
      if (score) return score;
      return eventTime(b) - eventTime(a) || String(a.event_id).localeCompare(String(b.event_id));
    });
  }

  function isNewSince(event, baseline) {
    if (!baseline) return false;
    var since = Date.parse(baseline);
    if (!Number.isFinite(since)) return false;
    return eventTime(event, "first_seen") > since;
  }

  function buildSuggestions(events) {
    var topicCounts = Object.create(null);
    var vendorCounts = Object.create(null);
    (events || []).forEach(function (event) {
      uniqueStrings(event.topics, 10).forEach(function (value) { topicCounts[value] = (topicCounts[value] || 0) + 1; });
      uniqueStrings(event.vendors, 10).forEach(function (value) { vendorCounts[value] = (vendorCounts[value] || 0) + 1; });
    });
    var topics = Object.keys(topicCounts).sort(function (a, b) {
      var ai = TOPIC_PRIORITY.indexOf(a); var bi = TOPIC_PRIORITY.indexOf(b);
      ai = ai < 0 ? 999 : ai; bi = bi < 0 ? 999 : bi;
      return ai - bi || topicCounts[b] - topicCounts[a] || a.localeCompare(b);
    }).slice(0, 8).map(function (value) { return { kind: "topic", value: value, count: topicCounts[value] }; });
    var vendors = Object.keys(vendorCounts).sort(function (a, b) {
      return vendorCounts[b] - vendorCounts[a] || a.localeCompare(b);
    }).slice(0, 8).map(function (value) { return { kind: "vendor", value: value, count: vendorCounts[value] }; });
    return topics.concat(vendors);
  }

  function boot(win) {
    var doc = win.document;
    var config = doc.getElementById("forMeDataConfig");
    if (!config) return;
    var storage = null; var session = null;
    try { storage = win.localStorage; session = win.sessionStorage; } catch (_error) {}

    function loadJson(store, key, fallback) {
      if (!store) return fallback;
      try { return JSON.parse(store.getItem(key) || "null") || fallback; } catch (_error) { return fallback; }
    }
    function saveJson(store, key, value) {
      if (!store) return;
      try { store.setItem(key, JSON.stringify(value)); } catch (_error) {}
    }
    function setSession(key, value) {
      if (!session) return;
      try { session.setItem(key, value); } catch (_error) {}
    }
    function getSession(key) {
      if (!session) return "";
      try { return session.getItem(key) || ""; } catch (_error) { return ""; }
    }

    var state = normalizeState(loadJson(storage, STORAGE_KEY, {}));
    state.favorites = uniqueStrings(loadJson(storage, FAVORITES_KEY, []), 500);
    var baseline = getSession(SESSION_BASELINE_KEY);
    if (!baseline) {
      baseline = state.lastVisit;
      setSession(SESSION_BASELINE_KEY, baseline || "first");
    } else if (baseline === "first") {
      baseline = "";
    }
    state.lastVisit = new Date().toISOString();
    saveState();

    try {
      var followParam = new URL(win.location.href).searchParams.get("follow") || "";
      var separator = followParam.indexOf(":");
      if (separator > 0) {
        var kind = followParam.slice(0, separator);
        var value = followParam.slice(separator + 1).trim().slice(0, 80);
        if ((kind === "topic" || kind === "vendor") && value) addFollow(kind, value);
        if (win.history && win.history.replaceState) win.history.replaceState({}, "", win.location.pathname + win.location.hash);
      }
    } catch (_error) {}

    var refs = {
      loading: doc.getElementById("fmLoading"), content: doc.getElementById("fmContent"), error: doc.getElementById("fmError"),
      setup: doc.getElementById("fmSetup"), suggestions: doc.getElementById("fmSuggestions"), progress: doc.getElementById("fmProgress"),
      customize: doc.getElementById("fmCustomize"), visit: doc.getElementById("fmVisit"), newCount: doc.getElementById("fmNewCount"),
      must: doc.getElementById("fmMust"), mustList: doc.getElementById("fmMustList"), feed: doc.getElementById("fmFeed"),
      feedList: doc.getElementById("fmFeedList"), watch: doc.getElementById("fmWatch"), discovery: doc.getElementById("fmDiscovery"),
      discoveryList: doc.getElementById("fmDiscoveryList"), empty: doc.getElementById("fmEmpty"), weeklyCount: doc.getElementById("fmWeeklyCount")
    };
    var events = [];
    var setupOpen = follows(state).length < 3;

    function saveState() {
      var clean = normalizeState(state);
      clean.lastVisit = state.lastVisit;
      saveJson(storage, STORAGE_KEY, clean);
    }
    function isFollowing(kind, value) {
      return (kind === "topic" ? state.topics : state.vendors).indexOf(value) >= 0;
    }
    function addFollow(kind, value) {
      var list = kind === "topic" ? state.topics : state.vendors;
      if (list.indexOf(value) < 0) list.push(value);
      saveState();
    }
    function removeFollow(kind, value) {
      var list = kind === "topic" ? state.topics : state.vendors;
      var index = list.indexOf(value);
      if (index >= 0) list.splice(index, 1);
      saveState();
    }
    function element(tag, className, text) {
      var node = doc.createElement(tag);
      if (className) node.className = className;
      if (text !== undefined) node.textContent = text;
      return node;
    }
    function relativeVisit(value) {
      var time = Date.parse(value || "");
      if (!Number.isFinite(time)) return "首次为你整理 · 从近 7 天开始";
      var minutes = Math.max(1, Math.floor((Date.now() - time) / 60000));
      if (minutes < 60) return "距离上次访问约 " + minutes + " 分钟";
      var hours = Math.floor(minutes / 60);
      if (hours < 24) return "距离上次访问约 " + hours + " 小时";
      return "距离上次访问约 " + Math.floor(hours / 24) + " 天";
    }
    function primarySource(event) {
      return event.items && event.items[0] ? String(event.items[0].source || "") : "";
    }
    function card(event, priority, context) {
      var id = String(event.event_id || "");
      var article = element("article", "fm-signal" + (state.read[id] ? " is-read" : ""));
      article.dataset.eventId = id;
      article.dataset.category = String(event.category || "");
      article.dataset.source = primarySource(event);
      var top = element("div", "fm-signal-top");
      var badge = element("span", "fm-signal-badge", priority ? "必须知道" : String(event.category_label || "动态"));
      top.appendChild(badge);
      if (isNewSince(event, baseline)) top.appendChild(element("span", "fm-new", "新"));
      var sourceText = (event.items || []).length > 1 ? (event.items.length + " 个来源") : (primarySource(event) || "DataHot");
      top.appendChild(element("span", "fm-source", sourceText));
      article.appendChild(top);

      var link = element("a", "fm-signal-title", String(event.zh_title || "未命名变化"));
      link.href = "e/" + encodeURIComponent(id) + ".html";
      link.addEventListener("click", function () { state.read[id] = new Date().toISOString(); saveState(); });
      article.appendChild(link);
      if (event.zh_summary) article.appendChild(element("p", "fm-signal-summary", String(event.zh_summary)));

      var reasons = matchReasons(event, state);
      var why = reasons.length
        ? "因为你关注了 " + reasons.map(function (reason) { return reason.value; }).join("、")
        : (context === "discovery" ? "与你关注的领域相邻，帮助发现意外变化" : "热门内容预览 · 关注后只保留与你相关的变化");
      var whyNode = element("div", "fm-why");
      whyNode.appendChild(element("span", "fm-why-label", "For Me"));
      whyNode.appendChild(element("span", "", why));
      article.appendChild(whyNode);
      if (event.reason) {
        var impact = element("p", "fm-impact");
        impact.appendChild(element("b", "", "为什么重要："));
        impact.appendChild(doc.createTextNode(String(event.reason)));
        article.appendChild(impact);
      }

      var actions = element("div", "fm-actions");
      var read = element("button", "fm-action", state.read[id] ? "已读" : "标记已读");
      read.type = "button"; read.dataset.action = "read"; read.setAttribute("aria-pressed", state.read[id] ? "true" : "false");
      read.addEventListener("click", function () {
        if (state.read[id]) delete state.read[id]; else state.read[id] = new Date().toISOString();
        saveState(); render();
      });
      var favorite = state.favorites.indexOf(id) >= 0;
      var save = element("button", "fm-action", favorite ? "已收藏" : "收藏");
      save.type = "button"; save.dataset.action = "favorite"; save.setAttribute("aria-pressed", favorite ? "true" : "false");
      save.addEventListener("click", function () {
        var index = state.favorites.indexOf(id);
        if (index >= 0) state.favorites.splice(index, 1); else state.favorites.push(id);
        saveJson(storage, FAVORITES_KEY, state.favorites); render();
      });
      var dismiss = element("button", "fm-action fm-dismiss", "不感兴趣");
      dismiss.type = "button"; dismiss.dataset.action = "dismiss";
      dismiss.addEventListener("click", function () {
        state.dismissed.push(id); state.dismissed = uniqueStrings(state.dismissed, 200); saveState(); render();
      });
      actions.appendChild(read); actions.appendChild(save); actions.appendChild(dismiss);
      article.appendChild(actions);
      return article;
    }
    function renderCards(container, list, limit, priority, context) {
      container.replaceChildren();
      list.slice(0, limit).forEach(function (event) { container.appendChild(card(event, priority, context)); });
    }
    function renderSuggestions() {
      refs.suggestions.replaceChildren();
      buildSuggestions(events).forEach(function (suggestion) {
        var selected = isFollowing(suggestion.kind, suggestion.value);
        var button = element("button", "fm-follow-chip" + (selected ? " on" : ""));
        button.type = "button";
        button.dataset.kind = suggestion.kind;
        button.dataset.value = suggestion.value;
        button.setAttribute("aria-pressed", selected ? "true" : "false");
        button.appendChild(element("span", "fm-follow-kind", suggestion.kind === "topic" ? "主题" : "厂商"));
        button.appendChild(element("span", "", suggestion.value));
        button.addEventListener("click", function () {
          if (isFollowing(suggestion.kind, suggestion.value)) removeFollow(suggestion.kind, suggestion.value);
          else addFollow(suggestion.kind, suggestion.value);
          if (follows(state).length >= 3) setupOpen = false;
          render();
        });
        refs.suggestions.appendChild(button);
      });
    }
    function renderWatch(ranked) {
      refs.watch.replaceChildren();
      follows(state).forEach(function (follow) {
        var related = ranked.filter(function (event) {
          return matchReasons(event, { topics: follow.kind === "topic" ? [follow.value] : [], vendors: follow.kind === "vendor" ? [follow.value] : [] }).length;
        });
        var row = element("div", "fm-watch-row");
        var label = element("div", "fm-watch-label");
        label.appendChild(element("span", "fm-follow-kind", follow.kind === "topic" ? "主题" : "厂商"));
        label.appendChild(element("b", "", follow.value));
        label.appendChild(element("span", "fm-watch-count", related.length + " 条相关变化" + (related[0] ? " · 最新：" + String(related[0].zh_title || "") : "")));
        var remove = element("button", "fm-watch-remove", "取消关注");
        remove.type = "button";
        remove.addEventListener("click", function () { removeFollow(follow.kind, follow.value); setupOpen = true; render(); });
        row.appendChild(label); row.appendChild(remove); refs.watch.appendChild(row);
      });
    }
    function render() {
      var followed = follows(state);
      var personalized = followed.length >= 3;
      var now = Date.now();
      var ranked = rankEvents(events, state, now, personalized);
      var preview = personalized ? ranked : rankEvents(events, state, now, false);
      var newCount = personalized ? ranked.filter(function (event) { return isNewSince(event, baseline) && !state.read[event.event_id]; }).length : 0;
      refs.visit.textContent = relativeVisit(baseline);
      refs.newCount.textContent = personalized ? String(newCount) : "—";
      refs.progress.textContent = personalized
        ? "已关注 " + followed.length + " 个对象，可以随时调整"
        : "已选择 " + followed.length + "/3 · 再选 " + (3 - followed.length) + " 个即可生成";
      refs.setup.hidden = !setupOpen;
      refs.customize.setAttribute("aria-expanded", setupOpen ? "true" : "false");
      refs.customize.textContent = setupOpen ? "收起设置" : "调整关注";
      renderSuggestions();

      var must = preview.slice(0, 3);
      var feed = personalized ? preview.slice(3, 15) : [];
      refs.must.querySelector("h2").textContent = personalized ? "必须知道" : "先感受一下";
      refs.must.querySelector("p").textContent = personalized ? "与你的关注最相关，最多 3 条" : "近期高价值变化预览，完成关注后将只显示相关内容";
      renderCards(refs.mustList, must, 3, personalized);
      refs.feed.hidden = !feed.length;
      renderCards(refs.feedList, feed, 12, false);
      refs.empty.hidden = Boolean(preview.length);

      var discovery = personalized ? rankEvents(events, state, now, false).filter(function (event) {
        return matchReasons(event, state).length === 0;
      }).slice(0, 2) : [];
      refs.discovery.hidden = !discovery.length;
      renderCards(refs.discoveryList, discovery, 2, false, "discovery");
      refs.watch.closest("section").hidden = !followed.length;
      renderWatch(ranked);
      var weekAgo = now - 7 * 86400000;
      refs.weeklyCount.textContent = personalized
        ? ranked.filter(function (event) { return eventTime(event) >= weekAgo; }).length + " 条关注变化"
        : "完成关注后生成你的本周回顾";
    }

    refs.customize.addEventListener("click", function () { setupOpen = !setupOpen; render(); });
    refs.error.querySelector("button").addEventListener("click", function () { win.location.reload(); });
    fetch(config.dataset.liteUrl || "data/latest-lite.json", { credentials: "same-origin" }).then(function (response) {
      if (!response.ok) throw new Error("HTTP " + response.status);
      return response.json();
    }).then(function (payload) {
      events = Array.isArray(payload.events) ? payload.events : [];
      refs.loading.hidden = true; refs.content.hidden = false; render();
    }).catch(function () {
      refs.loading.hidden = true; refs.error.hidden = false;
    });
  }

  return {
    STORAGE_KEY: STORAGE_KEY,
    normalizeState: normalizeState,
    matchReasons: matchReasons,
    scoreEvent: scoreEvent,
    rankEvents: rankEvents,
    isNewSince: isNewSince,
    buildSuggestions: buildSuggestions,
    boot: boot
  };
});
