import { buildNextHeaderRules } from "@gold/config/security-headers";
import { resolve } from "node:path";
import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  output: "standalone",
  outputFileTracingRoot: resolve(process.cwd(), "../.."),
  poweredByHeader: false,
  reactStrictMode: true,
  productionBrowserSourceMaps: false,
  transpilePackages: [
    "@gold/api-client",
    "@gold/auth-client",
    "@gold/localization",
    "@gold/ui",
  ],
  async headers() {
    return buildNextHeaderRules({
      enableHsts: process.env.SECURITY_HSTS_ENABLED === "true",
      allowDevelopmentEval: process.env.NODE_ENV !== "production",
      protectedPagePatterns: [
        "/dashboard/:path*",
        "/work-queues/:path*",
        "/traders/:path*",
        "/payment-requests/:path*",
        "/payment-batches/:path*",
        "/bank-exports/:path*",
        "/bank-result-bundles/:path*",
        "/audit/:path*",
        "/settings/:path*",
      ],
    });
  },
};

export default nextConfig;
