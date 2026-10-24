'use strict';
const assert=require('node:assert/strict');
const {waitForFeed,watchPage}=require('./browser-readiness.cjs');
module.exports=async function(context,base) {
  const page=await context.newPage();watchPage(page);
  try {
    await page.addInitScript(()=>{
      localStorage.setItem('dh_analytics_optout_v1','1');
      const json=Response.prototype.json;
      Response.prototype.json=async function(){
        const value=await json.call(this);
        if(this.url.includes('latest-lite')) await new Promise(resolve=>{window.__releaseTestData=resolve;});
        return value;
      };
    });
    await page.goto(base+'for-me.html',{waitUntil:'networkidle'});
    await page.waitForFunction(()=>typeof window.__releaseTestData==='function');
    assert(!(await page.locator('#fmMustList .fm-signal').first().isVisible()),'Old immediate assertion fails while parsing is pending');
    const ready=waitForFeed(page);
    await page.evaluate(()=>window.__releaseTestData());
    await ready;
    assert(await page.locator('#fmMustList .fm-signal').first().isVisible(),'Original card requirement still enforced');
    await page.setContent('<div id="fmLoading">Loading</div><div id="fmContent" hidden></div><div id="fmError" hidden></div>');
    await assert.rejects(waitForFeed(page,200),/Timeout/,'Permanent loading must still fail');
    await page.setContent('<div id="fmContent" hidden></div><div id="fmError">Failed</div>');
    await assert.rejects(waitForFeed(page),/data failed to load/,'Data errors must still fail');
    return {networkIdleBeforeRender:true,waitsForContent:true,permanentLoadingRejected:true,dataErrorRejected:true};
  } finally {await page.close();}
};
