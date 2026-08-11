"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const tts = require("../pipeline/assets/tts-player.js");


function fakeNode() {
  return {
    listeners: {},
    attributes: {},
    dataset: {},
    textContent: "",
    value: "",
    hidden: false,
    addEventListener(name, handler) { this.listeners[name] = handler; },
    setAttribute(name, value) { this.attributes[name] = value; },
    querySelector(selector) { return this.children && this.children[selector]; },
  };
}


test("time and rate helpers reject surprising values", () => {
  assert.equal(tts.formatTime(0), "0:00");
  assert.equal(tts.formatTime(65.9), "1:05");
  assert.equal(tts.formatTime(-3), "0:00");
  assert.equal(tts.safeRate("1.2"), 1.2);
  assert.equal(tts.safeRate("4"), 1);
  assert.deepEqual(tts.rates, [1, 1.2, 1.5]);
});


test("button reveals player, plays, pauses and updates the selected rate", async () => {
  const open = fakeNode();
  const openLabel = fakeNode();
  open.children = { "[data-tts-open-label]": openLabel };
  const player = fakeNode();
  player.hidden = true;
  player.dataset.duration = "60";
  const audio = fakeNode();
  audio.paused = true;
  audio.ended = false;
  audio.duration = 60;
  audio.currentTime = 0;
  audio.playbackRate = 1;
  audio.play = function () {
    this.paused = false;
    if (this.listeners.playing) this.listeners.playing();
    return Promise.resolve();
  };
  audio.pause = function () {
    this.paused = true;
    if (this.listeners.pause) this.listeners.pause();
  };
  const toggle = fakeNode();
  const progress = fakeNode();
  const time = fakeNode();
  const status = fakeNode();
  const rate = fakeNode();
  player.children = {
    "[data-tts-audio]": audio,
    "[data-tts-toggle]": toggle,
    "[data-tts-progress]": progress,
    "[data-tts-time]": time,
    "[data-tts-status]": status,
    "[data-tts-rate]": rate,
  };
  const storage = new Map();
  const win = {
    document: {
      querySelector(selector) {
        return selector === "[data-tts-player]" ? player : (selector === "[data-tts-open]" ? open : null);
      },
    },
    localStorage: {
      getItem(key) { return storage.get(key) || null; },
      setItem(key, value) { storage.set(key, value); },
    },
  };

  const controller = tts.boot(win);
  assert.ok(controller);
  open.listeners.click();
  await Promise.resolve();
  assert.equal(player.hidden, false);
  assert.equal(open.attributes["aria-expanded"], "true");
  assert.equal(audio.paused, false);
  assert.equal(toggle.textContent, "暂停");
  toggle.listeners.click();
  assert.equal(audio.paused, true);
  assert.equal(toggle.textContent, "继续");
  rate.value = "1.5";
  rate.listeners.change();
  assert.equal(audio.playbackRate, 1.5);
  assert.equal(storage.get("datahot_tts_rate_v1"), "1.5");
});
