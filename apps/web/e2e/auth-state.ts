/**
 * Where the shared admin session is written and read.
 *
 * A plain module, not a spec or a setup file, because Playwright refuses
 * to let one test file import another — and both `admin.setup.ts` (which
 * writes the state) and `admin.spec.ts` (which uses it) need this path.
 */
export const ADMIN_STATE = "e2e/.auth/admin.json";
