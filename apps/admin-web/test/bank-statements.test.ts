/**
 * The statement import screens, and the claims a reachability gate cannot make.
 *
 * M0 slice D. `tests/backend/test_every_operation_has_a_screen.py` proves the five operations are
 * *reached* — and the way this slice was found proves how weak that is on its own: those five were
 * recorded as having no screen for a reason that was true and was not the blocker. The real one was
 * that an import run needs an active mapping and nothing could produce one.
 *
 * So these assert the things that would let a screen be reachable and still wrong: naming a mapping
 * it has no business naming, collapsing "not yet parsed" into "nothing found", or offering an
 * operator a form whose preconditions cannot be met.
 *
 * Asserted on source for the reason `bank-configuration.test.ts` gives: these are claims about
 * completeness and about what is absent, and rendering them would need a browser, a router and a
 * stubbed transport to say what the source says plainly. The a11y sweep opens both pages for real.
 *
 * Covers: UI-STATEMENT-001.
 */

import { readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

const APP_ROOT = join(import.meta.dirname, "..");
const LIST = join(APP_ROOT, "app", "bank-statements", "page.tsx");
const DETAIL = join(APP_ROOT, "app", "bank-statements", "[statementId]", "page.tsx");
const DATA = join(APP_ROOT, "src", "bank-statements.ts");

const read = (path: string): string => readFileSync(path, "utf8");

/**
 * The file with its comments removed.
 *
 * Every file here explains in prose why it does *not* name a mapping, so a substring assertion
 * against the raw source would match the explanation and fail. `bank-configuration.test.ts` hit
 * exactly this and records it; so does `test_governance_counts_reconcile.py`.
 */
const code = (path: string): string =>
  read(path)
    .replace(/\/\*[\s\S]*?\*\//g, "")
    .replace(/^\s*\/\/.*$/gm, "");

describe("the statement data module", () => {
  it("never sends a bank mapping, though it reads the one a run used", () => {
    const source = code(DATA);
    const startRun = source.slice(source.indexOf("export async function startImportRun"));

    // The owner decided on 2026-09-13 that there is one fixed mapping in code, resolved from the
    // statement's own bank-profile version. A client that sent an id would be holding a copy of a
    // value the server derives — and a stale copy would aim a run at a retired version's mapping,
    // which the server then refuses for a reason no operator could act on.
    expect(startRun).toContain("body: {}");
    expect(startRun).not.toContain("bank_mapping_id");
    expect(source).not.toContain("bankMappingId");

    // **The response type keeps it, and that is the opposite claim rather than an exception.**
    // `TRACE-IMPORT-001` asks which mapping a run used; the run records it because the answer must
    // survive the mapping being superseded. Not sending a value and not being able to read it back
    // are different things, and a test that banned the string outright would forbid the second.
    expect(source).toContain("bank_mapping_id: string");
  });

  it("fixes the upload purpose rather than letting a screen choose it", () => {
    const source = code(DATA);

    // The purpose decides visibility and the size ceiling. A screen that could name one could ask
    // for a purpose it has no business using; `trader-pwa/src/evidence.ts` fixes its own for the
    // same reason.
    expect(source).toContain('body.append("purpose", "bank_statement")');
    expect(source).not.toMatch(/purpose\s*:\s*string/);
  });

  it("carries an idempotency key on both commands and on neither read", () => {
    const source = code(DATA);
    const create = source.slice(source.indexOf("export async function createBankStatement"));
    const startRun = source.slice(source.indexOf("export async function startImportRun"));
    const list = source.slice(
      source.indexOf("export async function listBankStatements"),
      source.indexOf("export async function readBankStatement"),
    );

    // `command_catalog.yaml` marks both `idempotency: required` and the route answers 428 without
    // one. An upload retried without a key would file the bank's statement twice.
    expect(create).toContain("idempotencyKey");
    expect(startRun).toContain("idempotencyKey");
    expect(list).not.toContain("idempotencyKey");
  });

  it("sends a date range as null rather than as an empty string", () => {
    const source = code(DATA);

    // The column is null-tolerant and the command refuses half a range. An empty string would be a
    // value the server has to reject, and the operator would be told their blank field was invalid.
    expect(source).toContain("date_range_start");
    expect(source).toMatch(/date_range_start:[^,]*:\s*null/);
  });
});

describe("the statement list screen", () => {
  it("refuses to submit half a date range", () => {
    const source = code(LIST);

    // §8.1 makes the range optional and the command refuses one end alone. Enforced here too, so
    // the operator is told which end is missing before a round trip rather than after.
    expect(source).toContain("rangeIsWhole");
    expect(source).toContain("!rangeIsWhole");
  });

  it("will not submit without an uploaded file, an account and a version", () => {
    const source = code(LIST);
    const button = source.slice(source.indexOf('data-testid="statement-create"'));

    // Every one of the three is a `NOT NULL` the command resolves before it writes. A form that
    // let them be blank would turn three preconditions into three 404s.
    expect(button).toContain("uploadedFileId === null");
    expect(button).toContain('form.bankAccountId === ""');
    expect(button).toContain('form.bankProfileVersionId === ""');
  });

  it("says what file shape is expected, because no conversion happens", () => {
    // The owner's decision of 2026-09-13 in the one place somebody acts on it. A file whose columns
    // differ fails the parse; it is not converted, and a screen that did not say so would let an
    // operator upload the wrong export and read the failure as a broken platform.
    expect(read(LIST)).toContain("statement.expectedShape");
  });

  it("tells an operator with no configured bank what to do instead of showing a dead form", () => {
    const source = code(LIST);

    // A fresh deployment has no active version, so no mapping was seeded and nothing here can work.
    // The refusal from the server would be accurate and useless on its own.
    expect(source).toContain("statement.configureBankFirst");
    expect(source).toContain("phase.versions.length === 0");
  });

  it("clears the uploaded file once it belongs to a statement", () => {
    const source = code(LIST);

    // Without this a second press files the same bytes under a new record, and two statements would
    // claim to be the original of one file.
    expect(source).toContain("setUploadedFileId(null)");
  });
});

describe("the statement detail screen", () => {
  it("shows every run rather than only the last", () => {
    const source = code(DETAIL);

    // §8.2: "Reprocessing never overwrites earlier rows." An operator who could only see the latest
    // run would have to take that on trust — which is why M10 added the list route at all.
    expect(source).toContain("listImportRuns");
    expect(source).toContain("runs.map");
  });

  it("distinguishes a run that has not finished from one that found nothing", () => {
    const source = code(DETAIL);

    // Null is "not parsed yet"; zero is "parsed and empty". The server keeps them apart
    // deliberately, and a screen that rendered both as a number would report an empty statement
    // when nothing had run.
    expect(source).toContain("run.row_count === null");
    expect(source).toContain("statement.rowCountPending");
  });

  it("does not offer a second parse while one is in flight", () => {
    const source = code(DETAIL);

    // The server refuses it — two row sets for one file with nothing to say which is authoritative.
    // Disabled here so the operator learns before the click.
    expect(source).toContain("inFlight");
    expect(source).toMatch(/disabled=\{busy \|\| inFlight\}/);
  });

  it("starts a run without naming a mapping", () => {
    const source = code(DETAIL);

    expect(source).toContain("startImportRun(statementId)");
    expect(source).not.toContain("mapping");
  });
});
