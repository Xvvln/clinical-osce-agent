import { strict as assert } from "node:assert";
import { test } from "node:test";
import nextConfig from "./next.config.mjs";

test("Next dev Segment Explorer is disabled", () => {
  assert.equal(nextConfig.experimental?.devtoolSegmentExplorer, false);
});
