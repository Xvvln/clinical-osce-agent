import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

const appDir = dirname(fileURLToPath(import.meta.url));
const repoRoot = resolve(appDir, "../..");

function readAppFile(path) {
  return readFileSync(resolve(appDir, path), "utf8");
}

function readRepoFile(path) {
  return readFileSync(resolve(repoRoot, path), "utf8");
}

test("Playwright critical flow keeps one deterministic Chromium worker and failure artifacts", () => {
  const configSource = readAppFile("playwright.config.ts");
  const specSource = readAppFile("e2e/critical-training-flow.spec.ts");
  const packageJson = JSON.parse(readAppFile("package.json"));

  assert.equal(packageJson.devDependencies["@playwright/test"], "1.62.0");
  assert.equal(packageJson.scripts["test:e2e"], "playwright test");
  assert.match(configSource, /retries:\s*0/);
  assert.match(configSource, /workers:\s*1/);
  assert.match(configSource, /trace:\s*"retain-on-failure"/);
  assert.match(configSource, /video:\s*"retain-on-failure"/);
  assert.match(configSource, /screenshot:\s*"only-on-failure"/);
  assert.match(configSource, /channel:\s*process\.env\.E2E_BROWSER_CHANNEL/);
  assert.match(specSource, /http:\/\/localhost:3000/);
  assert.match(specSource, /http:\/\/127\.0\.0\.1:3001/);
  assert.equal(specSource.match(/context\.newPage\(\)/g)?.length, 2);
  assert.match(specSource, /\/profile/);
  assert.match(specSource, /profile\.report_count/);
  assert.match(specSource, /profile\.recent_sessions/);
});

test("E2E Compose isolates persistence and disables network model dependencies", () => {
  const composeSource = readRepoFile("docker-compose.e2e.yml");

  assert.match(composeSource, /e2e_runtime:\/app\/data\/runtime/);
  assert.doesNotMatch(composeSource, /\.\/data\/runtime:\/app\/data\/runtime/);
  assert.match(composeSource, /OSCE_REQUIRE_RUNTIME_MODEL_CONFIG_FOR_TRAINING:\s*"false"/);
  assert.match(composeSource, /CLINICAL_OSCE_ALLOW_UNSAFE_ACCOUNT_MODEL_ENDPOINTS:\s*"false"/);
  for (const setting of [
    "OSCE_VERTEX_ENABLED",
    "OSCE_VERTEX_SKILL_CANDIDATE_ENABLED",
    "OSCE_VERTEX_EMBEDDING_ENABLED",
    "OSCE_OPENAI_ENABLED",
    "OSCE_LOCAL_EMBEDDING_ENABLED",
    "OSCE_CHROMA_ENABLED",
  ]) {
    assert.match(composeSource, new RegExp(`${setting}:\\s*"false"`));
  }
  assert.match(composeSource, /student@e2e\.test/);
  assert.match(composeSource, /admin@e2e\.test/);
  assert.match(composeSource, /"127\.0\.0\.1:3000:3000"/);
  assert.match(composeSource, /"127\.0\.0\.1:3001:3000"/);
});

test("CI starts the isolated stack and always preserves diagnostics before volume cleanup", () => {
  const workflowSource = readRepoFile(".github/workflows/ci.yml");
  const e2eJobSource = workflowSource.slice(workflowSource.indexOf("\n  e2e:"));

  assert.match(e2eJobSource, /timeout-minutes:\s*45/);
  assert.match(e2eJobSource, /playwright install --with-deps chromium/);
  assert.match(e2eJobSource, /docker compose -f docker-compose\.e2e\.yml up --build --wait --wait-timeout 240/);
  assert.match(e2eJobSource, /name:\s*Collect E2E service logs[\s\S]*?if:\s*always\(\)/);
  assert.match(e2eJobSource, /name:\s*Upload E2E diagnostics[\s\S]*?if:\s*always\(\)/);
  assert.match(e2eJobSource, /name:\s*Stop isolated E2E stack[\s\S]*?if:\s*always\(\)/);
  assert.match(e2eJobSource, /down --volumes --remove-orphans/);
});
