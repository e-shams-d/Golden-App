/**
 * Taking the file, and coming back to say it was sent — with the sentence that separates the two.
 *
 * Screens slice 4, the last of the plan. `UI-DOWNLOAD-001` is the one obligation in this milestone
 * whose whole content is a form of words: `15_Agent_Implementation_Plan.md:989` makes "downloading
 * does not mean sent" the central human-factors risk, and §14.6 answers it by giving the sentence.
 * A paraphrase is not a translation decision — it is dropping the requirement.
 *
 * Asserted against source rather than a rendered DOM, for the reason `export-screens.test.ts`
 * gives: three of these five are claims about what the code *cannot* do — infer the reminder
 * client-side, target a batch, show fewer than ten fields — and a rendering test proves the path it
 * exercises rather than the absence of another.
 *
 * Covers: UI-DOWNLOAD-001, UI-SENT-001, UI-SENT-002, UI-SENT-003, TRACE-SCREENS-001.
 */

import { existsSync, readdirSync, readFileSync, statSync } from "node:fs";
import { join, relative } from "node:path";

import { describe, expect, it } from "vitest";

import {
  DOWNLOAD_IS_NOT_SENDING,
  downloadPath,
  isAwaitingSendConfirmation,
} from "../src/bank-exports";

const APP_ROOT = join(import.meta.dirname, "..");
const REPOSITORY_ROOT = join(APP_ROOT, "..", "..");
const SPECIFICATION = join(
  REPOSITORY_ROOT,
  "Implementation Docs",
  "04_Frontend_and_Experience",
  "21_UI_Design_System_and_Screen_Specification.md",
);

const EXPORT_PAGE = join(APP_ROOT, "app", "bank-exports", "[exportId]", "page.tsx");
const DIALOG = join(APP_ROOT, "components", "mark-sent-dialog.tsx");
const SWEEP = join(APP_ROOT, "tests", "a11y", "shell.spec.ts");

const page = readFileSync(EXPORT_PAGE, "utf8");
const dialog = readFileSync(DIALOG, "utf8");
const specification = readFileSync(SPECIFICATION, "utf8");

/** The first fenced block under a heading — how the document writes text that must appear as-is. */
function fenced(heading: string): string {
  const start = specification.indexOf(heading);
  const body = specification.slice(start + heading.length);
  const open = body.indexOf("```");
  const afterFence = body.indexOf("\n", open) + 1;
  return body.slice(afterFence, body.indexOf("```", afterFence)).trim();
}

function bulleted(heading: string): readonly string[] {
  const start = specification.indexOf(heading);
  const body = specification.slice(start + heading.length);
  return body
    .slice(0, body.indexOf("\n#"))
    .split("\n")
    .filter((line) => line.startsWith("- "))
    .map((line) => line.slice(2).trim().replace(/[;.]$/u, "").toLowerCase());
}

describe("the specification still says these things", () => {
  it("finds §14.6's sentence and §14.7's list", () => {
    // Guard the guard. Every assertion below reads from the document, and a parser returning ""
    // would make all of them pass — which is the failure this repository keeps producing.
    expect(fenced("## 14.6 Download").length).toBeGreaterThan(30);
    expect(bulleted("## 14.7 Mark exact export as sent")).toHaveLength(10);
  });
});

describe("UI-DOWNLOAD-001: §14.6's sentence, verbatim, beside the control", () => {
  it("matches the specification character for character", () => {
    expect(DOWNLOAD_IS_NOT_SENDING).toBe(fenced("## 14.6 Download"));
  });

  it("renders the constant rather than a copy of the words", () => {
    expect(page).toContain("{DOWNLOAD_IS_NOT_SENDING}");
    // A literal on the page would satisfy the comparison above and drift the moment somebody
    // edited the page instead of the constant.
    expect(page).not.toContain("does not mean it was sent");
  });

  it("puts it beside the download control, not after the click", () => {
    // §14.6 says the UI "must clearly state" it, and the moment it has to be stated is *before*
    // somebody clicks — afterwards they have the file and have left the screen.
    const actions = page.slice(page.indexOf("function Actions"), page.indexOf("function PreviewBanner"));
    const sentenceAt = actions.indexOf("DOWNLOAD_IS_NOT_SENDING");
    const controlAt = actions.indexOf('data-testid="download-export"');

    expect(sentenceAt).toBeGreaterThan(-1);
    expect(controlAt).toBeGreaterThan(sentenceAt);
  });

  it("marks it as English inside a right-to-left page", () => {
    const marker = page.slice(page.indexOf('data-testid="download-is-not-sending"'));
    expect(marker.slice(0, 100)).toContain('dir="ltr"');
  });

  it("says the same thing in Persian as well", () => {
    // The English is what §14.6 requires; the Persian is what the accountant reads. Neither
    // replaces the other, and a screen with only the English would satisfy the letter of the
    // obligation while communicating nothing.
    expect(page).toContain("admin.export.downloadIsNotSending");
  });
});

describe("UI-SENT-001: all ten of §14.7's fields, before the command", () => {
  // The mapping a human gets right; the list comes from the document. Three of the ten are the
  // values being *supplied*, so they appear as controls rather than read-only rows — recorded here
  // rather than left as a gap, because §14.7 lists them among what the confirmation shows.
  const ROWS: Record<string, string> = {
    "export reference": "admin.export.reference",
    filename: "admin.export.fileName",
    "batch/version": "admin.export.batchAndVersion",
    "checksum/integrity state": "admin.export.checksumAndIntegrity",
    "row count": "admin.export.rowCount",
    total: "admin.export.total",
    "bank/source account": "admin.export.bankAndSourceAccount",
  };

  const CONTROLS: Record<string, string> = {
    "submission channel": "submission-channel",
    "sent time": "sentAt: new Date().toISOString()",
    note: "mark-sent-note",
  };

  it.each(Object.keys(ROWS))("shows %s in the summary", (item) => {
    expect(dialog, `§14.7 names ${item} and the dialog has no ${ROWS[item]}`).toContain(ROWS[item]);
  });

  it.each(Object.keys(CONTROLS))("collects %s as a control", (item) => {
    expect(dialog, `§14.7 names ${item} and the dialog collects nothing for it`).toContain(
      CONTROLS[item],
    );
  });

  it("maps every item the document lists", () => {
    const mapped = new Set([...Object.keys(ROWS), ...Object.keys(CONTROLS)]);
    const unmapped = bulleted("## 14.7 Mark exact export as sent")
      .filter((item) => !mapped.has(item))
      .sort();

    expect(unmapped, "§14.7 names these and the dialog neither shows nor collects them").toEqual([]);
  });

  it("shows them before the command rather than after", () => {
    // "Confirmation" is the word §14.7 uses. A dialog that asked "mark as sent?" with a Yes button
    // would be asking somebody to confirm a decision they cannot see.
    const summaryAt = dialog.indexOf('data-testid="mark-sent-summary"');
    const submitAt = dialog.indexOf('data-testid="mark-sent-submit"');

    expect(summaryAt).toBeGreaterThan(-1);
    expect(submitAt).toBeGreaterThan(summaryAt);
  });
});

describe("UI-SENT-002: the reminder comes from the API, not from a timestamp", () => {
  it("reads the field and nothing else", () => {
    expect(isAwaitingSendConfirmation({ awaiting_send_confirmation: true } as never)).toBe(true);
    expect(isAwaitingSendConfirmation({ awaiting_send_confirmation: false } as never)).toBe(false);
  });

  it("ignores the timestamps entirely", () => {
    // The obvious client-side version is `downloaded_at !== null && sent_to_bank_marked_at === null`
    // and it is wrong rather than merely duplicated: it omits `export_type`, so a downloaded
    // preview would grow a reminder to confirm sending a file nobody may send. Proved by handing it
    // exactly those timestamps and requiring the field to win.
    expect(
      isAwaitingSendConfirmation({
        awaiting_send_confirmation: false,
        downloaded_at: "2026-08-23T00:00:00Z",
        sent_to_bank_marked_at: null,
      } as never),
    ).toBe(false);
  });

  it("renders the reminder from that function", () => {
    expect(page).toContain("isAwaitingSendConfirmation(phase.view)");
    expect(page).toContain('data-testid="awaiting-send-confirmation"');
    // No page-level inference. If either timestamp were compared here, this is where it would be.
    const ready = page.slice(page.indexOf('phase.kind === "ready"'), page.indexOf("function Awaiting"));
    expect(ready).not.toContain("downloaded_at");
  });
});

describe("UI-SENT-003: the command targets the exact export", () => {
  it("sends the export id and never a batch id", () => {
    expect(dialog).toContain("exportId: view.id");
    expect(dialog).not.toContain("batch_id");
    expect(dialog).not.toContain("batchId");
  });

  it("takes one target, and the command's signature offers no other", () => {
    // The structural half. The first version of this test asserted the dialog never mentions a
    // batch at all, and that was simply wrong: §14.7 requires "batch/version" among the ten fields,
    // so the dialog displays `view.batch_number` on purpose. Displaying a batch and *targeting* one
    // are different claims, and only the second is `UI-SENT-003`.
    //
    // What holds is that the command takes exactly one identifier. `markSentToBank` accepts
    // `exportId` and no batch parameter, so there is no argument a careless edit could fill with the
    // wrong id — the call would not compile.
    const client = readFileSync(join(APP_ROOT, "src", "bank-exports.ts"), "utf8");
    const signature = client.slice(
      client.indexOf("export async function markSentToBank"),
      client.indexOf("): Promise<MarkSentConfirmation>"),
    );

    expect(signature).toContain("exportId: string");
    expect(signature).not.toMatch(/batch/iu);
  });

  it("interpolates only the export id into the path", () => {
    const client = readFileSync(join(APP_ROOT, "src", "bank-exports.ts"), "utf8");
    expect(client).toContain("/bank-exports/${encodeURIComponent(input.exportId)}/mark-sent-to-bank");
  });

  it("builds the download URL from the export id too", () => {
    expect(downloadPath("abc-123")).toBe("/api/v1/bank-exports/abc-123/download");
    // Percent-encoded, because an id that is not a UUID must not be able to change the path.
    expect(downloadPath("../batches/1")).not.toContain("../");
  });
});

describe("TRACE-SCREENS-001: every screen this plan added is in the a11y sweep", () => {
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

  it("finds the sweep's list at all", () => {
    expect(sweep).toContain('"/batches"');
    expect(routes().length).toBeGreaterThan(8);
  });

  it("covers every route, including the dynamic ones", () => {
    // The static prefix is what a dynamic route contributes: the sweep visits it with obviously
    // fake ids, which renders the "not found" state — a real state somebody reaches by following a
    // stale link, and the one most likely to ship without a heading.
    //
    // A screen outside this list is a screen nobody checks. `pnpm check` passed over an unswept
    // screen twice in this repository before the list became an assertion.
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
    // The other direction: a sweep entry for a route that no longer exists passes forever, because
    // Next.js answers its own 404 page and that page is accessible.
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
});
