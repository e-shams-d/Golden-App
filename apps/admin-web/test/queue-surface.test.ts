import { readFileSync } from "node:fs";
import { join } from "node:path";

import { faMessages, queueLabel, queueSortLabel } from "@gold/localization";
import { describe, expect, it } from "vitest";

/**
 * The work queue surface: one table, sixteen queues, and the paging model §19.3 requires.
 *
 * M11 Screens slice 2. **Structural, in this app's house style** — every test file in
 * `apps/admin-web/test/` reads source rather than rendering, and `preconditions-come-from-the-
 * server.test.ts` states why that is the right shape for claims of the form "this code does not
 * construct X". The behavioural half needs a database and lives in
 * `tests/integration/test_queue_index.py`.
 *
 * The claims here are the ones a renderer could not check anyway:
 *
 * - the client has no way to construct an offset, so cursor paging is not merely the default;
 * - a control is rendered from the server's allowlist rather than from a list in this app;
 * - the count shown is the server's `total`, not the length of the page;
 * - no queue screen carries an amount, which is a disclosure decision inherited sixteen times.
 */

const APP_ROOT = join(import.meta.dirname, "..");

function source(...parts: string[]): string {
  return readFileSync(join(APP_ROOT, ...parts), "utf8");
}

/**
 * The same file with its comments removed.
 *
 * Necessary for exactly the reason `preconditions-come-from-the-server.test.ts` records: these
 * modules *explain* the rules in prose — "a cursor, never an offset" — and a check a prose
 * mention can trip is one somebody eventually satisfies by deleting the explanation.
 *
 * Block comments then line comments, in that order: a `//` inside a block comment is part of the
 * block, and stripping lines first would leave the block's opener behind.
 */
function code(...parts: string[]): string {
  return source(...parts)
    .replace(/\/\*[\s\S]*?\*\//g, "")
    .replace(/^\s*\/\/.*$/gm, "");
}

const DATA_MODULE = ["src", "queues.ts"] as const;
const QUEUE_PAGE = ["app", "queues", "[queue]", "page.tsx"] as const;
const QUEUE_TABLE = ["components", "queue-table.tsx"] as const;
const INDEX_PANEL = ["components", "queue-index.tsx"] as const;
const DASHBOARD = ["app", "page.tsx"] as const;

/**
 * Building an offset parameter, as regex **literals**.
 *
 * Not assembled with `new RegExp` over a template string: inside a template literal `\b` is a
 * backspace rather than a word boundary, which made an earlier structural check in this repository
 * match nothing and pass over any source at all.
 */
const OFFSET_CONSTRUCTION: readonly RegExp[] = [
  /\boffset\b/,
  /\bskip\b/,
  /["'`]page["'`]/,
  /\bpageNumber\b/,
];

describe("the client cannot page by offset", () => {
  it("names no offset parameter anywhere in the queue surface", () => {
    // An offset re-reads from the top on every page, so rows shift under somebody draining a
    // queue and items are skipped or seen twice — in the one place whose purpose is to touch
    // every row exactly once. The server ignores an offset if sent; that it is never sent is the
    // half checkable from here.
    for (const parts of [DATA_MODULE, QUEUE_PAGE, QUEUE_TABLE, INDEX_PANEL]) {
      const body = code(...parts);
      for (const pattern of OFFSET_CONSTRUCTION) {
        expect(pattern.test(body), `${parts.join("/")} matches ${pattern}`).toBe(false);
      }
    }
  });

  it("sends the cursor the server returned", () => {
    const body = code(...DATA_MODULE);
    expect(body).toContain('parameters.set("cursor"');
    expect(body).toContain("query.cursor");
  });

  it("returns to the first page whenever the question changes", () => {
    // A cursor is only meaningful for the query it came from. Keeping it across a sort or filter
    // change resumes from a position in a different result set, which is how paging silently
    // skips rows — the same defect an offset has, arrived at from the other direction.
    const body = code(...QUEUE_PAGE);
    const resets = body.match(/setCursor\(null\)/g) ?? [];
    expect(
      resets.length,
      "the sort handler, the apply handler and the clear handler must each reset the cursor",
    ).toBeGreaterThanOrEqual(3);
  });
});

describe("the controls come from the server", () => {
  it("renders filter inputs from the queue's own allowlist", () => {
    // `read_queue_page` refuses an unlisted filter rather than ignoring it, so a control
    // hardcoded here would put a 400 in front of somebody working the day a spec changed.
    const body = code(...QUEUE_TABLE);
    expect(body).toContain("listing.filters.map");
    expect(body).toContain("listing.sorts.map");
  });

  it("holds no list of queue names in the code that decides which queues to show", () => {
    // The set of queues is the backend's, reached through `GET /api/v1/queues`. A second list
    // here drifts the day a queue is renamed, and its failure mode is a link to a queue the
    // server no longer serves. `tests/backend/test_queue_screens_exist.py` holds the same claim
    // against the registry itself, which is the half that knows all sixteen names.
    for (const parts of [DATA_MODULE, QUEUE_PAGE, QUEUE_TABLE, INDEX_PANEL, DASHBOARD]) {
      const body = code(...parts);
      expect(body, `${parts.join("/")} names a queue literally`).not.toMatch(
        /"(new-requests|orders-ready-for-dispatch|quarantined-files-exports)"/,
      );
    }
  });
});

describe("what the screen claims about numbers", () => {
  it("shows the server's total rather than the length of the page", () => {
    // §2.3 `:205` — server truth over visual state. Here the two differ by construction: a page
    // is at most `limit` rows and the queue is however long it is.
    //
    // Asserted on what fills the message rather than on `rows.length` being absent from the file:
    // the first version banned the phrase outright and failed, because the table legitimately
    // uses it twice — for the empty check and for a caption saying how many rows are *shown*,
    // which is an honest statement about the page. **Proximity was the wrong question.** What
    // matters is which value reaches the total.
    const body = code(...QUEUE_TABLE);
    expect(body).toContain('t("queues.total").replace("{count}", String(total))');
    expect(body).not.toMatch(/queues\.total"\)\s*\.replace\([^)]*rows\.length/);
  });

  it("shows each queue's waiting count from the index entry", () => {
    const body = code(...INDEX_PANEL);
    expect(body).toContain("listing.waiting");
  });

  it("no longer renders the placeholder the dashboard carried since M1", () => {
    // Four invented queue names and an em dash, with a screen-reader note saying the count had
    // not been received. Honest for eleven milestones and false now.
    const body = source(...DASHBOARD);
    expect(body).not.toContain("تعداد هنوز دریافت نشده است");
    expect(body).not.toContain("admin.queue.traderApproval");
    expect(body).toContain("QueueIndexPanel");
  });
});

describe("what the queue table does not show", () => {
  it("carries no amount, on any queue", () => {
    // Not an omission but a disclosure decision. §19 `:1298`'s last rule — a technical admin does
    // not receive full financial detail by default — is honoured by there being no amount in
    // `QueueRow` at all, and one table means a well-meaning later change would inherit an added
    // column sixteen times.
    const body = code(...QUEUE_TABLE);
    for (const pattern of [/\bamount\b/i, /\brial\b/i, /مبلغ/]) {
      expect(pattern.test(body), `the queue table matches ${pattern}`).toBe(false);
    }
  });
});

describe("the Persian labels", () => {
  it("names every queue the sixteen routes serve", () => {
    // The authoritative version of this check reads `BUILT` and lives in
    // `tests/backend/test_queue_screens_exist.py` — it is the half that knows what the registry
    // holds. This one asserts the lookup itself works, so a `queueLabel` that had stopped finding
    // anything would not be discovered only by reading a screen.
    expect(queueLabel("new-requests")).toBe("درخواست‌های جدید");
    expect(queueLabel("orders-ready-for-dispatch")).toBe("سفارش‌های آماده تحویل");
  });

  it("falls back to the raw segment rather than inventing a name", () => {
    expect(queueLabel("a-queue-that-does-not-exist")).toBe("a-queue-that-does-not-exist");
    expect(queueSortLabel("some_field")).toBe("some_field");
  });

  it("labels both sort fields the sixteen queues use", () => {
    expect(queueSortLabel("created_at")).toBe("زمان ثبت");
    expect(queueSortLabel("id")).toBe("شناسه داخلی");
  });

  it("has a count of queue labels worth checking, so the lookups above are not vacuous", () => {
    const labels = Object.keys(faMessages).filter((key) => key.startsWith("queue."));
    expect(labels.length).toBe(16);
  });
});
