/**
 * The evidence panel, and the one claim that makes slice C worth doing.
 *
 * M0 slice C. `POST /evidence-links` has existed since M9 with no caller. Its `NO_SCREEN` entry
 * blamed a missing file browser; the actual blocker was one read — nothing enumerated an attempt's
 * links, so the confirmation form had nothing to cite and could only ever offer the *reason*
 * evidence was unavailable. Every payment confirmed through this screen recorded an excuse.
 *
 * Asserted on source, for the reason `approval-screens.test.ts` gives.
 *
 * Covers: UI-EVIDENCE-001.
 */

import { readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

const APP_ROOT = join(import.meta.dirname, "..");
const ATTEMPT = join(APP_ROOT, "app", "payment-attempts", "[attemptId]", "page.tsx");
const DATA = join(APP_ROOT, "src", "payment-results.ts");

const read = (path: string): string => readFileSync(path, "utf8");

/** The file without comments; a claim about what a screen does not do cannot read its prose. */
const code = (path: string): string =>
  read(path)
    .replace(/\/\*[\s\S]*?\*\//g, "")
    .replace(/^\s*\/\/.*$/gm, "");

describe("the payment confirmation", () => {
  it("cites the evidence link when one exists and asks for a reason only when none does", () => {
    const source = code(ATTEMPT);

    // `evidence_policy_satisfied` wants one or the other. Sending both would record a document and
    // an apology for its absence; sending neither is what the policy exists to refuse.
    expect(source).toContain("primaryEvidenceLinkId: activeLink?.id ?? null");
    expect(source).toMatch(/evidenceUnavailableReason:\s*\n?\s*activeLink === null \? unavailableReason : null/);
  });

  it("hides the unavailable-reason field when a link is attached", () => {
    const source = code(ATTEMPT);

    // A field that is required and meaningless is worse than an absent one: it teaches somebody to
    // invent a reason for the absence of evidence that is sitting in front of them.
    expect(source).toContain("{activeLink === null ? (");
    expect(source).toContain("attempt-evidence-unavailable");
    expect(source).toContain("attempt-evidence-cited");
  });
});

describe("the evidence panel", () => {
  it("lists replaced and revoked links rather than only the active one", () => {
    const source = code(ATTEMPT);

    // §12.6 `:1306`: a replacement never deletes the old relationship. An attempt whose evidence
    // was corrected must read as corrected rather than as one row that quietly changed.
    expect(source).toContain("links.map((link)");
    expect(source).not.toMatch(/links\.filter\([^)]*status[^)]*active/);
  });

  it("offers replace and void only on the active link", () => {
    const source = code(ATTEMPT);

    // A replaced link is history. Offering to replace it again would be offering to rewrite what
    // happened, and the server refuses it — better not to ask.
    expect(source).toContain('link.status === "active" ? (');
  });

  it("does not offer to confirm a second link while one is active", () => {
    const source = code(ATTEMPT);

    // `uq_evidence_link_attempt_type` permits one active primary link per attempt. A button that
    // always submitted would produce a 409 a person cannot act on.
    expect(source).toContain("activeLink !== null");
    expect(source).toContain("attempt.evidenceAlreadyLinked");
  });

  it("reads the links with the attempt, in one state", () => {
    const source = code(ATTEMPT);

    // Two pieces of state would let the panel describe an attempt the page has already replaced,
    // and a second `setState` inside the effect is what the lint rule refuses.
    expect(source).toContain("return { kind: \"ready\", attempt, ifMatch, links }");
    expect(source).not.toContain("setLinks");
  });
});

describe("the evidence data module", () => {
  it("scopes the list to one attempt", () => {
    const source = code(DATA);
    const listing = source.slice(source.indexOf("export async function listEvidenceLinks"));

    // An unfiltered list would hand every holder of `receipt_segment.read` every evidence link in
    // the centre — a different and much larger disclosure than "what proves this attempt".
    expect(listing).toContain("payment_attempt_id=");
    expect(listing).toContain("encodeURIComponent(paymentAttemptId)");
  });

  it("sends no precondition with any of the three commands", () => {
    const source = code(DATA);
    const evidence = source.slice(
      source.indexOf("export async function confirmEvidenceLink"),
      source.indexOf("export async function readEvidenceLink"),
    );

    // §12.6 gives this table no `record_version`, and none of the three routes takes an `If-Match`.
    // The concurrency is two partial unique indexes, enforced in the database.
    expect(evidence).not.toContain("ifMatch");
    expect(evidence).not.toContain("rv-");
    // All three are commands and all three require a key.
    expect(evidence.match(/idempotencyKey: commandKey\(\)/g)).toHaveLength(3);
  });
});
