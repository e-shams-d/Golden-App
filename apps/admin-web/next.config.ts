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
      // Every authenticated page, so none of them lands in a browser's disk or
      // back/forward cache. `local.conf` sets `no-store` on `/api/` and `/files/`
      // only — never on `location /` — so this list is the whole of it for pages.
      //
      // **M12 slice 1 rewrote this list, and four of its nine entries pointed at
      // pages renamed during M5-M7** (`/payment-requests` became `/requests`,
      // `/payment-batches` became `/batches`, `/work-queues` became `/queues`);
      // two more never existed. Thirteen real pages were absent. Nothing noticed
      // across three milestones, which is why
      // `test_authenticated_pages_are_not_cacheable.py` now compares this list
      // against the directories under `app/` on every run.
      //
      // Sorted, and kept sorted: the gate reports a diff, and an unsorted list
      // makes that diff unreadable.
      protectedPagePatterns: [
        "/admin-users/:path*",
        "/bank-configuration/:path*",
        "/bank-exports/:path*",
        "/bank-result-bundles/:path*",
        // `/bank-statements` is deliberately absent: M0 slice D builds that page and
        // has not merged. The gate refuses a pattern with no page behind it, and will
        // refuse the *page* with no pattern the moment slice D lands — so it is added
        // on the rebase that follows, named by a failing test rather than remembered.
        "/batches/:path*",
        "/gold-orders/:path*",
        "/incoming-payments/:path*",
        "/notifications/:path*",
        "/password/:path*",
        "/payment-attempts/:path*",
        "/queues/:path*",
        "/requests/:path*",
        "/review-tasks/:path*",
        "/roles/:path*",
        "/traders/:path*",
      ],
    });
  },
};

export default nextConfig;
