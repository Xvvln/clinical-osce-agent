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

test("Next responses disable framework disclosure and set browser security headers", async () => {
  assert.equal(nextConfig.poweredByHeader, false);

  const rules = await nextConfig.headers();
  assert.equal(rules.length, 1);
  assert.equal(rules[0].source, "/:path*");
  const headers = Object.fromEntries(rules[0].headers.map(({ key, value }) => [key, value]));

  assert.equal(
    headers["Content-Security-Policy"],
    "base-uri 'self'; frame-ancestors 'none'; object-src 'none'; form-action 'self'",
  );
  assert.equal(headers["Cross-Origin-Opener-Policy"], "same-origin");
  assert.equal(headers["Cross-Origin-Resource-Policy"], "same-origin");
  assert.equal(
    headers["Permissions-Policy"],
    "camera=(), geolocation=(), microphone=(self), payment=(), usb=()",
  );
  assert.equal(headers["Referrer-Policy"], "no-referrer");
  assert.equal(headers["X-Content-Type-Options"], "nosniff");
  assert.equal(headers["X-Frame-Options"], "DENY");
});

test("web app uses an explicit API proxy route for long training requests", () => {
  assert.equal(existsSync(apiProxyRoutePath), true);
  const routeSource = readFileSync(apiProxyRoutePath, "utf8");

  assert.match(routeSource, /process\.env\.CLINICAL_OSCE_WEB_API_URL/);
  assert.match(routeSource, /"http:\/\/127\.0\.0\.1:8000"/);
  assert.match(routeSource, /export async function GET/);
  assert.match(routeSource, /export async function POST/);
  assert.match(routeSource, /const MAX_API_PROXY_REQUEST_BYTES = 12 \* 1024 \* 1024/);
  assert.match(routeSource, /request\.body\.getReader\(\)/);
  assert.match(routeSource, /totalBytes > MAX_API_PROXY_REQUEST_BYTES/);
  assert.match(
    routeSource,
    /const boundedRequestBody = await readBoundedRequestBody\(request\);[\s\S]*?method === "GET" \|\| method === "HEAD" \? undefined : boundedRequestBody/,
  );
  assert.match(routeSource, /await request\.body\?\.cancel\("request body is too large"\)/);
  assert.match(routeSource, /status: 413/);
  assert.doesNotMatch(routeSource, /request\.arrayBuffer\(\)/);
  assert.match(routeSource, /fetch\(upstreamUrl/);
  assert.match(routeSource, /headers\.delete\("server"\)/);
  assert.match(routeSource, /headers\.delete\("x-powered-by"\)/);
  assert.match(routeSource, /headers\.set\("cache-control", "private, no-store, max-age=0"\)/);
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
