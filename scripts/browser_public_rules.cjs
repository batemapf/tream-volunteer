// Browser-only schedule fixture: no real bookings or production data are changed.
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || "playwright");
(async () => {
  const browser = await chromium.launch({ headless: true }),
    context = await browser.newContext();
  const shift = {
    id: "policy-fixture",
    date: "2026-12-01",
    name: "<b>Setup & help</b>",
    role: "Custom crew",
    location: "Gate <east>",
    start: 9,
    end: 10,
    capacity: 5,
    effectiveCapacity: 5,
    open: true,
    flex: true,
    roster: [],
    attendance: {
      incrementMinutes: 5,
      minMinutes: 5,
      maxMinutes: 5,
      allowedStarts: [9 + 5 / 60],
      allowedEnds: [9 + 10 / 60],
    },
  };
  await context.route("**/config.js", (route) =>
    route.fulfill({
      contentType: "application/javascript",
      body: 'window.TREAM_CONFIG={apiBase:"https://policy-fixture.execute-api.us-east-2.amazonaws.com"}',
    }),
  );
  await context.route(
    "https://policy-fixture.execute-api.us-east-2.amazonaws.com/**",
    (route) =>
      route.fulfill({
        headers: {
          "access-control-allow-origin": "*",
          "access-control-allow-headers": "content-type",
          "access-control-allow-methods": "GET,OPTIONS",
        },
        json: { shifts: [shift], emailEnabled: false },
      }),
  );
  const page = await context.newPage(),
    errors = [];
  page.on("pageerror", (error) => errors.push(error.message));
  try {
    await page.goto(process.env.SITE_URL || "http://127.0.0.1:8000");
    await page.getByRole("button", { name: "Tue 01", exact: true }).waitFor();
    await page.locator("#jobfilter").selectOption("Custom crew");
    await page
      .getByRole("button", { name: "<b>Setup & help</b>", exact: true })
      .click();
    await page
      .getByRole("heading", { name: "<b>Setup & help</b>", exact: true })
      .waitFor();
    if (await page.locator("#modal h2 b").count())
      throw Error("Job name interpreted as markup");
    if (
      (await page.locator("#start option").allTextContents()).join() !==
      "9:05 am"
    )
      throw Error("Arrival choice ignored policy");
    if (
      (await page.locator("#end option").allTextContents()).join() !== "9:10 am"
    )
      throw Error("Departure choice ignored policy or minute formatting");
    if (
      !(await page.locator("#modal .eyebrow").innerText()).includes(
        "Gate <east>",
      )
    )
      throw Error("Edited location was not shown");
    if (errors.length) throw Error(errors.join("\n"));
    console.log(
      "PASS: public board handles edited dates/roles, literal text, location and exact five-minute attendance choices.",
    );
  } finally {
    await browser.close();
  }
})().catch((error) => {
  console.error(error.message);
  process.exit(1);
});
