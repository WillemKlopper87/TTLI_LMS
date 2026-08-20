import path from "node:path";

import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Standalone output: the container image ships a self-contained
  // server.js plus a minimal node_modules instead of the whole install
  // tree (apps/web/Dockerfile). No effect on `next dev`.
  output: "standalone",
  // The build runs from apps/web but the repo root is the Docker build
  // context (@ttli/api-client lives outside this app), so Next must be
  // told where the workspace root is or it guesses and warns.
  outputFileTracingRoot: path.join(import.meta.dirname, "../.."),
  // The client package ships TypeScript source, not compiled JS — Next
  // transpiles it as part of this app's build.
  transpilePackages: ["@ttli/api-client"],
  // Found by a ZAP baseline scan: Next sends this by default, leaking
  // the framework identity to every response for no functional benefit.
  poweredByHeader: false,
  // proxy.ts's matcher deliberately skips static assets — a per-request
  // CSP nonce is pointless on a JS chunk that never executes an inline
  // script. But a ZAP baseline scan correctly flagged those same assets
  // as missing X-Content-Type-Options/Permissions-Policy, which cost
  // nothing to set and don't need per-request randomness — set here,
  // at the config level, rather than paying middleware overhead on
  // every static-asset request just to add two static header values.
  async headers() {
    return [
      {
        source: "/_next/static/:path*",
        headers: [
          { key: "X-Content-Type-Options", value: "nosniff" },
          { key: "Permissions-Policy", value: "camera=(), microphone=(), geolocation=()" },
        ],
      },
      {
        source: "/_next/image",
        headers: [
          { key: "X-Content-Type-Options", value: "nosniff" },
          { key: "Permissions-Policy", value: "camera=(), microphone=(), geolocation=()" },
        ],
      },
      {
        source: "/icon.png",
        headers: [{ key: "X-Content-Type-Options", value: "nosniff" }],
      },
    ];
  },
};

// Next 16 defaults dev/build to Turbopack (package.json scripts pass
// --webpack to opt back out). Turbopack cannot currently resolve
// @ttli/api-client through the npm workspace symlink at
// node_modules/@ttli/api-client -> ../../packages/api-client — a known,
// still-open upstream limitation (vercel/next.js#85316, #88335, #77562),
// reproducible even after adding an explicit "exports" field to that
// package's package.json. Webpack resolves it correctly, same as it did
// on Next 15. Revisit --webpack once those issues close.
export default nextConfig;
