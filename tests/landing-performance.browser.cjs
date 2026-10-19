'use strict';
// Compare complete builds of the SAME data, not live pages from different dates.
// npm ci --prefix ops/cloud-acceptance --ignore-scripts
// DATAHOT_BEFORE_SITE=/path/to/before/site DATAHOT_AFTER_SITE=/path/to/after/site \
//   node tests/landing-performance.browser.cjs
// Optional: CHROME_PATH, DATAHOT_PERF_OUT. No mainland-network claim is implied.
const {chromium} = require('../ops/cloud-acceptance/node_modules/playwright');
const fs = require('node:fs');
const http = require('node:http');
const path = require('node:path');
const zlib = require('node:zlib');
const assert = require('node:assert/strict');
const roots = {before:process.env.DATAHOT_BEFORE_SITE, after:process.env.DATAHOT_AFTER_SITE};
assert(roots.before && roots.after, 'Set DATAHOT_BEFORE_SITE and DATAHOT_AFTER_SITE');
assert.deepEqual(fs.readFileSync(path.join(roots.before,'data/latest-lite.json')),
  fs.readFileSync(path.join(roots.after,'data/latest-lite.json')), 'Use identical content');

(async () => {
  const server = http.createServer((req,res) => {
    const [,variant,...rest] = new URL(req.url,'http://localhost').pathname.split('/');
    if (!roots[variant]) {res.writeHead(404);return res.end();}
    const root = path.resolve(roots[variant]);
    const file = path.resolve(root,rest.join('/') || 'index.html');
    if (!file.startsWith(root+path.sep)) {res.writeHead(403);return res.end();}
    try {
      const bytes = fs.readFileSync(file);
      const mime = {'.html':'text/html; charset=utf-8','.js':'text/javascript',
        '.json':'application/json','.css':'text/css'};
      res.writeHead(200, {'Content-Type':mime[path.extname(file)] || 'application/octet-stream',
        'Content-Encoding':'gzip','Cache-Control':'max-age=600'});
      res.end(zlib.gzipSync(bytes));
    } catch {res.writeHead(404);res.end();}
  });
  await new Promise(resolve => server.listen(0,'127.0.0.1',resolve));
  const browser = await chromium.launch({headless:true,
    ...(process.env.CHROME_PATH ? {executablePath:process.env.CHROME_PATH} : {})});
  const rows = [];
  try {
    for (const variant of ['before','after']) {
      for (const scenario of ['home','for-me','default-home']) {
        for (let run=0;run<3;run++) {
          const context = await browser.newContext({viewport:{width:390,height:844},
            extraHTTPHeaders:{DNT:'1'}});
          await context.addInitScript(({scenario}) => {
            localStorage.setItem('dh_analytics_optout_v1','1');
            if (scenario==='default-home') localStorage.setItem('dh_default_home_v1','for-you');
            if (scenario!=='home') localStorage.setItem('dh_reading_v1',JSON.stringify({
              enabled:true,entries:{'64843a2454f2':[Date.now()],'7175222a4aa1':[Date.now()]}}));
            window.__p = {lcp:0,long:[],ready:0};
            new PerformanceObserver(list => list.getEntries().forEach(e => window.__p.lcp=e.startTime))
              .observe({type:'largest-contentful-paint',buffered:true});
            new PerformanceObserver(list => list.getEntries().forEach(e => window.__p.long.push(e.duration)))
              .observe({type:'longtask',buffered:true});
            new MutationObserver(() => {
              if (document.querySelector('#fmMustList .fm-signal') && !window.__p.ready)
                window.__p.ready=performance.now();
            }).observe(document,{subtree:true,childList:true});
          },{scenario});
          const page = await context.newPage();
          const cdp = await context.newCDPSession(page);
          await cdp.send('Network.enable');
          await cdp.send('Network.emulateNetworkConditions',{offline:false,latency:150,
            downloadThroughput:200000,uploadThroughput:100000,connectionType:'cellular4g'});
          await cdp.send('Emulation.setCPUThrottlingRate',{rate:4});
          await cdp.send('Performance.enable');
          const base = `http://127.0.0.1:${server.address().port}/${variant}/`;
          const started = Date.now();
          await page.goto(base+(scenario==='for-me'?'for-me.html':''));
          if (scenario!=='home') {
            await page.waitForURL('**/for-me.html');
            await page.locator('#fmMustList .fm-signal').first().waitFor();
          }
          const elapsed = Date.now()-started;
          await page.waitForTimeout(1800);
          const row = await page.evaluate(() => ({url:location.pathname,
            nav:performance.getEntriesByType('navigation')[0].toJSON(),
            paint:performance.getEntriesByType('paint').map(e=>({name:e.name,start:e.startTime})),
            ...window.__p,
            resources:performance.getEntriesByType('resource').map(e=>({
              name:new URL(e.name).pathname,start:e.startTime,duration:e.duration,
              bytes:e.transferSize,decoded:e.decodedBodySize})),
            ids:Array.from(document.querySelectorAll('#fmContent .fm-signal')).map(e=>e.dataset.eventId)}));
          Object.assign(row,{variant,scenario,elapsed});
          row.metrics=(await cdp.send('Performance.getMetrics')).metrics.filter(m=>
            ['ScriptDuration','LayoutDuration','RecalcStyleDuration','TaskDuration'].includes(m.name));
          rows.push(row);
          console.log(variant,scenario,run,'elapsed',elapsed,'ready',Math.round(row.ready),
            'LCP',row.lcp,'long',row.long);
          await context.close();
        }
      }
    }
    for (const scenario of ['for-me','default-home']) {
      const expected=rows.find(r=>r.variant==='before'&&r.scenario===scenario).ids;
      for (const row of rows.filter(r=>r.scenario===scenario)) assert.deepEqual(row.ids,expected);
    }
    // Landing decisions cannot depend on the old deferred home.js succeeding.
    const checks = await browser.newContext();
    await checks.addInitScript(() => localStorage.setItem('dh_default_home_v1','for-you'));
    await checks.route('**/home.js?*', route => route.abort());
    const page = await checks.newPage();
    const base = `http://127.0.0.1:${server.address().port}/after/`;
    await page.goto(base);
    await page.waitForURL('**/for-me.html');
    await page.locator('#fmMustList .fm-signal').first().waitFor();
    for (const suffix of ['index.html','?q=Snowflake','#timeline']) {
      await page.goto(base+suffix);
      assert(!page.url().includes('for-me.html'), 'Explicit feed links must stay on the feed');
      await page.locator('#timeline .item').first().waitFor();
    }
    await checks.close();
    const blocked = await browser.newContext();
    await blocked.addInitScript(() => Object.defineProperty(window,'localStorage',{
      get() {throw new Error('Storage blocked');}}));
    const blockedPage = await blocked.newPage();
    await blockedPage.goto(base);
    await blockedPage.locator('#timeline .item').first().waitFor();
    assert(!blockedPage.url().includes('for-me.html'));
    await blocked.close();
    fs.writeFileSync(process.env.DATAHOT_PERF_OUT || 'controlled-comparison.json',JSON.stringify(rows,null,2));
  } finally {await browser.close();server.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
