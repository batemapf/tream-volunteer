// Runs only with a short-lived synthetic account created by smoke_admin.py.
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || "playwright");
(async () => {
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({
    viewport: { width: 1440, height: 1000 },
  });
  const errors = [];
  let draftId = null;
  let previewDiagnostic = null;
  page.on("pageerror", (error) => errors.push(error.message));
  page.on("response", async (response) => {
    if (
      response.request().method() === "POST" &&
      response.url().endsWith("/admin/messages/preview")
    ) {
      const body = await response.json().catch(() => ({}));
      previewDiagnostic = {
        status: response.status(),
        recipientCount: body.recipientCount,
        volunteerCount: body.volunteerCount,
        code: body.code,
        message: body.message,
      };
    }

    if (
      response.request().method() === "POST" &&
      response.url().endsWith("/admin/messages") &&
      response.ok()
    ) {
      draftId = (await response.json()).id;
    }
  });
  try {
    await page.goto(process.env.SITE_URL + "/organizer.html");
    await page.locator("#username").fill(process.env.TREAM_TEST_USERNAME);
    await page.locator("#password").fill(process.env.TREAM_TEST_PASSWORD);
    await page.getByRole("button", { name: "Sign in", exact: true }).click();
    await page
      .getByRole("heading", { name: "Organizer desk", exact: true })
      .waitFor({ timeout: 30000 });
    await page.locator('[data-edit="0"]').click();
    await page.getByRole("button", { name: "Save shift", exact: true }).click();
    await page.locator("#dialog").waitFor({ state: "hidden", timeout: 30000 });
    await page.getByRole("button", { name: "Volunteers", exact: true }).click();
    await page.locator("#search").fill(process.env.TREAM_TEST_EMAIL);
    await page.locator("#select-all").check();
    await page
      .getByRole("button", { name: "Message selected (2)", exact: true })
      .click();
    await page.locator("#subject").fill("Browser smoke draft");
    await page
      .locator("#message-body")
      .fill("Synthetic test only. Do not send.");
    await page
      .getByRole("button", { name: "Preview recipients", exact: true })
      .click();
    await page
      .getByRole("heading", { name: "1 contact · 2 commitments", exact: true })
      .waitFor();
    await page
      .getByRole("button", {
        name: "Save draft · sending disabled",
        exact: true,
      })
      .click();
    await page
      .getByText("Private draft saved. No messages sent.", { exact: true })
      .waitFor();
    const saved = page
      .locator("#saved-drafts .a-recipient")
      .filter({ hasText: "Browser smoke draft" })
      .first();
    for (let i = 0; i < 6 && (await saved.count()) === 0; i++) {
      await page
        .getByRole("button", { name: "Refresh drafts", exact: true })
        .click();
      await page.waitForTimeout(500);
    }
    await saved
      .getByRole("button", { name: "Load draft", exact: true })
      .click();
    await page
      .getByRole("heading", { name: "Draft loaded", exact: true })
      .waitFor();
    await page.getByRole("button", { name: /^Overlaps/ }).click();
    await page.locator("#show-reviewed").check();
    const conflict = page
      .locator(".a-conflict")
      .filter({ hasText: process.env.TREAM_TEST_EMAIL });
    await conflict
      .getByRole("button", { name: "Update review", exact: true })
      .click();
    await page
      .getByRole("button", { name: "Save review", exact: true })
      .click();
    await page.locator("#dialog").waitFor({ state: "hidden" });
    await page.getByRole("button", { name: "Volunteers", exact: true }).click();
    const download = page.waitForEvent("download");
    await page
      .getByRole("button", { name: "Export filtered roster", exact: true })
      .click();
    if ((await download).suggestedFilename() !== "tream-roster.csv")
      throw new Error("CSV download missing");
    await page.setViewportSize({ width: 390, height: 844 });
    // Hold an authorized refresh in flight while signing out; stale data must stay hidden.
    let complete;
    const heldResponse = new Promise((resolve) => {
      complete = resolve;
    });
    await page.route("**/admin/overview", async (route) => {
      try {
        await new Promise((resolve) => setTimeout(resolve, 500));
        const response = await route.fetch();
        await route.fulfill({ response });
      } finally {
        complete();
      }
    });
    const refreshing = page.waitForRequest((request) =>
      request.url().endsWith("/admin/overview"),
    );
    await page.getByRole("button", { name: "Refresh", exact: true }).click();
    await refreshing;
    await page.getByRole("button", { name: "Sign out", exact: true }).click();
    await page
      .getByRole("heading", { name: "Organizer sign-in", exact: true })
      .waitFor();
    await heldResponse;
    await page.waitForTimeout(100);
    await page
      .getByRole("heading", { name: "Organizer sign-in", exact: true })
      .waitFor();
    if (
      (await page.locator("body").innerText()).includes(
        process.env.TREAM_TEST_EMAIL,
      )
    )
      throw new Error("Private data remained after logout");
    if (errors.length) throw new Error(errors.join("\n"));
    console.log(
      "PASS: organizer browser login, shift edit, contact selection, recipient preview, draft, overlap review, CSV and logout.",
    );
  } catch (error) {
    console.error(
      JSON.stringify({
        previewDiagnostic,
        previewHeading: await page
          .locator("#message-preview h2")
          .allTextContents(),
        messageError: await page
          .locator("#message-error")
          .textContent()
          .catch(() => null),
        invalidFields: await page
          .locator("#message-form :invalid")
          .evaluateAll((nodes) => nodes.map((n) => n.id)),
      }),
    );
    throw error;
  } finally {
    await browser.close();
    // Report even on failure so the Python harness can delete the synthetic draft.
    console.log(JSON.stringify({ browserDraftId: draftId }));
  }
})().catch((error) => {
  console.error(error.message);
  process.exit(1);
});
