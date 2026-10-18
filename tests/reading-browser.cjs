'use strict';
const assert=require('node:assert/strict'),path=require('node:path'),crypto=require('node:crypto');
module.exports=async function(context,base,out,width){
 const page=await context.newPage(),errors=[];
 page.on('pageerror',e=>errors.push(e.message));
 await page.goto(base+'for-me.html',{waitUntil:'networkidle'});
 await page.evaluate(()=>{
  for(const k of ['dh_reading_v1','dh_for_me_v1','dh_favs','dh_favs_v2','dh_content_feedback_v1','dh_default_home_v1'])localStorage.removeItem(k);
  localStorage.setItem('dh_for_me_v1',JSON.stringify({setupDone:true}));sessionStorage.clear();
 });
 const data=await (await context.request.get(base+'data/latest-lite.json')).json();
 const candidates=data.events.filter(e=>(e.topics||[]).includes('语义层'));
 assert(candidates.length>=3);
 const readIds=[];
 for(const e of candidates){
  await page.goto(base+'e/'+e.event_id+'.html',{waitUntil:'networkidle'});
  if(!(await page.locator('.fulltext').count()))continue;
  await page.bringToFront();
  const asset=new URL(await page.locator('script[src*="reading-profile.js?"]').getAttribute('src'),base+'e/'+e.event_id+'.html');
  const response=await context.request.get(asset.href);assert(response.ok());
  assert.equal(crypto.createHash('sha256').update(await response.body()).digest('hex').slice(0,12),asset.searchParams.get('v'));
  await page.locator('.fulltext').evaluate(el=>window.scrollTo(0,el.getBoundingClientRect().top+scrollY+el.getBoundingClientRect().height*.55-innerHeight*.7));
  // Real foreground dwell; no fake clock or production writes.
  await page.waitForFunction(id=>!!JSON.parse(localStorage.getItem('dh_reading_v1')||'{}').entries?.[id],e.event_id,{timeout:35000});
  readIds.push(e.event_id);if(readIds.length===2)break;
 }
 assert.equal(readIds.length,2);
 await page.goto(base+'for-me.html',{waitUntil:'networkidle'});
 assert(!(await page.locator('#fmSetup').isVisible()),'Learned preferences bypass mandatory setup');
 const reasons=await page.locator('#fmMustList .fm-why').allTextContents();
 assert(reasons.some(x=>x.includes('近期的阅读')),'Behavior should recommend without selected keywords');
 for(const id of readIds) assert.equal(await page.locator(`#fmMustList [data-event-id="${id}"]`).count(),0);
 await page.screenshot({path:path.join(out,`${width}-reading-recommendations.png`)});
 const reduce=page.locator('[data-action="reduce"]').first();await reduce.click();
 assert((await page.evaluate(()=>JSON.parse(localStorage.getItem('dh_reading_v1')).muted.length))>0);
 await page.locator('#fmNotice button').click();
 assert.equal(await page.evaluate(()=>JSON.parse(localStorage.getItem('dh_reading_v1')).muted.length),0);
 await page.locator('#reading-settings summary').click();
 await page.locator('#fmBehaviorEnabled').uncheck();
 assert.match(await page.locator('#fmBehaviorStatus').innerText(),/已暂停/);
 assert.equal(await page.locator('.fm-why').filter({hasText:'近期的阅读'}).count(),0);
 await page.locator('#fmClearReading').click();
 assert.equal(await page.evaluate(()=>Object.keys(JSON.parse(localStorage.getItem('dh_reading_v1')).entries).length),0);
 await page.reload({waitUntil:'networkidle'});
 await page.locator('#reading-settings summary').click();
 assert(!(await page.locator('#fmBehaviorEnabled').isChecked()),'Clear does not re-enable learning');
 await page.screenshot({path:path.join(out,`${width}-reading-paused.png`)});
 // Cross-tab pause is honored by the actual reader, even after sufficient dwell.
 const detail=await context.newPage();
 await detail.goto(base+'e/'+readIds[0]+'.html',{waitUntil:'networkidle'});await detail.bringToFront();
 await detail.locator('.fulltext').evaluate(el=>window.scrollTo(0,el.getBoundingClientRect().top+scrollY+el.getBoundingClientRect().height*.55-innerHeight*.7));
 await detail.waitForTimeout(22000);
 assert.equal(await detail.evaluate(()=>Object.keys(JSON.parse(localStorage.getItem('dh_reading_v1')).entries).length),0);
 await detail.close();await page.bringToFront();
 assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));
 assert.deepEqual(errors,[]);
 await page.close();
 return {status:'PASS',readIds,reasons,checks:['real foreground reading','behavior recommendations without keywords','qualified articles folded','reduce/undo','pause and clear persisted','paused detail creates no record','asset hash','no overflow']};
};
