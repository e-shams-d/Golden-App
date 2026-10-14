import { readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

/**
 * A screen that confirms something uses the kind that says so.
 *
 * F-10 was recorded on three pages — the registration result, the password page and the
 * bank-configuration detail — as "the phrase «بدون داده» where there is data". It was one
 * cause: `StateView` prints a label for its kind, and screens with no kind of their own
 * had borrowed `empty`.
 *
 * **This is a naming-convention gate, and says so.** It reads each `StateView` panel and
 * holds one rule: a panel whose title key ends in `doneTitle` is a confirmation and takes
 * the `success` kind. That catches the regression that happened — the next confirmation
 * screen copied from the one beside it — and it does not catch a screen that borrows
 * `empty` under some other title. The test in `packages/ui` holds the other half: every
 * kind has a label of its own.
 *
 * **A panel is read whole, from its opening tag to its closing one.** The first version
 * looked four lines either side of the `kind` attribute, and two of the four
 * confirmations have longer prop lists than that — so it saw two panels and would have
 * passed with the other two reverted. The count assertion below is what caught it, on the
 * first run, before any sabotage was needed.
 *
 * Plain string work throughout. A check of this shape was silently disarmed three times
 * in this codebase by an escape sequence lost on the way to the file, and the durable
 * answer was to have nothing to escape.
 *
 * Covers: F-10.
 */

const APPS = ["admin-web", "trader-pwa"] as const;
const ROOT = join(import.meta.dirname, "..", "..", "..", "apps");
const NEWLINE = String.fromCharCode(10);
const OPENING = "<StateView";
const CLOSING = "/>";
const KIND_ATTRIBUTE = 'kind="';
const CONFIRMATION_TITLE = 'doneTitle")';
const LONGEST_PANEL = 40;

type Panel = Readonly<{ file: string; kind: string; source: string }>;

function sources(app: string): string[] {
  const out: string[] = [];
  const walk = (dir: string): void => {
    for (const entry of readdirSync(dir, { withFileTypes: true })) {
      if (entry.name === "node_modules" || entry.name === ".next") continue;
      const full = join(dir, entry.name);
      if (entry.isDirectory()) walk(full);
      else if (entry.name.endsWith(".tsx")) out.push(full);
    }
  };
  for (const part of ["app", "components"]) {
    try {
      walk(join(ROOT, app, part));
    } catch {
      // Not every app has every directory.
    }
  }
  return out;
}

/** Every `StateView` in a file, each as the whole text of its tag. */
function panels(path: string): Panel[] {
  const lines = readFileSync(path, "utf8").split(NEWLINE);
  const out: Panel[] = [];
  lines.forEach((line, index) => {
    if (!line.includes(OPENING)) return;
    const rest = lines.slice(index, index + LONGEST_PANEL);
    const end = rest.findIndex((candidate) => candidate.includes(CLOSING));
    const source = rest.slice(0, end < 0 ? rest.length : end + 1).join(NEWLINE);

    const at = source.indexOf(KIND_ATTRIBUTE);
    const after = at < 0 ? "" : source.slice(at + KIND_ATTRIBUTE.length);
    // A kind passed as an expression is decided at run time and is not this gate's to read.
    const kind = at < 0 ? "(computed)" : after.slice(0, after.indexOf('"'));

    out.push({ file: path.slice(path.indexOf("apps/")), kind, source });
  });
  return out;
}

const everyPanel = APPS.flatMap((app) => sources(app).flatMap(panels));
const confirmations = everyPanel.filter((panel) => panel.source.includes(CONFIRMATION_TITLE));

describe("the kind a screen gives its state panel", () => {
  it("finds panels to check, so the assertions below are not vacuous", () => {
    expect(everyPanel.length).toBeGreaterThan(30);
    expect(everyPanel.filter((panel) => panel.kind === "empty").length).toBeGreaterThan(10);
  });

  it("sees all four confirmations, so the rule is met rather than dodged", () => {
    // Without this, deleting every confirmation panel would satisfy the rule below — and
    // so would a reader too narrow to find them, which is how this assertion earned its
    // place: the first version of `panels` found two.
    expect(confirmations.map((panel) => panel.file).sort()).toEqual([
      "apps/admin-web/app/password/page.tsx",
      "apps/admin-web/app/recover-password/page.tsx",
      "apps/trader-pwa/app/password/page.tsx",
      "apps/trader-pwa/app/register/page.tsx",
    ]);
  });

  it("gives a confirmation the kind that says it completed", () => {
    const borrowed = confirmations
      .filter((panel) => panel.kind !== "success")
      .map((panel) => `${panel.file} uses the ${panel.kind} kind`);

    expect(
      borrowed,
      "these panels confirm a completed action under the label of another kind, so the " +
        `screen says something its own title contradicts: ${borrowed.join(", ")}`,
    ).toEqual([]);
  });

  it("labels the note about the missing form as a note", () => {
    // The bank-configuration detail screen explains why there is no "new version" form,
    // directly under the table of versions. "No data" was false on its face there.
    const note = everyPanel.filter((panel) => panel.source.includes("bank.newVersionBlockedTitle"));

    expect(note.length).toBe(1);
    expect(note[0]?.kind).toBe("info");
  });
});
