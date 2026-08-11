/**
 * The browser half of audience isolation, asserted in a real browser.
 *
 * `services/backend/app/security/cookies.py` states the deployment's central claim:
 * "`__Host-` is doing real work, not decoration", and "having the client enforce it
 * is stronger than setting the attributes correctly ourselves, because an attribute
 * we set is one a later edit can change." Every audience-isolation argument in M3
 * rests on that sentence, and until this file existed it was a comment. Nothing
 * anywhere checked that a browser enforces the rule the design delegates to it.
 *
 * That matters in a specific, non-hypothetical way. The M3 plan proposed, as the
 * negative control for the end-to-end isolation obligation, setting `Domain` on the
 * session cookie so it becomes visible to the sibling host, and requiring the
 * isolation test to fail. This file shows that control **cannot fail**: Chromium
 * refuses the cookie outright, so the trader ends up with no session at all and the
 * admin host refuses them for being anonymous rather than for being a trader. The
 * control would have reported success while testing nothing — the second time in this
 * plan a proposed control turned out to be inert, and the first was also about this
 * cookie.
 *
 * WHAT THIS PROVES: that the browser enforces the prefix the deployment relies on.
 * WHAT IT DOES NOT: that the running stack isolates the two audiences end to end.
 * That remaining half needs the compose stack's two hostnames, which no test here
 * stands up. It is recorded as pending, with its owning slice, in
 * `tests/backend/test_traceability.py`.
 *
 * That obligation's identifier is deliberately **not** spelled out anywhere in this
 * file, and the omission is load-bearing rather than stylistic. Coverage is decided by
 * a plain search for the id across test files, so a sentence explaining why something
 * is *deferred* registers as proof that it is *done* — and writing this docstring is
 * what demonstrated it: the traceability gate immediately reported the obligation as
 * both pending and covered. The gate cannot tell an explanation from an assertion, so
 * the discipline has to be here.
 *
 * Two design notes:
 *
 * It serves its own responses instead of driving the application. The claim is about
 * the *platform*, not about our routes, so introducing Next, the backend and nginx
 * would add three ways for the test to fail for reasons that are not the claim.
 *
 * It lives in the trader app rather than in both. The cookie whose sibling-visibility
 * matters is the trader's — an admin who reaches a trader surface is a lesser problem
 * than the reverse — and one fact asserted in two places is the drift this repository
 * keeps paying for.
 *
 * Covers: UI-ISO-003.
 */

import { createServer, type Server } from "node:http";
import { expect, test } from "@playwright/test";

/**
 * `Domain=localhost` while the page is served from `localhost`, deliberately.
 *
 * If the host and the Domain disagreed, a rejection would be explained by the
 * mismatch and would say nothing about the prefix. Matching them leaves the prefix as
 * the only reason a cookie can be refused.
 */
const CANDIDATES = [
  {
    name: "__Host-correct",
    header: "__Host-correct=1; Secure; Path=/",
    stored: true,
    because: "Secure, no Domain, Path=/ — the combination the prefix requires",
  },
  {
    name: "__Host-with-domain",
    header: "__Host-with-domain=1; Secure; Path=/; Domain=localhost",
    stored: false,
    because:
      "a Domain attribute would make the cookie visible to sibling hosts, which is " +
      "exactly what the prefix exists to forbid — and why the plan's proposed " +
      "sibling-visibility negative control cannot fail",
  },
  {
    name: "__Host-no-secure",
    header: "__Host-no-secure=1; Path=/",
    stored: false,
    because: "without Secure the cookie could be set by a network attacker over HTTP",
  },
  {
    name: "__Host-narrow-path",
    header: "__Host-narrow-path=1; Secure; Path=/somewhere",
    stored: false,
    because:
      "a narrowed Path would leave the API's other prefixes uncovered; the deployment " +
      "needs Path=/ because `/auth/*` and `/files/` are separate trees",
  },
  {
    name: "ordinary-with-domain",
    header: "ordinary-with-domain=1; Path=/; Domain=localhost",
    stored: true,
    because:
      "the control inside the experiment: an ordinary cookie carrying the same Domain " +
      "IS stored, so the refusals above are caused by the prefix and not by the " +
      "attribute being invalid or the server being unreachable",
  },
] as const;

let server: Server;
let origin: string;

test.beforeAll(async () => {
  server = createServer((_request, response) => {
    response.setHeader(
      "Set-Cookie",
      CANDIDATES.map((candidate) => candidate.header),
    );
    response.setHeader("Content-Type", "text/html; charset=utf-8");
    response.end("<!doctype html><title>cookie prefix</title><p>ok");
  });
  await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", () => resolve()));
  const address = server.address() as { port: number };
  // `localhost`, not `127.0.0.1`: the name is what makes `Domain=localhost` a
  // matching attribute rather than a mismatched one.
  origin = "http://localhost:" + String(address.port);
});

test.afterAll(() => {
  server.close();
});

test("plain-HTTP localhost is a secure context, so Secure cookies are storable", async ({
  page,
}) => {
  // The fact the rest of this file depends on, and the one that makes a browser-level
  // isolation test possible at all without TLS. The session cookie is `secure=True`
  // unconditionally (`app/api/v1/auth.py:252`) with no environment escape hatch, so if
  // localhost were not trustworthy the cookie could never be stored in local
  // development and the only options would be terminating TLS in the local stack or
  // relaxing the flag — the second of which would test a different system from the one
  // that ships.
  await page.goto(origin);

  expect(await page.evaluate(() => window.isSecureContext)).toBe(true);
});

test("the browser enforces every part of the __Host- contract", async ({ page, context }) => {
  await page.goto(origin);
  const stored = new Set((await context.cookies()).map((cookie) => cookie.name));

  // Asserted first and separately. Every "must be refused" expectation below is also
  // satisfied by a browser that stored nothing at all — by a server that sent no
  // headers, a navigation that failed, a port that closed. These two say the transport
  // worked, which is what gives the refusals their meaning.
  expect(
    stored.has("__Host-correct"),
    "a correctly formed __Host- cookie was not stored, so this test is asserting " +
      "refusals against a browser that received nothing",
  ).toBe(true);
  expect(
    stored.has("ordinary-with-domain"),
    "an ordinary cookie with Domain=localhost was not stored, so Domain is being " +
      "rejected for some reason other than the __Host- prefix and the refusals below " +
      "do not mean what they appear to",
  ).toBe(true);

  for (const candidate of CANDIDATES) {
    expect(
      stored.has(candidate.name),
      candidate.header + " — " + candidate.because,
    ).toBe(candidate.stored);
  }
});
