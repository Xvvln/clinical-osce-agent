import { strict as assert } from "node:assert";
import { existsSync, readFileSync } from "node:fs";
import { test } from "node:test";

const pageUrl = new URL("./src/app/v2/page.tsx", import.meta.url);
const dashboardUrl = new URL("./src/app/v2/admin-v2-dashboard.tsx", import.meta.url);
const oldPageUrl = new URL("./src/app/page.tsx", import.meta.url);
const docsUrl = new URL("../../docs/admin-v2-dashboard.md", import.meta.url);

const pageSource = existsSync(pageUrl) ? readFileSync(pageUrl, "utf8") : "";
const dashboardSource = existsSync(dashboardUrl) ? readFileSync(dashboardUrl, "utf8") : "";
const oldPageSource = existsSync(oldPageUrl) ? readFileSync(oldPageUrl, "utf8") : "";
const docsSource = existsSync(docsUrl) ? readFileSync(docsUrl, "utf8") : "";

test("admin v2 is an independent dashboard route and leaves the current admin page as the legacy entry", () => {
  assert.ok(existsSync(pageUrl), "v2 page should exist");
  assert.ok(existsSync(dashboardUrl), "v2 dashboard client should exist");
  assert.match(pageSource, /AdminV2Dashboard/);
  assert.doesNotMatch(pageSource, /from "\.\.\/page"/);
  assert.doesNotMatch(dashboardSource, /from "\.\.\/page"/);
  assert.doesNotMatch(oldPageSource, /AdminV2Dashboard/);
  assert.match(dashboardSource, /旧版调试入口/);
});

test("admin v2 documents the Dashboard Blocks adaptation and migration boundary", () => {
  assert.ok(existsSync(docsUrl), "admin v2 design document should exist");
  assert.match(docsSource, /shadcn\/ui Dashboard Blocks/);
  assert.match(docsSource, /不改动现有管理端首页 `\/`/);
  assert.match(docsSource, /v2 不删除、不覆盖旧管理端 `\/`/);
  assert.match(docsSource, /技术 ID 和原始 JSON 不作为主界面阅读内容/);
  assert.match(docsSource, /http:\/\/127\.0\.0\.1:3100\/v2/);
});

test("admin v2 exposes the core management modules with clean Chinese labels", () => {
  for (const label of ["概览", "教学资源", "训练管理", "教学洞察", "Skill 进化", "系统评测", "调用日志"]) {
    assert.match(dashboardSource, new RegExp(label), `v2 dashboard should expose ${label}`);
  }

  for (const label of ["训练 Session", "评分报告", "候选 Skill", "模型成功率", "API 成功率和最近错误"]) {
    assert.match(dashboardSource, new RegExp(label), `v2 dashboard should show ${label}`);
  }

  assert.match(dashboardSource, /TraceOSCE Admin v2/);
  assert.match(dashboardSource, /管理员登录/);
  assert.match(dashboardSource, /账号信息不在前端预填或展示/);
});

test("admin v2 reads the existing backend APIs without adding a new backend contract", () => {
  for (const endpoint of [
    "/api/admin/model-config",
    "/api/admin/model-api-logs?limit=60",
    "/api/admin/sessions?limit=20",
    "/api/admin/reports?limit=20",
    "/api/admin/evolution/candidates?limit=20&review_status=all",
    "/api/admin/evaluations?limit=20",
    "/api/cases",
    "/api/admin/sources",
    "/api/admin/rag/documents",
    "/api/admin/insights",
    "/api/admin/evolution/skill-effects",
    "/api/admin/evals/run",
    "/api/admin/evolution/candidates/generate",
  ]) {
    assert.match(dashboardSource, new RegExp(endpoint.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")), `v2 dashboard should use ${endpoint}`);
  }
});

test("admin v2 does not leak demo account credentials in the new login surface", () => {
  for (const forbidden of ["admin@osce.test", "student@osce.test", "DEMO_ADMIN_PASSWORD", "admin / admin", "student / student"]) {
    assert.doesNotMatch(dashboardSource, new RegExp(forbidden.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")));
  }
});
