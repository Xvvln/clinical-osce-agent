import { strict as assert } from "node:assert";
import { test } from "node:test";
import nextConfig from "./next.config.mjs";

test("admin API requests keep using the configured backend rewrite", async () => {
  const rules = await nextConfig.rewrites();

  assert.deepEqual(rules, [
    {
      source: "/api/:path*",
      destination: "http://127.0.0.1:8000/api/:path*",
    },
  ]);
});

test("admin responses disable framework disclosure and browser capabilities", async () => {
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
    "camera=(), geolocation=(), microphone=(), payment=(), usb=()",
  );
  assert.equal(headers["Referrer-Policy"], "no-referrer");
  assert.equal(headers["X-Content-Type-Options"], "nosniff");
  assert.equal(headers["X-Frame-Options"], "DENY");
});
