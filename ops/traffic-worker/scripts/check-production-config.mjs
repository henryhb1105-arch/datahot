import { readFileSync } from "node:fs";

const config = readFileSync(new URL("../wrangler.toml", import.meta.url), "utf8");
const failures = [];
if (config.includes("00000000-0000-0000-0000-000000000000")) failures.push("D1 database_id 仍是占位值");
if (!config.includes('workers_dev = false')) failures.push("workers.dev 必须关闭");
if (!config.includes('preview_urls = false')) failures.push("预览地址必须关闭");
if (!config.includes('admin.datahot.xiahongbin.com')) failures.push("缺少私有后台域名");
if (!config.includes('metrics.datahot.xiahongbin.com')) failures.push("缺少采集域名");

if (failures.length) {
  console.error(failures.join("\n"));
  process.exit(1);
}
console.log("生产配置检查通过");
