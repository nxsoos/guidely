import { test, expect, type Page } from "@playwright/test";

const answer = (conversation = "new-conversation", text = "Contact the Service Desk [1].") => ({
  answer: text,
  conversation_id: conversation,
  references: [{ source_id: "1", document_id: "policy", filename: "it-support.md", chunk_id: "policy-0", snippet: "Contact the Service Desk.", page: null, section: "Support", score: 0.9 }],
  passages: [],
  elapsed_ms: 3000,
});

async function login(page: Page) {
  await page.route("**/api/documents", (route) => route.fulfill({ json: [] }));
  await page.route("**/api/conversations", (route) => route.fulfill({ json: [] }));
  await page.goto("/");
  await page.getByLabel("Username", { exact: true }).fill("admin");
  await page.getByLabel("Password", { exact: true }).fill("browser-test-password");
  await page.getByRole("button", { name: /^Sign in/ }).click();
  await expect(page.getByRole("heading", { name: "Ask your knowledge" })).toBeVisible();
}

test("sent questions appear immediately and gain one answer after the wait", async ({ page }) => {
  let release!: () => void;
  const gate = new Promise<void>((resolve) => { release = resolve; });
  let requests = 0;
  let historyReads = 0;
  await page.route("**/api/conversations/new-conversation", async (route) => {
    historyReads += 1;
    await route.fulfill({ json: { id: "new-conversation", title: "Support", messages: [] } });
  });
  await page.route("**/api/questions", async (route) => {
    requests += 1;
    expect(route.request().postDataJSON()).toEqual({ question: "How do I contact support?", conversation_id: null, category: "", tags: [] });
    await gate;
    await route.fulfill({ json: answer() });
  });
  await login(page);
  const composer = page.getByLabel("Your question", { exact: true });
  await composer.fill("How do I contact support?");
  await composer.press("Enter");
  await expect(page.locator(".question-bubble")).toHaveText(/How do I contact support\?/);
  await expect(page.locator(".exchange")).toHaveCount(1);
  await expect(page.locator(".welcome")).toHaveCount(0);
  await expect(composer).toHaveValue("");
  await expect(composer).toBeDisabled();
  await expect(page.getByLabel("Category filter")).toBeDisabled();
  await expect(page.getByLabel("Tag filter")).toBeDisabled();
  await expect(page.locator(".exchange [role=status]")).toContainText("Finding passages");
  await page.locator(".composer").evaluate((form: HTMLFormElement) => form.requestSubmit());
  expect(requests).toBe(1);
  release();
  await expect(page.locator(".answer-text")).toHaveText("Contact the Service Desk [1].");
  await expect(page.locator(".exchange")).toHaveCount(1);
  await expect(page.locator(".question-bubble")).toHaveCount(1);
  await expect(page.locator(".exchange [role=status]")).toHaveCount(0);
  await expect(page.locator(".answer > .source-card")).toHaveCount(1);
  await expect(composer).toBeEnabled();
  expect(historyReads).toBe(0);
});

test("a failed send keeps the question and retries the same turn", async ({ page }) => {
  let requests = 0;
  await page.route("**/api/questions", async (route) => {
    requests += 1;
    expect(route.request().postDataJSON().question).toBe("Can I contact support at 5 PM?");
    if (requests === 1) await route.fulfill({ status: 429, json: { error: { message: "Please wait and retry." } } });
    else await route.fulfill({ json: answer() });
  });
  await login(page);
  const composer = page.getByLabel("Your question", { exact: true });
  await composer.fill("Can I contact support at 5 PM?");
  await composer.press("Enter");
  await expect(page.locator(".question-bubble")).toContainText("Can I contact support at 5 PM?");
  await expect(page.locator(".exchange [role=alert]")).toHaveText("Please wait and retry.");
  await expect(composer).toBeEnabled();
  await expect(composer).toHaveValue("");
  await page.getByRole("button", { name: "Retry question" }).click();
  await expect(page.locator(".answer-text")).toHaveText("Contact the Service Desk [1].");
  await expect(page.locator(".exchange")).toHaveCount(1);
  await expect(page.locator(".exchange [role=alert]")).toHaveCount(0);
  expect(requests).toBe(2);
});

test("new conversation resets a first pending question and ignores its late response", async ({ page }) => {
  let release!: () => void;
  const gate = new Promise<void>((resolve) => { release = resolve; });
  let finishOld!: () => void;
  const oldFinished = new Promise<void>((resolve) => { finishOld = resolve; });
  await page.route("**/api/questions", async (route) => {
    if (route.request().postDataJSON().question === "Old question") {
      await gate;
      await route.fulfill({ json: answer("old-chat", "Old answer [1].") }).catch(() => {});
      finishOld();
    } else await route.fulfill({ json: answer("fresh-chat", "Fresh answer [1].") });
  });
  await login(page);
  const composer = page.getByLabel("Your question", { exact: true });
  await composer.fill("Old question");
  await composer.press("Enter");
  await expect(page.locator(".question-bubble")).toContainText("Old question");
  await page.getByRole("button", { name: "New conversation", exact: false }).click();
  await expect(page.locator(".welcome")).toBeVisible();
  await expect(composer).toBeEnabled();
  await composer.fill("Fresh question");
  await composer.press("Enter");
  await expect(page.locator(".answer-text")).toHaveText("Fresh answer [1].");
  release();
  await oldFinished;
  await expect(page.locator(".exchange")).toHaveCount(1);
  await expect(page.locator(".question-bubble")).toContainText("Fresh question");
  await expect(page.locator(".answer-text")).toHaveText("Fresh answer [1].");
});
