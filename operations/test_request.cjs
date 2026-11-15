const { test } = require("node:test");
const assert = require("node:assert/strict");
const vm = require("node:vm");
const fs = require("node:fs");
function setup(responses) {
  const calls = [],
    delays = [];
  const context = {
    window: {},
    location: { href: "https://volunteer.brentholidaysale.com/" },
    URL,
    fetch: async (...args) => {
      calls.push(args);
      const r = responses.shift();
      if (r instanceof Error) throw r;
      return r;
    },
    setTimeout: (fn, ms) => {
      delays.push(ms);
      fn();
    },
    Math,
  };
  vm.runInNewContext(fs.readFileSync("public/request.js", "utf8"), context);
  return { request: context.window.treamFetch, calls, delays };
}
const response = (status, retryAfter = null) => ({
  status,
  headers: { get: () => retryAfter },
});
test("GET retries temporary throttles and honors Retry-After", async () => {
  const s = setup([response(429, "2"), response(503), response(200)]);
  assert.equal((await s.request("https://api.test/schedule")).status, 200);
  assert.equal(s.calls.length, 3);
  assert.ok(s.delays[0] >= 2000);
});
test("booking retries reuse exact request body and idempotency keys", async () => {
  const s = setup([new Error("connection lost"), response(502), response(200)]);
  const options = {
    method: "POST",
    body: JSON.stringify({ selections: [{ idempotencyKey: "same-key" }] }),
  };
  await s.request("https://api.test/bookings", options);
  assert.ok(s.calls.every(([, value]) => value === options));
});
test("errors are bounded; validation and authentication are never retried", async () => {
  const s = setup(Array.from({ length: 5 }, () => response(503)));
  assert.equal((await s.request("https://api.test/schedule")).status, 503);
  assert.equal(s.calls.length, 5);
  assert.equal(s.delays.length, 4);
  for (const status of [400, 401, 403, 409]) {
    const v = setup([response(status)]);
    await v.request("https://api.test/bookings", { method: "POST" });
    assert.equal(v.calls.length, 1);
  }
});
test("non-idempotent mutations do not retry; changes and cancellation do", async () => {
  for (const path of ["/recovery", "/bookings/id/resend", "/admin/shifts/id"]) {
    const s = setup([response(503)]);
    await s.request("https://api.test" + path, { method: "POST" });
    assert.equal(s.calls.length, 1);
  }
  for (const path of ["/bookings/id/change", "/bookings/id/cancel"]) {
    const s = setup([response(503), response(200)]);
    await s.request("https://api.test" + path, { method: "POST" });
    assert.equal(s.calls.length, 2);
  }
});
