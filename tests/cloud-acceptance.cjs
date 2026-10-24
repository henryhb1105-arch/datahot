'use strict';

// Runs in a disposable Linux browser. Local mode starts its own static server.
// Production mode requires the exact released source SHA and never sends analytics.
const assert = require('node:assert/strict');
const fs = require('node:fs/promises');
const path = require('node:path');
const http = require('node:http');
const crypto = require('node:crypto');
const {chromium} = require('../ops/cloud-acceptance/node_modules/playwright');
const root = path.resolve(__dirname, '..');
const site = path.join(root, 'site');
const out = path.resolve(process.env.DATAHOT_ARTIFACT_DIR || path.join(root, 'artifacts/cloud-acceptance'));
const production = process.env.DATAHOT_TEST_BASE === 'https://datahot.xiahongbin.com/';
assert(!process.env.DATAHOT_TEST_BASE || production, 'Only the fixed production origin or local mode is allowed');
if (production) assert.match(process.env.DATAHOT_EXPECTED_SHA || '', /^[a-f0-9]{40}$/, 'Production requires DATAHOT_EXPECTED_SHA');
const readiness = require('./browser-readiness.cjs');
const summary = {started_at: new Date().toISOString(), production, checks: [], viewports: []};
let server, browser;

async function localServer() {
  server = http.createServer(async (req, res) => {
    try {
      const pathname = decodeURIComponent(new URL(req.url, 'http://localhost').pathname);
      const file = path.resolve(site, '.' + (pathname === '/' ? '/index.html' : pathname));
      if (!file.startsWith(site + path.sep)) { res.writeHead(403); return res.end(); }
      const bytes = await fs.readFile(file);
      const mime = {'.html':'text/html; charset=utf-8','.js':'text/javascript','.json':'application/json','.css':'text/css','.svg':'image/svg+xml','.png':'image/png','.webp':'image/webp','.jpg':'image/jpeg'};
      res.writeHead(200, {'Content-Type':mime[path.extname(file)] || 'application/octet-stream'});
      res.end(bytes);
    } catch { res.writeHead(404); res.end('Not found'); }
  });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  return `http://127.0.0.1:${server.address().port}/`;
}

async function main() {
  await fs.mkdir(out, {recursive:true});
  const base = production ? process.env.DATAHOT_TEST_BASE : await localServer();
  const proxy = production && (process.env.HTTPS_PROXY || process.env.HTTP_PROXY);
  browser = await chromium.launch({headless:true,
    ...(process.env.CHROME_PATH ? {executablePath:process.env.CHROME_PATH} : {}),
    ...(proxy ? {proxy:{server:proxy}} : {})});
  summary.browser = browser.version();
  summary.base = base;
  const dataContext = await browser.newContext({extraHTTPHeaders:{DNT:'1'}});
  async function get(relative) {
    const response = await dataContext.request.get(new URL(relative, base).href);
    assert(response.ok(), `${relative}: HTTP ${response.status()}`);
    return response;
  }
  let release;
  if (production) {
    release = await (await get('data/release.json')).json();
    assert.equal(release.source_sha, process.env.DATAHOT_EXPECTED_SHA, 'Wrong live source version');
    summary.release = release;
  }
  const latest = await (await get('data/latest.json')).json();
  const ids = latest.events.map(e => e.event_id);
  assert(ids.length > 0);
  assert.equal(new Set(ids).size, ids.length, 'Duplicate event IDs');
  if (release) {
    assert.equal(ids.length, release.event_count, 'Manifest/data count mismatch');
    assert.equal(ids.length, release.detail_count, 'Manifest/detail count mismatch');
  }
  // Check every indexed detail, not a historical hardcoded count.
  const pending = [...ids];
  await Promise.all(Array.from({length:6}, async () => {
    while (pending.length) {
      const id = pending.pop();
      assert.match(id, /^[A-Za-z0-9_-]{1,64}$/);
      if (production) {
        const detail = await get(`e/${id}.html`);
        assert.match(await detail.text(), /<html[\s>]/i, `Invalid detail ${id}`);
      } else {
        assert.match(await fs.readFile(path.join(site, 'e', id + '.html'), 'utf8'), /<html[\s>]/i);
      }
    }
  }));
  summary.event_count = ids.length;
  summary.checks.push('all indexed details exist', 'unique events', 'manifest version/counts where applicable');
  await dataContext.close();
  if (!production) {
    const fixture=await browser.newContext();
    await fixture.route('**/*', route => new URL(route.request().url()).origin === new URL(base).origin ? route.continue() : route.abort());
    try { summary.readiness=await require('./browser-readiness-browser.cjs')(fixture,base); } finally { await fixture.close(); }
  }

  for (const width of [390, 1440]) {
    const context = await browser.newContext({viewport:{width,height:900}, extraHTTPHeaders:{DNT:'1'}, reducedMotion:'reduce'});
    context.on('page', readiness.watchPage);
    await context.addInitScript(() => {
      localStorage.setItem('dh_analytics_optout_v1', '1');
      Object.defineProperty(navigator, 'doNotTrack', {get:() => '1'});
      Object.defineProperty(navigator, 'globalPrivacyControl', {get:() => true});
    });
    const errors = [], broken = [], analyticsAttempts = [];
    await context.route('**/*', route => {
      const request = route.request(), url = new URL(request.url());
      if (/metrics\.datahot\.|\/api\/events|\/collect(?:\?|$)/.test(url.href)) {
        analyticsAttempts.push(url.origin + url.pathname);
        return route.abort();
      }
      if (url.origin !== new URL(base).origin) return route.abort();
      return route.continue();
    });
    const page = await context.newPage();
    page.on('pageerror', e => errors.push(e.message));
    page.on('response', response => {
      if (response.url().startsWith(base) && response.status() >= 400) broken.push(`${response.status()} ${response.url()}`);
    });
    const noOverflow = async () => {
      const overflow = await page.evaluate(() => ({width:innerWidth, scrollWidth:document.documentElement.scrollWidth,
        offenders:[...document.querySelectorAll('body *')].filter(el => {
          const r=el.getBoundingClientRect(); return r.width && (r.right > innerWidth + 1 || r.left < -1);
        }).slice(0,12).map(el => ({tag:el.tagName,class:el.className,width:el.getBoundingClientRect().width}))}));
      if (overflow.scrollWidth > width + 1) {
        await page.screenshot({path:path.join(out, `${width}-overflow.png`)});
        throw new Error(`Overflow ${page.url()}: ${JSON.stringify(overflow)}`);
      }
    };
    let screenshotCount = 0;
    const shot = async name => { await page.screenshot({path:path.join(out, `${width}-${name}.png`)}); screenshotCount++; };
    await page.goto(base, {waitUntil:'networkidle'});
    await page.locator('#timeline .item').first().waitFor();
    await noOverflow();
    await shot('home');
    const homeScript = await page.locator('script[src*="home.js?"]').getAttribute('src');
    const liteUrl = await page.locator('#homeDataConfig').getAttribute('data-lite-url');
    for (const relative of [homeScript, liteUrl]) {
      const url = new URL(relative, base);
      assert.match(url.searchParams.get('v') || '', /^[a-f0-9]{12}$/);
      const response = await context.request.get(url.href);
      assert(response.ok());
      const digest = crypto.createHash('sha256').update(await response.body()).digest('hex').slice(0,12);
      assert.equal(digest, url.searchParams.get('v'), 'Versioned asset bytes do not match URL: ' + url.pathname);
    }
    const reason = page.locator('#timeline .item .why').first();
    await reason.scrollIntoViewIfNeeded();
    assert(await reason.isVisible(), 'Reason must be expanded by default');
    await shot('timeline');
    const input = page.locator('#q');
    async function search(query) {
      await input.fill(query);
      await page.waitForFunction(q => new URL(location.href).searchParams.get('q') === q, query);
      return Number(await page.locator('#rCount').innerText());
    }
    const forward = await search('Snowflake Cortex');
    const reversed = await search('Cortex Snowflake');
    const normalized = await search('Ｓｎｏｗｆｌａｋｅ　Ｃｏｒｔｅｘ');
    assert(forward > 0, 'Known multiword search must return results');
    assert.equal(reversed, forward, 'Word-order regression');
    assert.equal(normalized, forward, 'NFKC regression');
    await shot('search');
    assert.equal(await search('no-such-datahot-cloud-acceptance-result'), 0);
    await page.locator('[data-filter-clear]').click();
    await page.waitForFunction(() => !new URL(location.href).searchParams.has('q') && document.querySelectorAll('#timeline .item').length > 0);
    assert.equal(await input.inputValue(), '');
    const detailLink = page.locator('#timeline .item h3 a').first();
    const detailHref = await detailLink.getAttribute('href');
    await detailLink.click();
    await page.waitForURL(new URL(detailHref, base).href);
    await noOverflow();
    await shot('detail');
    const longIdentifier = page.locator('.fulltext p').filter({hasText:'SNOWFLAKE.ACCOUNT_USAGE.DATA_MOVEMENT_VIOLATIONS'});
    if (await longIdentifier.count()) {
      await longIdentifier.first().scrollIntoViewIfNeeded();
      assert(await longIdentifier.first().evaluate(el => el.scrollWidth <= el.clientWidth + 1), 'Long identifier is clipped');
      await shot('long-identifier');
    }
    await page.goto(base, {waitUntil:'networkidle'});
    const nav = page.locator('a[href="for-me.html"]:visible').first();
    await nav.click();
    await page.waitForURL('**/for-me.html');
    await page.locator('#fmCustomize').click();
    if (await page.locator('#fmNext').isVisible()) await page.locator('#fmNext').click();
    const follow = page.locator('.fm-follow-chip:visible').first();
    await follow.waitFor();
    const followKind = await follow.getAttribute('data-kind'), followValue = await follow.getAttribute('data-value');
    await follow.click();
    await noOverflow();
    await shot('following');
    await page.reload({waitUntil:'networkidle'});
    const stored = await page.evaluate(() => JSON.parse(localStorage.getItem('dh_for_me_v1')));
    assert(stored[{topic:'topics',vendor:'vendors',product:'products'}[followKind]].includes(followValue), 'Follow was not persisted');
    assert.deepEqual(errors, [], 'Browser exceptions');
    assert.deepEqual(broken, [], 'Broken same-origin resources');
    assert.deepEqual(analyticsAttempts, [], 'Acceptance attempted analytics despite opt-out');
    summary.viewports.push({width,search_results:forward,follow:{kind:followKind,value:followValue},screenshots:screenshotCount,errors,broken,analyticsAttempts});
    // Simulate a transient network outage in a fresh page before idle prefetch.
    const recovery = await context.newPage();
    let offline = true;
    await recovery.route('**/data/latest-lite.json*', route => offline ? route.abort() : route.continue());
    await recovery.goto(base, {waitUntil:'networkidle'});
    const existingIds = await recovery.locator('#timeline .item').evaluateAll(nodes => nodes.map(n => n.dataset.eventId));
    const loadMore = recovery.locator('#loadMore');
    await loadMore.click();
    await recovery.waitForFunction(() => document.querySelector('#loadMore').textContent.includes('点击重试'));
    assert.equal(await loadMore.isEnabled(), true, 'Network failure must offer usable retry');
    assert.deepEqual(await recovery.locator('#timeline .item').evaluateAll(nodes => nodes.map(n => n.dataset.eventId)), existingIds);
    await recovery.screenshot({path:path.join(out, `${width}-load-retry.png`)});
    offline = false;
    await loadMore.click();
    await recovery.waitForFunction(() => new URL(location.href).searchParams.get('page') === '2');
    assert.equal(await recovery.locator('#timeline .item').count(), existingIds.length * 2, 'Retry must not skip ahead to page 3');
    await recovery.screenshot({path:path.join(out, `${width}-load-recovered.png`)});
    summary.viewports[summary.viewports.length - 1].loadMoreRecovery = 'PASS: retained cards and retried page 2';
    // A malformed packed response must expose the existing retry, not empty recommendations.
    let corrupt = true;
    await recovery.route('**/data/latest-lite-columns.json*', route => corrupt
      ? route.fulfill({contentType:'application/json', body:JSON.stringify({transport:'datahot-columns-v1',count:-1})})
      : route.continue());
    await recovery.goto(base + 'for-me.html');
    await recovery.locator('#fmError').waitFor();
    corrupt = false;
    await recovery.locator('#fmError button').click();
    await recovery.locator('#fmMustList .fm-signal').first().waitFor();
    summary.viewports[summary.viewports.length - 1].columnarRecovery = 'PASS: invalid transport shows error; reload recovers';
    await recovery.close();
    await require('./for-you-browser.cjs')(context, base, out, width);
    summary.viewports[summary.viewports.length - 1].forYou = 'PASS: setup/skip, task relevance, read, dismiss/undo, default/escape, persistence, asset hash';
    summary.viewports[summary.viewports.length - 1].screenshots += 4;
    // Actual qualified reading plus a local counterfactual verifies content intent, not just labels.
    summary.viewports[summary.viewports.length - 1].reading = await require("./reading-browser.cjs")(context,base,out,width);
    summary.viewports[summary.viewports.length - 1].screenshots += 2;
    summary.viewports[summary.viewports.length - 1].continuation = await require("./for-you-continuation-browser.cjs")(context,base,out,width);
    summary.viewports[summary.viewports.length - 1].screenshots += 1;
    await context.close();
  }
  if (production) {
    const verify = await browser.newContext();
    const after = await (await verify.request.get(base + 'data/release.json')).json();
    assert.equal(after.source_sha, release.source_sha, 'Release changed during acceptance; rerun against a stable release');
    await verify.close();
  }
  summary.checks.push('390px and 1440px interactions', 'asset content hashes', 'search order and normalization', 'empty-result recovery', 'expanded reasons', 'detail navigation', 'follow persistence', 'no horizontal overflow', 'analytics excluded');
  summary.status = 'PASS';
}

main().catch(async error => {summary.status='FAIL'; summary.error=error.stack; process.exitCode=1;
    if (browser) { try { summary.diagnostics=await readiness.diagnostics(browser); } catch { summary.diagnostics='unavailable'; } }
  })
  .finally(async () => {
    if (browser) await browser.close();
    if (server) await new Promise(resolve => server.close(resolve));
    summary.finished_at = new Date().toISOString();
    await fs.mkdir(out, {recursive:true});
    await fs.writeFile(path.join(out, 'summary.json'), JSON.stringify(summary,null,2));
    console.log(JSON.stringify(summary,null,2));
  });
