import Link from "next/link";

export const metadata = {
  title: "Page not found",
};

export default function NotFound() {
  return (
    <main className="pad-lg" style={{ textAlign: "center" }}>
      <div style={{ maxWidth: "32rem", marginInline: "auto" }}>
        <p className="eyebrow">404</p>
        <h1 className="serif" style={{ fontSize: "2rem", marginTop: "0.5rem" }}>
          We couldn&rsquo;t find that page.
        </h1>
        <p style={{ color: "var(--muted)", marginTop: "1rem" }}>
          The page you&rsquo;re looking for may have moved, been renamed, or never existed.
        </p>
        <div
          style={{
            marginTop: "2rem",
            display: "flex",
            gap: "1rem",
            justifyContent: "center",
            flexWrap: "wrap",
          }}
        >
          <Link href="/" className="btn btn--primary btn--lg">
            Back to home
          </Link>
          <Link href="/catalogue" className="btn btn--ghost btn--lg">
            Browse courses
          </Link>
        </div>
      </div>
    </main>
  );
}
