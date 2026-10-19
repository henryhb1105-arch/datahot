'use strict';
// DATAHOT_BEFORE_ROOT=/path/to/base-checkout node tests/ranking-performance.cjs
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const {performance}=require('node:perf_hooks');
assert(process.env.DATAHOT_BEFORE_ROOT,'Set DATAHOT_BEFORE_ROOT to the baseline checkout');
const beforeRoot=path.resolve(process.env.DATAHOT_BEFORE_ROOT);
const before=require(path.join(beforeRoot,'pipeline/assets/for-me'));
const after=require('../pipeline/assets/for-me');
const affinity=require('../pipeline/assets/content-affinity');
const events=JSON.parse(fs.readFileSync(path.join(beforeRoot,'site/data/latest-lite.json'))).events;
const now=Date.parse('2026-10-19T05:35:00Z'),results=[];
for(const history of [0,2,40,200]) {
  const state=before.normalizeState({});
  state.reading={enabled:true,entries:Object.fromEntries(events.slice(0,history).map(e=>[e.event_id,[now]])),muted:[]};
  state.affinity=affinity.profile(events,state,now);
  state.favorites=[];state.feedback={entries:{}};
  assert.deepEqual(before.sections(events,state,now,null),after.sections(events,state,now,null));
  function sample(api) {
    const times=[];
    for(let i=0;i<25;i++) {
      const start=performance.now();
      // The baseline render performs this extra ranking before sections().
      if(api===before) api.rankEvents(events,state,now,!!Object.keys(state.affinity.matches).length);
      api.sections(events,state,now,null);
      times.push(performance.now()-start);
    }
    return times.slice(5).sort((a,b)=>a-b)[10];
  }
  results.push({history,beforeMs:sample(before),afterMs:sample(after)});
}
console.log(JSON.stringify(results,null,2));
