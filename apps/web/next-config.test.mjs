import { strict as assert } from "node:assert";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import nextConfig from "./next.config.mjs";

const packageJson = JSON.parse(readFileSync(new URL("./package.json", import.meta.url), "utf8"));

async function importNextConfigWithApiUrl(apiUrl) {
  const originalApiUrl = process.env.CLINICAL_OSCE_WEB_API_URL;
  if (apiUrl) {
    process.env.CLINICAL_OSCE_WEB_API_URL = apiUrl;
  } else {
    delete process.env.CLINICAL_OSCE_WEB_API_URL;
  }

  const moduleUrl = new URL(`./next.config.mjs?api-url=${encodeURIComponent(apiUrl ?? "default")}-${Date.now()}`, import.meta.url);
  const nextConfigModule = await import(moduleUrl.href);

  if (originalApiUrl === undefined) {
    delete process.env.CLINICAL_OSCE_WEB_API_URL;
  } else {
    process.env.CLINICAL_OSCE_WEB_API_URL = originalApiUrl;
  }

  return nextConfigModule.default;
}

test("Next dev Segment Explorer is disabled", () => {
  assert.equal(nextConfig.experimental?.devtoolSegmentExplorer, false);
});

test("Next dev indicator is disabled in favor of the OSCE dock", () => {
  assert.equal(nextConfig.devIndicators, false);
});

test("Next rewrites proxy API calls to the local backend by default", async () => {
  const rewrites = await nextConfig.rewrites();

  assert.deepEqual(rewrites, [
    {
      source: "/api/:path*",
      destination: "http://127.0.0.1:8000/api/:path*",
    },
  ]);
});

test("Next rewrites proxy API calls to the Compose backend when configured", async () => {
  const composeNextConfig = await importNextConfigWithApiUrl("http://api:8000");
  const rewrites = await composeNextConfig.rewrites();

  assert.deepEqual(rewrites, [
    {
      source: "/api/:path*",
      destination: "http://api:8000/api/:path*",
    },
  ]);
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
