/**
 * A time an operator types is a wall clock in Tehran, and reaches the API as the instant it names.
 *
 * F-39. `<input type="datetime-local">` submits `2026-10-14T10:30`, with no zone. The payment
 * confirmation sent it as typed, and PostgreSQL, whose session zone is UTC, stored the bank's 10:30
 * as 14:00 in Tehran. **The API now refuses a timestamp without a zone — that is the enforcement**,
 * and it turns this mistake from a silent wrong instant into a visible refusal
 * (`tests/backend/test_request_timestamps_name_an_instant.py`). This file is the reminder at the
 * place the next such input would be written: every screen with a `datetime-local` input, in
 * either app, converts through `tehranWallClockToInstant`.
 *
 * A `type="time"` input is deliberately outside it. The bank configuration's cutoff is a wall-clock
 * *rule* — "16:00 at the bank", stored as TIME and evaluated in the business zone — not an instant.
 */

import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, relative } from "node:path";

import { describe, expect, it } from "vitest";

const APPS = join(import.meta.dirname, "..", "..");

function sources(directory: string): string[] {
  return readdirSync(directory).flatMap((name) => {
    const path = join(directory, name);
    if (statSync(path).isDirectory()) return sources(path);
    return /\.tsx?$/u.test(name) ? [path] : [];
  });
}

const screens = ["admin-web", "trader-pwa"].flatMap((app) =>
  ["app", "components"].flatMap((folder) => sources(join(APPS, app, folder))),
);
const withWallClockInput = screens.filter((file) =>
  readFileSync(file, "utf8").includes('type="datetime-local"'),
);

describe("F-39: a typed wall clock is converted before it is sent", () => {
  it("finds the screens that take a date and a time", () => {
    // Guard the guard. The payment confirmation is one; a reader that found none would make the
    // next assertion pass on nothing.
    expect(screens.length).toBeGreaterThan(40);
    expect(withWallClockInput.map((file) => relative(APPS, file))).toContain(
      join("admin-web", "app", "payment-attempts", "[attemptId]", "page.tsx"),
    );
  });

  it("converts through tehranWallClockToInstant on every one of them", () => {
    const unconverted = withWallClockInput.filter(
      (file) => !readFileSync(file, "utf8").includes("tehranWallClockToInstant("),
    );
    expect(unconverted.map((file) => relative(APPS, file))).toEqual([]);
  });
});
