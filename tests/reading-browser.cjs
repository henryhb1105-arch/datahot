'use strict';
const {feedNavigation}=require('./browser-readiness.cjs');
const assert=require('node:assert/strict'),path=require('node:path'),crypto=require('node:crypto');
module.exports=async function(context,base,out,width){
 const page=await context.newPage(),errors=[];
 page.on('pageerror',e=>errors.push(e.message));
 await feedNavigation(page, () => page.goto(base+'for-me.html', {waitUntil:'domcontentloaded'}));
 await page.evaluate(()=>{
  for(const k of ['dh_reading_v1','dh_for_me_v1','dh_favs','dh_favs_v2','dh_content_feedback_v1','dh_default_home_v1'])localStorage.removeItem(k);
  localStorage.setItem('dh_for_me_v1',JSON.stringify({setupDone:true}));sessionStorage.clear();
 });
 const data=await (await context.request.get(base+'data/latest-lite.json')).json();
 const candidates=['64843a2454f2','7175222a4aa1'].map(id=>data.events.find(e=>e.event_id===id));
 assert(candidates.every(Boolean),'Evaluation reading fixtures must remain in the index');
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
 await feedNavigation(page, () => page.goto(base+'for-me.html', {waitUntil:'domcontentloaded'}));
 assert(!(await page.locator('#fmSetup').isVisible()),'Learned preferences bypass mandatory setup');
 const reasons=await page.locator('#fmMustList .fm-why').allTextContents();
 assert(reasons.some(x=>x.includes('接着你读过')),'Behavior should recommend without selected keywords');
 for(const id of readIds) assert.equal(await page.locator(`#fmMustList [data-event-id="${id}"]`).count(),0);
 const affinityAsset=new URL(await page.locator('script[src*="content-affinity.js?"]').getAttribute('src'),base);
 const affinityResponse=await context.request.get(affinityAsset.href);assert(affinityResponse.ok());
 assert.equal(crypto.createHash('sha256').update(await affinityResponse.body()).digest('hex').slice(0,12),affinityAsset.searchParams.get('v'));
 const evaluationIds=await page.locator('#fmMustList .fm-signal').evaluateAll(nodes=>nodes.map(n=>n.dataset.eventId));
 assert(evaluationIds.some(id=>['d59935fed7ef','40c2caf96019'].includes(id)),'Evaluation reading must surface concrete evaluation material');
 assert(!evaluationIds.includes('b8c3b1774462'),'A broad semantic-layer label must not replace the reading intent');
 assert((await page.locator('#fmMustList .fm-signal').first().boundingBox()).y<200);
 assert(await page.locator('#fmMustList time').count()>0,'Older references retain visible publication dates');
 for(const id of evaluationIds){
  const e=data.events.find(e=>e.event_id===id);
  const date=String(e.published||e.first_seen).slice(0,10);
  const time=page.locator(`#fmMustList [data-event-id="${id}"] time`);
  assert.equal(await time.getAttribute('datetime'),date,'Keep source calendar date across time zones');
  assert.equal(await time.innerText(),(e.published?'发布 ':'收录 ')+date,'Distinguish publication from collection date');
 }
 await page.screenshot({path:path.join(out,`${width}-reading-recommendations.png`)});
 // Counterfactual history is local to this disposable browser, not production activity.
 const actualHistory=await page.evaluate(()=>localStorage.getItem('dh_reading_v1'));
 await page.evaluate(()=>localStorage.setItem('dh_reading_v1',JSON.stringify({enabled:true,entries:{a5e85b0e5b72:[Date.now()],f2cae75df487:[Date.now()]}})));
 await feedNavigation(page, () => page.reload({waitUntil:'domcontentloaded'}));
 const metricIds=await page.locator('#fmMustList .fm-signal').evaluateAll(nodes=>nodes.map(n=>n.dataset.eventId));
 const metricReasons=await page.locator('#fmMustList .fm-why').allTextContents();
 assert(metricReasons.some(text=>text.includes('共同讨论：指标口径与定义')),'Metric definition reading must surface its concrete intent');
 assert(metricIds.every(id=>!data.events.find(e=>e.event_id===id)?.body_review_required),'Unverified references must not enter priority recommendations');
 assert(!metricIds.includes('40c2caf96019'));assert.notDeepEqual(metricIds,evaluationIds);
 await page.screenshot({path:path.join(out,`${width}-reading-metrics.png`)});
 await page.evaluate(history=>localStorage.setItem('dh_reading_v1',history),actualHistory);
 await feedNavigation(page, () => page.reload({waitUntil:'domcontentloaded'}));
 const reduce=page.locator('[data-action="reduce"]').first();await reduce.click();
 assert((await page.evaluate(()=>JSON.parse(localStorage.getItem('dh_reading_v1')).muted.length))>0);
 await page.locator('#fmNotice button').click();
 assert.equal(await page.evaluate(()=>JSON.parse(localStorage.getItem('dh_reading_v1')).muted.length),0);
 await page.locator('#fmCustomize').click();
 await page.locator('#reading-settings summary').click();
 await page.locator('#fmBehaviorEnabled').uncheck();
 assert.match(await page.locator('#fmBehaviorStatus').innerText(),/已暂停/);
 assert.equal(await page.locator('.fm-why').filter({hasText:'接着你读过'}).count(),0);
 await page.locator('#fmClearReading').click();
 assert.equal(await page.evaluate(()=>Object.keys(JSON.parse(localStorage.getItem('dh_reading_v1')).entries).length),0);
 await feedNavigation(page, () => page.reload({waitUntil:'domcontentloaded'}));
 await page.locator('#fmCustomize').click();
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
 return {status:'PASS',readIds,reasons,evaluationIds,metricIds,checks:['real foreground reading','concrete content recommendations without keywords','different histories yield different first picks','no broad label substitution','older references dated','first card under 200px','qualified articles folded','reduce/undo','pause and clear persisted','paused detail creates no record','asset hash','no overflow']};
};
