import { strict as assert } from "node:assert";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import nextConfig from "./next.config.mjs";

const packageJson = JSON.parse(readFileSync(new URL("./package.json", import.meta.url), "utf8"));

test("Next dev Segment Explorer is disabled", () => {
  assert.equal(nextConfig.experimental?.devtoolSegmentExplorer, false);
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
