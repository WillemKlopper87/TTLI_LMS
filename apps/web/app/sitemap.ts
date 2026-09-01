import type { MetadataRoute } from "next";

import { FACILITATORS } from "@/lib/facilitators";
import {
  getPublicArticles,
  getPublicCourses,
  getPublicEpisodes,
  getPublicPaths,
} from "@/lib/server-api";
import { getSiteUrl } from "@/lib/site-url";

/**
 * Mirrors robots.ts's own boundary: only the pages that file leaves
 * crawlable for everyone. Functional/transactional routes (login,
 * guest-access, checkout, account, admin, auth) carry no SEO value and
 * are left out on purpose, same reasoning as that file's NEVER_CRAWLED
 * list — this is the "here are the good ones" complement to it.
 */
const STATIC_PAGES = [
  "/",
  "/catalogue",
  "/executive-programmes",
  "/cultivate-with-intent",
  "/lead-with-intent",
  "/for-organisations",
  "/workshops",
  "/resources",
  "/about",
  "/contact",
  "/paths",
  "/privacy",
  "/terms",
  "/faq",
];

export default async function sitemap(): Promise<MetadataRoute.Sitemap> {
  const [base, courses, paths, episodes, articles] = await Promise.all([
    getSiteUrl(),
    getPublicCourses(),
    getPublicPaths(),
    getPublicEpisodes(),
    getPublicArticles(),
  ]);

  return [
    ...STATIC_PAGES.map((path) => ({ url: `${base}${path}` })),
    ...FACILITATORS.map((f) => ({ url: `${base}/about/${f.slug}` })),
    // Course/path links use `id` — the routes are /courses/[courseId] and
    // /paths/[pathId], not slug-based (see catalogue/course-card.tsx and
    // paths/path-card.tsx, the same links learners actually click).
    ...courses.map((c) => ({ url: `${base}/courses/${c.id}` })),
    ...paths.map((p) => ({ url: `${base}/paths/${p.id}` })),
    ...episodes.map((e) => ({ url: `${base}/podcasts/${e.slug}` })),
    ...articles.map((a) => ({
      url: `${base}/resources/articles/${a.slug}`,
      lastModified: a.published_at ?? undefined,
    })),
  ];
}
