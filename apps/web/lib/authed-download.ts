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
import { authedFetch } from "@/lib/authed-fetch";

export async function authedDownload(
  url: string,
  filename: string,
  { open = false }: { open?: boolean } = {},
): Promise<boolean> {
  const resp = await authedFetch(url).catch(() => null);
  if (!resp || !resp.ok) return false;

  // Prefer the name the API put on the file (the BFF forwards
  // Content-Disposition): for an arbitrary learner upload the caller
  // can't know the original filename or extension, and saving
  // "submission-<uuid>" with no extension leaves the grader guessing
  // what will open it. `filename` stays as the fallback.
  const disposition = resp.headers.get("content-disposition") ?? "";
  const served = /filename="([^"]+)"/.exec(disposition)?.[1];

  const objectUrl = URL.createObjectURL(await resp.blob());
  if (open) {
    window.open(objectUrl, "_blank", "noopener");
  } else {
    const anchor = document.createElement("a");
    anchor.href = objectUrl;
    anchor.download = served || filename;
    document.body.appendChild(anchor);
    anchor.click();
    anchor.remove();
  }
  // Revoking immediately would race the new tab's own load.
  window.setTimeout(() => URL.revokeObjectURL(objectUrl), 60_000);
  return true;
}
