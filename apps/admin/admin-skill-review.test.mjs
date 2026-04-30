import { strict as assert } from "node:assert";
import { existsSync, readFileSync } from "node:fs";
import { test } from "node:test";

const adminPageUrl = new URL("./src/app/page.tsx", import.meta.url);
const adminPackageUrl = new URL("./package.json", import.meta.url);
const adminTsconfigUrl = new URL("./tsconfig.json", import.meta.url);
const adminLayoutUrl = new URL("./src/app/layout.tsx", import.meta.url);
const adminGlobalsUrl = new URL("./src/app/globals.css", import.meta.url);
const adminNextConfigUrl = new URL("./next.config.mjs", import.meta.url);
const adminPostcssConfigUrl = new URL("./postcss.config.mjs", import.meta.url);
const adminPageSource = existsSync(adminPageUrl) ? readFileSync(adminPageUrl, "utf8") : "";
const adminPackageSource = existsSync(adminPackageUrl) ? readFileSync(adminPackageUrl, "utf8") : "";
const adminTsconfigSource = existsSync(adminTsconfigUrl) ? readFileSync(adminTsconfigUrl, "utf8") : "";
const adminLayoutSource = existsSync(adminLayoutUrl) ? readFileSync(adminLayoutUrl, "utf8") : "";
const adminGlobalsSource = existsSync(adminGlobalsUrl) ? readFileSync(adminGlobalsUrl, "utf8") : "";
const adminNextConfigSource = existsSync(adminNextConfigUrl) ? readFileSync(adminNextConfigUrl, "utf8") : "";
const adminPostcssConfigSource = existsSync(adminPostcssConfigUrl) ? readFileSync(adminPostcssConfigUrl, "utf8") : "";

test("admin dashboard reads management data and exposes review actions", () => {
  assert.ok(existsSync(adminPageUrl), "admin dashboard page should exist");
  assert.match(adminPageSource, /type AdminSessionSummary = Readonly<\{/);
  assert.match(adminPageSource, /type AdminSessionReport = Readonly<\{/);
  assert.match(adminPageSource, /type EvaluationBatchSummary = Readonly<\{/);
  assert.match(adminPageSource, /type EvaluationBatchDetail = Readonly<\{/);
  assert.match(adminPageSource, /type AdminTrainingInsights = Readonly<\{/);
  assert.match(adminPageSource, /type FrequentMissedItem = Readonly<\{/);
  assert.match(adminPageSource, /type FrequentLearningRecommendation = Readonly<\{/);
  assert.match(adminPageSource, /type TrainingSkillCandidateSummary = Readonly<\{/);
  assert.match(adminPageSource, /type TrainingSkillCandidateDetail = Readonly<\{/);
  assert.match(adminPageSource, /type TrainingEventRecord = Readonly<\{/);
  assert.match(adminPageSource, /fetch\("\/api\/admin\/sessions"/);
  assert.match(adminPageSource, /fetch\(`\/api\/admin\/sessions\/\$\{sessionId\}\/report`/);
  assert.match(adminPageSource, /fetch\(`\/api\/admin\/sessions\/\$\{sessionId\}\/events`/);
  assert.match(adminPageSource, /fetch\("\/api\/admin\/insights"/);
  assert.match(adminPageSource, /fetch\("\/api\/admin\/evaluations"/);
  assert.match(adminPageSource, /fetch\(`\/api\/admin\/evaluations\/\$\{batchId\}`/);
  assert.match(adminPageSource, /fetch\("\/api\/admin\/evolution\/candidates"/);
  assert.match(adminPageSource, /fetch\(`\/api\/admin\/evolution\/candidates\/\$\{candidateId\}`/);
  assert.match(adminPageSource, /fetch\("\/api\/admin\/evolution\/approve"/);
  assert.match(adminPageSource, /fetch\("\/api\/admin\/evolution\/reject"/);
  assert.match(adminPageSource, /Clinical OSCE 管理后台/);
  assert.match(adminPageSource, /总览/);
  assert.match(adminPageSource, /训练 Session/);
  assert.match(adminPageSource, /评分报告/);
  assert.match(adminPageSource, /错误模式统计/);
  assert.match(adminPageSource, /常见漏项/);
  assert.match(adminPageSource, /学习建议/);
  assert.match(adminPageSource, /系统评测/);
  assert.match(adminPageSource, /训练日志/);
  assert.match(adminPageSource, /候选 Skill 审核/);
  assert.match(adminPageSource, /事件类型/);
  assert.match(adminPageSource, /事件内容/);
  assert.match(adminPageSource, /回归通过/);
  assert.match(adminPageSource, /批准并启用/);
  assert.match(adminPageSource, /拒绝候选/);
  assert.match(adminPageSource, /教学策略/);
});

test("admin app has standalone Next.js package and TypeScript config", () => {
  assert.ok(existsSync(adminPackageUrl), "admin package.json should exist");
  assert.ok(existsSync(adminTsconfigUrl), "admin tsconfig.json should exist");
  assert.match(adminPackageSource, /"name": "clinical-osce-admin"/);
  assert.match(adminPackageSource, /"dev": "next dev"/);
  assert.match(adminPackageSource, /"build": "next build"/);
  assert.match(adminPackageSource, /"typecheck": "tsc --noEmit"/);
  assert.match(adminPackageSource, /"next": "\^15\.5\.14"/);
  assert.match(adminPackageSource, /"react": "\^19\.1\.0"/);
  assert.match(adminTsconfigSource, /"strict": true/);
  assert.match(adminTsconfigSource, /"plugins": \[\{ "name": "next" \}\]/);
  assert.match(adminTsconfigSource, /"include": \["next-env\.d\.ts", "\*\*\/\*\.ts", "\*\*\/\*\.tsx", "\.next\/types\/\*\*\/\*\.ts"\]/);
});

test("admin app has Next.js root layout and global styles", () => {
  assert.ok(existsSync(adminLayoutUrl), "admin root layout should exist");
  assert.ok(existsSync(adminGlobalsUrl), "admin globals stylesheet should exist");
  assert.match(adminLayoutSource, /import type \{ Metadata \} from "next"/);
  assert.match(adminLayoutSource, /import "\.\/globals\.css"/);
  assert.match(adminLayoutSource, /title: "Clinical OSCE 管理后台"/);
  assert.match(adminLayoutSource, /<html lang="zh-CN">/);
  assert.match(adminGlobalsSource, /@import "tailwindcss";/);
  assert.match(adminGlobalsSource, /--admin-paper: #faf9f5;/);
});

test("admin app proxies API requests and compiles Tailwind styles", () => {
  assert.ok(existsSync(adminNextConfigUrl), "admin next.config.mjs should exist");
  assert.ok(existsSync(adminPostcssConfigUrl), "admin postcss.config.mjs should exist");
  assert.match(adminNextConfigSource, /async rewrites\(\)/);
  assert.match(adminNextConfigSource, /source: "\/api\/:path\*"/);
  assert.match(adminNextConfigSource, /destination: "http:\/\/127\.0\.0\.1:8000\/api\/:path\*"/);
  assert.match(adminPostcssConfigSource, /plugins: \["@tailwindcss\/postcss"\]/);
});
