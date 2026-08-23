(function (root, factory) {
  "use strict";
  var api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  if (root) root.DataHotFavorites = api;
  if (root && root.document) api.boot(root);
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  "use strict";

  var STORAGE_KEY = "dh_favs_v2";
  var LEGACY_KEY = "dh_favs";
  var SCHEMA_VERSION = 2;
  var SEARCH_THRESHOLD = 8;
  var EVENT_ID_RE = /^[a-f0-9]{12}$/;
  var CATEGORY_LABELS = {
    agent: "Data Agent",
    platform: "AI 数据平台",
    bi: "BI 与可视化",
    product: "数据产品",
    insight: "AI 分析"
  };
  var BOOKMARK_ICON = '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M19 21l-7-4.5L5 21V4a2 2 0 0 1 2-2h10a2 2 0 0 1 2 2v17z"></path></svg>';

  function escapeHtml(value) {
    return String(value == null ? "" : value).replace(/[&<>"']/g, function (char) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[char];
    });
  }

  function cleanString(value, limit) {
    return String(value == null ? "" : value).replace(/\s+/g, " ").trim().slice(0, limit);
  }

  function safeParse(value) {
    if (!value) return null;
    try { return JSON.parse(value); } catch (error) { return null; }
  }

  function storageValue(storage, key) {
    try { return storage && storage.getItem(key); } catch (error) { return null; }
  }

  function validEventId(value) {
    var eventId = String(value || "").toLowerCase();
    return EVENT_ID_RE.test(eventId) ? eventId : "";
  }

  function safeOriginalUrl(value) {
    var url = cleanString(value, 2000);
    return /^https?:\/\//i.test(url) ? url : "";
  }

  function normalizeTopics(value) {
    if (!Array.isArray(value)) return [];
    var seen = Object.create(null);
    return value.map(function (topic) { return cleanString(topic, 80); }).filter(function (topic) {
      if (!topic || seen[topic]) return false;
      seen[topic] = true;
      return true;
    }).slice(0, 12);
  }

  function normalizeRecord(value) {
    var source = typeof value === "string" ? { event_id: value } : (value || {});
    var eventId = validEventId(source.event_id || source.id);
    if (!eventId) return null;
    var savedAt = cleanString(source.saved_at, 80);
    if (savedAt && !Number.isFinite(Date.parse(savedAt))) savedAt = "";
    return {
      event_id: eventId,
      title: cleanString(source.title || source.zh_title, 500),
      summary: cleanString(source.summary || source.zh_summary, 1400),
      source: cleanString(source.source, 200),
      category: cleanString(source.category, 40),
      topics: normalizeTopics(source.topics),
      published: cleanString(source.published || source.first_seen, 80),
      original_url: safeOriginalUrl(source.original_url),
      saved_at: savedAt
    };
  }

  function dedupe(records) {
    var seen = Object.create(null);
    return (records || []).map(normalizeRecord).filter(function (record) {
      if (!record || seen[record.event_id]) return false;
      seen[record.event_id] = true;
      return true;
    });
  }

  function readRecords(storage) {
    var versioned = safeParse(storageValue(storage, STORAGE_KEY));
    var versionedItems = versioned && Array.isArray(versioned.items) ? versioned.items : [];
    var records = dedupe(versionedItems);
    var byId = Object.create(null);
    records.forEach(function (record) { byId[record.event_id] = record; });

    var legacyRaw = storageValue(storage, LEGACY_KEY);
    var legacy = safeParse(legacyRaw);
    if (legacyRaw !== null && Array.isArray(legacy)) {
      return dedupe(legacy.map(function (eventId) {
        var normalizedId = validEventId(eventId);
        return byId[normalizedId] || { event_id: normalizedId };
      }));
    }
    return records;
  }

  function writeRecords(storage, records) {
    var normalized = dedupe(records);
    try {
      storage.setItem(STORAGE_KEY, JSON.stringify({ version: SCHEMA_VERSION, items: normalized }));
    } catch (error) {
      return false;
    }
    try {
      storage.setItem(LEGACY_KEY, JSON.stringify(normalized.map(function (record) { return record.event_id; })));
    } catch (error) {}
    return true;
  }

  function recordFromButton(button, now) {
    var payload = safeParse(button && button.getAttribute ? button.getAttribute("data-fav-record") : "");
    var record = normalizeRecord(payload || {});
    var eventId = validEventId(button && button.getAttribute ? button.getAttribute("data-fav") : "");
    if (!record && eventId) record = normalizeRecord({ event_id: eventId });
    if (!record) return null;
    record.event_id = eventId || record.event_id;
    record.saved_at = (now || new Date()).toISOString();
    return record;
  }

  function toggleRecords(records, incoming, now) {
    var normalized = dedupe(records);
    var record = normalizeRecord(incoming);
    if (!record) return { records: normalized, action: "invalid", record: null, index: -1 };
    var index = normalized.findIndex(function (item) { return item.event_id === record.event_id; });
    if (index >= 0) {
      var removed = normalized[index];
      normalized.splice(index, 1);
      return { records: normalized, action: "remove", record: removed, index: index };
    }
    if (!record.saved_at) record.saved_at = (now || new Date()).toISOString();
    normalized.push(record);
    return { records: normalized, action: "add", record: record, index: normalized.length - 1 };
  }

  function eventSnapshot(event) {
    var item = event && event.items && event.items[0] ? event.items[0] : {};
    return normalizeRecord({
      event_id: event && event.event_id,
      title: event && event.zh_title,
      summary: event && event.zh_summary,
      source: item.source,
      category: event && event.category,
      topics: event && event.topics,
      published: event && (event.published || event.first_seen)
    });
  }

  function enrichRecords(records, events) {
    var eventMap = Object.create(null);
    (events || []).forEach(function (event) {
      var snapshot = eventSnapshot(event);
      if (snapshot) eventMap[snapshot.event_id] = snapshot;
    });
    return dedupe(records).map(function (record) {
      var snapshot = eventMap[record.event_id];
      if (!snapshot) return record;
      return normalizeRecord({
        event_id: record.event_id,
        title: record.title || snapshot.title,
        summary: record.summary || snapshot.summary,
        source: record.source || snapshot.source,
        category: record.category || snapshot.category,
        topics: record.topics.length ? record.topics : snapshot.topics,
        published: record.published || snapshot.published,
        original_url: record.original_url || snapshot.original_url,
        saved_at: record.saved_at
      });
    });
  }

  function sortRecords(records) {
    return dedupe(records).map(function (record, index) {
      return { record: record, index: index, time: Date.parse(record.saved_at || "") };
    }).sort(function (left, right) {
      var leftValid = Number.isFinite(left.time);
      var rightValid = Number.isFinite(right.time);
      if (leftValid && rightValid && left.time !== right.time) return right.time - left.time;
      if (leftValid !== rightValid) return leftValid ? -1 : 1;
      return right.index - left.index;
    }).map(function (item) { return item.record; });
  }

  function topicOptions(records) {
    var counts = Object.create(null);
    dedupe(records).forEach(function (record) {
      record.topics.forEach(function (topic) { counts[topic] = (counts[topic] || 0) + 1; });
    });
    return Object.keys(counts).sort(function (left, right) {
      return counts[right] - counts[left] || left.localeCompare(right, "zh-CN");
    }).slice(0, 8);
  }

  function filterRecords(records, query, topic) {
    var normalizedQuery = cleanString(query, 120).toLocaleLowerCase("zh-CN");
    var selectedTopic = cleanString(topic, 80);
    return sortRecords(records).filter(function (record) {
      if (selectedTopic && record.topics.indexOf(selectedTopic) < 0) return false;
      if (!normalizedQuery) return true;
      return [record.title, record.summary, record.source, record.category].concat(record.topics).join(" ")
        .toLocaleLowerCase("zh-CN").indexOf(normalizedQuery) >= 0;
    });
  }

  function groupLabel(record, now) {
    var saved = new Date(record.saved_at || "");
    if (!Number.isFinite(saved.getTime())) return "更早";
    var today = new Date(now || new Date());
    var savedDay = new Date(saved.getFullYear(), saved.getMonth(), saved.getDate());
    var todayDay = new Date(today.getFullYear(), today.getMonth(), today.getDate());
    var days = Math.floor((todayDay.getTime() - savedDay.getTime()) / 86400000);
    if (days <= 0) return "今天";
    if (days < 7) return "本周";
    return "更早";
  }

  function groupRecords(records, now) {
    var labels = ["今天", "本周", "更早"];
    var groups = { "今天": [], "本周": [], "更早": [] };
    sortRecords(records).forEach(function (record) { groups[groupLabel(record, now)].push(record); });
    return labels.filter(function (label) { return groups[label].length; }).map(function (label) {
      return { label: label, records: groups[label] };
    });
  }

  function formatSavedAt(value, now) {
    var saved = new Date(value || "");
    if (!Number.isFinite(saved.getTime())) return "较早收藏";
    var current = new Date(now || new Date());
    if (saved.toDateString() === current.toDateString()) {
      return "收藏于 " + String(saved.getHours()).padStart(2, "0") + ":" + String(saved.getMinutes()).padStart(2, "0");
    }
    if (saved.getFullYear() === current.getFullYear()) return "收藏于 " + (saved.getMonth() + 1) + "月" + saved.getDate() + "日";
    return "收藏于 " + saved.getFullYear() + "-" + String(saved.getMonth() + 1).padStart(2, "0") + "-" + String(saved.getDate()).padStart(2, "0");
  }

  function recordAttribute(record) {
    return escapeHtml(JSON.stringify(record));
  }

  function renderCard(record, now) {
    var topic = record.topics[0] || CATEGORY_LABELS[record.category] || "收藏";
    var title = record.title || "已保存的内容";
    var summary = record.summary || "旧版收藏已保留；打开详情查看原内容。";
    var published = cleanString(record.published, 80).slice(0, 10);
    var source = record.source || "DataHot";
    var meta = escapeHtml(source) + (published ? " · " + escapeHtml(published) : "");
    return '<article class="favorite-card" role="listitem" data-event-id="' + escapeHtml(record.event_id) + '">' +
      '<a class="favorite-card-main" href="e/' + encodeURIComponent(record.event_id) + '.html">' +
      '<div class="favorite-card-top"><span class="favorite-card-topic">' + escapeHtml(topic) + '</span>' +
      '<span class="favorite-card-saved">' + escapeHtml(formatSavedAt(record.saved_at, now)) + '</span></div>' +
      '<h3>' + escapeHtml(title) + '</h3><p class="favorite-card-summary">' + escapeHtml(summary) + '</p>' +
      '<div class="favorite-card-meta"><span>' + meta + '</span></div></a>' +
      '<button class="favbtn on" type="button" data-fav="' + escapeHtml(record.event_id) + '" data-fav-record="' +
      recordAttribute(record) + '" title="取消收藏" aria-label="取消收藏" aria-pressed="true">' + BOOKMARK_ICON + '</button></article>';
  }

  function renderGroups(records, now) {
    return groupRecords(records, now).map(function (group) {
      return '<section class="favorites-group"><h2>' + group.label + '</h2><div class="favorites-list" role="list">' +
        group.records.map(function (record) { return renderCard(record, now); }).join("") + '</div></section>';
    }).join("");
  }

  function renderEmpty(filtered) {
    var title = filtered ? "没有匹配的收藏" : "还没有收藏";
    var copy = filtered ? "换个关键词或主题再试试。" : "遇到想稍后阅读的内容，点一下书签即可保存在这里。";
    var action = filtered ? "" : '<a class="favorites-empty-cta" href="index.html">去看今日热榜</a>';
    return '<div class="favorites-empty"><div class="favorites-empty-inner"><div class="favorites-empty-icon">' +
      BOOKMARK_ICON + '</div><h2>' + title + '</h2><p>' + copy + '</p>' + action + '</div></div>';
  }

  function renderFilters(topics, selected) {
    return ['<button class="favorites-filter' + (!selected ? ' on' : '') + '" type="button" data-favorites-topic="" aria-pressed="' + (!selected) + '">全部</button>']
      .concat(topics.map(function (topic) {
        var on = selected === topic;
        return '<button class="favorites-filter' + (on ? ' on' : '') + '" type="button" data-favorites-topic="' +
          escapeHtml(topic) + '" aria-pressed="' + on + '">' + escapeHtml(topic) + '</button>';
      })).join("");
  }

  function syncButtons(document, storage) {
    var ids = Object.create(null);
    readRecords(storage).forEach(function (record) { ids[record.event_id] = true; });
    Array.prototype.forEach.call(document.querySelectorAll("[data-fav]"), function (button) {
      var on = Boolean(ids[validEventId(button.getAttribute("data-fav"))]);
      button.classList.toggle("on", on);
      button.setAttribute("aria-pressed", on ? "true" : "false");
      button.setAttribute("aria-label", on ? "取消收藏" : "收藏");
      button.setAttribute("title", on ? "取消收藏" : "收藏");
      var label = button.querySelector(".sbtn-label");
      if (label) label.textContent = on ? "已收藏" : "收藏";
    });
  }

  function favoritesUrl(document) {
    var script = document.querySelector('script[src$="favorites.js"]');
    try { return new URL("favorites.html", script && script.src ? script.src : document.baseURI).href; }
    catch (error) { return "favorites.html"; }
  }

  function showToast(win, message, actionLabel, action) {
    var document = win.document;
    var toast = document.getElementById("favoriteToast");
    if (!toast) {
      toast = document.createElement("div");
      toast.id = "favoriteToast";
      toast.className = "fav-toast";
      toast.setAttribute("role", "status");
      toast.setAttribute("aria-live", "polite");
      var text = document.createElement("span");
      text.className = "fav-toast-text";
      var button = document.createElement("button");
      button.className = "fav-toast-action";
      button.type = "button";
      button.addEventListener("click", function () {
        var handler = toast._action;
        toast.classList.remove("show");
        if (typeof handler === "function") handler();
      });
      toast.appendChild(text);
      toast.appendChild(button);
      document.body.appendChild(toast);
    }
    toast.querySelector(".fav-toast-text").textContent = message;
    var actionButton = toast.querySelector(".fav-toast-action");
    actionButton.textContent = actionLabel || "";
    actionButton.hidden = !actionLabel;
    toast._action = action;
    toast.classList.add("show");
    win.clearTimeout(toast._timer);
    toast._timer = win.setTimeout(function () { toast.classList.remove("show"); }, 3600);
  }

  function dispatchChange(win, action, record) {
    if (typeof win.CustomEvent !== "function") return;
    win.dispatchEvent(new win.CustomEvent("datahot:favorites-change", { detail: { action: action, record: record } }));
  }

  function initFavoritesPage(win, storage) {
    var document = win.document;
    var page = document.querySelector("[data-favorites-page]");
    if (!page) return;
    var list = document.getElementById("favList");
    var count = document.getElementById("favoritesCount");
    var tools = document.getElementById("favoritesTools");
    var search = document.getElementById("favoritesSearch");
    var filters = document.getElementById("favoritesFilters");
    var state = { query: "", topic: "" };

    function render() {
      var records = sortRecords(readRecords(storage));
      var topics = topicOptions(records);
      if (state.topic && topics.indexOf(state.topic) < 0) state.topic = "";
      count.textContent = records.length + " 条";
      tools.hidden = records.length < SEARCH_THRESHOLD;
      filters.innerHTML = renderFilters(topics, state.topic);
      var visible = filterRecords(records, state.query, state.topic);
      list.innerHTML = records.length ? (visible.length ? renderGroups(visible, new Date()) : renderEmpty(true)) : renderEmpty(false);
      list.setAttribute("aria-busy", "false");
      syncButtons(document, storage);
    }

    search.addEventListener("input", function () { state.query = search.value; render(); });
    filters.addEventListener("click", function (event) {
      var button = event.target.closest("[data-favorites-topic]");
      if (!button) return;
      state.topic = button.getAttribute("data-favorites-topic") || "";
      render();
    });
    win.addEventListener("datahot:favorites-change", render);
    render();

    var records = readRecords(storage);
    var needsEnrichment = records.some(function (record) { return !record.title; });
    var dataUrl = page.getAttribute("data-favorites-data-url");
    if (needsEnrichment && dataUrl && typeof win.fetch === "function") {
      win.fetch(dataUrl, { cache: "no-store", credentials: "same-origin" }).then(function (response) {
        if (!response.ok) throw new Error("favorites metadata " + response.status);
        return response.json();
      }).then(function (payload) {
        var enriched = enrichRecords(readRecords(storage), payload.events || []);
        if (writeRecords(storage, enriched)) render();
      }).catch(function () {
        list.setAttribute("data-enrichment", "unavailable");
      });
    }
  }

  function boot(win) {
    var document = win.document;
    var storage;
    try { storage = win.localStorage; } catch (error) { storage = null; }
    if (!storage) return;
    var initial = readRecords(storage);
    if (initial.length && storageValue(storage, STORAGE_KEY) === null) writeRecords(storage, initial);
    win.dhInitFav = function () { syncButtons(document, storage); };
    syncButtons(document, storage);

    document.addEventListener("click", function (event) {
      var button = event.target.closest("[data-fav]");
      if (!button) return;
      event.preventDefault();
      event.stopPropagation();
      var eventId = validEventId(button.getAttribute("data-fav"));
      var records = readRecords(storage);
      var existing = records.find(function (record) { return record.event_id === eventId; });
      var incoming = existing || recordFromButton(button, new Date());
      var result = toggleRecords(records, incoming, new Date());
      if (result.action === "invalid") return;
      if (!writeRecords(storage, result.records)) {
        showToast(win, "当前浏览器无法保存收藏", "", null);
        return;
      }
      syncButtons(document, storage);
      dispatchChange(win, result.action, result.record);
      if (result.action === "add") {
        showToast(win, "已收藏", "查看", function () { win.location.href = favoritesUrl(document); });
      } else {
        showToast(win, "已取消收藏", "撤销", function () {
          var current = readRecords(storage);
          if (current.some(function (record) { return record.event_id === result.record.event_id; })) return;
          current.splice(Math.min(result.index, current.length), 0, result.record);
          if (!writeRecords(storage, current)) return;
          syncButtons(document, storage);
          dispatchChange(win, "restore", result.record);
        });
      }
    });

    win.addEventListener("storage", function (event) {
      if (event.key !== STORAGE_KEY && event.key !== LEGACY_KEY) return;
      syncButtons(document, storage);
      dispatchChange(win, "storage", null);
    });
    initFavoritesPage(win, storage);
  }

  return {
    STORAGE_KEY: STORAGE_KEY,
    LEGACY_KEY: LEGACY_KEY,
    SCHEMA_VERSION: SCHEMA_VERSION,
    normalizeRecord: normalizeRecord,
    readRecords: readRecords,
    writeRecords: writeRecords,
    recordFromButton: recordFromButton,
    toggleRecords: toggleRecords,
    enrichRecords: enrichRecords,
    sortRecords: sortRecords,
    topicOptions: topicOptions,
    filterRecords: filterRecords,
    groupRecords: groupRecords,
    renderCard: renderCard,
    renderGroups: renderGroups,
    boot: boot
  };
});
