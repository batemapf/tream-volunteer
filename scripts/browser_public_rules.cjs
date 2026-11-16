// Browser-only schedule fixture: no real bookings or production data are changed.
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || "playwright");
(async () => {
  const browser = await chromium.launch({ headless: true }),
    context = await browser.newContext();
  const shift = {
    id: "policy-fixture",
    date: "2026-12-01",
    name: "<b>Setup & help</b>",

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
  let transientResponses = 0;
  await context.route(
    "https://policy-fixture.execute-api.us-east-2.amazonaws.com/**",
    (route) =>
      route.fulfill({
        status: transientResponses++ < 2 ? 429 : 200,
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
    await page
      .getByRole("button", { name: "Tue 12/01", exact: true })
      .waitFor();
    await page
      .getByRole("button", { name: "<b>Setup & help</b>", exact: true })
      .click();
    await page
      .getByRole("heading", { name: "<b>Setup & help</b>", exact: true })
      .waitFor();
    const date = page.locator("#modal .signup-date time");
    if (
      (await date.getAttribute("datetime")) !== "2026-12-01" ||
      !(await date.innerText()).includes("Tuesday, Dec 1")
    )
      throw Error("Signup date is missing or incorrect");
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
      !(await page.locator("#modal .signup-location").innerText()).includes(
        "Gate <east>",
      )
    )
      throw Error("Edited location was not shown");
    await page.locator("#modal .close").click();
    shift.name = "Capacity fixture";
    shift.capacity = 1;
    shift.effectiveCapacity = 1;
    shift.attendance = { incrementMinutes: 30, minMinutes: 30 };
    shift.roster = [{ publicName: "Volunteer", start: 9, end: 10 }];
    await page.reload();
    await page
      .locator(".coverage small")
      .getByText("Full", { exact: true })
      .waitFor();
    await page.getByRole("button", { name: "View shift", exact: true }).click();
    if (
      !(await page
        .getByRole("button", { name: "Sign up", exact: true })
        .isDisabled())
    )
      throw Error("Full shift signup must be disabled");
    shift.roster[0].end = 9.5;
    await page.reload();
    await page
      .getByRole("button", { name: "View & join →", exact: true })
      .click();
    if (
      !(await page
        .getByRole("button", { name: "Sign up", exact: true })
        .isDisabled())
    )
      throw Error("Full selected window must be disabled");
    await page.locator("#start").selectOption("9.5");
    if (
      await page
        .getByRole("button", { name: "Sign up", exact: true })
        .isDisabled()
    )
      throw Error("Available partial window should remain bookable");
    shift.roster[0].end = 10;
    shift.effectiveCapacity = 2;
    await page.reload();
    await page
      .getByRole("button", { name: "View & join →", exact: true })
      .click();
    if (
      await page
        .getByRole("button", { name: "Sign up", exact: true })
        .isDisabled()
    )
      throw Error("Configured overflow must remain bookable");
    shift.effectiveCapacity = 1;
    shift.flex = false;
    shift.roster[0].end = 9.5;
    await page.reload();
    await page.getByRole("button", { name: "View shift", exact: true }).click();
    if (
      !(await page
        .getByRole("button", { name: "Sign up", exact: true })
        .isDisabled())
    )
      throw Error("Fixed shifts must fit the entire window");
    if (await page.locator("#need").count())
      throw Error("Needs-help filter should be removed");
    if (errors.length) throw Error(errors.join("\n"));
    console.log(
      "PASS: public board handles edited dates/roles, literal text, location and exact five-minute attendance choices, full-shift blocking, partial-window availability and configured overflow.",
    );
  } finally {
    await browser.close();
  }
})().catch((error) => {
  console.error(error.message);
  process.exit(1);
});
