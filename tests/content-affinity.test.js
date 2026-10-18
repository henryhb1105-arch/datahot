'use strict';
const test=require('node:test'),assert=require('node:assert/strict');
const affinity=require('../pipeline/assets/content-affinity'),forMe=require('../pipeline/assets/for-me'),reading=require('../pipeline/assets/reading-profile');
const events=require('./fixtures/reading-intents.json');
const now=Date.parse('2026-10-18T08:00:00Z'),day=86400000;
const evaluation=['64843a2454f2','7175222a4aa1'],metrics=['a5e85b0e5b72','f2cae75df487'];
function state(ids){const s=forMe.normalizeState({setupDone:true});s.reading={enabled:true,entries:Object.fromEntries(ids.map(id=>[id,[now]]))};s.affinity=affinity.profile(events,s,now);return s;}
const has=(s,id)=>!!s.affinity.matches[id];
test('real articles: evaluation readings cross labels, without expanding to metric governance',()=>{
 const s=state(evaluation);
 assert(has(s,'40c2caf96019'));assert(has(s,'d59935fed7ef'));
 assert(!has(s,'b8c3b1774462'));assert(!has(s,'1040324d5b86'));
 const evidence=s.affinity.matches['40c2caf96019'];assert(evaluation.includes(evidence.sourceId));assert(evidence.terms.length);assert.equal(evidence.value,'答案与工具评测');
});
test('same broad labels, different concrete need: definitions and governance have different recommendations',()=>{
 const s=state(metrics);
 for(const id of ['b8c3b1774462','1040324d5b86','17b3b16903c0'])assert(has(s,id),id);
 assert(!has(s,'40c2caf96019'));assert(!has(s,'8bfe1611f440'),'Brand award announcement is not metric governance practice');
 assert.notDeepEqual(forMe.sections(events,s,now,'').must.map(x=>x.event_id),forMe.sections(events,state(evaluation),now,'').must.map(x=>x.event_id));
});
test('observability does not become business KPI root-cause analysis or generic semantic layers',()=>{
 const s=state(['ec818542f6dc']);assert(has(s,'18d4c041883c'));assert(has(s,'592746be7343'));
 assert(!has(s,'82828eac5164'));assert(!has(s,'b8c3b1774462'));
});
test('no category or vendor label can manufacture behavioral relevance',()=>{
 const altered=events.map(e=>({...e,topics:['同一泛标签'],vendors:['SameBrand'],product_ids:['same'],work_tags:['same']}));
 const p=affinity.profile(altered,state(evaluation),now);
 assert(p.matches['40c2caf96019']);assert(!p.matches['b8c3b1774462']);
 const brandOnly={event_id:'ffffffffffff',zh_title:'Snowflake融资大会',zh_summary:'Snowflake融资榜单获奖。',topics:['语义层'],vendors:['Snowflake']};
 assert.equal(affinity.match(brandOnly,affinity.profile([...events,brandOnly],state(evaluation),now)).length,0);
});
test('relevant older work can lead, carries source evidence, read articles stay out and sections do not duplicate',()=>{
 const s=state(evaluation),grouped=forMe.sections(events,s,now,'');
 assert(grouped.must.some(x=>x.event_id==='d59935fed7ef'));
 assert(!grouped.must.some(x=>evaluation.includes(x.event_id)));
 const ids=['must','updates','work','discovery'].flatMap(k=>grouped[k].map(x=>x.event_id));assert.equal(new Set(ids).size,ids.length);
});
test('article feedback reduces similar content, preserves unrelated interests, and undo restores scores',()=>{
 const s=state([...evaluation,...metrics]),target=events.find(x=>x.event_id==='d59935fed7ef'),other=events.find(x=>x.event_id==='b8c3b1774462');
 const before=affinity.score(target,s.affinity),otherBefore=affinity.score(other,s.affinity);
 s.reading.muted=['article:40c2caf96019'];let reduced=affinity.profile(events,s,now);
 assert(affinity.score(target,reduced)<before);assert.equal(affinity.score(other,reduced),otherBefore);
 s.reading.muted=[];assert.equal(affinity.score(target,affinity.profile(events,s,now)),before);
 assert.deepEqual(reading.normalize({muted:['article:40c2caf96019']},now).muted,['article:40c2caf96019']);
 const rejected=affinity.profile(events,{reading:{enabled:true},dismissed:['40c2caf96019']},now);
 assert(affinity.score(target,rejected)<0,'Negative feedback works before any positive reading');
});
test('pause, expiration, favorite and useful signals respect user control',()=>{
 const s=state(evaluation);assert.equal(Object.keys(affinity.profile(events,{...s,reading:{...s.reading,enabled:false}},now).matches).length,0);
 assert.equal(Object.keys(affinity.profile(events,s,now+91*day).matches).length,0);
 for(const field of [{favorites:[evaluation[0]]},{feedback:{entries:{[evaluation[0]]:{value:'useful'}}}}])assert(affinity.profile(events,{reading:{enabled:true},...field},now).matches['d59935fed7ef']);
 const p=affinity.profile(events,{reading:s.reading,feedback:{entries:Object.fromEntries(evaluation.map(id=>[id,{value:'not_useful',reason:'irrelevant'}]))}},now);assert.equal(Object.keys(p.matches).length,0);
});
test('unknown articles and empty content do not invent preference evidence',()=>{
 assert.equal(Object.keys(state(['ffffffffffff']).affinity.matches).length,0);
 const empty=[{event_id:'aaaaaaaaaaaa'},{event_id:'bbbbbbbbbbbb'}];assert.equal(Object.keys(affinity.profile(empty,{favorites:['aaaaaaaaaaaa']},now).matches).length,0);
});
