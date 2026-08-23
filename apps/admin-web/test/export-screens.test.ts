/**
 * The export screens render §14 — and, more importantly, do not offer what §14 forbids.
 *
 * Screens slice 3. `tests/backend/test_export_read_shape.py` parses §14.4 to check the API carries
 * every item; this parses it again to check the screen renders every label. Two copies of "the
 * twelve items" would disagree the day the document gained a thirteenth, and neither copy would
 * say which.
 *
 * **Three of the five obligations are absences**, and that is why this file asserts against source
 * rather than a rendered DOM. "There is no download-anyway control" is a claim about the whole
 * bundle: a rendering test proves it of the states it renders, and the control somebody adds under
 * pressure will be behind a condition that test did not reach. The a11y sweep opens the page for
 * real; this checks what is and is not in it.
 *
 * Covers: UI-PREVIEW-001, UI-PREVIEW-002, UI-EXPORT-001, UI-INTEGRITY-001, UI-INTEGRITY-002.
 */

import { readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

import {
  EXPORT_STATUS_LABELS,
  PREVIEW_BANNER,
  splitCheck,
  statusLabelKey,
} from "../src/bank-exports";

const APP_ROOT = join(import.meta.dirname, "..");
const REPOSITORY_ROOT = join(APP_ROOT, "..", "..");
const SPECIFICATION = join(
  REPOSITORY_ROOT,
  "Implementation Docs",
  "04_Frontend_and_Experience",
  "21_UI_Design_System_and_Screen_Specification.md",
);
const CATALOGUE = join(REPOSITORY_ROOT, "docs", "governance", "status_catalog.yaml");

const EXPORT_PAGE = join(APP_ROOT, "app", "bank-exports", "[exportId]", "page.tsx");
const page = readFileSync(EXPORT_PAGE, "utf8");
const specification = readFileSync(SPECIFICATION, "utf8");

/** Every `.ts`/`.tsx` file this app ships, for the assertions that are about the whole surface. */
function bundleSource(): string {
  const found: string[] = [];
  const walk = (directory: string) => {
    for (const entry of readdirSync(directory)) {
      const path = join(directory, entry);
      if (statSync(path).isDirectory()) walk(path);
      else if (/\.tsx?$/u.test(entry)) found.push(path);
    }
  };
  walk(join(APP_ROOT, "app"));
  walk(join(APP_ROOT, "components"));
  walk(join(APP_ROOT, "src"));
  return found.map((path) => readFileSync(path, "utf8")).join("\n");
}

/** The bullet list under a heading, ending at the next heading of any level. */
function bulleted(heading: string): readonly string[] {
  const start = specification.indexOf(heading);
  const body = specification.slice(start + heading.length);
  return body
    .slice(0, body.indexOf("\n#"))
    .split("\n")
    .filter((line) => line.startsWith("- "))
    .map((line) => line.slice(2).trim().replace(/[;.]$/u, "").toLowerCase());
}

/** The first fenced block under a heading, which is how the document writes verbatim text. */
function fenced(heading: string): string {
  const start = specification.indexOf(heading);
  const body = specification.slice(start + heading.length);
  const open = body.indexOf("```");
  const afterFence = body.indexOf("\n", open) + 1;
  return body.slice(afterFence, body.indexOf("```", afterFence)).trim();
}

describe("the specification still says these things", () => {
  it("finds §14.1's banner and §14.4's list at all", () => {
    // Guard the guard, for the sixth time in this repository. Every assertion below reads from the
    // document, and a parser that quietly returned "" would make all of them pass.
    expect(fenced("## 14.1 Preview export").length).toBeGreaterThan(20);
    expect(bulleted("## 14.4 Final export detail")).toHaveLength(12);
    expect(bulleted("## 14.1 Preview export")).toHaveLength(3);
  });
});

describe("UI-PREVIEW-001: the banner is verbatim", () => {
  it("matches the specification character for character", () => {
    // Parsed, not transcribed. The em dash is the character a transcription gets wrong, and a
    // banner with a hyphen would still look like a warning while no longer being the words the
    // document requires.
    expect(PREVIEW_BANNER).toBe(fenced("## 14.1 Preview export"));
  });

  it("renders that constant rather than a string of its own", () => {
    expect(page).toContain("{PREVIEW_BANNER}");
    // A literal copy on the page would pass the comparison above and drift the moment somebody
    // edited the page instead of the constant.
    expect(page).not.toContain("NOT APPROVED FOR BANK SUBMISSION");
  });

  it("marks the banner as English inside a right-to-left page", () => {
    // Without this the em dash renders on the wrong side. A mangled safety label is one people
    // stop reading, which is the failure §14.1 exists to prevent.
    const banner = page.slice(page.indexOf('data-testid="preview-banner-text"'));
    expect(banner.slice(0, 120)).toContain('dir="ltr"');
  });
});

describe("UI-PREVIEW-002: a preview offers none of §14.1's three things", () => {
  it("has no mark-as-sent control anywhere in the bundle yet", () => {
    // §14.1's first clause. Slice 4 adds this control to this screen, gated on `sendable` — which
    // the server derives and which is false for every preview. Until then the guarantee is the
    // strongest available: the bundle contains no such control to be shown by mistake.
    const source = bundleSource();
    expect(source).not.toContain("mark-sent-to-bank");
    expect(source).not.toMatch(/markSent|mark_sent/u);
  });

  it("labels a preview checksum as unofficial", () => {
    // §14.1's second clause: not "official checksum as final". Handled by labelling rather than by
    // hiding — a preview's checksum is a real checksum, and withholding it would make the screen
    // less honest — so the label is what carries the prohibition.
    expect(page).toContain("admin.export.checksumPreview");
    expect(page).toMatch(/preview \? t\("admin\.export\.checksumPreview"\)/u);
  });

  it("shows no send-ready status for a preview", () => {
    // §14.1's third clause. The screen derives no send-readiness at all: `sendable` arrives from
    // the server and this slice renders no control from it. What a preview shows for integrity is
    // "not applicable", which is the honest answer — half of §15.5's comparisons read an approval
    // and a preview has none.
    expect(page).toContain("admin.export.integrityNotApplicable");
    expect(page).not.toMatch(/sendReady|send_ready|readyToSend/u);
  });
});

describe("UI-INTEGRITY-002: there is no download-anyway control, anywhere", () => {
  it("contains no such phrase in the whole bundle", () => {
    // §14.5's last clause, asserted over the surface rather than the screen. The control somebody
    // adds under pressure gets added wherever the download lives, not necessarily here.
    const source = bundleSource().toLowerCase();

    for (const phrase of [
      "downloadanyway",
      "download_anyway",
      "download anyway",
      "forcedownload",
      "force_download",
      "downloadregardless",
      "overrideintegrity",
      "ignoreintegrity",
    ]) {
      expect(source, `the bundle contains ${phrase}`).not.toContain(phrase);
    }
  });

  it("blocks by not rendering rather than by disabling", () => {
    // A disabled control is a control. Nothing on this screen is disabled on the strength of
    // quarantine — the quarantined branch renders an explanation and no actions at all.
    const quarantine = page.slice(
      page.indexOf("function Quarantine"),
      page.indexOf("function Detail"),
    );
    expect(quarantine).not.toContain("<button");
    expect(quarantine).not.toContain("disabled");
  });
});

describe("UI-INTEGRITY-001: a quarantined export shows each failed check", () => {
  it("renders the list from the field the server evaluated", () => {
    expect(page).toContain('data-testid="integrity-quarantine"');
    expect(page).toContain("view.integrity_failed_checks.map");
    expect(page).toContain('role="alert"');
  });

  it("keeps §15.5's own name for each comparison", () => {
    // An operator who finds `export_total_matches_version` in a report must find the same string
    // on the screen. A prettified "Content hash mismatch" would be a third spelling of a
    // comparison that already has two places to be spelled.
    expect(splitCheck("export_total_matches_version: expected 5, found 4")).toEqual({
      name: "export_total_matches_version",
      detail: "expected 5, found 4",
    });
    // A line the server sends without the separator still shows something rather than nothing.
    expect(splitCheck("something_unexpected")).toEqual({
      name: "something_unexpected",
      detail: "",
    });
  });

  it("says something when a quarantined export has no failures to list", () => {
    // The case that would otherwise render a red banner over an empty list: quarantined because a
    // comparison failed when it was checked, sound at this moment. That is itself a finding — the
    // file changed between two checks — and the screen says so rather than showing nothing.
    expect(page).toContain('data-testid="failed-checks-empty"');
    expect(page).toContain("admin.export.failedChecksUnavailable");
  });
});

describe("UI-EXPORT-001: every item §14.4 lists", () => {
  // The mapping a human has to get right; the list comes from the document. Two items are
  // deliberately absent, each with the plan question that owns it — and the completeness test
  // below asserts against exactly that set, so a thirteenth item still fails.
  const LABELS: Record<string, string> = {
    "file name": "admin.export.fileName",
    checksum: "admin.export.checksum",
    "generation time": "admin.export.generationTime",
    "exact version": "admin.export.exactVersion",
    "approval/hash match": "admin.export.approvalMatch",
    "row count": "admin.export.rowCount",
    total: "admin.export.total",
    mapping: "admin.export.mapping",
    "source account": "admin.export.sourceAccount",
    "integrity state": "admin.export.integrityState",
  };

  const ABSENT: Record<string, string> = {
    "generator version":
      "S-6 — nothing in the system records one, so the screen says that rather than showing a " +
      "constant that would name the current writer instead of the one that made this file",
    "download history where permitted":
      "S-5 — the table keeps one timestamp, not a history; it is shown as the single fact it is",
  };

  it.each(Object.keys(LABELS))("renders a label for %s", (item) => {
    expect(page, `§14.4 names ${item} and the page has no ${LABELS[item]}`).toContain(LABELS[item]);
  });

  it("maps or records every item the document lists", () => {
    const unmapped = bulleted("## 14.4 Final export detail")
      .filter((item) => !(item in LABELS))
      .sort();

    expect(unmapped, "each §14.4 item needs a label or a recorded reason").toEqual(
      Object.keys(ABSENT).sort(),
    );
  });

  it("says on the screen that the generator version is not recorded", () => {
    // S-6, put where an accountant will look rather than only in the plan. Somebody comparing two
    // exports that render differently needs to know this is not a question the platform answers.
    expect(page).toContain('data-testid="generator-version-absent"');
    expect(page).toContain("admin.export.generatorVersionAbsent");
  });

  it("leaves no recorded absence without a reason", () => {
    for (const [item, reason] of Object.entries(ABSENT)) {
      expect(reason.length, `${item} is recorded absent with no real reason`).toBeGreaterThan(80);
      expect(reason).toContain("S-");
    }
  });
});

describe("§14.3's states are the catalogue's, not the document's", () => {
  /** The `states:` block of the `bank_export` aggregate, stopping before `unresolved_aliases:`. */
  function catalogueStates(): readonly string[] {
    const catalogue = readFileSync(CATALOGUE, "utf8");
    const aggregate = catalogue.slice(catalogue.indexOf("\n  bank_export:"));
    const states = aggregate.slice(
      aggregate.indexOf("states:"),
      aggregate.indexOf("unresolved_aliases:"),
    );
    return (states.match(/canonical: (\w+)/gu) ?? []).map((line) =>
      line.replace("canonical: ", ""),
    );
  }

  it("labels every status the bank_export aggregate has", () => {
    // Parsed from the governance catalogue, which is what the enforced CHECK is held to. §14.3
    // names `requested` and `superseded`; a screen built on the document would carry two states the
    // API can never return.
    const statuses = catalogueStates();

    expect(statuses.length, "the catalogue parse found nothing").toBeGreaterThan(4);
    expect(Object.keys(EXPORT_STATUS_LABELS).sort()).toEqual([...statuses].sort());
  });

  it("finds superseded recorded as unresolved rather than merely missing", () => {
    // This is what makes the omission provably right instead of assumed. The catalogue does not
    // just lack `superseded` — it records it under `unresolved_aliases` with `canonical: null`,
    // which is DOC-CONFLICT-016 in the catalogue's own words. If M0 ever resolves it, that block
    // changes and this test is where somebody finds out the screen needs a ninth label.
    const catalogue = readFileSync(CATALOGUE, "utf8");
    const aggregate = catalogue.slice(catalogue.indexOf("\n  bank_export:"));
    const unresolved = aggregate.slice(aggregate.indexOf("unresolved_aliases:"));

    expect(unresolved.slice(0, 400)).toContain("superseded");
    expect(unresolved.slice(0, 400)).toContain("canonical: null");
    expect(catalogueStates()).not.toContain("superseded");
  });

  it("shows the raw value for a status it has not been taught", () => {
    // Rather than an empty cell. A blank state on a payment file hides that anything is odd; a
    // raw `superseded` tells whoever is looking that the platform returned something new.
    expect(statusLabelKey("superseded")).toBeNull();
    expect(statusLabelKey("validated")).toBe("admin.export.status.validated");
  });
});
