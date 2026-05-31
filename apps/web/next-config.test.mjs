import { strict as assert } from "node:assert";
import { existsSync, readFileSync } from "node:fs";
import { test } from "node:test";
import nextConfig from "./next.config.mjs";

const packageJson = JSON.parse(readFileSync(new URL("./package.json", import.meta.url), "utf8"));
const apiProxyRoutePath = new URL("./src/app/api/[...path]/route.ts", import.meta.url);

test("Next dev Segment Explorer is disabled", () => {
  assert.equal(nextConfig.experimental?.devtoolSegmentExplorer, false);
});

test("Next dev indicator is disabled in favor of the OSCE dock", () => {
  assert.equal(nextConfig.devIndicators, false);
});

test("Next config does not use rewrite proxy for API calls", () => {
  assert.equal(nextConfig.rewrites, undefined);
});

test("web app uses an explicit API proxy route for long training requests", () => {
  assert.equal(existsSync(apiProxyRoutePath), true);
  const routeSource = readFileSync(apiProxyRoutePath, "utf8");

  assert.match(routeSource, /process\.env\.CLINICAL_OSCE_WEB_API_URL/);
  assert.match(routeSource, /"http:\/\/127\.0\.0\.1:8000"/);
  assert.match(routeSource, /export async function GET/);
  assert.match(routeSource, /export async function POST/);
  assert.match(routeSource, /request\.arrayBuffer\(\)/);
  assert.match(routeSource, /fetch\(upstreamUrl/);
});

test("Next dev uses Webpack polling for reliable Windows hot reload", () => {
  assert.equal(packageJson.scripts.dev, "next dev");
  assert.doesNotMatch(packageJson.scripts.dev, /--webpack|--turbo|--turbopack/);

  const config = { watchOptions: {} };
  const nextWebpackConfig = nextConfig.webpack(config);

  assert.equal(nextWebpackConfig, config);
  assert.deepEqual(config.watchOptions, {
    aggregateTimeout: 300,
    ignored: ["**/node_modules/**", "**/.next/**"],
    poll: 1000,
  });
});
