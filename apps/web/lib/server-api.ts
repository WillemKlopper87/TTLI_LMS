/**
 * Server-side API access. Components running on the server talk to the API
 * directly; the browser only ever talks to the BFF route (app/api/bff),
 * which is what sets X-Tenant-Host — the API's tenancy contract.
 */
import { headers } from "next/headers";

import { createApiClient } from "@ttli/api-client";

export const API_URL = process.env.API_URL ?? "http://localhost:8010";

export interface Theme {
  tenant_slug: string;
  tenant_name: string;
  logo_url: string | null;
  primary_color: string | null;
  secondary_color: string | null;
  login_background_url: string | null;
  support_email: string | null;
}

export async function getTheme(): Promise<Theme | null> {
  const host = (await headers()).get("host") ?? "localhost";
  const client = createApiClient(API_URL);
  const { data, response } = await client.GET("/api/v1/tenant/theme", {
    headers: { "X-Tenant-Host": host },
    cache: "no-store",
  });
  if (!response.ok || !data) return null;
  return data as Theme;
}
