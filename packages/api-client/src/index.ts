/**
 * The hand-written half of this package. `schema.gen.ts` is generated —
 * `npm run generate` from apps/api/openapi.json — and never edited by hand;
 * everything here just wraps it in a typed client.
 */
import createClient from "openapi-fetch";

import type { paths } from "./schema.gen";

export type { components, operations, paths } from "./schema.gen";

export function createApiClient(baseUrl: string) {
  return createClient<paths>({ baseUrl });
}

export type ApiClient = ReturnType<typeof createApiClient>;
