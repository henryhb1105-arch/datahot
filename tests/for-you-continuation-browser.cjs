'use strict';
const assert = require('node:assert/strict');
const path = require('node:path');
module.exports = async function(context, base, out, width) {
  const page = await context.newPage(), errors = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.goto(base + 'for-me.html', {waitUntil:'networkidle'});
  const data = await (await context.request.get(base + 'data/latest-lite.json')).json();
  const readIds = data.events.filter(event => (event.vendors || []).includes('Cube')).map(event => event.event_id);
  assert(readIds.length > 0 && readIds.length < 500, 'Need a bounded real followed collection');
  async function setState(options) {
    await page.evaluate(options => {
      for (const key of ['dh_reading_v1','dh_for_me_v1','dh_favs','dh_favs_v2','dh_content_feedback_v1','dh_default_home_v1']) localStorage.removeItem(key);
      localStorage.setItem('dh_for_me_v1', JSON.stringify({setupDone:true,...options}));
      sessionStorage.clear();
    }, options);
    await page.reload({waitUntil:'networkidle'});
    await page.locator('#fmContent').waitFor();
  }
  await setState({vendors:['Cube'],read:Object.fromEntries(readIds.map(id => [id,new Date().toISOString()]))});
  assert.equal(await page.locator('#fmDiscoveryTitle').textContent(), '继续发现');
  assert(!(await page.locator('#fmMust').isVisible()));
  assert(!(await page.locator('#fmEmpty').isVisible()));
  assert(!(await page.locator('#fmWork').isVisible()));
  const first = page.locator('#fmDiscoveryList .fm-signal').first();
  await first.waitFor();
  const top = (await first.boundingBox()).y;
  assert(top < 220, `After reading, next article starts at ${top}px`);
  assert((await first.locator('.fm-why').textContent()).includes('关注范围之外'));
  assert(!(await first.locator('.fm-signal-badge').textContent()).includes('优先推荐'));
  await page.screenshot({path:path.join(out, `${width}-for-you-continuation.png`)});
  const id = await first.getAttribute('data-event-id');
  await first.locator('[data-action="read"]').click();
  assert.equal(await page.locator(`#fmDiscoveryList [data-event-id="${id}"]`).count(),0);
  const second = await first.getAttribute('data-event-id');
  await first.locator('[data-action="dismiss"]').click();
  assert.equal(await page.locator(`#fmDiscoveryList [data-event-id="${second}"]`).count(),0);
  await page.locator('#fmNotice button').click();
  assert.equal(await page.locator(`#fmDiscoveryList [data-event-id="${second}"]`).count(),1);
  const saved = await page.evaluate(()=>JSON.parse(localStorage.getItem('dh_for_me_v1')));
  assert.deepEqual(saved.vendors,['Cube']);
  for (const readId of readIds) assert(saved.read[readId], 'Original reading history retained');
  assert(saved.read[id]);

  // Small deterministic response tests reference-only and genuinely exhausted states.
  // It stays inside this disposable browser; production data is never changed.
  const reference = {promotion_suppressed:false,body_review_required:false,zh_title:'Synthetic durable reference',zh_summary:'Local browser reference-only fixture',reason:'Reference-only discovery acceptance',event_id:'aaaaaaaaaaaa',vendors:['Cube'],topics:[],published:'2020-01-01T00:00:00Z',first_seen:'2020-01-01T00:00:00Z',shelf:'reference',focus:{practical:true}};
  await page.route('**/data/latest-lite-columns.json*', route => route.fulfill({contentType:'application/json',body:JSON.stringify({events:[reference],products:[]})}));
  await setState({vendors:['Cube']});
  assert(await page.locator('#fmWork').isVisible());
  assert(!(await page.locator('#fmEmpty').isVisible()));
  assert((await page.locator('#fmWork .fm-signal').first().boundingBox()).y < 220);
  await page.locator('#fmWork [data-action="read"]').click();
  assert(await page.locator('#fmEmpty').isVisible(), 'Show honest empty state when nothing remains');
  assert.equal(await page.locator('.fm-signal:visible').count(),0);
  await page.unroute('**/data/latest-lite-columns.json*');
  await setState({vendors:['No matching vendor in this index']});
  assert.equal(await page.locator('#fmDiscoveryTitle').textContent(),'继续发现');
  assert(!(await page.locator('#fmDiscovery .fm-section-head p').textContent()).includes('已读完'), 'No match must not imply reading completion');
  assert.deepEqual(errors,[]);
  await page.close();
  return {readIds:readIds.length,firstArticleTop:top,historyPreserved:true,readDismissUndo:true,referenceAndEmptyStates:true};
};
