// Real management-link UI; credentials are passed only in process environment.
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || "playwright");
(async () => {
  const browser = await chromium.launch({ headless: true });
  try {
    const context = await browser.newContext(),
      page = await context.newPage();
    await page.setViewportSize({ width: 390, height: 844 });
    if (process.env.EMAIL_ACTION === "recover") {
      await page.goto(process.env.SITE_URL);
      await page
        .getByRole("button", { name: "Find my signups", exact: true })
        .click();
      await page.locator("#recovery-email").fill("batemapf@gmail.com");
      await page
        .getByRole("button", { name: "Email my signup links", exact: true })
        .click();
      await page
        .getByRole("heading", { name: "Check your email", exact: true })
        .waitFor();
      if (await page.evaluate(() => localStorage.getItem("tream-aws-manage")))
        throw Error("Browser signup record should not persist");
      console.log("PASS: public email recovery form from a fresh browser");
      return;
    }
    await page.goto(
      process.env.SITE_URL +
        "/manage.html#" +
        new URLSearchParams({
          booking: process.env.BOOKING_ID,
          token: process.env.MANAGE_TOKEN,
        }),
    );
    await page
      .getByRole("button", { name: "Change signup", exact: true })
      .waitFor();
    if (process.env.EMAIL_ACTION === "change") {
      await page
        .getByRole("button", { name: "Change signup", exact: true })
        .click();
      await page.locator("#shift").selectOption("9");
      await page.locator("#start").selectOption("14");
      await page.locator("#end").selectOption("16");
      await page
        .getByRole("button", { name: "Save changes", exact: true })
        .click();
      await page
        .getByRole("button", { name: "Change signup", exact: true })
        .waitFor();
      await page
        .getByText("2026-12-05 · 2:00 pm–4:00 pm Eastern", { exact: false })
        .waitFor();
    } else if (process.env.EMAIL_ACTION === "cancel") {
      await page
        .getByRole("button", { name: "Cancel signup", exact: true })
        .click();
      await page
        .getByRole("button", { name: "Yes, cancel", exact: true })
        .click();
      await page
        .getByText(
          "Your place has reopened. You can choose a new shift on the board.",
          { exact: true },
        )
        .waitFor();
    }
    if (
      await page.evaluate(
        () => document.documentElement.scrollWidth > innerWidth,
      )
    )
      throw Error("Management page overflow");
    console.log("PASS: management link " + process.env.EMAIL_ACTION);
  } finally {
    await browser.close();
  }
})().catch(() => {
  console.error("Management browser check failed (private link omitted).");
  process.exit(1);
});
