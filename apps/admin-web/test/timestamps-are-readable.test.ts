/**
 * Every timestamp the API sends reaches a person through `Instant`, in the form document 21 §4.5
 * gives. F-40.
 *
 * The screens printed the contract's date-time values as they came — `2026-10-14T07:00:00Z` —
 * thirteen times in nine files. A goldsmith who received a message at 10:30 read "07:00", on the
 * Gregorian calendar, in Latin digits.
 *
 * **The fields are read from the contract, not from a naming habit.** Thirty-eight properties in
 * `services/backend/openapi/v1.json` are `format: date-time` when this was written, and three of
 * them do not end in `_at`, so a sweep keyed on the suffix would have missed them. The sweep flags
 * a JSX child expression that renders one of those properties directly — `{row.created_at}` or
 * `{row.created_at ?? fallback}` — in either app. It does not look inside template strings or
 * props; that is its scope, stated rather than implied, and the guard checks it still finds what
 * it is for.
 */

import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, relative } from "node:path";

import { Instant, formatInstant } from "@gold/ui";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

const APPS = join(import.meta.dirname, "..", "..");
const REPOSITORY_ROOT = join(APPS, "..");
const CONTRACT = join(REPOSITORY_ROOT, "services", "backend", "openapi", "v1.json");
const SPECIFICATION = join(
  REPOSITORY_ROOT,
  "Implementation Docs",
  "04_Frontend_and_Experience",
  "21_UI_Design_System_and_Screen_Specification.md",
);

function dateTimeProperties(node: unknown, found: Set<string> = new Set()): Set<string> {
  if (Array.isArray(node)) {
    for (const item of node) dateTimeProperties(item, found);
    return found;
  }
  if (node === null || typeof node !== "object") return found;
  const record = node as Record<string, unknown>;
  const properties = record.properties;
  if (properties !== null && typeof properties === "object") {
    for (const [name, schema] of Object.entries(properties as Record<string, unknown>)) {
      const variants: unknown[] = [schema, ...((schema as { anyOf?: unknown[] }).anyOf ?? [])];
      if (variants.some((variant) => (variant as { format?: unknown } | null)?.format === "date-time")) {
        found.add(name);
      }
    }
  }
  for (const value of Object.values(record)) dateTimeProperties(value, found);
  return found;
}

function sources(directory: string): string[] {
  return readdirSync(directory).flatMap((name) => {
    const path = join(directory, name);
    if (statSync(path).isDirectory()) return sources(path);
    return name.endsWith(".tsx") ? [path] : [];
  });
}

const fields = dateTimeProperties(JSON.parse(readFileSync(CONTRACT, "utf8")));
const screens = ["admin-web", "trader-pwa"].flatMap((app) =>
  ["app", "components"].flatMap((folder) => sources(join(APPS, app, folder))),
);
// Property names are lowercase words and underscores, so nothing in them needs escaping. The
// lookbehind leaves out a prop — `value={row.created_at}` is how `Instant` receives one.
const rawRender = new RegExp(
  String.raw`(?<!=)\{[A-Za-z_.?\[\]0-9]*\.(${[...fields].sort().join("|")})( \?\? [^}]+)?\}`,
  "g",
);

/** The first fenced block under a heading — how the document writes text that must appear as-is. */
function fenced(heading: string): string[] {
  const specification = readFileSync(SPECIFICATION, "utf8");
  const body = specification.slice(specification.indexOf(heading) + heading.length);
  const afterFence = body.indexOf("\n", body.indexOf("```")) + 1;
  return body
    .slice(afterFence, body.indexOf("```", afterFence))
    .split("\n")
    .map((line) => line.trim())
    .filter((line) => line.length > 0);
}

describe("F-40: a timestamp is shown as a person in Tehran reads it", () => {
  it("reads the contract's timestamps and the screens that might print them", () => {
    // Guard the guard: a reader that found no field, or no screen, would make the sweep pass.
    expect(fields.size).toBeGreaterThanOrEqual(30);
    for (const known of ["created_at", "published_at", "effective_from", "payment_at_normalized"]) {
      expect(fields.has(known), known).toBe(true);
    }
    expect(screens.length).toBeGreaterThan(40);
    const instances = screens.reduce(
      (count, file) => count + (readFileSync(file, "utf8").match(/<Instant /g)?.length ?? 0),
      0,
    );
    expect(instances).toBeGreaterThanOrEqual(13);
  });

  it("no screen prints a contract timestamp as it came", () => {
    const printed = screens.flatMap((file) =>
      readFileSync(file, "utf8")
        .split("\n")
        .flatMap((line, index) =>
          [...line.matchAll(rawRender)].map(
            (match) => `${relative(APPS, file)}:${index + 1} ${match[0]}`,
          ),
        ),
    );
    expect(printed).toEqual([]);
  });

  it("writes document 21 §4.5's own example exactly", () => {
    const example = fenced("## 4.5 Date and time");
    expect(example).toHaveLength(2);
    const [readable = "", exact = ""] = example;
    const label = "زمان دقیق سامانه: ";
    expect(exact.startsWith(label), exact).toBe(true);
    const instant = exact.slice(label.length);

    expect(formatInstant(instant)).toBe(readable);
    expect(renderToStaticMarkup(createElement(Instant, { value: instant }))).toContain(
      `title="${exact}"`,
    );
  });
});
