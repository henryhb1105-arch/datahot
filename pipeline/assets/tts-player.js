(function (root, factory) {
  "use strict";
  var api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  if (root) root.DataHotTTS = api;
  if (root && root.document) api.boot(root);
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  "use strict";

  var RATE_KEY = "datahot_tts_rate_v1";
  var RATES = [1, 1.2, 1.5];

  function formatTime(value) {
    var seconds = Math.max(0, Number(value) || 0);
    var minutes = Math.floor(seconds / 60);
    var remainder = Math.floor(seconds % 60);
    return minutes + ":" + String(remainder).padStart(2, "0");
  }

  function safeRate(value) {
    var rate = Number(value);
    return RATES.indexOf(rate) >= 0 ? rate : 1;
  }

  function boot(win) {
    var doc = win.document;
    var player = doc.querySelector("[data-tts-player]");
    var openButton = doc.querySelector("[data-tts-open]");
    if (!player || !openButton) return null;
    var audio = player.querySelector("[data-tts-audio]");
    var toggle = player.querySelector("[data-tts-toggle]");
    var progress = player.querySelector("[data-tts-progress]");
    var time = player.querySelector("[data-tts-time]");
    var status = player.querySelector("[data-tts-status]");
    var rate = player.querySelector("[data-tts-rate]");
    var openLabel = openButton.querySelector("[data-tts-open-label]");
    if (!audio || !toggle || !progress || !time || !status || !rate) return null;

    function readStoredRate() {
      try { return safeRate(win.localStorage.getItem(RATE_KEY)); }
      catch (_error) { return 1; }
    }
    function storeRate(value) {
      try { win.localStorage.setItem(RATE_KEY, String(value)); }
      catch (_error) {}
    }
    function updateTime() {
      var duration = Number.isFinite(audio.duration) ? audio.duration : Number(player.dataset.duration || 0);
      progress.max = duration || 0;
      progress.value = Math.min(Number(audio.currentTime || 0), duration || 0);
      time.textContent = formatTime(audio.currentTime) + " / " + formatTime(duration);
    }
    function updateState(label, message) {
      toggle.textContent = label;
      toggle.setAttribute("aria-label", label + "朗读");
      var actionLabel = label === "播放" ? "速听" : label;
      if (openLabel) openLabel.textContent = actionLabel;
      openButton.setAttribute("aria-label", actionLabel);
      openButton.setAttribute("title", actionLabel);
      status.textContent = message;
    }
    function showPlayer() {
      player.hidden = false;
      openButton.setAttribute("aria-expanded", "true");
    }
    function play() {
      showPlayer();
      updateState("暂停", "正在加载…");
      var result;
      try { result = audio.play(); }
      catch (_error) { updateState("重试", "音频暂时无法播放"); return; }
      if (result && typeof result.catch === "function") {
        result.catch(function () { updateState("重试", "音频暂时无法播放"); });
      }
    }
    function togglePlayback() {
      if (audio.paused || audio.ended) play();
      else audio.pause();
    }

    var initialRate = readStoredRate();
    audio.playbackRate = initialRate;
    rate.value = String(initialRate);
    updateTime();
    openButton.addEventListener("click", togglePlayback);
    toggle.addEventListener("click", togglePlayback);
    progress.addEventListener("input", function () {
      if (Number.isFinite(audio.duration)) audio.currentTime = Math.min(Number(progress.value || 0), audio.duration);
      updateTime();
    });
    rate.addEventListener("change", function () {
      var value = safeRate(rate.value);
      audio.playbackRate = value;
      rate.value = String(value);
      storeRate(value);
    });
    audio.addEventListener("loadedmetadata", updateTime);
    audio.addEventListener("durationchange", updateTime);
    audio.addEventListener("timeupdate", updateTime);
    audio.addEventListener("playing", function () { updateState("暂停", "DataHot 主播正在朗读"); });
    audio.addEventListener("pause", function () {
      if (!audio.ended) updateState("继续", "已暂停");
    });
    audio.addEventListener("ended", function () {
      audio.currentTime = 0;
      updateTime();
      updateState("播放", "播放完成");
    });
    audio.addEventListener("error", function () { updateState("重试", "音频加载失败"); });
    return { audio: audio, play: play, toggle: togglePlayback, updateTime: updateTime };
  }

  return { boot: boot, formatTime: formatTime, safeRate: safeRate, rates: RATES.slice() };
});
