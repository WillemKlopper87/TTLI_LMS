import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";

/**
 * The Institute skin (`lib/skin.ts`, the `[data-skin="institute"]` block
 * in globals.css) gets the same accessibility gate the default skin has.
 *
 * A skin is a colour and geometry swap, which is exactly the kind of
 * change that quietly breaks contrast — the palette it comes from had
 * six values failing WCAG before they were re-stepped, so "it looked
 * fine in the mockup" is not evidence. Running axe under the second skin
 * is what keeps that true after the next token edit.
 *
 * These run whether or not NEXT_PUBLIC_SKIN_SWITCHER is set: the switch
 * is a demo affordance, but the skin itself is always reachable by
 * cookie, so it is always something a person can be looking at.
 */
const PAGES = [
  { path: "/", name: "home" },
  { path: "/catalogue", name: "catalogue" },
  { path: "/login", name: "login" },
];

test.beforeEach(async ({ context, baseURL }) => {
  await context.addCookies([
    {
      name: "ttli_skin",
      value: "institute",
      url: baseURL ?? "http://localhost:3011",
    },
  ]);
});

test("the cookie reaches the first paint, not a hydration correction", async ({
  page,
}) => {
  // Read from the server's own HTML rather than the live DOM: the point
  // of stamping data-skin server-side is that there is never a frame of
  // the other skin, and only the raw response can show that.
  const response = await page.goto("/");
  const html = (await response?.text()) ?? "";
  expect(html).toContain('data-skin="institute"');
});

for (const page_ of PAGES) {
  test(`${page_.name} renders under the institute skin`, async ({ page }) => {
    const response = await page.goto(page_.path);
    expect(response?.status(), `${page_.path} should not error`).toBeLessThan(
      400,
    );
    await expect(page.locator("header").first()).toBeVisible();

    // The three things the direction is: its own serif, square corners,
    // and warm paper. If a future edit drops the skin block entirely the
    // page would still render and still pass axe — this is what notices.
    const applied = await page.evaluate(() => {
      const style = getComputedStyle(document.body);
      return {
        skin: document.documentElement.dataset.skin,
        radius: style.getPropertyValue("--r").trim(),
        stone: style.getPropertyValue("--stone").trim(),
        serif: style.getPropertyValue("--serif").trim(),
      };
    });
    expect(applied.skin).toBe("institute");
    expect(applied.radius).toBe("0");
    expect(applied.stone).toBe("#f6f4ef");
    expect(applied.serif).toContain("Newsreader");
  });

  test(`${page_.name} has no WCAG A/AA violations under the institute skin`, async ({
    page,
  }) => {
    await page.goto(page_.path);
    const results = await new AxeBuilder({ page })
      .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"])
      .analyze();
    const summary = results.violations.map(
      (v) =>
        `${v.id}: ${v.help} -> ${v.nodes.map((n) => n.target.join(" ")).join(" | ")}`,
    );
    expect(summary, `axe violations on ${page_.path} (institute skin)`).toEqual(
      [],
    );
  });
}

test("the brand colour still comes from the tenant, not the skin", async ({
  page,
}) => {
  // The handoff is explicit that every red must resolve from the tenant
  // theme. A skin that hardcoded #8E151C would look identical on the
  // demo tenant and wrong on every other one.
  await page.goto("/");
  const brand = await page.evaluate(() =>
    getComputedStyle(document.body).getPropertyValue("--brand-primary").trim(),
  );
  const inline = await page.evaluate(
    () => document.body.getAttribute("style") ?? "",
  );
  expect(brand).not.toBe("");
  expect(inline).toContain("--brand-primary");
});
