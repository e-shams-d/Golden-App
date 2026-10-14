import { readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

/**
 * The gates in this directory are run, not replayed.
 *
 * Several tests here read the *trader* app's sources by path —
 * `permission-refusal-is-not-a-retry`, `typed-amounts-are-folded`,
 * `server-errors-are-translated`, `state-kinds-are-not-borrowed`. They are here rather
 * than in the trader app because each rule spans both apps and one file is easier to keep
 * true than two.
 *
 * Turbo hashes a task from its own package and that package's dependencies. The trader
 * app is neither, so a change confined to it left this package's `test` task a cache hit:
 * the log was replayed, the assertions were not evaluated, and the run was green.
 *
 * **Found by a sabotage that was applied and produced no failure.** A confirmation panel
 * in `apps/trader-pwa/app/register/page.tsx` was put back to the `empty` kind, the file
 * verifiably changed, and `turbo run test` exited 0 with
 * `@gold/admin-web:test: cache hit, replaying logs`. A fresh CI checkout has no cache, so
 * CI was never wrong — which is exactly why this would have gone unnoticed: the only place
 * it bites is the local run a person trusts before pushing.
 *
 * The fix is `"cache": false` on this one task. `turbo.json` is plain JSON and carries no
 * comment, so the reason lives here, where the line is defended by a test that fails when
 * it is removed. This suite costs about two seconds.
 *
 * Covers: F-38.
 */

const TURBO = join(import.meta.dirname, "..", "..", "..", "turbo.json");

describe("this package's test task", () => {
  const config = JSON.parse(readFileSync(TURBO, "utf8")) as {
    tasks: Record<string, { cache?: boolean; dependsOn?: string[] }>;
  };

  it("is never served from the cache", () => {
    expect(config.tasks["@gold/admin-web#test"]?.cache).toBe(false);
  });

  it("still waits for the packages it imports", () => {
    // The override replaces the generic `test` entry for this package rather than merging
    // with it, so the dependency has to be restated or the suite would run before the
    // shared packages are type-checked.
    expect(config.tasks["@gold/admin-web#test"]?.dependsOn).toEqual(
      config.tasks["test"]?.dependsOn,
    );
  });
});
