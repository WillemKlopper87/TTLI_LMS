import { expect, test } from "@playwright/test";

import { authorAndSellAssessmentCourse } from "./fixtures/author-content";

/**
 * The learner player and completion rules, end to end through a real
 * browser: start a lesson, mark it complete, take a quiz, respond to a
 * survey, submit an assignment, and watch the curriculum unlock as each
 * one clears. This is the journey every other learner-side spec assumes
 * works — until now it had no browser coverage at all, only the pytest
 * integration suite's HTTP-level assertions.
 *
 * The course is authored fresh per run (see fixtures/author-content.ts)
 * rather than reused from a seed script, so re-running this spec never
 * collides with a previous run's completed lessons or exhausted quiz
 * attempts.
 *
 * Video-lesson coverage is deliberately out of scope here: a real video
 * asset needs the ffmpeg transcode pipeline (`apps/api/tests/
 * test_media.py`'s own `sample_video` fixture generates one via a real
 * ffmpeg subprocess), which this spec does not attempt to reproduce.
 * Flagged as a gap, not silently skipped.
 */
const CONTENT_EMAIL = process.env.E2E_CONTENT_EMAIL ?? "content-fixture@example.com";
const CONTENT_PASSWORD = process.env.E2E_CONTENT_PASSWORD ?? "SmokeTest123!content";
const LEARNER_EMAIL = process.env.E2E_ASSESS_EMAIL ?? "assess-learner@example.com";
const LEARNER_PASSWORD = process.env.E2E_ASSESS_PASSWORD ?? "SmokeTest123!assess";

test.beforeEach(async ({ request }) => {
  const probe = await request
    .get("/api/bff/public/workshops", { failOnStatusCode: false })
    .catch(() => null);
  test.skip(
    !probe || !probe.ok(),
    "no API on :8010 — start it (scripts/dev-up.sh + uvicorn) and seed " +
      "content-fixture@/assess-learner@ (scripts/seed_e2e_accounts.py)",
  );
});

test("a learner completes a document lesson, a quiz, a survey and an assignment", async ({
  page,
  request,
}) => {
  const fixture = await authorAndSellAssessmentCourse(request, {
    contentEmail: CONTENT_EMAIL,
    contentPassword: CONTENT_PASSWORD,
    learnerEmail: LEARNER_EMAIL,
    learnerPassword: LEARNER_PASSWORD,
  });

  await page.goto("/login");
  await page.getByLabel(/email/i).fill(LEARNER_EMAIL);
  await page.getByLabel(/password/i).fill(LEARNER_PASSWORD);
  await page.getByRole("button", { name: /sign in|log ?in/i }).click();
  await page.waitForURL(/\/(admin|learn)/, { timeout: 30_000 });

  await page.goto(`/learn/${fixture.enrolmentId}`);
  await expect(page.getByRole("heading", { name: "Read this first" })).toBeVisible();

  // --- Document lesson: start, then mark complete. ---
  await page.getByRole("button", { name: "Start lesson" }).click();
  await expect(page.getByText("In progress")).toBeVisible();
  await page.getByRole("button", { name: "Mark complete" }).click();

  // --- Quiz lesson: auto-advances here via next_lesson_id. ---
  await expect(page.getByRole("heading", { name: "Quick check" })).toBeVisible({
    timeout: 10_000,
  });
  await page.getByRole("button", { name: "Start lesson" }).click();
  await expect(page.getByText("What is 2 + 2?")).toBeVisible();
  await page.getByRole("button", { name: "4" }).click();
  await page.getByRole("button", { name: "Submit answers" }).click();
  await expect(page.getByText("Score: 100.00%")).toBeVisible();
  await expect(page.getByText("Passed.")).toBeVisible();
  await page.getByRole("button", { name: "Mark complete" }).click();

  // --- Survey lesson. ---
  await expect(page.getByRole("heading", { name: "Tell us more" })).toBeVisible({
    timeout: 10_000,
  });
  await page.getByRole("button", { name: "Start lesson" }).click();
  await page.getByLabel("What did you think?").fill("Genuinely useful.");
  await page.getByRole("button", { name: "Submit response" }).click();
  await expect(page.getByText("Thank you — your response has been recorded.")).toBeVisible();
  await page.getByRole("button", { name: "Mark complete" }).click();

  // --- Assignment lesson. ---
  await expect(page.getByRole("heading", { name: "Submit your work" })).toBeVisible({
    timeout: 10_000,
  });
  await page.getByRole("button", { name: "Start lesson" }).click();
  await page
    .getByLabel("Assignment file")
    .setInputFiles({ name: "work.txt", mimeType: "text/plain", buffer: Buffer.from("my work") });
  await page.getByRole("button", { name: "Submit assignment" }).click();
  await expect(page.getByText(/^Submitted \(version 1\)\.$/)).toBeVisible();
  await page.getByRole("button", { name: "Mark complete" }).click();

  // The course is now fully complete — the curriculum rail's own progress
  // indicator is the one server-computed number every lesson state feeds,
  // so it is the correctness check rather than re-deriving 100% by hand.
  await expect(page.getByText("100% complete")).toBeVisible({ timeout: 10_000 });
});
