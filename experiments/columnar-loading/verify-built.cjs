'use strict';
const fs=require('fs'),assert=require('assert/strict');
const fm=require('../../pipeline/assets/for-me.js'),affinity=require('../../pipeline/assets/content-affinity.js');
const raw=JSON.parse(fs.readFileSync('site/data/latest-lite.json'));
const decoded=fm.decodePayload(JSON.parse(fs.readFileSync('site/data/latest-lite-columns.json')));
assert.deepEqual(decoded,raw);
const now=Date.parse('2026-10-19T06:00:00Z');
for(const history of [0,2,40,200]) {
 const state=fm.normalizeState({});state.reading={enabled:true,entries:Object.fromEntries(raw.events.slice(0,history).map(e=>[e.event_id,[now]])),muted:[]};state.favorites=[];state.feedback={entries:{}};
 state.affinity=affinity.profile(raw.events,state,now);
 const expected=fm.sections(raw.events,state,now,null);
 state.affinity=affinity.profile(decoded.events,state,now);
 assert.deepEqual(fm.sections(decoded.events,state,now,null),expected);
}
console.log(`PASS: ${raw.events.length} events deeply equal; all sections/order equal for 0/2/40/200 histories`);
