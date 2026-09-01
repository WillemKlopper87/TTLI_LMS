import { headers } from "next/headers";

/**
 * The current request's own origin, resolved from its Host header — same
 * source getTheme() reads for X-Tenant-Host. Needed because this is a
 * white-label platform: metadataBase/canonical/sitemap URLs must reflect
 * whichever tenant host actually served the request (localhost in dev,
 * ttli.co.za in production, another tenant's domain elsewhere), not a
 * single hardcoded production domain.
 */
export async function getSiteUrl(): Promise<string> {
  const host = (await headers()).get("host") ?? "localhost:3010";
  const protocol = host.startsWith("localhost") || host.startsWith("127.0.0.1") ? "http" : "https";
  return `${protocol}://${host}`;
}
