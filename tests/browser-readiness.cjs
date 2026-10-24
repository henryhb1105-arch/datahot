'use strict';
const assert = require('node:assert/strict');
const watchers = new WeakMap();
function watchPage(page) {
  if (watchers.has(page)) return;
  const pending = new Map(), failures = [];
  const pathname = request => { try { return new URL(request.url()).pathname; } catch { return '(invalid URL)'; } };
  page.on('request', request => pending.set(request, {path:pathname(request),started:Date.now()}));
  page.on('requestfinished', request => pending.delete(request));
  page.on('requestfailed', request => { pending.delete(request); failures.push({path:pathname(request),error:request.failure()?.errorText}); if (failures.length > 30) failures.shift(); });
  page.on('response', response => { if (response.status() >= 400) { failures.push({path:pathname(response.request()),status:response.status()}); if (failures.length > 30) failures.shift(); } });
  watchers.set(page, () => ({pending:[...pending.values()].slice(-30).map(r=>({path:r.path,ageMs:Date.now()-r.started})),failures:[...failures]}));
}
async function waitForFeed(page, timeout = 30000) {
  // DOMContentLoaded/network idle do not imply async JSON decoding and render are done.
  await page.waitForFunction(() => {
    const visible = id => { const el=document.getElementById(id); return el && !el.hidden && el.getClientRects().length > 0; };
    return visible('fmContent') || visible('fmError');
  }, null, {timeout});
  assert(!(await page.locator('#fmError').isVisible()), 'For-you data failed to load');
  assert(await page.locator('#fmContent').isVisible(), 'For-you content must be ready');
}
async function feedNavigation(page, navigate) {
  watchPage(page);
  const response = await navigate();
  if (response) assert(response.ok(), `Navigation failed: HTTP ${response.status()}`);
  await waitForFeed(page);
}
async function diagnostics(browser) {
  const result=[];
  for (const context of browser.contexts()) for (const page of context.pages()) {
    if (page.isClosed()) continue;
    const record={url:new URL(page.url()).pathname,...(watchers.get(page)?.() || {})};
    try { record.state=await page.evaluate(()=>({readyState:document.readyState,loading:!!document.querySelector('#fmLoading:not([hidden])'),content:!!document.querySelector('#fmContent:not([hidden])'),error:!!document.querySelector('#fmError:not([hidden])'),cards:document.querySelectorAll('.fm-signal').length})); } catch { record.state='unavailable'; }
    result.push(record);
  }
  return result;
}
module.exports={waitForFeed,feedNavigation,watchPage,diagnostics};
