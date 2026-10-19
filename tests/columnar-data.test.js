const test=require('node:test'),assert=require('node:assert/strict');
const {decodePayload:decode}=require('../pipeline/assets/for-me.js');
const {pack}=require('../experiments/columnar-loading/codec.cjs');
test('column transport preserves missing/null, unicode, nested data and metadata',()=>{
 for(const p of [{events:[]},{schema_version:1,home_event_ids:['a'],events:[{a:null,b:false,c:0,d:'中文😀',e:[null,{z:''}]},{b:true}]}]) assert.deepEqual(decode(JSON.parse(JSON.stringify(pack(p)))),p);
 const raw={events:[{a:1}]};assert.equal(decode(raw),raw);
});
test('malformed columns fail closed',()=>{
 const p=pack({events:[{a:1},{a:2}]});
 for(const invalid of [{...p,count:-1},{...p,transport:'future'},{...p,columns:{a:[]}},{...p,columns:{a:{rows:[0,0],values:[1,2]}}},{...p,columns:{a:{rows:[2],values:[1]}}},{...p,columns:JSON.parse('{"__proto__":[{},{}]}')}]) assert.throws(()=>decode(invalid));
});
