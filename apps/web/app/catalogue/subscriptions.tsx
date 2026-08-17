"use client";

/**
 * Subscription products — the part of `GET /products` that has no course
 * of its own (`subscription_plan_id` set), which the `.course-grid`
 * above cannot represent. The CTA is unchanged from the previous
 * catalogue: a subscription needs an account, so a signed-out visitor
 * goes to /login first and comes back.
 */
import { useRouter } from "next/navigation";

import { formatMoney, vatSuffix } from "@/lib/format";
import type { PublicProduct } from "@/lib/server-api";
import { useSession } from "@/lib/session-context";

export function Subscriptions({ products }: { products: PublicProduct[] }) {
  const router = useRouter();
  const { status } = useSession();

  if (products.length === 0) return null;

  function subscribe(planId: string) {
    if (status !== "authenticated") {
      router.push("/login");
      return;
    }
    router.push(`/account/subscription?plan=${planId}`);
  }

  return (
    <div className="band">
      <div className="pad">
        <h2 className="serif" style={{ fontSize: "1.5rem", marginBottom: "0.35rem" }}>
          Subscriptions
        </h2>
        <p style={{ fontSize: "0.8125rem", color: "var(--muted)", marginBottom: "1.1rem" }}>
          Continuous access to a bundle of programmes, billed per period.
        </p>
        <div className="course-grid">
          {products.map((product) => (
            <div className="card" key={product.id} style={{ padding: "1.05rem", display: "grid", gap: "0.5rem" }}>
              <span className="tag tag--brand" style={{ justifySelf: "start" }}>
                Subscription
              </span>
              <h3 className="serif" style={{ fontSize: "1.0625rem" }}>
                {product.name}
              </h3>
              {product.description ? (
                <p style={{ fontSize: "0.8125rem", color: "var(--muted)" }}>{product.description}</p>
              ) : null}
              {product.bundled_courses?.length ? (
                <p style={{ fontSize: "0.75rem", color: "var(--muted)" }}>
                  Includes: {product.bundled_courses.join(", ")}
                </p>
              ) : null}
              {product.prices.map((price) => (
                <span className="ccard-price" key={price.id}>
                  {formatMoney(price.unit_amount, price.currency)}{" "}
                  <small>
                    {vatSuffix(price.tax_behaviour === "inclusive")} / period
                  </small>
                </span>
              ))}
              <button
                type="button"
                className="btn btn--primary"
                style={{ justifySelf: "start" }}
                onClick={() => subscribe(product.subscription_plan_id as string)}
              >
                Subscribe
              </button>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
