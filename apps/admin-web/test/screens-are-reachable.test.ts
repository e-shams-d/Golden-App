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
    const source = routeSource();

    const unreachable = routes().filter((route) => {
      if (navigable.has(route) || route === "/") return false;
      if (route.includes("[")) {
        // Reached from whatever lists its instances, by a template or by a literal for a
        // known value. Both contain the static prefix.
        return !source.includes(route.slice(0, route.indexOf("[")));
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
