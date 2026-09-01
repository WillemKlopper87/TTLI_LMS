import Link from "next/link";
import { notFound } from "next/navigation";
import ReactMarkdown from "react-markdown";

import { formatDate, joinMeta } from "@/lib/format";
import { getPublicArticle, getPublicCurriculum } from "@/lib/server-api";

import ArticleViewTracker from "./view-tracker";

/**
 * A published article (resources-hub design doc §2.3). Server-rendered,
 * unlike the podcast detail page — an article has no player state, so
 * the only thing that needs the browser is `ArticleViewTracker`
 * (R3: a "viewed" event now exists, for symmetry with podcasts' six),
 * kept as its own small client leaf so the page around it stays SSR.
 *
 * `body` is rendered through `react-markdown` rather than
 * `dangerouslySetInnerHTML` — it never touches raw HTML, so even though
 * this is author-authenticated content (podcast:manage-gated, the same
 * trust boundary show_notes/transcript already have), a compromised or
 * careless author account still can't inject a script tag into a reader's
 * page.
 */
export async function generateMetadata({ params }: { params: Promise<{ slug: string }> }) {
  const { slug } = await params;
  const article = await getPublicArticle(slug);
  if (!article) return { title: "Article" };
  return {
    title: article.title,
    description: article.dek ?? undefined,
    alternates: { canonical: `/resources/articles/${article.slug}` },
  };
}

export default async function ArticlePage({ params }: { params: Promise<{ slug: string }> }) {
  const { slug } = await params;
  const article = await getPublicArticle(slug);
  if (!article) notFound();

  const related = article.related_course_id
    ? await getPublicCurriculum(article.related_course_id)
    : null;

  const eyebrow = joinMeta([
    "Article",
    article.author_name ? `By ${article.author_name}` : null,
    article.published_at ? formatDate(article.published_at) : null,
    article.reading_minutes ? `${article.reading_minutes} min read` : null,
  ]);

  return (
    <main className="pad-lg">
      <ArticleViewTracker slug={slug} />
      <div className="article">
        <div>
          <p className="eyebrow">{eyebrow}</p>
          <h1
            className="serif"
            style={{
              fontSize: "clamp(1.6rem, 3.2vw, 2.3rem)",
              letterSpacing: "-0.018em",
              margin: "0.5rem 0 1.15rem",
            }}
          >
            {article.title}
          </h1>

          {article.dek ? (
            <div className="prose">
              <p className="lead">{article.dek}</p>
            </div>
          ) : null}

          <div className="prose" style={{ marginTop: "1.5rem" }}>
            <ReactMarkdown>{article.body}</ReactMarkdown>
          </div>

          <div className="gate" style={{ marginTop: "1.5rem" }}>
            <p className="eyebrow" style={{ color: "var(--brand-ink)" }}>
              More like this
            </p>
            <h4>Try a full sample lesson</h4>
            <p>
              One free lesson and a marked sample assessment. No card, no automatic renewal — we
              just need somewhere to send the sign-in link.
            </p>
            <Link
              href="/guest-access"
              className="btn btn--primary"
              style={{ justifySelf: "start" }}
            >
              Try a free lesson
            </Link>
          </div>
        </div>

        <aside style={{ display: "grid", gap: "1rem", alignContent: "start" }}>
          {article.author_name ? (
            <div className="aside-card">
              <p className="eyebrow">Written by</p>
              <h4 className="serif" style={{ fontSize: "1.0625rem" }}>
                {article.author_name}
              </h4>
            </div>
          ) : null}

          {article.related_course_id ? (
            <div className="aside-card">
              <p className="eyebrow">Related programme</p>
              <h4 className="serif" style={{ fontSize: "1.0625rem" }}>
                {related?.title ?? "The programme this comes from"}
              </h4>
              <Link
                href={`/courses/${article.related_course_id}`}
                className="btn btn--ghost btn--block"
              >
                View programme
              </Link>
            </div>
          ) : null}

          <div className="aside-card">
            <p className="eyebrow">Resources</p>
            <h4 className="serif" style={{ fontSize: "1.0625rem" }}>
              Everything else we publish
            </h4>
            <Link href="/resources" className="btn btn--ghost btn--block">
              Back to Resources
            </Link>
          </div>
        </aside>
      </div>
    </main>
  );
}
