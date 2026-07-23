const baseContentSecurityPolicy = [
  "default-src 'self'",
  "base-uri 'self'",
  "object-src 'none'",
  "frame-ancestors 'none'",
  "form-action 'self'",
  "img-src 'self' data: blob:",
  "font-src 'self' data:",
  "style-src 'self' 'unsafe-inline'",
  // Next.js currently emits bootstrap scripts inline. A nonce-based CSP belongs
  // behind the auth/proxy ADR; do not weaken other directives in the meantime.
  "connect-src 'self'",
  "worker-src 'self' blob:",
  "manifest-src 'self'",
  "frame-src 'self' blob:",
];

const commonSecurityHeaders = [
  { key: "Referrer-Policy", value: "no-referrer" },
  { key: "X-Content-Type-Options", value: "nosniff" },
  { key: "X-Frame-Options", value: "DENY" },
  { key: "X-DNS-Prefetch-Control", value: "off" },
  { key: "Cross-Origin-Opener-Policy", value: "same-origin" },
  {
    key: "Permissions-Policy",
    value:
      "camera=(self), microphone=(), geolocation=(), payment=(), usb=(), browsing-topics=()",
  },
];

const noStoreHeaders = [
  { key: "Cache-Control", value: "private, no-store, max-age=0, must-revalidate" },
  { key: "Pragma", value: "no-cache" },
  { key: "Expires", value: "0" },
  { key: "Vary", value: "Cookie, Authorization" },
];

/**
 * HSTS remains opt-in until TLS readiness is validated at the edge. The flag is
 * server-only (`SECURITY_HSTS_ENABLED`), never a NEXT_PUBLIC value.
 *
 * @param {{ enableHsts?: boolean, allowDevelopmentEval?: boolean }} [options]
 */
export function buildSecurityHeaders({
  enableHsts = false,
  allowDevelopmentEval = false,
} = {}) {
  const scriptSource = allowDevelopmentEval
    ? "script-src 'self' 'unsafe-inline' 'unsafe-eval'"
    : "script-src 'self' 'unsafe-inline'";
  const contentSecurityPolicy = [
    ...baseContentSecurityPolicy,
    scriptSource,
    ...(enableHsts ? ["upgrade-insecure-requests"] : []),
  ].join("; ");
  const headers = [
    { key: "Content-Security-Policy", value: contentSecurityPolicy },
    ...commonSecurityHeaders,
  ];

  if (enableHsts) {
    headers.push({
      key: "Strict-Transport-Security",
      value: "max-age=31536000; includeSubDomains",
    });
  }

  return headers;
}

/**
 * Shared Next.js header rules. API, file, download and authenticated page paths
 * are explicitly non-cacheable. The reverse proxy must enforce the same policy.
 *
 * @param {{ enableHsts?: boolean, allowDevelopmentEval?: boolean, protectedPagePatterns?: string[] }} [options]
 */
export function buildNextHeaderRules({
  enableHsts = false,
  allowDevelopmentEval = false,
  protectedPagePatterns = [],
} = {}) {
  const protectedRules = protectedPagePatterns.map((source) => ({
    source,
    headers: noStoreHeaders,
  }));

  return [
    {
      source: "/:path*",
      headers: buildSecurityHeaders({ enableHsts, allowDevelopmentEval }),
    },
    { source: "/api/:path*", headers: noStoreHeaders },
    { source: "/files/:path*", headers: noStoreHeaders },
    { source: "/downloads/:path*", headers: noStoreHeaders },
    { source: "/sw.js", headers: noStoreHeaders },
    ...protectedRules,
  ];
}

export { noStoreHeaders };
