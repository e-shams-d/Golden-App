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
      // Every authenticated page. See the admin app's config for why this is the
      // whole of the protection for page routes, and why it is now gated.
      //
      // **`/beneficiaries` and `/evidence` were the two absences that mattered**:
      // a trader's bank details and the receipts they uploaded, left cacheable
      // while `/results` and `/publications` — pages that do not exist — were
      // listed. This application is a PWA installed on a personal phone, which
      // makes a disk-cached page longer-lived than on a desktop.
      //
      // Sorted, and kept sorted, so the gate's diff stays readable.
      protectedPagePatterns: [
        "/beneficiaries/:path*",
        "/evidence/:path*",
        "/gold-orders/:path*",
        "/notifications/:path*",
        "/password/:path*",
        "/profile/:path*",
        "/requests/:path*",
      ],
    });
  },
};

export default nextConfig;
