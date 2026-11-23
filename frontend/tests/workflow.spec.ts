import { test, expect, type Page } from "@playwright/test";
import path from "node:path";

async function login(page: Page, username: string) {
  await page.goto("/");
  await page.getByLabel("Username", { exact: true }).fill(username);
  await page
    .getByLabel("Password", { exact: true })
    .fill("browser-test-password");
  await page.getByRole("button", { name: "Sign in →" }).click();
  await expect(
    page.getByRole("heading", { name: "Ask your knowledge" }),
  ).toBeVisible();
}

test("admin and reader complete the knowledge workflow", async ({
  page,
  browser,
}) => {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await login(page, "admin");
  await page.screenshot({
    path: test.info().outputPath("desktop.png"),
    fullPage: true,
  });
  await page
    .getByRole("button", { name: "Documents", exact: false })
    .first()
    .click();
  for (const filename of [
    "leave-policy.md",
    "it-support.md",
    "onboarding.md",
    "expenses.md",
    "security.md",
  ]) {
    await page
      .getByLabel("Upload document", { exact: true })
      .setInputFiles(path.resolve("..", "data", "sample-docs", filename));
    const row = page.locator(".document-row").filter({
      has: page.getByRole("heading", { name: filename, exact: true }),
    });
    await expect(row).toBeVisible();
    await row.getByRole("button", { name: "Index", exact: true }).click();
    await expect(row.locator(".status")).toHaveText("ready");
  }
  await page.screenshot({
    path: test.info().outputPath("documents.png"),
    fullPage: true,
  });
  const leave = page.locator(".document-row").filter({
    has: page.getByRole("heading", { name: "leave-policy.md", exact: true }),
  });
  await leave.getByRole("button", { name: "Edit", exact: true }).click();
  await page.getByLabel("Category", { exact: true }).fill("People");
  await page.getByLabel("Tags (comma separated)").fill("hr, policy");
  await page.getByRole("button", { name: "Save changes" }).click();
  await expect(page.locator(".notice.success")).toContainText("Saved");
  await page
    .getByRole("button", { name: "Ask Guidely", exact: false })
    .first()
    .click();
  await page.getByLabel("Category filter").selectOption("People");
  await page.getByLabel("Tag filter").selectOption("hr");
  await page
    .getByLabel("Your question", { exact: true })
    .fill("How many annual leave days do I get?");
  await page
    .getByRole("button", { name: "Ask Guidely ↑", exact: true })
    .click();
  await expect(page.locator(".answer-text")).toContainText("25");
  await page
    .locator(".answer > .source-card")
    .first()
    .locator("summary")
    .click();
  await expect(
    page.locator(".answer > .source-card").first().locator(".snippet"),
  ).toBeVisible();
  await page
    .getByLabel("Your question", { exact: true })
    .fill("How do I request it?");
  await page
    .getByRole("button", { name: "Ask Guidely ↑", exact: true })
    .click();
  await expect(page.locator(".exchange")).toHaveCount(2);
  await page.reload();
  await page.locator(".recent-row").first().getByRole("button").first().click();
  await expect(page.locator(".exchange")).toHaveCount(2);
  await page
    .getByRole("button", { name: "People & access", exact: false })
    .click();
  await page.getByLabel("Username", { exact: true }).fill("newreader");
  await page.getByLabel("Temporary password").fill("new-reader-password");
  await page
    .getByRole("combobox", { name: "Role", exact: true })
    .selectOption("reader");
  await page.getByRole("button", { name: "Create account" }).click();
  await expect(
    page.locator(".member-row").filter({ hasText: "newreader" }),
  ).toBeVisible();
  await page.screenshot({
    path: test.info().outputPath("accounts.png"),
    fullPage: true,
  });
  await page.getByRole("button", { name: "Activity", exact: false }).click();
  await expect(page.locator(".metric").first()).toBeVisible();
  await page.screenshot({
    path: test.info().outputPath("activity.png"),
    fullPage: true,
  });
  const downloadPromise = page.waitForEvent("download");
  await page.getByRole("link", { name: "Export query logs (CSV) ↓" }).click();
  const download = await downloadPromise;
  expect(download.suggestedFilename()).toBe("guidely-query-logs.csv");
  await page
    .getByRole("button", { name: "Documents", exact: false })
    .first()
    .click();
  await leave.getByRole("button", { name: "Edit", exact: true }).click();
  await page
    .getByLabel("Extracted document text")
    .fill(
      "# Updated leave\nEmployees receive 30 annual leave days. Apply in the People Portal.",
    );
  await page.getByRole("button", { name: "Save changes" }).click();
  await expect(leave.locator(".status")).toHaveText("changed");
  await leave.getByRole("button", { name: "Index", exact: true }).click();
  await expect(leave.locator(".status")).toHaveText("ready");
  const readerContext = await browser.newContext();
  const reader = await readerContext.newPage();
  await login(reader, "reader");
  await expect(
    reader.getByRole("button", { name: "People & access", exact: false }),
  ).toHaveCount(0);
  await expect(reader.locator(".recent-row")).toHaveCount(0);
  await reader
    .getByLabel("Your question", { exact: true })
    .fill("annual leave days");
  await reader
    .getByRole("button", { name: "Ask Guidely ↑", exact: true })
    .click();
  await expect(reader.locator(".answer-text")).toBeVisible();
  await reader
    .getByRole("button", { name: "Documents", exact: false })
    .first()
    .click();
  await expect(reader.getByLabel("Upload document")).toHaveCount(0);
  await reader
    .getByRole("button", { name: "View", exact: true })
    .first()
    .click();
  await expect(reader.getByLabel("Extracted document text")).toHaveAttribute(
    "readonly",
    "",
  );
  await readerContext.close();
  await page.setViewportSize({ width: 390, height: 844 });
  await page
    .getByRole("button", { name: "Ask Guidely", exact: false })
    .first()
    .click();
  await expect(page.getByLabel("Your question", { exact: true })).toBeVisible();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBeTruthy();
  expect(errors).toEqual([]);
  for (const width of [375, 768, 1440]) {
    await page.setViewportSize({ width, height: 900 });
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= window.innerWidth,
      ),
    ).toBeTruthy();
  }
  await page.setViewportSize({ width: 390, height: 844 });
  await page.screenshot({
    path: test.info().outputPath("mobile.png"),
    fullPage: true,
  });
});

test("friendly authentication and upload errors", async ({ page }) => {
  await page.goto("/");
  await expect(
    page.getByRole("heading", { name: "Welcome to Guidely" }),
  ).toBeVisible();
  await page.screenshot({
    path: test.info().outputPath("login.png"),
    fullPage: true,
  });
  await page.getByLabel("Username", { exact: true }).fill("admin");
  await page.getByLabel("Password", { exact: true }).fill("incorrect-password");
  await page.getByRole("button", { name: "Sign in →" }).click();
  await expect(page.getByRole("alert")).toContainText("incorrect");
  await page
    .getByLabel("Password", { exact: true })
    .fill("browser-test-password");
  await page.getByRole("button", { name: "Sign in →" }).click();
  await page
    .getByRole("button", { name: "Documents", exact: false })
    .first()
    .click();
  await page.getByLabel("Upload document", { exact: true }).setInputFiles({
    name: "broken.pdf",
    mimeType: "application/pdf",
    buffer: Buffer.from("not a PDF"),
  });
  await expect(page.getByRole("alert")).toContainText("could not be read");
  await page.getByRole("button", { name: "Sign out" }).click();
  await expect(
    page.getByRole("heading", { name: "Welcome to Guidely" }),
  ).toBeVisible();
});
