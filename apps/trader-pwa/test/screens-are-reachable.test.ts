import { existsSync, readFileSync, readdirSync, statSync } from "node:fs";
import { join, relative } from "node:path";

import { describe, expect, it } from "vitest";

import { traderNavigation } from "../src/navigation";

/**
 * `UI-REQ-004`'s second half: every screen has an importer that is a route.
 *
 * The first half — every navigation item has a page — lives in `navigation.test.ts` and has
 * caught real dead links twice. This is the same defect from the other end, and it is the one
 * this repository keeps producing: five times in M3 a complete mechanism shipped that nothing
 * called, and `app/core/money.py` was the fifth. A screen nothing routes to is that, in the
 * interface — finished work, reviewed, merged, unreachable.
 *
 * Two directions, because they fail differently:
 *
 * - A `page.tsx` under a path no navigation item and no link points at is reachable only by
 *   somebody who knows the URL. Nested routes are exempt when a parent links to them: a
 *   detail page is reached from its list, not from the menu.
 * - A component under `components/` that no route imports is dead code that looks alive.
 *
 * Both apps are scanned by their own copy of this test, because each knows its own
 * navigation module and `UI-ISO-001` keeps the two bundles from importing each other.
 *
 * Covers: UI-REQ-004.
 */

const APP_ROOT = join(import.meta.dirname, "..");

function files(directory: string, suffix: RegExp): readonly string[] {
  if (!existsSync(directory)) return [];
  const found: string[] = [];
  for (const entry of readdirSync(directory)) {
    const path = join(directory, entry);
    if (statSync(path).isDirectory()) {
      found.push(...files(path, suffix));
    } else if (suffix.test(entry)) {
      found.push(path);
    }
  }
  return found;
}

/** Every `app/**\/page.tsx` as its route, so `app/requests/new/page.tsx` is `/requests/new`. */
function routes(): readonly string[] {
  return files(join(APP_ROOT, "app"), /^page\.tsx$/).map((path) => {
    const segment = relative(join(APP_ROOT, "app"), path).replace(/[/\\]?page\.tsx$/, "");
    return segment ? `/${segment.split(/[/\\]/).join("/")}` : "/";
  });
}

/**
 * Everything that can send a person to a route, which is not only JSX.
 *
 * `public/` is included because the service worker is a real way in: `/offline` is served by
 * `sw.js` when a navigation fails, and nothing links to it because nothing should. The first
 * version of this test scanned only `app/` and `components/` and reported that page as
 * unreachable — which would have been answered either by deleting a working offline fallback
 * or by writing it an exemption it does not need.
 */
function allSource(): string {
  return files(join(APP_ROOT, "app"), /\.tsx?$/)
    .concat(files(join(APP_ROOT, "components"), /\.tsx?$/))
    .concat(files(join(APP_ROOT, "public"), /\.js$/))
    .map((path) => readFileSync(path, "utf8"))
    .join("\n");
}

/** `"/x"`, `'/x'` or `` `/x` `` — delimited, so `/requests` is not matched by `/requests/new`. */
function linksTo(source: string, route: string): boolean {
  return ['"', "'", "`"].some((quote) => source.includes(`${quote}${route}${quote}`));
}

describe("every screen is reachable (UI-REQ-004)", () => {
  it("finds the routes and the navigation at all", () => {
    // Guard the guard. An empty route list would make both assertions below vacuous.
    expect(routes().length).toBeGreaterThan(5);
    expect(traderNavigation.length).toBeGreaterThan(0);
    expect(routes()).toContain("/requests");
  });

  it("gives every navigation item a page", () => {
    const missing = traderNavigation
      .map(({ href }) => href)
      .filter((href) => !routes().includes(href));

    expect(
      missing,
      "these navigation items point at routes with no page, so tapping them answers 404",
    ).toEqual([]);
  });

  it("leaves no page unreachable", () => {
    const navigable = new Set<string>(traderNavigation.map(({ href }) => href));
    const source = allSource();

    const unreachable = routes().filter((route) => {
      if (navigable.has(route) || route === "/") return false;

      if (route.includes("[")) {
        // A dynamic route is reached from whatever lists its instances, and that link can be
        // spelled two ways: a template for a value known at runtime — `` `/requests/${id}` ``
        // — or a literal for a known one, which is how `/states/[kind]` is reached
        // (`href="/states/empty"`). Both contain the static prefix, so the prefix is what is
        // looked for. Checking for the bracketed path itself found neither.
        return !source.includes(route.slice(0, route.indexOf("[")));
      }

      return !linksTo(source, route);
    });

    expect(
      unreachable,
      "these pages exist and nothing links to them, so only somebody who knows the URL " +
        "can reach them:\n" +
        unreachable.join("\n"),
    ).toEqual([]);
  });

  it("leaves no src module with nothing calling it", () => {
    // Written because I did it. `src/request-view.ts` arrived with thirteen passing tests and
    // no importer: three functions a screen was supposed to use, reviewed and green and
    // unreachable. That is the defect this repository has produced in every milestone — five
    // times in M3, and `app/core/money.py` was the fifth — and a test suite is the perfect
    // place to hide it, because the tests are callers and they pass.
    //
    // A module imported only by its own test is therefore not called. The corpus here is
    // `app/` and `components/` alone, deliberately excluding `test/`.
    const importers = files(join(APP_ROOT, "app"), /\.tsx?$/)
      .concat(files(join(APP_ROOT, "components"), /\.tsx?$/))
      .map((path) => readFileSync(path, "utf8"))
      .join("\n");

    const uncalled = files(join(APP_ROOT, "src"), /\.tsx?$/)
      .map((path) => path.replace(/\.tsx?$/, "").split(/[/\\]/).pop()!)
      .filter((name) => !importers.includes(`/${name}"`));

    expect(
      uncalled,
      "these src modules are tested and nothing in a route or component imports them, so " +
        "they ship as code no person can reach:\n" + uncalled.join("\n"),
    ).toEqual([]);
  });

  it("leaves no component unimported", () => {
    const source = files(join(APP_ROOT, "app"), /\.tsx?$/)
      .concat(files(join(APP_ROOT, "components"), /\.tsx?$/))
      .map((path) => ({ path, text: readFileSync(path, "utf8") }));

    const orphans = files(join(APP_ROOT, "components"), /\.tsx$/)
      .map((path) => path.replace(/\.tsx$/, "").split(/[/\\]/).pop()!)
      .filter((name) =>
        source.every(({ path, text }) =>
          path.endsWith(`${name}.tsx`) ? true : !text.includes(`/${name}"`),
        ),
      );

    expect(
      orphans,
      "these components are in the bundle and no route imports them:\n" + orphans.join("\n"),
    ).toEqual([]);
  });
});
