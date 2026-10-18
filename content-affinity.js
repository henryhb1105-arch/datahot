(function(root,factory){
  'use strict';
  var api=factory();
  if(typeof module==='object'&&module.exports) module.exports=api;
  if(root) root.DataHotAffinity=api;
})(typeof globalThis!=='undefined'?globalThis:this,function(){
  'use strict';
  var DAY=86400000, cache=new WeakMap();
  var stop=new Set(('ai agent agents data 数据 智能体 语义 语义层 分析 平台 模型 系统 企业 产品 技术 能力 功能 用户 团队 文章 介绍 通过 支持 提供 基于 使用 实现 如何 进行 可以 一个 一种 以及 相关 需要 主要 目前 更 多 的 和 与 在 为 将 对 从 到 是 了 并 等 中 其 本次 新增 发布 更新 公开 方法 不同 结合 复杂 知识 每秒 统一 面对 进入 问题 提升 提高 进一步 包括 其中 认为 指出 讨论 强调 说明 方式 参考 价值 构建 场景 核心 业务 内容 工作 已有 更好 要求 持续 基础 new the a an of to in for on with and or by from this that it is are as at into more using use about blog').split(' '));
  // These are grounded query/problem aliases, not event labels or user categories.
  var problems=[
    ['evaluation','答案与工具评测',/评测|benchmark|\bbird\b|参考答案|执行准确率|测试集/i,/agent|智能体|sql|模型|答案|推理/i],
    ['metrics','指标口径与定义',/指标定义|指标口径|口径|业务规则|术语定义|metric definitions?|业务含义/i],
    ['observability','可观测性与根因定位',/可观测|链路追踪|observability|tracing|日志事件|故障.{0,8}(根因|定位)|查询.{0,8}延迟/i],
    ['permissions','权限与访问控制',/权限|授权|访问控制|rbac|access control|authorization/i],
    ['lineage','血缘与影响分析',/血缘|lineage|影响分析/i],
    ['retrieval','检索与召回',/检索|召回|rerank|retrieval|向量搜索/i],
    ['cost','成本与资源优化',/成本|费用|计费|pricing|cost optimization/i],
    ['migration','接入与迁移',/迁移|兼容|驱动|jdbc|migration/i],
    ['interaction','交互与产品设计',/交互|界面|用户体验|设计模式|user experience|interface/i],
    ['tools','工具调用与任务编排',/工具调用|任务编排|tool calling|orchestration|执行轨迹/i]
  ];
  var segmenter=typeof Intl!=='undefined'&&Intl.Segmenter?new Intl.Segmenter('zh',{granularity:'word'}):null;
  function text(event){return [event.zh_title||'',event.zh_summary||''].join(' ').normalize('NFKC').toLowerCase().slice(0,6000);}
  function tokens(value){
    value=String(value||'').normalize('NFKC').toLowerCase().replace(/text[ -]?to[ -]?sql/g,'texttosql').replace(/\b(evaluations?|benchmarking)\b/g,'评测');
    var words=segmenter?Array.from(segmenter.segment(value)).filter(function(x){return x.isWordLike;}).map(function(x){return x.segment;}):(value.match(/[a-z][a-z0-9_-]{2,}|[\u3400-\u9fff]{2,}/g)||[]).flatMap(function(x){return /^[a-z]/.test(x)?[x]:Array.from({length:x.length-1},function(_,i){return x.slice(i,i+2);});});
    return words.filter(function(w){return w.length>=2&&w.length<=40&&!stop.has(w)&&!/^\d/.test(w)&&!/^https?/.test(w);});
  }
  function index(events){
    if(cache.has(events)) return cache.get(events);
    var df=new Map(),docs=new Map(),n=Math.max(1,events.length),brands=new Set();
    events.forEach(function(e){(e.vendors||[]).forEach(function(v){tokens(v).forEach(function(w){brands.add(w);});});});
    ['netflix','looker','snowflake','databricks','aloudata','google','openai','microsoft','amazon','aws','clickhouse','thoughtspot','cube'].forEach(function(w){brands.add(w);});
    events.forEach(function(e){
      var counts=new Map(),body=text(e),labels=[];
      tokens(e.zh_title).forEach(function(w){counts.set(w,(counts.get(w)||0)+2);});
      tokens(e.zh_summary).forEach(function(w){counts.set(w,(counts.get(w)||0)+1);});
      problems.forEach(function(p){if(p[2].test(body)&&(!p[3]||p[3].test(body))){counts.set('@'+p[0],2);labels.push(p[0]);}});
      counts.forEach(function(_,w){df.set(w,(df.get(w)||0)+1);});
      var title=String(e.zh_title||'').toLowerCase();
      var main=problems.filter(function(p){return labels.includes(p[0])&&(p[2].test(title)||(p[0]==='metrics'&&/指标|口径|定义/.test(title)));}).map(function(p){return p[0];});
      docs.set(e.event_id,{event:e,counts:counts,labels:labels,main:main,brands:brands,announcement:/入选|融资|收购|榜单|峰会|大会|发布会|获奖/.test(title)});
    });
    docs.forEach(function(d){
      var values=[];
      d.counts.forEach(function(tf,w){if((df.get(w)||0)/n>.55&&w[0]!=='@') return;values.push([w,(brands.has(w)?.25:1)*(1+Math.log(tf))*Math.log(1+n/(df.get(w)||1))]);});
      values.sort(function(a,b){return b[1]-a[1];});values=values.slice(0,100);
      var norm=Math.sqrt(values.reduce(function(s,x){return s+x[1]*x[1];},0))||1;
      d.vector=new Map(values.map(function(x){return [x[0],x[1]/norm];}));delete d.counts;
    });
    var result={docs:docs};cache.set(events,result);return result;
  }
  function compare(a,b){
    if(!a||!b||a.announcement!==b.announcement) return {similarity:0,terms:[],problem:''};
    var sum=0,terms=[],shared=[];
    a.vector.forEach(function(v,w){var other=b.vector.get(w);if(other){sum+=v*other;if(w[0]==='@')shared.push(w.slice(1));else if(!a.brands.has(w)) terms.push([w,v*other]);}});
    terms.sort(function(a,b){return b[1]-a[1];});
    var problem=problems.filter(function(p){return shared.includes(p[0]);}).sort(function(p,q){return (b.main.includes(q[0])+a.main.includes(q[0]))-(b.main.includes(p[0])+a.main.includes(p[0]));})[0];
    var mainBoth=problem&&a.main.includes(problem[0])&&b.main.includes(problem[0]);
    if(mainBoth)sum+=.16;else if(problem&&(a.main.includes(problem[0])||b.main.includes(problem[0])))sum+=.04;
    // A broad problem alias alone cannot establish relevance.
    var supported=sum>=.16&&terms.length>=(mainBoth?1:problem?2:3);
    return {similarity:supported?sum:0,terms:terms.slice(0,3).map(function(x){return x[0];}),problem:problem?problem[1]:'',problemId:problem?problem[0]:''};
  }
  function profile(events,state,now){
    var history=state.reading||{},empty={matches:{},penalties:{},positive:false};
    if(history.enabled===false) return empty;
    if(!Object.keys(history.entries||{}).length&&!(state.favorites||[]).length&&!Object.keys(state.feedback&&state.feedback.entries||{}).length&&!(state.dismissed||[]).length&&!(history.muted||[]).length)return empty;
    var idx=index(events),positive=[],negative=[],muted=history.muted||[];
    events.forEach(function(e){
      var id=e.event_id,row=(state.feedback&&state.feedback.entries||{})[id],days=(history.entries||{})[id]||[];
      var rejected=(state.dismissed||[]).includes(id)||muted.includes('article:'+id)||(row&&row.value==='not_useful');
      if(rejected){if(!row||row.reason==='irrelevant'||muted.includes('article:'+id)||(state.dismissed||[]).includes(id))negative.push(idx.docs.get(id));return;}
      var weight=days.reduce(function(s,t){return s+(t<=now&&t>now-90*DAY?2*Math.pow(.5,(now-t)/(14*DAY)):0);},0),reason='阅读';
      if((state.favorites||[]).includes(id)){weight+=6;reason='收藏';}
      if(row&&row.value==='useful'){weight+=6;reason='有用反馈';}
      if(weight>=.5)positive.push({doc:idx.docs.get(id),weight:Math.min(weight,6),reason:reason});
    });
    if(!positive.length&&!negative.length)return empty;
    // Bound synchronous work; retain full history, rank from the strongest 40 signals.
    positive.sort(function(a,b){return b.weight-a.weight;});positive=positive.slice(0,40);negative=negative.slice(-40);
    var result={matches:{},penalties:{},positive:positive.length>0};
    events.forEach(function(e){
      var doc=idx.docs.get(e.event_id),best=[],penalty=0;
      negative.forEach(function(n){if(!n)return;var c=compare(doc,n);penalty=Math.max(penalty,c.similarity*100);});
      result.penalties[e.event_id]=Math.min(70,penalty);
      var blocked=['topic','vendor','product'].some(function(kind){return (e[{topic:'topics',vendor:'vendors',product:'product_ids'}[kind]]||[]).some(function(v){return muted.includes(kind+':'+v);});});
      if(blocked)return;
      positive.forEach(function(p){
        if(p.doc.event.event_id===e.event_id)return;
        var c=compare(doc,p.doc);if(!c.similarity)return;
        // Incidental mentions in a read article are not a declaration of intent.
        if(p.doc.main.length&&c.problemId&&!p.doc.main.includes(c.problemId))return;
        var strength=Math.min(75,(18+(c.similarity-.13)*140)*Math.min(1.5,p.weight/2));
        best.push({key:'article:'+e.event_id,kind:'content',value:c.problem||c.terms.slice(0,2).join(' / '),weight:strength,reason:p.reason,sourceId:p.doc.event.event_id,sourceTitle:p.doc.event.zh_title,similarity:c.similarity,terms:c.terms});
      });
      best.sort(function(a,b){return b.weight-a.weight;});
      if(best.length){var first=best[0];first.weight=Math.min(85,first.weight+(best[1]?best[1].weight*.2:0))-penalty;if(first.weight>=12)result.matches[e.event_id]=first;}
    });
    return result;
  }
  function match(event,p){var row=p&&p.matches&&p.matches[event.event_id];return row?[row]:[];}
  function score(event,p){var row=match(event,p)[0];return row?row.weight:-(p&&p.penalties&&p.penalties[event.event_id]||0);}
  return {tokens:tokens,index:index,compare:compare,profile:profile,match:match,score:score};
});
