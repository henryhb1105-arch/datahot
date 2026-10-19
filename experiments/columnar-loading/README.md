# 无损列式推荐数据实验（2026-10-19）

基线：已上线的 e73e486c51e80952d4f43996dc169ba9e741db00。

`measure.cjs` 在同一个完整站点上建立两个gzip HTTP入口，唯一变量是推荐数据的无损列式传输及对应解码器。三个冷缓存样本交替执行，390×844、4倍CPU降速、150ms延迟、200,000B/s下行，固定两篇阅读历史。不是国内实网测量。

运行：

```sh
DATAHOT_SITE=/absolute/site CHROME_PATH=/path/to/chrome \
  node experiments/columnar-loading/measure.cjs
```

默认从仓库 ops/cloud-acceptance/node_modules 加载Playwright；可用PLAYWRIGHT_MODULE指定已有安装。

原型结果见 results.json：
- 原格式卡片出现2316.4/2311.8/2321ms；列式2089/2081.3/2083.6ms。
- 中位数2316.4→2083.6ms，减少232.8ms（10.0%）。
- 列式解码3.5/3.1/3.4ms（4倍CPU降速）。
- gzip正文290009→243374B（-16.1%），解压1042854→839660B。
- 全660条数据深度相等，保留缺失/null/false/0/Unicode/嵌套值；每轮推荐卡片顺序相同。
- 原有约220ms TF-IDF长任务仍在，不属于本轮优化范围。

集成范围仅为“为你”：构建额外 latest-lite-columns.json 并使用内容哈希URL；原 latest-lite.json 继续提供完整对象格式给首页、收藏和外部消费者。现有错误提示/重试与旧对象格式兼容保留。不截断内容，不改变排序或推荐算法。

完整集成构建对比（integrated-results.json，同样三次/场景）：
- 直接“为你”卡片出现中位数2328.1→2097.5ms（-9.9%），LCP2396→2164ms。
- 默认“为你”根入口跨导航到可见卡片2753→2339ms。跨导航用wall time，不能用第二页重新计时的LCP代替。
- 普通首页LCP696→716ms，未改首页数据加载，视为测量波动，不宣称改善。
- 完整集成比较时另一个功能验收浏览器也在运行；更严格的交替独立原型数据见上方，收益方向和量级一致。
- 构建729HTML链接检查通过，Python566项（3跳过）和Node96项通过；完整数据和0/2/40/200条历史所有推荐分区严格一致。
