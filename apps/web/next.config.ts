import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Containerised deployment, not Cloudflare Workers.
  // See docs/adr/0008-hosting-target-and-legacy-runtime.md.
  output: "standalone",
  reactStrictMode: true,
};

export default nextConfig;
