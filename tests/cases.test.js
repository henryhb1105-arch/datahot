"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const cases = require("../pipeline/assets/cases.js");

const records = [
  {
    productType: "Data Agent",
    taskType: "问数据",
    designQuestions: "入口与提问|可信与溯源",
    searchText: "Databricks Genie One 业务用户 文件协作 Agent 配置"
  },
  {
    productType: "数据平台",
    taskType: "管任务",
    designQuestions: "任务编排|治理与评估",
    searchText: "Snowflake CoWork Automations 调度 运行结果 邮件交付"
  },
  {
    productType: "BI",
    taskType: "看结果",
    designQuestions: "结果表达",
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

test("design-question navigation combines with secondary filters", () => {
  assert.equal(cases.filterCases(records, { question: "可信与溯源" }).length, 1);
  assert.equal(cases.filterCases(records, {
    question: "任务编排", product: "数据平台"
  })[0].taskType, "管任务");
  assert.equal(cases.filterCases(records, {
    question: "结果表达", task: "问数据"
  }).length, 0);
});

test("comparison selection toggles and never exceeds three cases", () => {
  assert.deepEqual(cases.selectedAfterToggle([], "a", 3), ["a"]);
  assert.deepEqual(cases.selectedAfterToggle(["a"], "a", 3), []);
  assert.deepEqual(cases.selectedAfterToggle(["a", "b", "c"], "d", 3), ["a", "b", "c"]);
});
