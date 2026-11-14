// Responsive UI regression using browser-local sample data; no shared bookings.
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || "playwright");
(async () => {
  const browser = await chromium.launch({ headless: true }),
    context = await browser.newContext();
  await context.route("**/config.js", (route) =>
    route.fulfill({
      contentType: "application/javascript",
      body: "window.TREAM_CONFIG={apiBase:null}",
    }),
  );
  const page = await context.newPage(),
    errors = [];
  page.on("pageerror", (error) => errors.push(error.message));
  try {
    for (const width of [320, 360, 390, 430, 768, 900, 1440]) {
      await page.setViewportSize({ width, height: 900 });
      await page.goto(process.env.SITE_URL || "http://127.0.0.1:8002");
      const overflow = await page.evaluate(
        () => document.documentElement.scrollWidth > innerWidth,
      );
      if ((await page.locator("h1").count()) !== 1)
        throw Error("Expected one event heading");
      await page
        .getByText("Volunteer signup · Organized by Brent PTA", { exact: true })
        .waitFor();
      if (overflow)
        throw Error("Page overflows horizontally at " + width + "px");
      if (width <= 900) {
        const dates = await page
          .locator("#days button")
          .evaluateAll((buttons) =>
            buttons.map((button) => {
              const rect = button.getBoundingClientRect();
              return {
                left: rect.left,
                right: rect.right,
                width: rect.width,
                height: rect.height,
              };
            }),
          );
        if (
          dates.length !== 6 ||
          dates.some(
            (box) => box.left < 0 || box.right > width || box.height < 44,
          )
        )
          throw Error(
            "Day choices are clipped or too small at " + width + "px",
          );
        if (
          await page
            .locator("#days")
            .evaluate((el) => el.scrollWidth > el.clientWidth)
        )
          throw Error(
            "Day choices need horizontal scrolling at " + width + "px",
          );

        await page.getByRole("button", { name: "Sat 05", exact: true }).click();
        const join = page.locator('.join[data-open="8"]');
        const box = await join.boundingBox();
        if (box.x < 0 || box.x + box.width > width || box.height < 44)
          throw Error(
            "Signup action is clipped or too small at " + width + "px",
          );
        const title = await page
          .locator('.job-title[data-open="8"]')
          .boundingBox();
        if (Math.abs(box.y - title.y) > 6 || box.x < title.x + title.width)
          throw Error("Mobile action should sit beside the shift title");
        if (await page.locator(".shift-row .people").count())
          throw Error("Summary roster previews should be removed");
        if (width === 390 || width === 430) {
          const countBefore = Number(
            (
              await join
                .locator("xpath=ancestor::tr")
                .locator(".coverage strong")
                .innerText()
            ).match(/\d+/)[0],
          );
          await join.click();
          if (await page.locator("#share").isChecked())
            throw Error("Name sharing should be the default");
          if (await page.getByRole("heading", { name: /Who’s coming/ }).count())
            throw Error("Unnecessary roster heading remains");
          await page.locator("#end").selectOption("11");
          await page.locator('[data-task][value="cashier"]').check();
          await page.locator('[data-task][value="tree-prep"]').check();
          await page.locator("#name").fill("Mobile Test");
          await page.locator("#email").fill("mobile@example.com");
          if (width === 430) await page.locator("#share").check();
          await page
            .getByRole("button", { name: "Sign up", exact: true })
            .click();
          await page
            .getByRole("heading", { name: "You’re on the Tream.", exact: true })
            .waitFor();
          await page
            .getByText(
              "Task preferences: Cashiering, Tree Prep (Chainsaw/Baling/Loading)",
              { exact: true },
            )
            .waitFor();
          await page
            .getByRole("button", { name: "Back to the board", exact: true })
            .click();
          const expectedName =
            width === 430 ? "Volunteer (name private)" : "Mobile T.";
          if (
            !(await page.evaluate(
              (expected) =>
                JSON.parse(localStorage.getItem("tream-board-demo")).some(
                  (entry) => entry.publicName === expected,
                ),
              expectedName,
            ))
          )
            throw Error("Signup name visibility did not match privacy choice");
          await page.reload();
          await page
            .getByRole("button", { name: "Sat 05", exact: true })
            .click();
          const countAfter = await page
            .locator('.join[data-open="8"]')
            .locator("xpath=ancestor::tr")
            .locator(".coverage strong")
            .innerText();
          if (
            Number(countAfter.match(/\d+/)[0]) !== countBefore + 1 ||
            /\d–\d/.test(countAfter)
          )
            throw Error("Partial signup should count as one whole volunteer");
          await page.locator("#mine").click();
          await page
            .getByRole("button", { name: "Cancel signup", exact: true })
            .click();
          await page
            .getByRole("button", { name: "Yes, cancel", exact: true })
            .click();
          await page
            .getByText("No demo signups yet.", { exact: false })
            .waitFor();
        }
      } else {
        if (!(await page.locator("thead").isVisible()))
          throw Error("Desktop spreadsheet headers missing");
      }
    }
    if (errors.length) throw Error(errors.join("\n"));
    console.log(
      "PASS: no page overflow at 320–1440px, mobile signup actions visible with touch targets, mobile signup/cancel, and desktop spreadsheet preserved.",
    );
  } finally {
    await browser.close();
  }
})().catch((error) => {
  console.error(error.message);
  process.exit(1);
});
