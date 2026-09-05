/* Local-only acceptance. Start site/serve.js and an agent-browser session, then:
 * NODE_PATH=<installed playwright runtime> node tests/design-studies.browser.cjs <cdp-url>
 * This script rejects production URLs and blocks every non-local request.
 */
const { chromium } = require('playwright');
const assert = require('node:assert/strict');
const manifest = require('../pipeline/design_studies.json');
const cases = require('../pipeline/product_cases.json').cases;

(async () => {
  const cdp = process.argv[2];
  assert.match(cdp || '', /^ws:\/\/127\.0\.0\.1:\d+\//);
  const browser = await chromium.connectOverCDP(cdp);
  const context = browser.contexts()[0];
  const base = 'http://127.0.0.1:7204/';
  const page = context.pages().find(p => p.url().startsWith(base));
  assert(page, 'Open the local preview in agent-browser first');
  assert.equal(new URL(page.url()).origin, new URL(base).origin);
  const errors = [], external = [], broken = [], unversioned = [];
  page.on('request', request => {
    const url = new URL(request.url());
    if (/\/(?:cases|design-studies)\.js$/.test(url.pathname) && !/^\?v=[a-f0-9]{12}$/.test(url.search)) unversioned.push(url.href);
  });
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
  assert((await page.locator('.case-card-media').first().boundingBox()).y < 280, 'first preview should be in the first screen');
  await page.screenshot({path:'/tmp/datahot-cases-mobile.png'});
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
  await page.locator('.cases-search').fill('no-such-case-204');
  assert.equal(await page.locator('.case-card:visible').count(), 0);
  await page.locator('.cases-reset').click();
  assert.equal(await page.locator('.case-card:visible').count(), 21);

  const upgraded = new Set(manifest.studies.map(s => s.event_id));
  const references = cases.filter(c => !upgraded.has(c.event_id));
  assert.equal(references.length, 15);
  for (const reference of references) {
    await open('cases/case-' + reference.event_id + '.html');
    await noOverflow();
    assert((await page.locator('.study-image').first().boundingBox()).y < 600, reference.product + ' first-screen image');
    await imageReady(page.locator('[data-study-step]:visible img'));
    assert.equal(await page.locator('[data-study-step]:visible').count(), 1);
    assert(await page.locator('a[href="../e/' + reference.event_id + '.html"]').count());
    assert.match(await page.locator('[data-step-status]').innerText(), /^配图 1 \/ /);
    const count = await page.locator('[data-study-step]').count();
    if (count > 1) {
      await page.locator('[data-step-next]').click();
      assert.equal(await page.locator('[data-study-step]:visible').getAttribute('id'), 'step-2');
      assert((await page.locator('#step-2').boundingBox()).y < 100, 'next figure brought into view');
    }
  }
  await open('cases/case-29e0b8236c7e.html');
  await page.screenshot({path:'/tmp/datahot-reference-mobile.png'});
  assert(await page.locator('.study-focus-region').first().isVisible());
  await page.locator('[data-study-step]:visible [data-case-image]').click();
  assert.equal(await dialog.locator('.study-focus-region').count(), 0, 'viewer preserves untouched image');
  await imageReady(dialog.locator('img'));
  await page.keyboard.press('Escape');
  await page.locator('.study-save').click();
  await open('favorites.html');
  await page.locator('a[href="cases/case-29e0b8236c7e.html"]').first().click();
  await page.locator('.study-save').click();

  await open('cases.html');
  for (let i = 0; i < 3; i++) await page.locator('[data-case-compare-toggle]').nth(i).click();
  await page.locator('[data-case-compare-open]').click();
  const compare = page.locator('[data-case-compare-dialog]');
  assert(await compare.evaluate(d => d.open));
  const dialogBox = await compare.boundingBox();
  assert(Math.abs(dialogBox.x * 2 + dialogBox.width - 390) < 2, 'dialog centered on phone');
  assert.equal(await compare.locator('tbody tr').count(), 5);
  assert.equal(await compare.locator('.case-compare-product:visible').count(), 15);
  assert(await compare.locator('.case-compare-scroll').evaluate(el => el.scrollWidth <= el.clientWidth + 1));
  await page.screenshot({path:'/tmp/datahot-custom-compare-mobile.png'});
  await compare.locator('[data-case-compare-close]').click();
  await page.locator('[data-case-compare-clear]').click();

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
  assert(await table.evaluate(el => el.scrollWidth <= el.clientWidth + 1));
  assert.equal(await table.locator('.study-comparison-product:visible').count(), 12);
  await noOverflow();
  await page.screenshot({path:'/tmp/datahot-compare-mobile.png'});
  for (const width of [320, 430, 700]) {
    await page.setViewportSize({width,height:844});
    for (const path of ['cases.html', 'cases/case-29e0b8236c7e.html', 'cases/compare.html']) {
      await open(path);
      await noOverflow();
    }
  }

  await page.setViewportSize({width:1440,height:1000});
  await open('cases.html');
  await noOverflow();
  await page.screenshot({path:'/tmp/datahot-cases-desktop.png'});
  await open('cases/compare.html');
  assert.equal(await page.locator('.study-comparison table').evaluate(el => getComputedStyle(el).display), 'table');
  assert.equal(await page.locator('.study-comparison-product:visible').count(), 0);
  await page.screenshot({path:'/tmp/datahot-compare-desktop.png'});
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
  await page.route(/\.js(?:\?|$)/, route => route.abort());
  await open('cases/hex-threads.html');
  assert.equal(await page.locator('[data-study-step]:visible').count(), 4);
  assert(!await page.locator('[data-step-nav]').isVisible());
  assert.match(await page.locator('[data-case-image]').first().getAttribute('href'), /^\.\.\/case-media\//);
  await open('cases/case-29e0b8236c7e.html');
  assert.equal(await page.locator('[data-study-step]:visible').count(), await page.locator('[data-study-step]').count());
  assert(!await page.locator('[data-step-nav]').isVisible());
  assert.deepEqual(errors, []);
  assert.deepEqual(broken, []);
  assert.deepEqual(external, []);
  assert.deepEqual(unversioned, [], 'case pages must request the matching script version');
  console.log('PASS: 21 cards, 15 reference readings, six studies / 23 images, first-screen previews, focal regions, filters, steps, zoom, focus, favorites, feedback, both mobile comparisons, 320/390/430/700/1440px, dark and no-JS. Zero external requests.');
  await page.unrouteAll({behavior:'wait'});
  await page.emulateMedia({colorScheme:'light'});
  await browser.close();
})().catch(error => { console.error(error); process.exit(1); });
