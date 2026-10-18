'use strict';
const test=require('node:test'),assert=require('node:assert/strict');
const reading=require('../pipeline/assets/reading-profile.js'),forMe=require('../pipeline/assets/for-me.js');
const now=Date.parse('2026-10-18T08:00:00Z'),day=86400000;
const input={elapsed:5,visible:true,focused:true,idleSeconds:0,inArticle:true,depth:0.6};
const event=(id,topics)=>({event_id:id,topics,vendors:[],product_ids:[],published:'2026-10-18T00:00:00Z',importance:50});

test('quick clicks, background, unfocused, idle and title-only time do not qualify',()=>{
 assert.equal(reading.sample({},input).qualified,false);
 for(const change of [{visible:false},{focused:false},{idleSeconds:61},{inArticle:false}]){
  let state={};for(let i=0;i<30;i++)state=reading.sample(state,{...input,...change});
  assert.equal(state.seconds,0);assert.equal(state.qualified,false);
 }
 let state={};for(let i=0;i<4;i++)state=reading.sample(state,input);
 assert.equal(state.qualified,true);
 assert.equal(reading.sample({}, {...input,elapsed:900}).seconds,5,'Throttled timers cannot count suspended time');
 assert.equal(reading.sample({seconds:30,depth:0},{...input,depth:0.1}).qualified,false);
});
test('record bounded history, repeat on another day only, expiry and pause',()=>{
 let s=reading.record({},'aaaaaaaaaaaa',now-day);
 s=reading.record(s,'aaaaaaaaaaaa',now-day+1000);assert.equal(s.entries.aaaaaaaaaaaa.length,1);
 s=reading.record(s,'aaaaaaaaaaaa',now);assert.equal(s.entries.aaaaaaaaaaaa.length,2);
 s.enabled=false;assert.deepEqual(reading.record(s,'bbbbbbbbbbbb',now).entries,s.entries);
 assert.equal(Object.keys(reading.normalize(s,now+91*day).entries).length,0);
 const entries={};for(let i=0;i<220;i++)entries[i.toString(16).padStart(12,'0')]=[now-i];
 entries.bad=[now];entries.ffffffffffff=[now+day];
 assert.equal(Object.keys(reading.normalize({entries},now).entries).length,200);
 assert.deepEqual(reading.normalize({entries:{aaaaaaaaaaaa:[now,now,now-day,now-2*day,now-3*day]}},now).entries.aaaaaaaaaaaa,[now,now-day,now-2*day]);
});
test('two qualified reads infer related unseen content without selecting keywords',()=>{
 const events=[event('aaaaaaaaaaaa',['语义层']),event('bbbbbbbbbbbb',['语义层']),event('cccccccccccc',['语义层']),event('dddddddddddd',['湖仓'])];
 const state=forMe.normalizeState({setupDone:true});
 state.reading=reading.record(reading.record({},'aaaaaaaaaaaa',now),'bbbbbbbbbbbb',now);
 state.behavior=reading.profile(events,state,now);
 assert.equal(reading.match(events[2],state.behavior)[0].reason,'阅读');
 assert.deepEqual(forMe.sections(events,state,now,'').must.map(e=>e.event_id),['cccccccccccc']);
 assert(forMe.sections(events,state,now,'').discovery.some(e=>e.event_id==='dddddddddddd'));
 assert.equal(Object.keys(reading.profile(events,{...state,reading:reading.record({},'aaaaaaaaaaaa',now)},now)).length,0);
 assert.equal(Object.keys(reading.profile(events,state,now+60*day)).length,0);
});
test('favorites, explicit feedback, muted dimensions, pause and clearing remain controllable',()=>{
 const a=event('aaaaaaaaaaaa',['语义层']),b=event('bbbbbbbbbbbb',['语义层']);
 const state={reading:{enabled:true},favorites:[a.event_id]};
 assert.equal(reading.match(b,reading.profile([a,b],state,now))[0].reason,'收藏');
 assert.deepEqual(Object.keys(reading.profile([a,b],{...state,reading:{enabled:false}},now)),[]);
 assert.deepEqual(Object.keys(reading.profile([a,b],{...state,reading:{muted:['topic:语义层']}},now)),[]);
 assert.deepEqual(Object.keys(reading.profile([a,b],{...state,feedback:{entries:{[a.event_id]:{value:'not_useful',reason:'irrelevant'}}}},now)),[]);
 assert.equal(reading.match(b,reading.profile([a,b],{feedback:{entries:{[a.event_id]:{value:'useful'}}}},now))[0].reason,'有用反馈');
 assert(reading.score(b,reading.profile([a,b],state,now))<=24);
});
test('corrupt and unavailable storage safely degrade without claiming persistence',()=>{
 assert.equal(reading.load({getItem(){throw Error();}}).enabled,true);
 assert.equal(reading.save({setItem(){throw Error();}},{}),false);
 assert.equal(reading.load({getItem(){return 'invalid JSON';}}).version,1);
});

test('expired history is purged from storage on next visit without enabling paused learning',()=>{
 let raw=JSON.stringify({enabled:false,entries:{aaaaaaaaaaaa:[now-91*day]}});
 const storage={getItem(){return raw;},setItem(k,v){raw=v;}};
 assert.equal(reading.load(storage,now).enabled,false);
 assert.deepEqual(JSON.parse(raw).entries,{});
});
