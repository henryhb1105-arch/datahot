"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const cases = require("../pipeline/assets/cases.js");

const records = [
  {
    productType: "Data Agent",
    taskType: "问数据",
    searchText: "Databricks Genie One 业务用户 文件协作 Agent 配置"
  },
  {
    productType: "数据平台",
    taskType: "管任务",
    searchText: "Snowflake CoWork Automations 调度 运行结果 邮件交付"
  },
  {
    productType: "BI",
    taskType: "看结果",
    searchText: "ThoughtSpot Spotter 仪表盘 指标解释"
  }
];

test("case filters combine product type, task and search", () => {
  assert.equal(cases.filterCases(records, { product: "Data Agent" }).length, 1);
  assert.equal(cases.filterCases(records, { task: "管任务" })[0].productType, "数据平台");
  assert.equal(cases.filterCases(records, { query: "email" }).length, 0);
  assert.equal(cases.filterCases(records, { query: "邮件" }).length, 1);
  assert.equal(cases.filterCases(records, {
    product: "BI", task: "问数据", query: "spotter"
  }).length, 0);
});

test("search is trimmed and case-insensitive", () => {
  assert.equal(cases.normalized("  GENIE One "), "genie one");
  assert.equal(cases.matchesCase(records[0], { query: "  genie one " }), true);
});
