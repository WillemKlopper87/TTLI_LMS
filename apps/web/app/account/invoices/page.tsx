"use client";

import { useCallback, useEffect, useState } from "react";

import { authedDownload } from "@/lib/authed-download";
import { getAccessToken } from "@/lib/session";
import { useRequireAuth } from "@/lib/session-context";

/**
 * A buyer's own invoices (backlog P6, feature-matrix gap #34).
 *
 * Invoicing has been gapless and ledger-backed since Phase 3, and until
 * now none of that was visible to the person who paid: there was no way
 * to fetch the tax invoice for something you had bought. This page is
 * that, and nothing more — reading your own documents needs no
 * permission, so there is no permission check here or on the endpoint.
 *
 * The PDF is fetched with the bearer and opened as an object URL, not
 * linked directly: the access token lives in memory, so a plain <a href>
 * navigation would carry no Authorization header and get a 401 — see
 * lib/authed-download.ts.
 */

interface InvoiceItem {
  description: string;
  quantity: number;
  unit_amount: string;
  tax_amount: string;
  line_total: string;
}

interface Invoice {
  id: string;
  number: string;
  status: string;
  issued_at: string;
  currency: string;
  subtotal: string;
  tax_total: string;
  grand_total: string;
  items: InvoiceItem[];
}

function money(currency: string, amount: string): string {
  const value = Number(amount);
  const symbol = currency === "ZAR" ? "R" : `${currency} `;
  return `${symbol}${value.toLocaleString("en-ZA", { minimumFractionDigits: 2 })}`;
}

export default function MyInvoices() {
  const { ready } = useRequireAuth();
  const [invoices, setInvoices] = useState<Invoice[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const resp = await fetch("/api/bff/invoices", {
        headers: { Authorization: `Bearer ${getAccessToken() ?? ""}` },
      });
      if (!resp.ok) {
        setError("Your invoices could not be loaded.");
        return;
      }
      setInvoices(((await resp.json()) as { items: Invoice[] }).items);
      setError(null);
    } catch {
      setError("Your invoices could not be loaded.");
    }
  }, []);

  useEffect(() => {
    if (ready) void load();
  }, [ready, load]);

  return (
    <main className="pad-lg">
      <div>
        <h1 className="serif" style={{ fontSize: "1.5rem" }}>
          Invoices
        </h1>
        <p className="mt-1" style={{ fontSize: "0.8125rem", color: "var(--muted)" }}>
          Every tax invoice issued to you, newest first.
        </p>

        {error ? (
          <div className="callout callout--warn mt-3" role="status">
            {error}
          </div>
        ) : null}

        {invoices !== null && invoices.length === 0 ? (
          <p className="mt-3" style={{ fontSize: "0.8125rem", color: "var(--muted)" }}>
            You have no invoices yet. One is issued when a payment is approved.
          </p>
        ) : null}

        {invoices && invoices.length > 0 ? (
          <div className="table-wrap mt-3">
            <table>
              <thead>
                <tr>
                  <th scope="col">Invoice</th>
                  <th scope="col">Issued</th>
                  <th scope="col">Status</th>
                  <th scope="col">VAT</th>
                  <th scope="col">Total</th>
                  <th scope="col">Document</th>
                </tr>
              </thead>
              <tbody>
                {invoices.map((invoice) => (
                  <tr key={invoice.id}>
                    <td className="mono" style={{ fontSize: "0.75rem" }}>
                      {invoice.number}
                    </td>
                    <td style={{ whiteSpace: "nowrap" }}>
                      {new Date(invoice.issued_at).toLocaleDateString("en-ZA", {
                        day: "2-digit",
                        month: "short",
                        year: "numeric",
                      })}
                    </td>
                    <td>
                      <span className="tag">{invoice.status}</span>
                    </td>
                    <td style={{ fontVariantNumeric: "tabular-nums" }}>
                      {money(invoice.currency, invoice.tax_total)}
                    </td>
                    <td style={{ fontVariantNumeric: "tabular-nums" }}>
                      {money(invoice.currency, invoice.grand_total)}
                    </td>
                    <td>
                      <button
                        type="button"
                        className="btn btn--quiet"
                        onClick={() => {
                          void authedDownload(
                            `/api/bff/invoices/${invoice.id}/pdf`,
                            `invoice-${invoice.number}.pdf`,
                            { open: true },
                          ).then((ok) => {
                            if (!ok) setError("That invoice PDF could not be opened.");
                          });
                        }}
                      >
                        PDF
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : null}
      </div>
    </main>
  );
}
