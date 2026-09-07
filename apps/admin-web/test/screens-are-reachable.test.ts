import { existsSync, readFileSync, readdirSync, statSync } from "node:fs";
import { join, relative } from "node:path";

import type { NavigationItem } from "@gold/ui";
import { describe, expect, it } from "vitest";

import { adminNavigation } from "../src/navigation";

/**
 * `UI-REQ-004` for the centre's bundle: every item has a page, every page is linked to, and
 * every module has a caller.
 *
 * A copy of the trader app's test rather than a shared helper, and deliberately: each app has
 * to import its own navigation module, and `UI-ISO-001` requires that neither bundle contain
 * the other's. A shared test package would be a third thing to keep in step with two routers;
 * two copies of forty lines is the cheaper of the two failures.
 *
 * The third assertion is the one written from experience. `src/request-view.ts` arrived in the
 * trader app with thirteen passing tests and no importer — three functions a screen was meant
 * to use, reviewed and green and unreachable. This repository has produced that defect in
 * every milestone, and a test suite is where it hides best, because tests are callers and they
 * pass.
 *
 * Covers: UI-REQ-004.
 */

const APP_ROOT = join(import.meta.dirname, "..");
const items: readonly NavigationItem[] = adminNavigation;

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

function routes(): readonly string[] {
  return files(join(APP_ROOT, "app"), /^page\.tsx$/).map((path) => {
    const segment = relative(join(APP_ROOT, "app"), path).replace(/[/\\]?page\.tsx$/, "");
    return segment ? `/${segment.split(/[/\\]/).join("/")}` : "/";
  });
}

/**
 * The queue registry, which is where a queue row's destination lives.
 *
 * Reaching across into the backend from a frontend test is unusual and is the honest consequence
 * of slice 4's decision: which screen opens a queue row is the server's answer, so the frontend
 * genuinely does not know it. The alternative — a map of sixteen names here — is the drift that
 * decision removed.
 */
const QUEUE_REGISTRY = join(
  APP_ROOT,
  "..",
  "..",
  "services",
  "backend",
  "app",
  "queues",
  "money_movement.py",
);

function routeSource(): string {
  return files(join(APP_ROOT, "app"), /\.tsx?$/)
    .concat(files(join(APP_ROOT, "components"), /\.tsx?$/))
    .map((path) => readFileSync(path, "utf8"))
    .join("\n");
}

/** `"/x"`, `'/x'` or `` `/x` `` — delimited, so `/requests` is not matched by `/requests/x`. */
function linksTo(source: string, route: string): boolean {
  return ['"', "'", "`"].some((quote) => source.includes(`${quote}${route}${quote}`));
}

describe("every screen is reachable (UI-REQ-004)", () => {
  it("finds the routes and the navigation at all", () => {
    // Guard the guard: an empty list makes everything below vacuous, and looks like success.
    expect(routes().length).toBeGreaterThan(4);
    expect(items.length).toBeGreaterThan(0);
    expect(routes()).toContain("/requests");
  });

  it("gives every navigation item a page", () => {
    const missing = items.map(({ href }) => href).filter((href) => !routes().includes(href));

    expect(
      missing,
      "these navigation items point at routes with no page, so clicking them answers 404",
    ).toEqual([]);
  });

  it("leaves no page unreachable", () => {
    const navigable = new Set<string>(items.map(({ href }) => href));
    // **A destination the server publishes counts as a link, and M11 Screens slice 6 is why.**
    //
    // Slice 4 moved queue row destinations onto the queue registry — `QueueDefinition.detail_path`
    // — precisely so this application would *not* hold a map of sixteen queue names to sixteen
    // screens. The queue table renders `listing.detail_path` and nothing else, so a screen reached
    // only from a queue row appears in no frontend file at all.
    //
    // This gate was right to fire on that, and the fix is not to weaken it: reachability is still
    // asserted, from the one other place a route can legitimately come from. Read as text because
    // the registry is Python, and `tests/backend/test_incoming_screens_exist.py` holds the same
    // pairing from the side that can import it — so neither half is trusted alone.
    const source = routeSource() + readFileSync(QUEUE_REGISTRY, "utf8");

    const unreachable = routes().filter((route) => {
      if (navigable.has(route) || route === "/") return false;
      if (route.includes("[")) {
        // Reached from whatever lists its instances, by a template or by a literal for a
        // known value. Both contain the static prefix.
        //
        // **Without its trailing slash too**, because a server-published `detail_path` is a
        // prefix the row id is appended to — `"/incoming-payments"` and not
        // `"/incoming-payments/"`. Matching only the slashed form asked whether the frontend
        // writes the link, which is the thing slice 4 deliberately stopped it doing.
        const prefix = route.slice(0, route.indexOf("["));
        return !source.includes(prefix) && !source.includes(prefix.replace(/\/$/u, ""));
      }
      return !linksTo(source, route);
    });

    expect(
      unreachable,
      "these pages exist and nothing links to them, so only somebody who knows the URL can " +
        "reach them:\n" + unreachable.join("\n"),
    ).toEqual([]);
  });

  it("leaves no src module with nothing calling it", () => {
    const importers = routeSource();
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
