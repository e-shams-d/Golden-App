import { describe, expect, it } from "vitest";

import {
  buildNextHeaderRules,
  buildSecurityHeaders,
} from "../src/security-headers.mjs";

describe("security header foundation", () => {
  it("ships browser hardening without enabling HSTS before TLS validation", () => {
    const headers = buildSecurityHeaders();
    const names = new Set(headers.map(({ key }) => key));

    expect(names).toContain("Content-Security-Policy");
    expect(names).toContain("X-Content-Type-Options");
    expect(names).toContain("Permissions-Policy");
    expect(names).not.toContain("Strict-Transport-Security");
  });

  it("marks every API and file surface as no-store", () => {
    const rules = buildNextHeaderRules();

    for (const source of ["/api/:path*", "/files/:path*", "/downloads/:path*"]) {
      const rule = rules.find((candidate) => candidate.source === source);
      const cacheControl = rule?.headers.find(({ key }) => key === "Cache-Control");

      expect(cacheControl?.value).toContain("no-store");
    }
  });

  it("allows eval only for local Next development and upgrades requests only after TLS readiness", () => {
    const developmentCsp = buildSecurityHeaders({ allowDevelopmentEval: true }).find(
      ({ key }) => key === "Content-Security-Policy",
    )?.value;
    const hardenedCsp = buildSecurityHeaders({ enableHsts: true }).find(
      ({ key }) => key === "Content-Security-Policy",
    )?.value;

    expect(developmentCsp).toContain("'unsafe-eval'");
    expect(developmentCsp).not.toContain("upgrade-insecure-requests");
    expect(hardenedCsp).not.toContain("'unsafe-eval'");
    expect(hardenedCsp).toContain("upgrade-insecure-requests");
  });
});
