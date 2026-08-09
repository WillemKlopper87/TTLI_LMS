import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // The client package ships TypeScript source, not compiled JS — Next
  // transpiles it as part of this app's build.
  transpilePackages: ["@ttli/api-client"],
};

export default nextConfig;
