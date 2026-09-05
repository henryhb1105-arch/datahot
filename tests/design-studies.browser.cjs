/* Local-only acceptance. Start site/serve.js and an agent-browser session, then:
 * NODE_PATH=<installed playwright runtime> node tests/design-studies.browser.cjs <cdp-url>
 * This script rejects production URLs and blocks every non-local request.
 */
const { chromium } = require('playwright');
const assert = require('node:assert/strict');
const manifest = require('../pipeline/design_studies.json');

(async () => {
  const cdp = process.argv[2];
  assert.match(cdp || '', /^ws:\/\/127\.0\.0\.1:\d+\//);
  const browser = await chromium.connectOverCDP(cdp);
  const context = browser.contexts()[0];
  const base = 'http://127.0.0.1:7204/';
  const page = context.pages().find(p => p.url().startsWith(base));
  assert(page, 'Open the local preview in agent-browser first');
  assert.equal(new URL(page.url()).origin, new URL(base).origin);
  const errors = [], external = [], broken = [];
  page.on('pageerror', e => errors.push(e.message));
  page.on('response', r => { if (r.status() >= 400) broken.push(r.url() + ' ' + r.status()); });
  await page.route('**/*', route => {
    const url = route.request().url();
    if (new URL(url).origin === new URL(base).origin) return route.continue();
    external.push(url);
    return route.abort();
  });
  const open = path => page.goto(base + path, {waitUntil:'networkidle'});
  const noOverflow = async () => assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), page.url() + ' overflow');
  const imageReady = async locator => {
    await locator.scrollIntoViewIfNeeded();
    await locator.evaluate(img => img.decode());
    assert(await locator.evaluate(img => img.naturalWidth > 0));
  };

  await page.setViewportSize({width:390, height:844});
  await open('cases.html');
  assert.equal(await page.locator('.case-card').count(), 21);
  await noOverflow();
  const cardImage = page.locator('.case-card [data-case-image]').first();
  await imageReady(cardImage.locator('img'));
  await cardImage.click();
  const dialog = page.locator('[data-image-dialog]');
  assert(await dialog.evaluate(d => d.open));
  await dialog.locator('[data-image-next]').click();
  assert.match(await dialog.locator('[data-image-count]').innerText(), /^2 \/ 21$/);
  await dialog.locator('[data-image-zoom]').click();
  assert.equal(await dialog.locator('[data-image-zoom]').getAttribute('aria-pressed'), 'true');
  await page.keyboard.press('Escape');
  assert(!await dialog.evaluate(d => d.open));
  assert(await cardImage.evaluate(el => document.activeElement === el));
  await open('cases.html?question=' + encodeURIComponent('结果表达'));
  assert(await page.locator('.case-card:visible').count() < 21);
  assert(await page.locator('.case-card:visible').count() >= 3);

  for (const study of manifest.studies) {
    await open('cases/' + study.slug + '.html');
    await noOverflow();
    assert.equal(await page.locator('.study-header').evaluate(el => getComputedStyle(el).position), 'static');
    assert.equal(await page.locator('[data-study-step]:visible').count(), 1);
    for (let i = 1; i <= study.steps.length; i++) {
      await page.locator('[data-step-select="' + i + '"]').click();
      assert.equal(await page.locator('[data-study-step]:visible').getAttribute('id'), 'step-' + i);
      assert.equal(new URL(page.url()).hash, '#step-' + i);
      const img = page.locator('#step-' + i + ' img');
      await imageReady(img);
      await noOverflow();
    }
    assert(await page.locator('[data-step-next]').isDisabled());
    await page.locator('[data-step-prev]').click();
    assert.equal(await page.locator('[data-study-step]:visible').getAttribute('id'), 'step-' + (study.steps.length - 1));
    await open('cases/' + study.slug + '.html#step-2');
    assert.equal(await page.locator('[data-study-step]:visible').getAttribute('id'), 'step-2');
    await page.locator('#step-2 [data-case-image]').click();
    assert.equal(await dialog.locator('[data-image-count]').innerText(), '2 / ' + study.steps.length);
    await page.keyboard.press('ArrowRight');
    assert.equal(await dialog.locator('[data-image-count]').innerText(), '3 / ' + study.steps.length);
    await dialog.locator('[data-image-close]').click();
  }

  await open('cases/metabase-metabot.html');
  if (await page.locator('.study-save').getAttribute('aria-pressed') !== 'true') await page.locator('.study-save').click();
  await open('favorites.html');
  const saved = page.locator('a[href="cases/metabase-metabot.html"]').first();
  assert(await saved.isVisible());
  await saved.click();
  assert.match(page.url(), /cases\/metabase-metabot\.html$/);
  await page.locator('.study-save').click(); // Restore local QA favorite state.
  await page.locator('[data-feedback-kind="design"] button').first().click();
  assert.match(await page.locator('[data-feedback-kind="design"]').innerText(), /已记录在当前设备/);

  await open('cases/compare.html');
  await noOverflow();
  assert.equal(await page.locator('.study-comparison table tbody tr').count(), 4);
  const table = page.locator('.study-comparison-scroll');
  assert(await table.evaluate(el => el.scrollWidth > el.clientWidth));
  await table.evaluate(el => { el.scrollLeft = el.scrollWidth; });
  await noOverflow();
  await page.screenshot({path:'/tmp/datahot-compare-mobile.png'});

  await page.setViewportSize({width:1440,height:1000});
  await open('cases.html');
  await noOverflow();
  await page.screenshot({path:'/tmp/datahot-cases-desktop.png'});
  await open('cases/metabase-metabot.html#step-3');
  await imageReady(page.locator('#step-3 img'));
  await noOverflow();
  await page.screenshot({path:'/tmp/datahot-study-desktop.png'});
  await page.emulateMedia({colorScheme:'dark'});
  await page.screenshot({path:'/tmp/datahot-study-dark.png'});
  await page.locator('#step-3 [data-case-image]').click();
  await imageReady(dialog.locator('img'));
  await page.screenshot({path:'/tmp/datahot-image-desktop.png'});
  await page.keyboard.press('Escape');

  // No-JS reading: all evidence remains in HTML and image links still work.
  await page.route('**/*.js', route => route.abort());
  await open('cases/hex-threads.html');
  assert.equal(await page.locator('[data-study-step]:visible').count(), 4);
  assert(!await page.locator('[data-step-nav]').isVisible());
  assert.match(await page.locator('[data-case-image]').first().getAttribute('href'), /^\.\.\/case-media\//);
  assert.deepEqual(errors, []);
  assert.deepEqual(broken, []);
  assert.deepEqual(external, []);
  console.log('PASS: 21 cards, six studies / 23 images, filters, step links, zoom, keyboard/focus, favorite round-trip, feedback, mobile comparison, desktop/dark and no-JS. Zero external requests.');
  await page.unrouteAll({behavior:'wait'});
  await page.emulateMedia({colorScheme:'light'});
  await browser.close();
})().catch(error => { console.error(error); process.exit(1); });
