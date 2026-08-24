import type { MetadataRoute } from "next";

/**
 * R8 (docs/BACKLOG.md; docs/research/devsecops-deployment.md §6.5's
 * "do now, cheap, real value" #1). Two different audiences, two
 * different rules:
 *
 * - Real search engines and human-driven AI fetch (Googlebot,
 *   Bingbot, ChatGPT-User — a user pasting a course link into an
 *   assistant) are left free to index the public marketing/content
 *   pages, same as before this file existed.
 * - AI-training crawlers (GPTBot, CCBot, ClaudeBot's training
 *   behaviour, Google-Extended) are disallowed from the paid-content
 *   asset class specifically — course pages, the free-preview lesson
 *   player, the learner course player, path/podcast/article content —
 *   the 2026 pattern the research doc cites at ~88% of major
 *   publishers: block training, allow discovery.
 *
 * Every path below is disallowed for everyone regardless of bot type
 * — admin, account, checkout, auth and the API are functional surfaces
 * with no SEO value and nothing a crawler should ever reach signed
 * out (access itself is still enforced server-side; this is hygiene,
 * not the control).
 *
 * No trailing slash: a robots.txt `Disallow` is a prefix match, and
 * several of these routes (`/admin`, `/checkout`, `/organisations`,
 * `/learn`, `/paths`, `/podcasts`, `/resources`, `/workshops`) have a
 * bare top-level page in addition to nested ones — `/admin/` alone
 * would silently leave the bare `/admin` dashboard crawlable.
 */
const NEVER_CRAWLED = [
  "/admin",
  "/account",
  "/api",
  "/auth",
  "/checkout",
  "/login",
  "/organisations",
  "/verify",
  "/unsubscribe",
];

// The paid-content asset class (§6.5's own three examples: course
// pages, lesson-shaped content, anything backed by private storage)
// plus this platform's other substantive content types — a learning
// path page, a podcast episode, an article — since the same "don't
// train on it, do let people find it" reasoning applies to all of them.
const TRAINING_DATA_OFF_LIMITS = [
  "/courses",
  "/preview",
  "/learn",
  "/paths",
  "/podcasts",
  "/resources",
  "/workshops",
];

const AI_TRAINING_USER_AGENTS = ["GPTBot", "CCBot", "ClaudeBot", "Google-Extended"];

export default function robots(): MetadataRoute.Robots {
  return {
    rules: [
      { userAgent: "*", disallow: NEVER_CRAWLED },
      ...AI_TRAINING_USER_AGENTS.map((userAgent) => ({
        userAgent,
        disallow: [...NEVER_CRAWLED, ...TRAINING_DATA_OFF_LIMITS],
      })),
    ],
  };
}
