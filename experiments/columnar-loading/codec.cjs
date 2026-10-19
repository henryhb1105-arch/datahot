'use strict';
function pack(payload) {
  const {events,...meta}=payload;
  const columns={};
  for(const key of new Set(events.flatMap(Object.keys))) {
    const rows=[],values=[];
    events.forEach((event,i)=>{if(Object.hasOwn(event,key)){rows.push(i);values.push(event[key]);}});
    columns[key]=rows.length===events.length?values:{rows,values};
  }
  return {transport:'datahot-columns-v1',meta,count:events.length,columns};
}
function decode(payload) {
  if(Array.isArray(payload.events)) return payload;
  if(payload.transport!=='datahot-columns-v1'||!Number.isSafeInteger(payload.count)||payload.count<0||payload.count>100000||!payload.meta||!payload.columns) throw new Error('Invalid lite transport');
  const events=Array.from({length:payload.count},()=>({}));
  for(const [key,column] of Object.entries(payload.columns)) {
    if(['__proto__','constructor','prototype'].includes(key)) throw new Error('Unsafe column');
    if(Array.isArray(column)) {
      if(column.length!==events.length) throw new Error('Invalid column length');
      column.forEach((value,i)=>{events[i][key]=value;});
    } else {
      if(!column||!Array.isArray(column.rows)||!Array.isArray(column.values)||column.rows.length!==column.values.length) throw new Error('Invalid sparse column');
      let previous=-1;
      column.rows.forEach((i,j)=>{
        if(!Number.isInteger(i)||i<=previous||i>=events.length) throw new Error('Invalid row');
        previous=i;events[i][key]=column.values[j];
      });
    }
  }
  return {...payload.meta,events};
}
module.exports={pack,decode};
