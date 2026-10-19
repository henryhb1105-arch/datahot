'use strict';
const fs=require('fs'),path=require('path'),http=require('http'),zlib=require('zlib'),assert=require('assert/strict');
const {pack,decode}=require('./codec.cjs');
const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'../../ops/cloud-acceptance/node_modules/playwright');
const root=path.resolve(process.env.DATAHOT_SITE||'site');
const original=JSON.parse(fs.readFileSync(path.join(root,'data/latest-lite.json')));
const packed=pack(original);assert.deepEqual(decode(JSON.parse(JSON.stringify(packed))),original);
for(const fixture of [{events:[]},{extra:{a:0},events:[{a:null,b:false,c:0,d:'中文😀',e:[null,{z:''}]},{b:true}]}]) assert.deepEqual(decode(JSON.parse(JSON.stringify(pack(fixture)))),fixture);
for(const bad of [{...packed,count:-1},{...packed,columns:{x:[]}},{...packed,columns:{x:{rows:[0,0],values:[1,2]}}}]) assert.throws(()=>decode(bad));
const raw=Buffer.from(JSON.stringify(original)+'\n'),column=Buffer.from(JSON.stringify(packed)+'\n');
const result={bytes:{raw:raw.length,column:column.length,gzipRaw:zlib.gzipSync(raw).length,gzipColumn:zlib.gzipSync(column).length},rows:[]};
(async()=>{
const server=http.createServer((req,res)=>{
 const [,variant,...rest]=new URL(req.url,'http://localhost').pathname.split('/');
 const file=path.resolve(root,rest.join('/')||'index.html');if(!file.startsWith(root+path.sep)){res.writeHead(403);return res.end();}
 try {let bytes=fs.readFileSync(file);
 if(file.endsWith('/data/latest-lite.json')) bytes=variant==='after'?column:raw;
 if(file.endsWith('/for-me.js')) {
  let js=bytes.toString();
  assert(js.includes('return response.json();'));
  js=js.replace('return response.json();',`return response.json().then(function(payload) { var t=performance.now(); var decoded=${variant==='after'?`(${decode.toString()})(payload)`:'payload'}; window.__decodeMs=performance.now()-t; return decoded; });`);
  bytes=Buffer.from(js);
 }
 const mime={'.html':'text/html; charset=utf-8','.js':'text/javascript','.json':'application/json','.css':'text/css'};
 res.writeHead(200,{'Content-Type':mime[path.extname(file)]||'application/octet-stream','Content-Encoding':'gzip','Cache-Control':'max-age=600'});res.end(zlib.gzipSync(bytes));
 }catch(e){res.writeHead(404);res.end();}
});await new Promise(r=>server.listen(0,'127.0.0.1',r));
const browser=await chromium.launch({headless:true,executablePath:process.env.CHROME_PATH});
try {
 for(let run=0;run<3;run++) for(const variant of (run%2?['after','before']:['before','after'])) {
  const ctx=await browser.newContext({viewport:{width:390,height:844},extraHTTPHeaders:{DNT:'1'}});
  await ctx.addInitScript(()=>{
   localStorage.setItem('dh_analytics_optout_v1','1');
   localStorage.setItem('dh_reading_v1',JSON.stringify({enabled:true,entries:{'64843a2454f2':[Date.now()],'7175222a4aa1':[Date.now()]}}));
   window.__perf={ready:0,lcp:0,long:[]};
   new PerformanceObserver(l=>l.getEntries().forEach(e=>window.__perf.lcp=e.startTime)).observe({type:'largest-contentful-paint',buffered:true});
   new PerformanceObserver(l=>l.getEntries().forEach(e=>window.__perf.long.push(e.duration))).observe({type:'longtask',buffered:true});
   new MutationObserver(()=>{if(document.querySelector('#fmMustList .fm-signal')&&!window.__perf.ready)window.__perf.ready=performance.now();}).observe(document,{subtree:true,childList:true});
  });
  const page=await ctx.newPage(),errors=[];page.on('pageerror',e=>errors.push(e.message));
  const cdp=await ctx.newCDPSession(page);await cdp.send('Network.enable');
  await cdp.send('Network.emulateNetworkConditions',{offline:false,latency:150,downloadThroughput:200000,uploadThroughput:100000,connectionType:'cellular4g'});
  await cdp.send('Emulation.setCPUThrottlingRate',{rate:4});
  await page.goto(`http://127.0.0.1:${server.address().port}/${variant}/for-me.html`);
  await page.locator('#fmMustList .fm-signal').first().waitFor();await page.waitForTimeout(1000);
  const row=await page.evaluate(()=>({...window.__perf,decodeMs:window.__decodeMs,ids:Array.from(document.querySelectorAll('#fmContent .fm-signal')).map(e=>e.dataset.eventId),data:performance.getEntriesByType('resource').filter(e=>e.name.includes('latest-lite')).map(e=>({bytes:e.transferSize,duration:e.duration}))}));
  assert.deepEqual(errors,[]);Object.assign(row,{variant,run});result.rows.push(row);console.log(row);await ctx.close();
 }
 for(const row of result.rows) assert.deepEqual(row.ids,result.rows[0].ids);
 result.status='PASS';fs.writeFileSync(path.join(__dirname,'results.json'),JSON.stringify(result,null,2));
}finally{await browser.close();server.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
