import type { APIRequestContext, APIResponse } from "@playwright/test";

/**
 * Builds a real, purchasable course with one lesson of each assessable
 * type (document, quiz, survey, assignment) via the actual HTTP API —
 * the same endpoints `apps/api/tests/test_catalogue.py::_author_course`
 * and the assessment router use — then buys it for a learner through the
 * real EFT flow (order -> checkout -> proof -> finance approval).
 *
 * No database bypass anywhere: every row this creates is the side effect
 * of a real request a real admin/learner would make, which is also why
 * this lives in e2e/fixtures rather than a seed script — a seed script
 * runs once against a shared dev database, this needs a fresh course per
 * spec run so re-running the suite doesn't collide with a previous run's
 * completed/attempted state.
 *
 * Verify these specs one file at a time locally (`npx playwright test
 * e2e/<file>.spec.ts`), the same as every other authenticated spec in
 * this suite — not `npm run test:e2e` with them all included. Login is
 * rate-limited both per-account (5/min) and per-IP (10/min,
 * `docs/03_API_SPEC.md`); four-plus spec files starting in parallel from
 * one machine, each logging in two or three times for its own fixture
 * setup and mid-test approval, blows past the per-IP ceiling even though
 * every individual account stays under its own. Not a concern in CI,
 * which never runs a live API for these specs at all (`.github/
 * workflows/ci.yml`'s own comment: "the authenticated spec skips itself,
 * loudly").
 */

async function check(resp: APIResponse, step: string): Promise<APIResponse> {
  if (!resp.ok()) {
    throw new Error(`fixture setup failed at "${step}": ${resp.status()} ${await resp.text()}`);
  }
  return resp;
}

async function login(request: APIRequestContext, email: string, password: string): Promise<string> {
  const resp = await check(
    await request.post("/api/bff/auth/login", { data: { email, password } }),
    `login as ${email}`,
  );
  return (await resp.json()).access_token as string;
}

function bearer(token: string) {
  return { Authorization: `Bearer ${token}` };
}

export interface AuthoredCourse {
  courseId: string;
  documentLessonId: string;
  quizLessonId: string;
  surveyLessonId: string;
  assignmentLessonId: string;
  correctOptionId: string;
  enrolmentId: string;
}

export async function authorAndSellAssessmentCourse(
  request: APIRequestContext,
  opts: {
    contentEmail: string;
    contentPassword: string;
    learnerEmail: string;
    learnerPassword: string;
  },
): Promise<AuthoredCourse> {
  const adminToken = await login(request, opts.contentEmail, opts.contentPassword);
  const adminAuth = bearer(adminToken);
  const suffix = Math.random().toString(36).slice(2, 10);

  const course = await (
    await check(
      await request.post("/api/bff/courses", {
        headers: adminAuth,
        data: { title: `E2E Assessment Course ${suffix}` },
      }),
      "create course",
    )
  ).json();

  const module_ = await (
    await check(
      await request.post(`/api/bff/courses/${course.id}/modules`, {
        headers: adminAuth,
        data: { title: "Foundations" },
      }),
      "create module",
    )
  ).json();

  const documentLesson = await (
    await check(
      await request.post(`/api/bff/modules/${module_.id}/lessons`, {
        headers: adminAuth,
        data: { title: "Read this first", body: "This is the reading material for the lesson." },
      }),
      "create document lesson",
    )
  ).json();

  const quizLesson = await (
    await check(
      await request.post(`/api/bff/modules/${module_.id}/lessons`, {
        headers: adminAuth,
        data: { title: "Quick check" },
      }),
      "create quiz lesson",
    )
  ).json();
  const quiz = await (
    await check(
      await request.post("/api/bff/quizzes", {
        headers: adminAuth,
        data: { title: "Quick check quiz", pass_score: 50, max_attempts: 3 },
      }),
      "create quiz",
    )
  ).json();
  const correctOptionId = "correct";
  await check(
    await request.post(`/api/bff/quizzes/${quiz.id}/questions`, {
      headers: adminAuth,
      data: {
        question_type: "single_choice",
        prompt: "What is 2 + 2?",
        options: [
          { id: "wrong", text: "3", correct: false },
          { id: correctOptionId, text: "4", correct: true },
        ],
        position: 1,
        points: 1,
      },
    }),
    "create quiz question",
  );
  await check(
    await request.post(`/api/bff/lessons/${quizLesson.id}/quiz?quiz_id=${quiz.id}`, {
      headers: adminAuth,
    }),
    "attach quiz to lesson",
  );

  const surveyLesson = await (
    await check(
      await request.post(`/api/bff/modules/${module_.id}/lessons`, {
        headers: adminAuth,
        data: { title: "Tell us more" },
      }),
      "create survey lesson",
    )
  ).json();
  const survey = await (
    await check(
      await request.post("/api/bff/surveys", {
        headers: adminAuth,
        data: { title: "Quick survey", response_mode: "identified" },
      }),
      "create survey",
    )
  ).json();
  await check(
    await request.post(`/api/bff/surveys/${survey.id}/questions`, {
      headers: adminAuth,
      data: { question_type: "long_text", prompt: "What did you think?", options: [], position: 1 },
    }),
    "create survey question",
  );
  await check(
    await request.post(`/api/bff/lessons/${surveyLesson.id}/survey?survey_id=${survey.id}`, {
      headers: adminAuth,
    }),
    "attach survey to lesson",
  );

  const assignmentLesson = await (
    await check(
      await request.post(`/api/bff/modules/${module_.id}/lessons`, {
        headers: adminAuth,
        data: { title: "Submit your work" },
      }),
      "create assignment lesson",
    )
  ).json();
  const assignment = await (
    await check(
      await request.post("/api/bff/assignments", {
        headers: adminAuth,
        data: { title: "Final piece", instructions: "Upload anything.", max_score: 100 },
      }),
      "create assignment",
    )
  ).json();
  await check(
    await request.post(
      `/api/bff/lessons/${assignmentLesson.id}/assignment?assignment_id=${assignment.id}`,
      { headers: adminAuth },
    ),
    "attach assignment to lesson",
  );

  await check(
    await request.post(`/api/bff/courses/${course.id}/publish`, { headers: adminAuth }),
    "publish course",
  );
  await check(
    await request.post(`/api/bff/courses/${course.id}/tenant-assignments`, {
      headers: adminAuth,
      data: { is_bespoke: false },
    }),
    "assign course to tenant",
  );

  const product = await (
    await check(
      await request.post("/api/bff/catalogue/products", {
        headers: adminAuth,
        data: {
          slug: `e2e-assess-${suffix}`,
          name: "E2E Assessment Course",
          description: "Fixture product for browser coverage.",
          course_id: course.id,
        },
      }),
      "create product",
    )
  ).json();
  const price = await (
    await check(
      await request.post(`/api/bff/catalogue/products/${product.id}/prices`, {
        headers: adminAuth,
        data: { currency: "ZAR", unit_amount: "10.00" },
      }),
      "create price",
    )
  ).json();
  await check(
    await request.patch(`/api/bff/catalogue/products/${product.id}`, {
      headers: adminAuth,
      data: { is_active: true },
    }),
    "activate product",
  );

  // Buy it for the learner via the real EFT path.
  const learnerToken = await login(request, opts.learnerEmail, opts.learnerPassword);
  const learnerAuth = bearer(learnerToken);
  const order = await (
    await check(
      await request.post("/api/bff/orders", {
        headers: { ...learnerAuth, "Idempotency-Key": `e2e-order-${suffix}` },
        data: {
          currency: "ZAR",
          customer_type: "individual",
          lines: [{ price_id: price.id, quantity: 1 }],
        },
      }),
      "create order",
    )
  ).json();
  const checkout = await (
    await check(
      await request.post(`/api/bff/orders/${order.id}/checkout/eft`, { headers: learnerAuth }),
      "checkout via EFT",
    )
  ).json();
  await check(
    await request.post(`/api/bff/orders/${order.id}/payment-proof`, {
      headers: learnerAuth,
      multipart: {
        file: { name: "proof.txt", mimeType: "text/plain", buffer: Buffer.from("proof") },
      },
    }),
    "upload payment proof",
  );
  await check(
    await request.post(`/api/bff/payments/${checkout.payment_id}/approve`, {
      headers: { ...adminAuth, "Idempotency-Key": `e2e-approve-${suffix}` },
    }),
    "approve payment",
  );

  const enrolments = await (
    await check(
      await request.get("/api/bff/enrolments", { headers: learnerAuth }),
      "list learner's enrolments",
    )
  ).json();
  const enrolment = enrolments.find((e: { course_id: string }) => e.course_id === course.id);
  if (!enrolment) throw new Error("fixture purchase did not produce an enrolment");

  return {
    courseId: course.id,
    documentLessonId: documentLesson.id,
    quizLessonId: quizLesson.id,
    surveyLessonId: surveyLesson.id,
    assignmentLessonId: assignmentLesson.id,
    correctOptionId,
    enrolmentId: enrolment.enrolment_id,
  };
}

export interface SellableCourse {
  courseId: string;
  title: string;
  priceId: string;
}

/** A published, priced, active course with nobody enrolled in it — for
 * specs that drive the purchase itself through the browser (checkout.spec.ts)
 * rather than needing it already bought (learner-assessment.spec.ts). */
export async function authorSellableCourse(
  request: APIRequestContext,
  opts: { contentEmail: string; contentPassword: string },
): Promise<SellableCourse> {
  const adminToken = await login(request, opts.contentEmail, opts.contentPassword);
  const adminAuth = bearer(adminToken);
  const suffix = Math.random().toString(36).slice(2, 10);
  const title = `E2E Checkout Course ${suffix}`;

  const course = await (
    await check(
      await request.post("/api/bff/courses", { headers: adminAuth, data: { title } }),
      "create course",
    )
  ).json();
  const module_ = await (
    await check(
      await request.post(`/api/bff/courses/${course.id}/modules`, {
        headers: adminAuth,
        data: { title: "Module 1" },
      }),
      "create module",
    )
  ).json();
  await check(
    await request.post(`/api/bff/modules/${module_.id}/lessons`, {
      headers: adminAuth,
      data: { title: "Lesson 1" },
    }),
    "create lesson",
  );
  await check(
    await request.post(`/api/bff/courses/${course.id}/publish`, { headers: adminAuth }),
    "publish course",
  );
  await check(
    await request.post(`/api/bff/courses/${course.id}/tenant-assignments`, {
      headers: adminAuth,
      data: { is_bespoke: false },
    }),
    "assign course to tenant",
  );

  const product = await (
    await check(
      await request.post("/api/bff/catalogue/products", {
        headers: adminAuth,
        data: {
          slug: `e2e-checkout-${suffix}`,
          name: title,
          description: "Fixture product for checkout browser coverage.",
          course_id: course.id,
        },
      }),
      "create product",
    )
  ).json();
  const price = await (
    await check(
      await request.post(`/api/bff/catalogue/products/${product.id}/prices`, {
        headers: adminAuth,
        data: { currency: "ZAR", unit_amount: "10.00" },
      }),
      "create price",
    )
  ).json();
  await check(
    await request.patch(`/api/bff/catalogue/products/${product.id}`, {
      headers: adminAuth,
      data: { is_active: true },
    }),
    "activate product",
  );

  return { courseId: course.id, title, priceId: price.id };
}

export interface PendingEftPayment {
  courseTitle: string;
  buyerEmail: string;
  paymentId: string;
  orderId: string;
}

/** A course, bought via EFT with proof already uploaded, sitting
 * unapproved in the finance queue — admin-finance.spec.ts drives the
 * *approval* itself through the browser, so the purchase that puts it
 * there is fixture setup, done via the API like everything else here. */
export async function authorAndSubmitPendingEftPayment(
  request: APIRequestContext,
  opts: {
    contentEmail: string;
    contentPassword: string;
    buyerEmail: string;
    buyerPassword: string;
  },
): Promise<PendingEftPayment> {
  const course = await authorSellableCourse(request, opts);

  const buyerToken = await login(request, opts.buyerEmail, opts.buyerPassword);
  const buyerAuth = bearer(buyerToken);
  const order = await (
    await check(
      await request.post("/api/bff/orders", {
        headers: { ...buyerAuth, "Idempotency-Key": `e2e-finance-order-${course.courseId}` },
        data: {
          currency: "ZAR",
          customer_type: "individual",
          lines: [{ price_id: course.priceId, quantity: 1 }],
        },
      }),
      "create order",
    )
  ).json();
  const checkout = await (
    await check(
      await request.post(`/api/bff/orders/${order.id}/checkout/eft`, { headers: buyerAuth }),
      "checkout via EFT",
    )
  ).json();
  await check(
    await request.post(`/api/bff/orders/${order.id}/payment-proof`, {
      headers: buyerAuth,
      multipart: {
        file: { name: "proof.txt", mimeType: "text/plain", buffer: Buffer.from("proof") },
      },
    }),
    "upload payment proof",
  );

  return {
    courseTitle: course.title,
    buyerEmail: opts.buyerEmail,
    paymentId: checkout.payment_id,
    orderId: order.id,
  };
}
