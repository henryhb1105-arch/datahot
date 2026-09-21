"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const products = require("../pipeline/assets/products.js");

test("radar reads the existing product follows without modifying user state", () => {
  const original = JSON.stringify({ products: ["hex", "databricks-genie", "../bad", 123], topics: ["语义层"] });
  let key;
  const storage = { getItem(k) { key = k; return original; }, setItem() { assert.fail("must be read only"); } };
  assert.deepEqual(products.readFollowing(storage), ["hex", "databricks-genie"]);
  assert.equal(key, "dh_for_me_v1");
});

test("missing, malformed or unavailable local storage keeps public browsing usable", () => {
  for (const value of [null, "bad json", "null", "[]", '{"products":"hex"}']) {
    assert.deepEqual(products.readFollowing({ getItem() { return value; } }), []);
  }
  assert.deepEqual(products.readFollowing({ getItem() { throw new Error("blocked"); } }), []);
});
