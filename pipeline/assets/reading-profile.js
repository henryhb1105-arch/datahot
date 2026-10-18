(function(root,factory){
  'use strict';
  var api=factory();
  if(typeof module==='object'&&module.exports) module.exports=api;
  if(root) root.DataHotReading=api;
  if(root&&root.document) api.boot(root);
})(typeof globalThis!=='undefined'?globalThis:this,function(){
  'use strict';
  var KEY='dh_reading_v1', DAY=86400000;
  function normalize(raw,now){
    raw=raw&&typeof raw==='object'?raw:{}; now=now||Date.now();
    var entries={};
    Object.keys(raw.entries||{}).filter(function(id){return /^[a-f0-9]{12}$/.test(id);}).map(function(id){
      var days=Array.isArray(raw.entries[id])?raw.entries[id]:[];
      days=Array.from(new Set(days.filter(function(t){return Number.isFinite(t)&&t>now-90*DAY&&t<=now;}))).sort(function(a,b){return b-a;}).slice(0,3);
      return {id:id,days:days};
    }).filter(function(row){return row.days.length;}).sort(function(a,b){return b.days[0]-a.days[0];}).slice(0,200).forEach(function(row){entries[row.id]=row.days;});
    return {version:1,enabled:raw.enabled!==false,entries:entries,muted:Array.from(new Set((Array.isArray(raw.muted)?raw.muted:[]).filter(function(x){return typeof x==='string'&&/^(topic|vendor|product):.{1,80}$/.test(x);}))).slice(-100)};
  }
  function load(storage,now){
    try {
      var raw=JSON.parse(storage.getItem(KEY)||'null'),clean=normalize(raw,now);
      if(raw&&JSON.stringify(raw.entries)!==JSON.stringify(clean.entries)) {
        try{storage.setItem(KEY,JSON.stringify(clean));}catch(_){}
      }
      return clean;
    } catch(_){return normalize({},now);}
  }
  function save(storage,state){try{storage.setItem(KEY,JSON.stringify(normalize(state)));return true;}catch(_){return false;}}
  function record(state,id,now){
    var clean=normalize(state,now);
    if(!clean.enabled||!/^[a-f0-9]{12}$/.test(id)) return clean;
    var days=clean.entries[id]||[];
    // One qualified visit per UTC day; reloads/tabs cannot inflate repeat interest.
    if(!days.some(function(t){return Math.floor(t/DAY)===Math.floor(now/DAY);})) days.unshift(now);
    clean.entries[id]=days;
    return normalize(clean,now);
  }
  function dimensions(event){return ['topic','vendor','product'].flatMap(function(kind){
    var values=event[{topic:'topics',vendor:'vendors',product:'product_ids'}[kind]]||[];
    return Array.from(new Set(values)).slice(0,8).map(function(value){return {key:kind+':'+value,kind:kind,value:String(value)};});
  });}
  function profile(events,state,now){
    var reading=normalize(state.reading,now), signals=Object.create(null);
    if(!reading.enabled) return signals;
    (events||[]).forEach(function(event){
      var id=event.event_id,feedback=(state.feedback&&state.feedback.entries||{})[id],days=reading.entries[id]||[];
      if((state.dismissed||[]).indexOf(id)>=0) return;
      var weight=days.reduce(function(total,t){return total+2*Math.pow(0.5,(now-t)/(14*DAY));},0),reason='阅读';
      if((state.favorites||[]).indexOf(id)>=0){weight+=6;reason='收藏';}
      if(feedback&&feedback.value==='useful'){weight+=6;reason='有用反馈';}
      if(feedback&&feedback.value==='not_useful') weight=feedback.reason==='irrelevant'?-6:0;
      dimensions(event).forEach(function(d){
        if(reading.muted.indexOf(d.key)>=0) return;
        var row=signals[d.key]||(signals[d.key]={kind:d.kind,value:d.value,weight:0,reason:reason});
        row.weight+=weight;
        if(reason!=='阅读'&&weight>0) row.reason=reason;
      });
    });
    Object.keys(signals).forEach(function(key){if(signals[key].weight<3) delete signals[key];});
    return signals;
  }
  function match(event,signals){return dimensions(event).map(function(d){var row=(signals||{})[d.key];return row?{key:d.key,kind:d.kind,value:d.value,weight:row.weight,reason:row.reason}:null;}).filter(Boolean).sort(function(a,b){return b.weight-a.weight;});}
  function score(event,signals){return Math.min(24,match(event,signals).reduce(function(sum,r){return sum+Math.min(12,r.weight*2);},0));}
  function sample(previous,input){
    var elapsed=Math.max(0,Math.min(5,input.elapsed||0));
    var active=input.visible&&input.focused&&input.idleSeconds<60&&input.inArticle;
    var seconds=(previous.seconds||0)+(active?elapsed:0);
    var depth=Math.max(previous.depth||0,active?input.depth||0:0);
    return {seconds:seconds,depth:depth,qualified:seconds>=20&&depth>=0.5};
  }
  function boot(win){
    var doc=win.document,body=doc.body,id=body&&body.dataset.eventId;
    var section=doc.querySelector('.fulltext')||doc.querySelector('.content-section');
    if(!id||!section) return;
    var storage;try{storage=win.localStorage;}catch(_){return;}
    var last=win.performance.now(),activity=last,progress={seconds:0,depth:0},done=false;
    function reset(){progress={seconds:0,depth:0};done=false;last=win.performance.now();}
    function touch(){activity=win.performance.now();}
    ['scroll','pointerdown','keydown','touchstart'].forEach(function(name){win.addEventListener(name,touch,{passive:true});});
    doc.addEventListener('visibilitychange',function(){last=win.performance.now();});
    win.addEventListener('focus',function(){last=win.performance.now();touch();});
    win.addEventListener('blur',function(){last=win.performance.now();});
    win.addEventListener('storage',function(e){if(e.key===KEY||e.key===null) reset();});
    function tick(){
      var now=win.performance.now(),elapsed=(now-last)/1000;last=now;
      var current=load(storage);
      if(!current.enabled){reset();return;}
      if(done) return;
      var r=section.getBoundingClientRect(),height=Math.max(1,r.height);
      progress=sample(progress,{elapsed:elapsed,visible:doc.visibilityState==='visible',focused:doc.hasFocus(),idleSeconds:(now-activity)/1000,inArticle:r.bottom>0&&r.top<win.innerHeight,depth:Math.max(0,Math.min(1,(win.innerHeight-r.top)/height))});
      if(progress.qualified){done=save(storage,record(current,id,Date.now()));}
    }
    var timer=win.setInterval(tick,1000);
    win.addEventListener('pagehide',function(){win.clearInterval(timer);});
    win.addEventListener('pageshow',function(e){if(e.persisted){reset();touch();timer=win.setInterval(tick,1000);}});
  }
  return {KEY:KEY,normalize:normalize,load:load,save:save,record:record,profile:profile,match:match,score:score,sample:sample,boot:boot};
});
