import { expect, test, type APIRequestContext, type Page } from "@playwright/test";

const EMAIL = process.env.E2E_SURVEY_ADMIN_EMAIL ?? "survey-admin@example.com";
const PASSWORD = process.env.E2E_SURVEY_ADMIN_PASSWORD ?? "SmokeTest123!survey";

async function signIn(page: Page) {
  await page.goto("/login");
  await page.getByLabel(/email/i).fill(EMAIL);
  await page.getByLabel(/password/i).fill(PASSWORD);
  await page.getByRole("button", { name: /sign in|log ?in/i }).click();
  await page.waitForURL(/\/(admin|learn)/, { timeout: 30_000 });
}

async function createPair(request: APIRequestContext) {
  const login = await request.post("/api/bff/auth/login", {
    data: { email: EMAIL, password: PASSWORD },
  });
  if (!login.ok()) throw new Error(`admin login failed: ${login.status()} ${await login.text()}`);
  const token = ((await login.json()) as { access_token: string }).access_token;
  const headers = { Authorization: `Bearer ${token}` };
  const suffix = Math.random().toString(36).slice(2, 10);

  const preResponse = await request.post("/api/bff/surveys", {
    headers,
    data: {
      title: `Pre-course confidence ${suffix}`,
      response_mode: "anonymous",
      minimum_group_size: 5,
      evaluation_role: "pre",
    },
  });
  if (!preResponse.ok()) {
    throw new Error(`pre survey creation failed: ${preResponse.status()} ${await preResponse.text()}`);
  }
  const pre = (await preResponse.json()) as { id: string };

  const postResponse = await request.post("/api/bff/surveys", {
    headers,
    data: {
      title: `Post-course confidence ${suffix}`,
      response_mode: "anonymous",
      minimum_group_size: 5,
      evaluation_role: "post",
      paired_survey_id: pre.id,
    },
  });
  if (!postResponse.ok()) {
    throw new Error(`post survey creation failed: ${postResponse.status()} ${await postResponse.text()}`);
  }
  const post = (await postResponse.json()) as { id: string };

  return { postId: post.id, suffix };
}

test.beforeEach(async ({ request }) => {
  const probe = await request
    .get("/api/bff/public/workshops", { failOnStatusCode: false })
    .catch(() => null);
  test.skip(!probe || !probe.ok(), "no live API and seeded admin account available");
});

test("an admin can see a paired survey and its privacy-gated delta report", async ({ page, request }) => {
  const pair = await createPair(request);
  await signIn(page);

  await page.goto("/admin/surveys");
  const preRow = page.getByRole("row").filter({ hasText: `Pre-course confidence ${pair.suffix}` });
  const postRow = page.getByRole("row").filter({ hasText: `Post-course confidence ${pair.suffix}` });
  await expect(preRow.getByText("Pre-course", { exact: true })).toBeVisible();
  await expect(postRow.getByText("Post-course", { exact: true })).toBeVisible();

  await page.goto(`/admin/surveys/${pair.postId}/results`);
  await expect(page.getByText(/Both stages must reach their privacy threshold/)).toBeVisible();
  await expect(page.getByText("Pre: 0/5; post: 0/5.", { exact: false })).toBeVisible();
});
