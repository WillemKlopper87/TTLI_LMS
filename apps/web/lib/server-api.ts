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

/* ------------------------------------------------------------------ *
 * Public storefront reads (landing, catalogue, course detail, podcasts)
 *
 * These pages render on the server, so they talk to the API directly
 * rather than through the BFF (which exists for the *browser*). The
 * tenancy contract is the same either way: X-Tenant-Host, taken from the
 * incoming request's own Host header, never from anything a caller sent.
 *
 * Every helper resolves to null / [] instead of throwing: the storefront
 * must still render its shell (and its "could not be loaded" copy) when
 * the API is down, rather than 500 the whole route.
 * ------------------------------------------------------------------ */

async function publicGet<T>(path: string): Promise<T | null> {
  try {
    const host = (await headers()).get("host") ?? "localhost";
    const resp = await fetch(`${API_URL}/api/v1${path}`, {
      headers: { "X-Tenant-Host": host },
      cache: "no-store",
    });
    if (!resp.ok) return null;
    return (await resp.json()) as T;
  } catch {
    return null;
  }
}

export interface PublicPrice {
  product_id: string;
  price_id: string;
  currency: string;
  unit_amount: string;
  tax_behaviour: string;
  includes_vat: boolean;
}

/** One row of `GET /public/courses`. Every presentation column is
 * nullable — a course created before the presentation pass (or by a
 * test) carries none of them, and each page degrades a part rather than
 * rendering an empty tag. */
export interface PublicCourse {
  id: string;
  slug: string;
  title: string;
  summary: string | null;
  description: string | null;
  level: string | null;
  topic: string | null;
  format: string | null;
  outcomes: string[] | null;
  includes_workshop: boolean;
  has_certificate: boolean;
  cpd_points: number | null;
  estimated_minutes: number | null;
  module_count: number;
  lesson_count: number;
  hero_colour: string | null;
  price: PublicPrice | null;
}

export interface PublicLesson {
  id: string;
  title: string;
  position: number;
  activity_type: string | null;
  access_level: string;
  estimated_minutes: number | null;
  is_preview: boolean;
}

export interface PublicModule {
  id: string;
  title: string;
  position: number;
  estimated_minutes: number | null;
  lesson_count: number;
  lessons: PublicLesson[];
}

/** `GET /public/courses/{id}/curriculum`. Deliberately *not* an
 * extension of PublicCourse: this payload keys the course as
 * `course_id`, and carries no `slug` or `module_count` (the module count
 * is `modules.length` here). */
export interface PublicCurriculum {
  course_id: string;
  title: string;
  summary: string | null;
  description: string | null;
  level: string | null;
  topic: string | null;
  format: string | null;
  outcomes: string[] | null;
  includes_workshop: boolean;
  has_certificate: boolean;
  cpd_points: number | null;
  estimated_minutes: number | null;
  lesson_count: number;
  hero_colour: string | null;
  price: PublicPrice | null;
  modules: PublicModule[];
}

export interface ProductPrice {
  id: string;
  currency: string;
  unit_amount: string;
  tax_behaviour: string;
}

export interface PublicProduct {
  id: string;
  slug: string;
  name: string;
  description: string | null;
  kind: string;
  prices: ProductPrice[];
  subscription_plan_id: string | null;
  bundled_courses: string[] | null;
}

export interface PublicEpisode {
  id: string;
  kind: string;
  slug: string;
  title: string;
  description: string | null;
  cover_image_url: string | null;
  curator_name: string | null;
  duration_seconds: number | null;
}


export interface PublicSession {
  session_id: string;
  workshop_id: string;
  title: string;
  description: string | null;
  session_type: string;
  facilitator_name: string | null;
  starts_at: string;
  ends_at: string;
  duration_minutes: number;
  capacity: number;
  seats_left: number;
  is_full: boolean;
}

export async function getPublicWorkshops(): Promise<PublicSession[]> {
  const body = await publicGet<{ items: PublicSession[] }>("/public/workshops");
  return body?.items ?? [];
}

export async function getPublicCourses(): Promise<PublicCourse[]> {
  const body = await publicGet<{ items: PublicCourse[] }>("/public/courses");
  return body?.items ?? [];
}

export async function getPublicCurriculum(courseId: string): Promise<PublicCurriculum | null> {
  return publicGet<PublicCurriculum>(`/public/courses/${encodeURIComponent(courseId)}/curriculum`);
}

export async function getPublicProducts(): Promise<PublicProduct[]> {
  const body = await publicGet<{ items: PublicProduct[] }>("/products");
  return body?.items ?? [];
}

export async function getPublicEpisodes(): Promise<PublicEpisode[]> {
  const body = await publicGet<{ items: PublicEpisode[] }>("/public/podcasts");
  return body?.items ?? [];
}
