"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { getAccessToken } from "@/lib/session";

interface PriceSummary {
  id: string;
  currency: string;
  unit_amount: string;
  tax_behaviour: string;
}

interface ProductSummary {
  id: string;
  slug: string;
  name: string;
  description: string | null;
  kind: string;
  prices: PriceSummary[];
}

/**
 * The public catalogue (REQ-STORE-01), backed by the real products/prices
 * seeded in migration 0009 — not the prototype's invented course names.
 * "Enrol now" requires an account: guests land on /login (via /guest-access
 * if they don't have one yet), then are sent back to complete checkout.
 */
export default function CataloguePage() {
  const router = useRouter();
  const [products, setProducts] = useState<ProductSummary[] | null>(null);
  const [error, setError] = useState(false);

  useEffect(() => {
    fetch("/api/bff/products")
      .then(async (resp) => {
        if (!resp.ok) {
          setError(true);
          return;
        }
        setProducts((await resp.json()).items);
      })
      .catch(() => setError(true));
  }, []);

  function enrol(priceId: string) {
    if (!getAccessToken()) {
      router.push("/login");
      return;
    }
    router.push(`/checkout?price=${priceId}`);
  }

  return (
    <main className="mx-auto max-w-4xl px-6 py-16">
      <p className="eyebrow">Programmes</p>
      <h1 className="serif mt-2" style={{ fontSize: "1.75rem" }}>
        Browse the catalogue
      </h1>
      <p className="mt-2" style={{ fontSize: "0.8125rem", color: "var(--muted)" }}>
        Buying for a team?{" "}
        <Link href="/organisations" style={{ color: "var(--brand-ink)" }}>
          Manage your organisation
        </Link>
        .
      </p>

      {error ? (
        <p className="mt-6" style={{ fontSize: "0.875rem", color: "var(--muted)" }}>
          The catalogue could not be loaded. Try again shortly.
        </p>
      ) : products === null ? (
        <p className="mt-6" style={{ fontSize: "0.875rem", color: "var(--faint)" }}>
          Loading…
        </p>
      ) : products.length === 0 ? (
        <p className="mt-6" style={{ fontSize: "0.875rem", color: "var(--muted)" }}>
          No programmes are listed for sale yet.
        </p>
      ) : (
        <div className="mt-8 grid gap-4 md:grid-cols-2">
          {products.map((product) => (
            <div key={product.id} className="card p-5">
              <span className="tag tag--brand">{product.kind}</span>
              <h2 className="serif mt-2" style={{ fontSize: "1.0625rem" }}>
                {product.name}
              </h2>
              {product.description ? (
                <p className="mt-1" style={{ fontSize: "0.8125rem", color: "var(--muted)" }}>
                  {product.description}
                </p>
              ) : null}
              {product.prices.map((price) => (
                <div key={price.id} className="mt-4 flex items-center justify-between">
                  <span className="serif" style={{ fontSize: "1.0625rem" }}>
                    {price.currency} {Number(price.unit_amount).toLocaleString()}
                    <small style={{ fontSize: "0.6875rem", color: "var(--muted)", fontWeight: 400 }}>
                      {" "}
                      {price.tax_behaviour === "exclusive" ? "excl. VAT" : "incl. VAT"}
                    </small>
                  </span>
                  <button type="button" className="btn btn--primary" onClick={() => enrol(price.id)}>
                    Enrol now
                  </button>
                </div>
              ))}
            </div>
          ))}
        </div>
      )}
    </main>
  );
}
