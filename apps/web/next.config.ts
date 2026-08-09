import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // The client package ships TypeScript source, not compiled JS — Next
  // transpiles it as part of this app's build.
  transpilePackages: ["@ttli/api-client"],
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
