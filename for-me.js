(function (root, factory) {
  "use strict";
  var api = factory(typeof module === "object" && module.exports ? require("./reading-profile.js") : root.DataHotReading, typeof module === "object" && module.exports ? require("./content-affinity.js") : root.DataHotAffinity);
  if (typeof module === "object" && module.exports) module.exports = api;
  if (root) root.DataHotForMe = api;
  if (root && root.document) api.boot(root);
})(typeof globalThis !== "undefined" ? globalThis : this, function (reading, affinity) {
  "use strict";

  // Reconstruct the exact object payload; missing sparse values stay absent.
  function decode(payload) {
    if (Array.isArray(payload.events)) return payload;
    if (payload.transport !== "datahot-columns-v1" ||
        !Number.isSafeInteger(payload.count) || payload.count < 0 || payload.count > 100000 ||
        !payload.meta || !payload.columns) throw new Error("Invalid lite transport");
    var events = Array.from({length: payload.count}, function () { return {}; });
    Object.keys(payload.columns).forEach(function (key) {
      if (["__proto__", "constructor", "prototype"].indexOf(key) >= 0) throw new Error("Unsafe column");
      var column = payload.columns[key];
      if (Array.isArray(column)) {
        if (column.length !== events.length) throw new Error("Invalid column length");
        column.forEach(function (value, i) { events[i][key] = value; });
      } else {
        if (!column || !Array.isArray(column.rows) || !Array.isArray(column.values) ||
            column.rows.length !== column.values.length) throw new Error("Invalid sparse column");
        var previous = -1;
        column.rows.forEach(function (i, j) {
          if (!Number.isInteger(i) || i <= previous || i >= events.length) throw new Error("Invalid row");
          previous = i;
          events[i][key] = column.values[j];
        });
      }
    });
    return Object.assign({}, payload.meta, {events: events});
  }

  var STORAGE_KEY = "dh_for_me_v1";
  var SESSION_BASELINE_KEY = "dh_for_me_session_baseline_v1";
  var FAVORITES_KEY = "dh_favs";
  var FEEDBACK_KEY = "dh_content_feedback_v1";
  var TOPIC_PRIORITY = [
    "Data Agent", "平台AI化", "语义层", "ChatBI", "BI变局", "实时分析", "湖仓",
    "数据人", "组织人才", "财务经营", "销售增长", "风险管理"
  ];

  var TASKS = [
    {id: "agent", label: "搭建 Data Agent", topics: ["Data Agent", "语义层", "ChatBI"], pattern: /agent|智能体|语义层|工具调用|评测/i},
    {id: "platform", label: "数据平台选型", topics: ["湖仓", "实时分析", "平台AI化"], pattern: /成本|性能|迁移|兼容|湖仓|benchmark|pricing/i},
    {id: "design", label: "研究 AI 产品设计", topics: ["ChatBI", "BI变局"], pattern: /交互|产品设计|界面|用户体验|体验设计|dashboard|copilot/i}
  ];
  var DEFAULT_HOME_KEY = "dh_default_home_v1";
  function taskReasons(event, state) {
    var text = [event.zh_title, event.zh_summary].join(" ");
    return TASKS.filter(function (task) {
      return (state.tasks || []).indexOf(task.id) >= 0 &&
        (task.topics.some(function (topic) { return (event.topics || []).indexOf(topic) >= 0; }) || task.pattern.test(text));
    }).map(function (task) { return {kind: "task", value: task.id}; });
  }
  function isRead(event, state) { return Boolean(state.read[event.event_id] || (state.reading && state.reading.enabled && state.reading.entries[event.event_id])); }
  function inferred(event, state) { return affinity ? affinity.match(event, state.affinity) : []; }
  function relevant(event, state) { return matchReasons(event, state).length > 0 || inferred(event, state).length > 0; }
  function personal(state) { return follows(state).length > 0 || (state.tasks || []).length > 0 || Object.keys(state.affinity && state.affinity.matches || {}).length > 0; }
  function sections(events, state, now, baseline) {
    var personalized = personal(state);
    var allRanked = rankEvents(events, state, now, false);
    var ranked = personalized ? allRanked.filter(function (event) { return relevant(event, state); }) : allRanked;
    var unread = ranked.filter(function (event) { return !isRead(event, state); });
    var cutoff = now - 7 * 86400000;
    var picks = unread.filter(function(event) {return eventTime(event) >= cutoff || inferred(event,state).length;});
    var must = picks.slice(0, 3), used = new Set(must.map(function (event) {return event.event_id;}));
    var updates = unread.filter(function (event) {
      return !used.has(event.event_id) && (baseline ? isNewSince(event, baseline) : eventTime(event, "first_seen") >= cutoff);
    }).slice(0, 12);
    updates.forEach(function (event) {used.add(event.event_id);});
    var work = unread.filter(function (event) {
      return !used.has(event.event_id) && ((event.focus || {}).practical || event.shelf === "reference" || taskReasons(event, state).length);
    }).slice(0, 6);
    work.forEach(function (event) {used.add(event.event_id);});
    var discovery = personalized ? allRanked.filter(function (event) {
      return !isRead(event, state) && !used.has(event.event_id) && !relevant(event, state) && eventTime(event) >= cutoff;
    }).slice(0, 2) : [];
    return {must: must, updates: updates, work: work, discovery: discovery, ranked: ranked};
  }

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
      tasks: uniqueStrings(source.tasks, 3).filter(function (id) {return TASKS.some(function (t) {return t.id === id;});}),
      setupDone: source.setupDone === true,
      topics: uniqueStrings(source.topics, 50),
      vendors: uniqueStrings(source.vendors, 50),
      products: uniqueStrings(source.products, 50).filter(function (id) { return /^[a-z][a-z0-9-]{1,63}$/.test(id); }),
      dismissed: uniqueStrings(source.dismissed, 200),
      read: read,
      lastVisit: /^\d{4}-\d{2}-\d{2}T/.test(String(source.lastVisit || "")) ? String(source.lastVisit) : ""
    };
  }

  function follows(state) {
    return (state.products || []).map(function (value) { return { kind: "product", value: value }; })
      .concat(state.topics.map(function (value) { return { kind: "topic", value: value }; }))
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
    return taskReasons(event, state).concat(state.topics.filter(function (value) { return topics.indexOf(value) >= 0; }).map(function (value) {
      return { kind: "topic", value: value };
    }).concat(state.vendors.filter(function (value) { return vendors.indexOf(value) >= 0; }).map(function (value) {
      return { kind: "vendor", value: value };
    })).concat((state.products || []).filter(function (value) { return (event.product_ids || []).indexOf(value) >= 0; }).map(function (value) {
      return { kind: "product", value: value };
    })));
  }

  function normalizeFeedbackStore(raw) {
    var source = raw && typeof raw === "object" ? raw : {};
    var entries = {};
    Object.keys(source.entries && typeof source.entries === "object" ? source.entries : {}).slice(-300).forEach(function (id) {
      var row = source.entries[id];
      if (!/^[a-f0-9]{12}$/.test(id) || !row || ["useful", "not_useful"].indexOf(row.value) < 0) return;
      entries[id] = {
        value: row.value, reason: String(row.reason || ""),
        topics: uniqueStrings(row.topics, 8), vendors: uniqueStrings(row.vendors, 8),
        source: String(row.source || "").trim().slice(0, 80)
      };
    });
    return { version: 1, entries: entries };
  }

  function overlap(left, right) {
    var wanted = new Set(Array.isArray(right) ? right : []);
    return (Array.isArray(left) ? left : []).filter(function (value) { return wanted.has(value); }).length;
  }

  function primarySource(event) {
    return event.items && event.items[0] ? String(event.items[0].source || "") : "";
  }

  function feedbackSignal(event, feedback) {
    var entries = feedback && feedback.entries && typeof feedback.entries === "object" ? feedback.entries : {};
    var eventId = String(event.event_id || "");
    var signal = 0;
    Object.keys(entries).forEach(function (id) {
      var row = entries[id];
      var positive = row.value === "useful";
      if (id === eventId) {
        signal += positive ? 45 : -100;
        return;
      }
      // Generalize feedback through article content, never a shared broad label.
    });
    return Math.max(-100, Math.min(45, signal));
  }

  function fitScore(event, state, feedback) {
    var explicit = Math.min(state.affinity && state.affinity.positive ? 18 : 45, matchReasons(event, state).length * 35);
    return Math.max(0, Math.min(100, 50 + explicit + feedbackSignal(event, feedback)));
  }

  function scoreEvent(event, state, now) {
    var ageDays = Math.max(0, (now - eventTime(event)) / 86400000);
    var freshness = Math.max(0, 18 - ageDays * 1.7);
    var quality = Math.max(0, Math.min(100, Number(event.quality_score) || Number(event.importance) || 50));
    var trend = Math.max(0, Math.min(100, Number(event.trend_score) || Number(event.heat) || 0));
    var fit = fitScore(event, state, state.feedback);
    var sourceBonus = Math.min(12, Math.max(0, ((event.items || []).length - 1) * 4));
    var favoriteBonus = state.favorites && state.favorites.indexOf(String(event.event_id || "")) >= 0 ? 10 : 0;
    return quality * 0.4 + trend * (state.affinity && state.affinity.positive ? 0.1 : 0.25) + fit + freshness + sourceBonus + favoriteBonus + (affinity ? affinity.score(event, state.affinity) : 0);
  }

  function rankEvents(events, state, now, requireMatch) {
    var dismissed = new Set(state.dismissed || []);
    var personalized = personal(state);
    return (Array.isArray(events) ? events : []).filter(function (event) {
      var id = String(event.event_id || "");
      if (!/^[A-Za-z0-9_-]{1,64}$/.test(id) || dismissed.has(id)) return false;
      return !requireMatch || relevant(event, state);
    }).map(function (event) {
      return { event: event, score: scoreEvent(event, state, now), time: eventTime(event) };
    }).sort(function (left, right) {
      var a = left.event, b = right.event;
      var aFocus = a.focus || {}, bFocus = b.focus || {};
      var aPriority = Number.isInteger(aFocus.priority) && aFocus.priority >= 0 && aFocus.priority <= 5 ? aFocus.priority : 5;
      var bPriority = Number.isInteger(bFocus.priority) && bFocus.priority >= 0 && bFocus.priority <= 5 ? bFocus.priority : 5;
      if (isRead(a, state) !== isRead(b, state)) return isRead(a, state) ? 1 : -1;
      if (!personalized) {
        if (aPriority !== bPriority) return aPriority - bPriority;
        if (Boolean(aFocus.practical) !== Boolean(bFocus.practical)) return aFocus.practical ? -1 : 1;
      }
      var score = right.score - left.score;
      if (score) return score;
      return right.time - left.time || String(a.event_id).localeCompare(String(b.event_id));
    }).map(function (row) { return row.event; });
  }

  function isNewSince(event, baseline) {
    if (!baseline) return false;
    var since = Date.parse(baseline);
    if (!Number.isFinite(since)) return false;
    return eventTime(event, "first_seen") > since;
  }

  function buildSuggestions(events, products) {
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
    return (products || []).map(function (product) {
      return { kind: "product", value: product.id, label: product.name };
    }).concat(topics, vendors);
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
    state.feedback = normalizeFeedbackStore(loadJson(storage, FEEDBACK_KEY, {}));
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
        if ((kind === "topic" || kind === "vendor" || (kind === "product" && /^[a-z][a-z0-9-]{1,63}$/.test(value))) && value) addFollow(kind, value);
        if (win.history && win.history.replaceState) win.history.replaceState({}, "", win.location.pathname + win.location.hash);
      }
    } catch (_error) {}

    var refs = {
      work: doc.getElementById("fmWork"), workList: doc.getElementById("fmWorkList"), readList: doc.getElementById("fmReadList"),
      notice: doc.getElementById("fmNotice"),
      loading: doc.getElementById("fmLoading"), content: doc.getElementById("fmContent"), error: doc.getElementById("fmError"),
      setup: doc.getElementById("fmSetup"), suggestions: doc.getElementById("fmSuggestions"), progress: doc.getElementById("fmProgress"),
      customize: doc.getElementById("fmCustomize"), visit: doc.getElementById("fmVisit"), newCount: doc.getElementById("fmNewCount"),
      must: doc.getElementById("fmMust"), mustList: doc.getElementById("fmMustList"), feed: doc.getElementById("fmFeed"),
      feedList: doc.getElementById("fmFeedList"), watch: doc.getElementById("fmWatch"), discovery: doc.getElementById("fmDiscovery"),
      discoveryList: doc.getElementById("fmDiscoveryList"), empty: doc.getElementById("fmEmpty"), weeklyCount: doc.getElementById("fmWeeklyCount")
    };
    var events = [];
    var products = [], productNames = {};
    var setupOpen = false;
    var settingsDialog = doc.getElementById("fmSettings");
    var setupStep = 1;

    function kindLabel(kind) { return kind === "product" ? "产品" : (kind === "topic" ? "主题" : "厂商"); }
    function followLabel(follow) { if (follow.kind === "task") return TASKS.find(function(t) {return t.id === follow.value;}).label; return follow.kind === "product" ? (productNames[follow.value] || follow.value) : follow.value; }
    function followList(kind) { return kind === "product" ? state.products : (kind === "topic" ? state.topics : state.vendors); }

    function saveState() {
      var clean = normalizeState(state);
      clean.lastVisit = state.lastVisit;
      saveJson(storage, STORAGE_KEY, clean);
    }
    function isFollowing(kind, value) {
      return followList(kind).indexOf(value) >= 0;
    }
    function addFollow(kind, value) {
      var list = followList(kind);
      if (list.indexOf(value) < 0) list.push(value);
      saveState();
    }
    function removeFollow(kind, value) {
      var list = followList(kind);
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
    function card(event, priority, context) {
      var id = String(event.event_id || "");
      var article = element("article", "fm-signal" + (state.read[id] ? " is-read" : ""));
      article.dataset.eventId = id;
      article.dataset.category = String(event.category || "");
      article.dataset.source = primarySource(event);
      var top = element("div", "fm-signal-top");
      var focusLabel = event.focus && event.focus.id !== "other" ? event.focus.label : "";
      var badge = element("span", "fm-signal-badge", priority ? "优先推荐" : String(focusLabel || event.category_label || "动态"));
      top.appendChild(badge);
      if (isNewSince(event, baseline)) top.appendChild(element("span", "fm-new", "新"));
      var sourceText = (event.items || []).length > 1 ? (event.items.length + " 个来源") : (primarySource(event) || "DataHot");
      top.appendChild(element("span", "fm-source", sourceText));
      var published = String(event.published || event.first_seen || "").slice(0,10);
      if (/^\d{4}-\d{2}-\d{2}$/.test(published)) {
        var date = element("time", "fm-source", published);date.dateTime=published;top.appendChild(date);
      }
      article.appendChild(top);

      var link = element("a", "fm-signal-title", String(event.zh_title || "未命名变化"));
      link.href = "e/" + encodeURIComponent(id) + ".html";
      link.addEventListener("click", function () { state.read[id] = new Date().toISOString(); saveState(); });
      article.appendChild(link);
      if (event.zh_summary) article.appendChild(element("p", "fm-signal-summary", String(event.zh_summary)));

      var reasons = matchReasons(event, state), learned = inferred(event, state)[0];
      var why = learned
        ? "接着你" + (learned.reason === "阅读" ? "读过" : learned.reason === "收藏" ? "收藏" : "认为有用") + "的《" + String(learned.sourceTitle || "文章").slice(0,55) + "》 · 共同讨论：" + learned.value
        : reasons.length ? "与你选择的 " + reasons.map(followLabel).join("、") + " 相关"
        : (context === "discovery" ? "关注范围之外的近期内容，帮助发现新方向" : "公共精选 · 近期重要变化");
      var whyNode = element("div", "fm-why");
      whyNode.appendChild(element("span", "fm-why-label", "为你推荐"));
      whyNode.appendChild(element("span", "", why));
      article.appendChild(whyNode);
      if (event.reason) {
        var impact = element("p", "fm-impact");
        impact.appendChild(element("b", "", "为什么重要："));
        impact.appendChild(doc.createTextNode(String(event.reason)));
        article.appendChild(impact);
      }

      var actions = element("div", "fm-actions");
      var read = element("button", "fm-action", isRead(event, state) ? "已读" : "标记已读");
      read.type = "button"; read.dataset.action = "read"; read.setAttribute("aria-pressed", isRead(event, state) ? "true" : "false");
      read.addEventListener("click", function () {
        if (isRead(event, state)) {
          delete state.read[id];
          if (reading) {var local = reading.load(storage);delete local.entries[id];reading.save(storage, local);}
        } else state.read[id] = new Date().toISOString();
        saveState(); render();
      });
      var favorite = state.favorites.indexOf(id) >= 0;
      var save = element("button", "fm-action", favorite ? "已收藏" : "收藏");
      save.type = "button"; save.dataset.action = "favorite"; save.setAttribute("aria-pressed", favorite ? "true" : "false");
      save.addEventListener("click", function () {
        var favorites = win.DataHotFavorites;
        if (favorites) {
          var result = favorites.toggleRecords(favorites.readRecords(storage), favorites.eventSnapshot(event), new Date());
          if (!favorites.writeRecords(storage, result.records)) {
            save.textContent = "保存失败，请重试";
            return;
          }
          state.favorites = result.records.map(function (record) { return record.event_id; });
          if (win.dhInitFav) win.dhInitFav();
          win.dispatchEvent(new win.CustomEvent("datahot:favorites-change", { detail:{action:result.action,record:result.record} }));
        } else {
          var index = state.favorites.indexOf(id);
          if (index >= 0) state.favorites.splice(index, 1); else state.favorites.push(id);
          saveJson(storage, FAVORITES_KEY, state.favorites);
        }
        render();
      });
      var dismiss = element("button", "fm-action fm-dismiss", "不感兴趣");
      dismiss.type = "button"; dismiss.dataset.action = "dismiss";
      dismiss.addEventListener("click", function () {
        state.dismissed.push(id); state.dismissed = uniqueStrings(state.dismissed, 200); saveState(); render();
        refs.notice.hidden = false; refs.notice.querySelector("button").hidden = false; refs.notice.querySelector("span").textContent = "已隐藏，并减少内容相近的推荐";
        refs.notice.querySelector("button").onclick = function () {state.dismissed = state.dismissed.filter(function(value) {return value !== id;}); saveState(); render(); refs.notice.hidden = true;};
      });
      actions.appendChild(read); actions.appendChild(save); actions.appendChild(dismiss);
      if (learned) {
        var less = element("button", "fm-action", "少推相似内容");
        less.type = "button";less.dataset.action = "reduce";
        less.onclick = function() {
          var local = reading.load(storage);local.muted.push(learned.key);
          if (!reading.save(storage, local)) {showNotice("浏览器未允许保存，设置没有改变。");return;}
          render();showNotice("已减少内容相近的推荐，其他方向不受影响", function(){var current=reading.load(storage);current.muted=current.muted.filter(function(key){return key!==learned.key;});reading.save(storage,current);render();});
        };
        actions.appendChild(less);
      }
      article.appendChild(actions);
      return article;
    }
    function renderCards(container, list, limit, priority, context) {
      container.replaceChildren();
      list.slice(0, limit).forEach(function (event) { container.appendChild(card(event, priority, context)); });
    }
    function renderSuggestions() {
      refs.suggestions.replaceChildren();
      buildSuggestions(events, products).forEach(function (suggestion) {
        var selected = isFollowing(suggestion.kind, suggestion.value);
        var button = element("button", "fm-follow-chip" + (selected ? " on" : ""));
        button.type = "button";
        button.dataset.kind = suggestion.kind;
        button.dataset.value = suggestion.value;
        button.setAttribute("aria-pressed", selected ? "true" : "false");
        button.appendChild(element("span", "fm-follow-kind", kindLabel(suggestion.kind)));
        button.appendChild(element("span", "", suggestion.label || suggestion.value));
        button.addEventListener("click", function () {
          if (isFollowing(suggestion.kind, suggestion.value)) removeFollow(suggestion.kind, suggestion.value);
          else addFollow(suggestion.kind, suggestion.value);
          render();
        });
        refs.suggestions.appendChild(button);
      });
    }
    function renderWatch(ranked) {
      refs.watch.replaceChildren();
      follows(state).forEach(function (follow) {
        var related = ranked.filter(function (event) {
          return matchReasons(event, { products: follow.kind === "product" ? [follow.value] : [], topics: follow.kind === "topic" ? [follow.value] : [], vendors: follow.kind === "vendor" ? [follow.value] : [] }).length;
        });
        related.sort(function (a, b) { return eventTime(b) - eventTime(a); });
        var row = element("div", "fm-watch-row");
        var label = element("div", "fm-watch-label");
        label.appendChild(element("span", "fm-follow-kind", kindLabel(follow.kind)));
        var name = element(follow.kind === "product" ? "a" : "b", "", followLabel(follow));
        if (follow.kind === "product") name.href = "products/" + follow.value + ".html";
        label.appendChild(name);
        label.appendChild(element("span", "fm-watch-count", related.length + " 条相关变化" + (related[0] ? " · 最新：" + String(related[0].zh_title || "") : "")));
        var remove = element("button", "fm-watch-remove", "取消关注");
        remove.type = "button";
        remove.addEventListener("click", function () { removeFollow(follow.kind, follow.value); setupOpen = true; render(); });
        row.appendChild(label); row.appendChild(remove); refs.watch.appendChild(row);
      });
    }
    function render() {
      var followed = follows(state);
      if (reading) {state.reading = reading.load(storage);state.affinity = affinity.profile(events, state, Date.now());}
      var personalized = personal(state);
      var now = Date.now();
      var grouped = sections(events, state, now, baseline);
      var ranked = grouped.ranked;
      var newCount = personalized ? ranked.filter(function (event) { return (baseline ? isNewSince(event, baseline) : eventTime(event, "first_seen") >= now - 7 * 86400000) && !isRead(event, state); }).length : 0;
      refs.visit.textContent = relativeVisit(baseline);
      refs.newCount.textContent = personalized ? String(newCount) : "—";
      refs.progress.textContent = personalized
        ? "已选 " + state.tasks.length + " 项工作 · 关注 " + followed.length + " 个对象"
        : "选择工作或关注对象，也可以跳过";
      refs.setup.hidden = !setupOpen;
      refs.customize.setAttribute("aria-expanded", setupOpen ? "true" : "false");
      refs.customize.textContent = "推荐设置";
      if (setupOpen && !settingsDialog.open) settingsDialog.showModal();
      if (!setupOpen && settingsDialog.open) settingsDialog.close();
      if (reading) {
        doc.getElementById("fmBehaviorEnabled").checked = state.reading.enabled;
        var count = Object.keys(state.reading.entries).length;
        doc.getElementById("fmBehaviorStatus").textContent = !state.reading.enabled ? "已暂停记录与行为推荐；主动关注仍有效。" : count ? "已在当前浏览器记录 " + count + " 篇有效阅读；按文章具体内容匹配相近问题，而非只看分类标签。" : "尚无有效阅读记录。认真阅读后按内容学习，也参考收藏与有用反馈；单次点击不计。";
      }
      renderSuggestions();

      var must = grouped.must;
      var feed = personalized ? grouped.updates : grouped.ranked.filter(function(event) {return !isRead(event,state) && !must.some(function(item) {return item.event_id===event.event_id;});}).slice(0,12);
      refs.must.querySelector("h2").textContent = personalized ? "为你挑选" : "近期精选";
      refs.must.querySelector("p").textContent = personalized ? "相关内容优先 · 保留原文日期" : "先读内容，逐渐了解你";
      renderCards(refs.mustList, must, 3, personalized);
      refs.feed.hidden = !feed.length;
      doc.getElementById("fmFeedTitle").textContent = personalized ? "你关注的新变化" : "继续发现";
      refs.feed.querySelector(".fm-section-head p").hidden = !personalized;
      renderCards(refs.feedList, feed, 12, false);
      refs.empty.hidden = Boolean(must.length);

      var discovery = grouped.discovery;
      refs.work.hidden = !personalized;
      renderCards(refs.workList, grouped.work, 6, false, "work");
      if (!grouped.work.length) refs.workList.textContent = "暂时没有更多匹配的工作参考，可调整兴趣或浏览案例库。";
      if (!feed.length) refs.feedList.textContent = "暂时没有更多未读的新变化。";
      var readEvents=ranked.filter(function(e) {return isRead(e, state);});
      renderCards(refs.readList, readEvents, 12, false);
      refs.readList.closest("details").hidden=!readEvents.length;
      renderSetup();
      refs.discovery.hidden = !discovery.length;
      renderCards(refs.discoveryList, discovery, 2, false, "discovery");
      refs.watch.closest("section").hidden = !followed.length;
      renderWatch(ranked);
      var weekAgo = now - 7 * 86400000;
      refs.weeklyCount.textContent = personalized
        ? ranked.filter(function (event) { return eventTime(event) >= weekAgo; }).length + " 条关注变化"
        : "本周公共回顾";
    }

    function showNotice(message, undo) {
      refs.notice.hidden=false;refs.notice.querySelector("span").textContent=message;
      var button=refs.notice.querySelector("button");button.hidden=!undo;
      button.onclick=function(){if(undo) undo();refs.notice.hidden=true;};
    }
    if (reading) {
      doc.getElementById("fmBehaviorEnabled").onchange=function(){
        var local=reading.load(storage);local.enabled=this.checked;
        if (!reading.save(storage,local)) showNotice("浏览器未允许保存，设置没有改变。");
        render();
      };
      doc.getElementById("fmClearReading").onclick=function(){
        var local=reading.load(storage);local.entries={};local.muted=[];
        if (reading.save(storage,local)) {render();showNotice("已清除阅读记录；收藏、反馈和主动关注仍保留。");}
        else showNotice("浏览器未允许清除，记录没有改变。");
      };
      function refreshLocal(){
        state.feedback=normalizeFeedbackStore(loadJson(storage,FEEDBACK_KEY,{}));
        state.favorites=win.DataHotFavorites?win.DataHotFavorites.readRecords(storage).map(function(r){return r.event_id;}):uniqueStrings(loadJson(storage,FAVORITES_KEY,[]),500);
        if(events.length) render();
      }
      win.addEventListener("storage",refreshLocal);
      win.addEventListener("pageshow",refreshLocal);
      win.addEventListener("focus",refreshLocal);
    }
    function renderSetup() {
      doc.getElementById("fmTaskStep").hidden = setupStep !== 1;
      doc.getElementById("fmFollowStep").hidden = setupStep !== 2;
      var tasks = doc.getElementById("fmTasks"); tasks.replaceChildren();
      TASKS.forEach(function(task) {
        var selected = state.tasks.indexOf(task.id) >= 0;
        var button = element("button", "fm-follow-chip" + (selected ? " on" : ""), task.label);
        button.type = "button"; button.dataset.task = task.id; button.setAttribute("aria-pressed", String(selected));
        button.onclick = function() {state.tasks = selected ? state.tasks.filter(function(id) {return id !== task.id;}) : state.tasks.concat(task.id);saveState();render();doc.querySelector('[data-task="' + task.id + '"]').focus();};
        tasks.appendChild(button);
      });
    }
    function clearSettingsHash() {if(win.location.hash==="#reading-settings") win.history.replaceState(null,"",win.location.pathname+win.location.search);}
    function finishSetup() {clearSettingsHash();setupOpen = false;state.setupDone = true;saveState();render();refs.customize.focus();}
    doc.getElementById("fmNext").onclick = function() {setupStep = 2;renderSetup();doc.getElementById("fmBack").focus();};
    doc.getElementById("fmBack").onclick = function() {setupStep = 1;renderSetup();doc.getElementById("fmNext").focus();};
    doc.getElementById("fmDone").onclick = finishSetup;
    doc.getElementById("fmSkip").onclick = finishSetup;
    doc.getElementById("fmReset").onclick = function() {state.tasks=[];state.topics=[];state.vendors=[];state.products=[];state.setupDone=false;setupOpen=true;setupStep=1;saveState();render();};
    var defaultHome = doc.getElementById("fmDefaultHome"), defaultStatus = doc.getElementById("fmDefaultStatus");
    try {defaultHome.checked = storage && storage.getItem(DEFAULT_HOME_KEY) === "for-you";} catch (_error) {}
    if (defaultHome.checked) defaultStatus.textContent = "已设为默认首页，仍可从导航查看热榜。";
    defaultHome.onchange = function() {
      try {if (!storage) throw new Error("storage unavailable");storage.setItem(DEFAULT_HOME_KEY, defaultHome.checked ? "for-you" : "all");defaultStatus.textContent = defaultHome.checked ? "下次打开网站首页时进入为你，仍可从导航查看热榜。" : "已恢复默认打开热榜。";}
      catch (_error) {defaultHome.checked=false;defaultStatus.textContent="浏览器未允许保存设置，请通过导航进入为你。";}
    };

    refs.customize.addEventListener("click", function () { setupOpen = true; render(); settingsDialog.scrollTop=0; });
    doc.getElementById("fmCloseSettings").onclick = finishSetup;
    settingsDialog.addEventListener("cancel", function () {clearSettingsHash();setupOpen=false;});
    settingsDialog.addEventListener("close", function () {if(settingsDialog.open) return;setupOpen=false;refs.setup.hidden=true;refs.customize.setAttribute("aria-expanded","false");refs.customize.focus();});
    settingsDialog.addEventListener("click", function(event) {
      var rect=settingsDialog.getBoundingClientRect();
      if(event.target===settingsDialog && (event.clientX<rect.left || event.clientX>rect.right || event.clientY<rect.top || event.clientY>rect.bottom)) finishSetup();
    });
    function openReadingSettings() {
      if(win.location.hash!=="#reading-settings") return;
      setupOpen=true;render();
      var settings=doc.getElementById("reading-settings");settings.open=true;
      settings.scrollIntoView({block:"start"});doc.getElementById("fmBehaviorEnabled").focus({preventScroll:true});
    }
    win.addEventListener("hashchange",openReadingSettings);
    refs.error.querySelector("button").addEventListener("click", function () { win.location.reload(); });
    win.addEventListener("datahot:feedback", function () {
      state.feedback = normalizeFeedbackStore(loadJson(storage, FEEDBACK_KEY, {}));
      render();
    });
    win.addEventListener("datahot:favorites-change", function () {
      state.favorites = win.DataHotFavorites ? win.DataHotFavorites.readRecords(storage).map(function (r) { return r.event_id; }) : uniqueStrings(loadJson(storage, FAVORITES_KEY, []), 500);
      render();
    });
    win.fetch(config.dataset.liteUrl || "data/latest-lite.json", { credentials: "same-origin" }).then(function (response) {
      if (!response.ok) throw new Error("HTTP " + response.status);
      return response.json();
    }).then(function (payload) {
      payload = decode(payload);
      events = Array.isArray(payload.events) ? payload.events : [];
      products = (Array.isArray(payload.products) ? payload.products : []).filter(function (p) {
        return p && /^[a-z][a-z0-9-]{1,63}$/.test(p.id) && typeof p.name === "string";
      });
      products.forEach(function (p) { productNames[p.id] = p.name; });
      refs.loading.hidden = true; refs.content.hidden = false; render();
      openReadingSettings();
    }).catch(function () {
      refs.loading.hidden = true; refs.error.hidden = false;
    });
  }

  return {
    decodePayload: decode,
    STORAGE_KEY: STORAGE_KEY,
    TASKS: TASKS, sections: sections, taskReasons: taskReasons, isRead: isRead,
    normalizeState: normalizeState,
    matchReasons: matchReasons,
    normalizeFeedbackStore: normalizeFeedbackStore,
    feedbackSignal: feedbackSignal,
    fitScore: fitScore,
    scoreEvent: scoreEvent,
    rankEvents: rankEvents,
    isNewSince: isNewSince,
    buildSuggestions: buildSuggestions,
    boot: boot
  };
});
