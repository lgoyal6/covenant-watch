import type { NextConfig } from "next";
import path from "node:path";

const nextConfig: NextConfig = {
  reactStrictMode: true,
  poweredByHeader: false,
  // web/ is its own package inside a Python repo; pin the workspace root so
  // Next does not walk up looking for lockfiles.
  turbopack: { root: path.resolve(__dirname) },
  outputFileTracingRoot: path.resolve(__dirname),
};

export default nextConfig;
