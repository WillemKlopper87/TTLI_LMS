/**
 * Fetch a file from the BFF with the bearer, then hand it to the browser.
 *
 * A plain `<a href="/api/bff/...">` cannot work for any authenticated
 * document: the access token lives in memory (lib/session.ts), not in a
 * cookie, so a browser-initiated navigation carries no Authorization
 * header and the API answers 401. The analytics CSV export learned this
 * first and solved it inline; this is that solution, extracted, because
 * P6 added three more of them (invoice PDF, invoices CSV, ledger CSV).
 *
 * `open` opens the object URL in a new tab instead of saving it — right
 * for a PDF the browser can render, wrong for a CSV.
 */
import { getAccessToken } from "@/lib/session";

export async function authedDownload(
  url: string,
  filename: string,
  { open = false }: { open?: boolean } = {},
): Promise<boolean> {
  const resp = await fetch(url, {
    headers: { Authorization: `Bearer ${getAccessToken() ?? ""}` },
  }).catch(() => null);
  if (!resp || !resp.ok) return false;

  const objectUrl = URL.createObjectURL(await resp.blob());
  if (open) {
    window.open(objectUrl, "_blank", "noopener");
  } else {
    const anchor = document.createElement("a");
    anchor.href = objectUrl;
    anchor.download = filename;
    document.body.appendChild(anchor);
    anchor.click();
    anchor.remove();
  }
  // Revoking immediately would race the new tab's own load.
  window.setTimeout(() => URL.revokeObjectURL(objectUrl), 60_000);
  return true;
}
