/* Run against a built local site served with HTTP caching, gzip, and audio Range support.
 * NODE_PATH=<playwright installation> node tests/loading-performance.browser.cjs
 * DATAHOT_TEST_BASE defaults to http://127.0.0.1:7204/; production is rejected.
 */
const assert = require('node:assert/strict');
const {chromium} = require('playwright');
const base = process.env.DATAHOT_TEST_BASE || 'http://127.0.0.1:7204/';
assert(['127.0.0.1', 'localhost'].includes(new URL(base).hostname));
(async () => {
  const browser = await chromium.launch({headless:true, executablePath:process.env.CHROME_PATH || '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'});
  try {
    const context = await browser.newContext({viewport:{width:390,height:844}});
    const page = await context.newPage(), requests = [], errors = [];
    page.on('request', r => requests.push(r.url()));
    page.on('pageerror', e => errors.push(e.message));
    const openHome = async () => {
      await page.goto(base);
      await page.waitForFunction(() => performance.getEntriesByType('resource').some(r => r.name.includes('latest-lite.json')));
      return page.evaluate(() => performance.getEntriesByType('resource').find(r => r.name.includes('latest-lite.json')).toJSON());
    };
    const first = await openHome();
    assert.match(first.name, /latest-lite\.json\?v=[a-f0-9]{12}$/);
    assert(first.transferSize > 0, 'cold data must be fetched');
    await page.locator('#loadMore').click();
    await page.waitForFunction(() => document.querySelectorAll('#timeline .item').length === 40);
    await page.locator('#q').fill('ClickHouse');
    await page.waitForFunction(() => location.search.includes('ClickHouse') && document.querySelectorAll('#timeline .item').length > 0);
    assert((await page.locator('#timeline').innerText()).includes('ClickHouse'));
    await page.goto(base + 'e/4e1f47dc01ac.html');
    const second = await openHome();
    assert.equal(second.name, first.name);
    assert.equal(second.transferSize, 0, 'same data version must come from browser cache');
    const changedVersionTransfer = await page.evaluate(async url => {
      const next = url.replace(/v=[a-f0-9]+$/, 'v=000000000000');
      await (await fetch(next)).text();
      return performance.getEntriesByName(next).at(-1).transferSize;
    }, first.name);
    assert(changedVersionTransfer > 0, 'different data version must fetch independently');
    requests.length = 0;
    await page.goto(base + 'e/4e1f47dc01ac.html', {waitUntil:'networkidle'});
    assert.equal(requests.filter(u => u.endsWith('.mp3')).length, 0, 'no audio before playback');
    await page.locator('[data-tts-open]').click();
    await page.waitForFunction(() => {const a=document.querySelector('audio');return !a.paused && a.currentTime > 0;});
    assert(requests.some(u => u.endsWith('.mp3')), 'playback must load audio');
    await page.locator('[data-tts-toggle]').click();
    assert(await page.locator('audio').evaluate(a => a.paused));
    await page.waitForFunction(() => Number.isFinite(document.querySelector('audio').duration));
    await page.locator('[data-tts-progress]').evaluate(e => {e.value='10';e.dispatchEvent(new Event('input'));});
    await page.waitForFunction(() => document.querySelector('audio').currentTime >= 9);
    await page.goto(base + 'cases.html', {waitUntil:'networkidle'});
    const images = page.locator('.case-card-media img');
    assert.equal(await images.count(), 21);
    assert.equal(await images.first().getAttribute('loading'), 'eager');
    assert.equal(await images.first().getAttribute('fetchpriority'), 'high');
    for (const width of [390,1440]) {
      await page.setViewportSize({width,height:900});
      assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1));
      const image = images.first();
      await image.evaluate(i => i.decode());
      assert((await image.evaluate(i => i.currentSrc)).includes('/derived-media/'));
    }
    assert.deepEqual(errors, []);
    console.log(JSON.stringify({status:'PASS',coldDataBytes:first.transferSize,warmDataBytes:second.transferSize,changedVersionTransfer,
      checks:['20/40 item pagination','search','versioned data cache','audio on-demand/play/pause/seek','21 responsive cases','mobile/desktop overflow','no page errors']},null,2));
  } finally {await browser.close();}
})().catch(e => {console.error(e);process.exitCode=1;});
