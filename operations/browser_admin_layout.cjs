// Synthetic responses only: this test never authenticates or mutates live data.
const { chromium, webkit } = require(
  process.env.PLAYWRIGHT_MODULE || "playwright",
);
const fixture = {
  shifts: [
    {
      id: "0",
      date: "2026-12-02",
      name: "Lot Maintenance/Inventory Replenishment and Tree Preparation",
      location: "Canal Park south entrance",
      start: 9,
      end: 13,
      capacity: 30,
      effectiveCapacity: 30,
      overflowPercent: 0,
      flex: true,
      open: true,
      revision: 0,
      subJobs: [],
      attendance: { incrementMinutes: 30, minMinutes: 30 },
      roster: [],
      coverage: Array.from({ length: 16 }, (_, i) => ({
        start: 9 + i / 4,
        end: 9 + (i + 1) / 4,
        count: 1,
        target: 30,
        limit: 30,
      })),
    },
  ],
  bookings: [
    {
      id: "booking",
      shiftId: "0",
      participantId: "fixture",
      name: "Test Volunteer",
      email: "a".repeat(65) + "@example.com",
      phone: "2025550123",
      start: 9,
      end: 11,
      publicName: "Test V.",
      comment: "LongComment".repeat(25),
      subJobPreferences: [],
    },
  ],
  conflicts: [
    {
      id: "overlap",
      bookingIds: ["booking"],
      email: "a".repeat(65) + "@example.com",
      kind: "shared_email",
      reviewed: false,
    },
  ],
  emailEnabled: false,
};
(async () => {
  for (const [name, engine] of process.env.LAYOUT_CHROMIUM_ONLY
    ? [["chromium", chromium]]
    : [
        ["chromium", chromium],
        ["webkit", webkit],
      ]) {
    const browser = await engine.launch({ headless: true });
    const context = await browser.newContext();
    await context.addInitScript(() =>
      sessionStorage.setItem(
        "tream-organizer-access",
        "synthetic-layout-token",
      ),
    );
    await context.route("**/config.js", (r) =>
      r.fulfill({
        contentType: "application/javascript",
        body: 'window.TREAM_CONFIG={apiBase:"https://layout-fixture.execute-api.us-east-2.amazonaws.com",organizerClientId:"fixture"}',
      }),
    );
    await context.route("https://layout-fixture.execute-api.us-east-2.amazonaws.com/**", (r) =>
      r.fulfill({
        headers: {
          "access-control-allow-origin": "*",
          "access-control-allow-headers": "authorization,content-type",
          "access-control-allow-methods": "GET,POST,OPTIONS",
        },
        json: r.request().url().endsWith("/admin/overview")
          ? fixture
          : { drafts: [] },
      }),
    );
    const page = await context.newPage(),
      errors = [];
    page.on("pageerror", (e) => errors.push(e.message));
    await page.goto(
      (process.env.SITE_URL || "http://127.0.0.1:8010") + "/organizer.html",
    );
    await page
      .getByRole("heading", { name: "Organizer desk", exact: true })
      .waitFor();
    async function fits(label) {
      const bad = await page.evaluate(() => {
        const width = innerWidth;
        const outside = [
          ...document.querySelectorAll(
            "header,header .brand,header .a-header,.a-title,.a-title button,.a-metric,.a-tabs button,.a-controls > *,dialog[open]",
          ),
        ]
          .filter((el) => {
            const b = el.getBoundingClientRect();
            return b.width && (b.left < -1 || b.right > width + 1);
          })
          .map((el) => el.className || el.id || el.tagName);
        return { width, scroll: document.documentElement.scrollWidth, outside };
      });
      if (bad.scroll > bad.width + 1 || bad.outside.length)
        throw Error(`${name} ${label}: ${JSON.stringify(bad)}`);
    }
    for (const width of [320, 360, 375, 390, 414, 600, 800, 1440]) {
      await page.setViewportSize({ width, height: 844 });
      for (const tab of ["coverage", "volunteers", "conflicts", "messages"]) {
        await page.locator(`[data-view="${tab}"]`).click();
        await fits(`${width}px ${tab}`);
        if (tab === "volunteers") {
          const wrapper = page.locator(".a-table-wrap");
          const scrollable = await wrapper.evaluate(
            (el) => el.scrollWidth > el.clientWidth,
          );
          if (width <= 600 && !scrollable)
            throw Error("Roster should scroll inside its own container");
        }
      }
      await page.locator('[data-view="coverage"]').click();
      await page.locator("#add-shift").click();
      await fits(`${width}px add shift`);
      const dialogOverflow = await page
        .locator("#dialog")
        .evaluate((el) => el.scrollWidth > el.clientWidth + 1);
      if (dialogOverflow)
        throw Error(`${name}: dialog contents overflow at ${width}px`);
      await page.locator("#dialog .close").click();
    }
    if (errors.length) throw Error(errors.join("\n"));
    await page.setViewportSize({ width: 375, height: 812 });
    await page.locator('[data-view="volunteers"]').click();
    if (process.env.LAYOUT_SCREENSHOT)
      await page.screenshot({
        path: `${process.env.LAYOUT_SCREENSHOT}-${name}.png`,
        fullPage: true,
      });
    await browser.close();
    console.log(
      `PASS: ${name} admin page, header, controls, metrics, four tabs and dialog fit 320–1440px; tables scroll internally.`,
    );
  }
})().catch((e) => {
  console.error(e);
  process.exit(1);
});
