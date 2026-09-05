/**
 * Tenant theme assets, made safe to hand to the browser.
 *
 * `GET /tenant/theme` returns `logo_url` as a path relative to the API's
 * own root — `/api/v1/tenant/branding/logo` for a tenant that uploaded
 * one through the Branding panel, or whatever site path a migration
 * seeded (`/brand/ttli-logo.png`). The browser never reaches the API
 * directly (proxy.ts: the BFF is the only path in), so the `/api/v1`
 * prefix has to become `/api/bff` before anything renders it.
 *
 * The fallback matters as much as the mapping. Before this existed the
 * API returned a bare storage key (`tenant-branding/<id>/logo.png`) and
 * every consumer fed it straight to `next/image`, which throws for any
 * src that is neither root-relative nor allow-listed in
 * `next.config.ts` — a render-time throw with no error boundary above
 * it, so uploading a logo 500'd `/login` and the admin shell for that
 * whole tenant (fable5.1 review H-16). The API no longer emits keys, but
 * a value this function cannot vouch for now resolves to null — the
 * callers all fall back to the tenant's name in text — rather than
 * being passed through to crash a page.
 */

const API_PREFIX = "/api/v1/";
const BFF_PREFIX = "/api/bff/";

export function browserThemeAssetUrl(raw: string | null | undefined): string | null {
  if (!raw) return null;
  if (raw.startsWith(API_PREFIX)) return `${BFF_PREFIX}${raw.slice(API_PREFIX.length)}`;
  // Root-relative only. An absolute URL would need a next.config.ts
  // remotePatterns entry per environment to render at all, and a
  // scheme-bearing value from the database is not something this tier
  // should be resolving on a tenant's behalf.
  return raw.startsWith("/") ? raw : null;
}
