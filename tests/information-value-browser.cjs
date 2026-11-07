'use strict';
const assert = require('node:assert/strict');
const path = require('node:path');

// Uses the real generated data and the caller's disposable, analytics-free context.
module.exports = async function(context, base, out, width) {
  const response = await context.request.get(new URL('data/latest-lite.json', base).href);
  assert(response.ok());
  const payload = await response.json();
  const low = payload.events.filter(e => e.promotion_suppressed === true);
  const home = new Set(payload.home_event_ids);
  for (const event of low) assert(!home.has(event.event_id), 'Suppressed announcement in timeline');
  const pending = payload.events.find(e => e.body_review_required && e.enrichment_status !== 'pending' && home.has(e.event_id));
  assert(pending, 'Candidate should expose the body-verification state');
  const page = await context.newPage();
  try {
    await page.goto(new URL('index.html?q=' + encodeURIComponent(pending.zh_title), base).href, {waitUntil:'domcontentloaded'});
    const card = page.locator('.item[data-event-id="' + pending.event_id + '"]');
    await card.waitFor({state:'visible'});
    assert.match(await card.innerText(), /正文待核验/);
    await card.scrollIntoViewIfNeeded();
    await page.screenshot({path:path.join(out, width + '-information-value.png')});
    for (const event of low) {
      const detail = await context.request.get(new URL('e/' + event.event_id + '.html', base).href);
      assert(detail.ok(), 'Suppressed items must retain their detail page');
    }
    await page.goto(new URL('for-me.html', base).href, {waitUntil:'domcontentloaded'});
    await page.locator('#fmContent').waitFor({state:'visible'});
    const ranked = await page.evaluate(async () => {
      const config = document.getElementById('forMeDataConfig');
      const data = DataHotForMe.decodePayload(await (await fetch(config.dataset.liteUrl)).json());
      return DataHotForMe.rankEvents(data.events, DataHotForMe.normalizeState({}), Date.now(), false).map(e => e.event_id);
    });
    for (const event of low) assert(!ranked.includes(event.event_id), 'For Me bypassed suppression');
    const pendingById = new Map(payload.events.filter(e => e.body_review_required || e.enrichment_status === 'pending').map(e => [e.event_id,e]));
    const visible = await page.locator('.fm-signal').all();
    for (const row of visible) {
      const pendingEvent = pendingById.get(await row.getAttribute('data-event-id'));
      if (pendingEvent) {
        assert.match(await row.innerText(), pendingEvent.enrichment_status === 'pending' ? /原文待处理/ : /正文待核验/);
        assert.doesNotMatch(await row.locator('.fm-signal-badge').innerText(), /优先推荐/);
      }
    }
    assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1));
    return {suppressed:low.length, pending:pending.event_id, detail_pages_preserved:true};
  } finally {await page.close();}
};
