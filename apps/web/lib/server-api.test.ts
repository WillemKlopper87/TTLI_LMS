/**
 * F18 (BACKLOG.md): every anonymous storefront read was `cache: "no-store"`,
 * so each page view cost a live API round trip per call.
 *
 * The hard part is tenancy, not caching. The tenant is identified by the
 * request's Host, sent to the API as an X-Tenant-Host *header*. Next's data
 * cache is keyed by the fetch URL, so two tenants requesting the same path
 * could be served each other's catalogue if the URL alone were the key.
 * These tests pin the two halves of the fix together: a bounded
 * revalidation window (so data is never stale for long) and a per-tenant
 * URL (so it can never be another tenant's).
 */
import { afterEach, describe, expect, it, vi } from "vitest";

const { headers } = vi.hoisted(() => ({ headers: vi.fn() }));
const { createApiClient } = vi.hoisted(() => ({ createApiClient: vi.fn() }));

vi.mock("next/headers", () => ({ headers }));
vi.mock("@ttli/api-client", () => ({ createApiClient }));

import { getPublicCourses, getPublicCurriculum, getTheme } from "@/lib/server-api";

function hostIs(host: string) {
  headers.mockResolvedValue({ get: (name: string) => (name === "host" ? host : null) });
}

function stubFetch(body: unknown = { items: [] }) {
  const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => body });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

afterEach(() => {
  vi.unstubAllGlobals();
  vi.clearAllMocks();
});

describe("public storefront reads", () => {
  it("revalidate on a bounded window instead of opting out of the cache", async () => {
    hostIs("acme.example");
    const fetchMock = stubFetch();

    await getPublicCourses();

    const init = fetchMock.mock.calls[0][1];
    expect(init.cache).not.toBe("no-store");
    expect(init.next?.revalidate).toBeGreaterThan(0);
    expect(init.next?.revalidate).toBeLessThanOrEqual(300);
  });

  it("keeps the tenant header the API's tenancy contract depends on", async () => {
    hostIs("acme.example");
    const fetchMock = stubFetch();

    await getPublicCourses();

    expect(fetchMock.mock.calls[0][1].headers).toEqual({ "X-Tenant-Host": "acme.example" });
  });

  it("gives each tenant its own cache key, so one can never be served another's data", async () => {
    const fetchMock = stubFetch();

    hostIs("acme.example");
    await getPublicCourses();
    hostIs("globex.example");
    await getPublicCourses();

    const [first, second] = fetchMock.mock.calls.map((call) => String(call[0]));
    expect(first).not.toBe(second);
    expect(first).toContain("acme.example");
    expect(second).toContain("globex.example");
  });

  it("keeps the real path and stays a valid URL for parameterised reads", async () => {
    hostIs("acme.example");
    const fetchMock = stubFetch({});

    await getPublicCurriculum("a b/c");

    const url = new URL(String(fetchMock.mock.calls[0][0]));
    expect(url.pathname).toBe("/api/v1/public/courses/a%20b%2Fc/curriculum");
  });

  it("still degrades to an empty list when the API is down", async () => {
    hostIs("acme.example");
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("down")));

    await expect(getPublicCourses()).resolves.toEqual([]);
  });
});

describe("getTheme", () => {
  it("is cached per tenant on a bounded window too, since every route reads it", async () => {
    hostIs("acme.example");
    const GET = vi.fn().mockResolvedValue({
      data: { tenant_slug: "acme", tenant_name: "Acme", logo_url: null },
      response: { ok: true },
    });
    createApiClient.mockReturnValue({ GET });

    await getTheme();

    const [path, options] = GET.mock.calls[0];
    expect(options.cache).not.toBe("no-store");
    expect(options.next?.revalidate).toBeGreaterThan(0);
    expect(options.headers).toEqual({ "X-Tenant-Host": "acme.example" });
    expect(path).toBe("/api/v1/tenant/theme");
    // The tenant is part of what the cache can see, not only a header.
    expect(options.params?.query?._tenant).toBe("acme.example");
  });
});
