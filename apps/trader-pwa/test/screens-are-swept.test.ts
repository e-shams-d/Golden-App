import { existsSync, readFileSync, readdirSync, statSync } from "node:fs";
import { join, relative } from "node:path";

import { describe, expect, it } from "vitest";

/**
 * `TRACE-SCREENS-001`, for the trader application.
 *
 * M11 Screens slice 3, and this file exists because of what slice 3 found: **the obligation's
 * sweep-versus-routes comparison was implemented for `admin-web` only.**
 * `apps/admin-web/test/download-and-sent.test.ts` walks that app's `app/` directory and fails on a
 * screen the accessibility sweep never opens. Nothing did that for this app, so a trader screen
 * could ship unswept and every gate stayed green.
 *
 * That is the shape the obligation was written to catch — it is the reason it once found `/login`
 * unswept since M3 — and it was half-deployed for eleven milestones. Slice 1 added
 * `/notifications` to the trader sweep by hand because a Python test asked for it, not because
 * anything compared the list against the routes.
 *
 * **The rules are deliberately identical to the admin version**, including the dynamic-route
 * prefix rule and the stale-entry check, because two gates for one obligation that disagree are
 * worse than one gate. Where they differ is only in which `app/` directory they walk.
 */

const APP_ROOT = join(import.meta.dirname, "..");
const SWEEP = join(APP_ROOT, "tests", "a11y", "shell.spec.ts");

function routes(): readonly string[] {
  const found: string[] = [];
  const walk = (directory: string) => {
    if (!existsSync(directory)) return;
    for (const entry of readdirSync(directory)) {
      const path = join(directory, entry);
      if (statSync(path).isDirectory()) walk(path);
      else if (entry === "page.tsx") found.push(path);
    }
  };
  walk(join(APP_ROOT, "app"));
  return found.map((path) => {
    const segment = relative(join(APP_ROOT, "app"), path).replace(/[/\\]?page\.tsx$/u, "");
    return segment ? `/${segment.split(/[/\\]/u).join("/")}` : "/";
  });
}

const sweep = readFileSync(SWEEP, "utf8");

describe("TRACE-SCREENS-001: every trader screen is in the a11y sweep", () => {
  it("finds the sweep's list at all", () => {
    // Guard the guard. A path that stopped matching, or a walk that found nothing, would make
    // every check below true for the wrong reason.
    expect(sweep).toContain('"/requests"');
    expect(routes().length).toBeGreaterThan(8);
  });

  it("covers every route, including the dynamic ones", () => {
    // The static prefix is what a dynamic route contributes: the sweep visits it with obviously
    // fake ids, which renders the "not found" or "nothing here" state — a real state somebody
    // reaches by following a stale link, and the one most likely to ship without a heading.
    const uncovered = routes()
      .filter((route) => route !== "/" && !route.startsWith("/health"))
      .filter((route) => {
        const prefix = route.includes("[") ? route.slice(0, route.indexOf("[")) : route;
        return !sweep.includes(`"${prefix}`);
      });

    expect(
      uncovered,
      "these screens exist and the accessibility sweep never opens them:\n" + uncovered.join("\n"),
    ).toEqual([]);
  });

  it("lists no path whose screen has been deleted", () => {
    // The other direction: a sweep entry for a route that no longer exists passes forever,
    // because Next.js answers its own 404 page and that page is accessible.
    const listed = [...sweep.matchAll(/^ {2}"(\/[^"]*)",$/gmu)].map((match) => match[1]!);
    const prefixes = routes().map((route) =>
      route.includes("[") ? route.slice(0, route.indexOf("[")) : route,
    );

    expect(listed.length).toBeGreaterThan(8);
    const stale = listed.filter(
      (path) => !prefixes.some((prefix) => path === prefix || path.startsWith(prefix)),
    );

    expect(stale, "the sweep visits these and no page serves them").toEqual([]);
  });

  it("opens the published result screen with a concrete path", () => {
    // The prefix rule above is satisfied by `/requests` alone, so the result screen would pass
    // without ever being rendered. **A prefix match is not coverage** — it is the compromise that
    // lets one entry stand for a family of dynamic routes, and here the family member is a
    // separate page with its own headings and its own controls.
    //
    // Asserted separately rather than by tightening the prefix rule, because tightening it would
    // demand a concrete path for every dynamic route in both applications, which is a decision
    // about the whole obligation and not about this slice.
    expect(sweep).toContain("/result");
  });
});
