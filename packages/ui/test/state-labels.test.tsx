import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { STATE_KINDS, StateView } from "../src";

/**
 * The label is the one piece of text on the panel that the screen does not choose.
 *
 * `StateView` prints a label for the kind it is given, above the title and description
 * the screen passes in. Four screens that confirm a completed action — a password change
 * in each app, an administrator's recovery, a trader's registration — had no kind of their
 * own and borrowed `empty`, so each of them said "بدون داده" directly above "گذرواژه تغییر
 * کرد". The acceptance pass recorded it as F-10 on three different pages before anyone
 * saw it was one cause.
 *
 * The component's own docstring gives the test for a separate kind, written for
 * `timeout`: a person told an operation failed retries it. The same reasoning applies
 * here — a person told there is no data after changing a password wonders whether it
 * worked, and does it again.
 *
 * Covers: F-10.
 */

/** The label's text: the first `span` the panel renders. No pattern, so nothing to escape. */
function labelOf(html: string): string {
  const closing = html.indexOf("</span>");
  const opening = html.lastIndexOf(">", closing);
  return html.slice(opening + 1, closing);
}

function render(kind: (typeof STATE_KINDS)[number], title = "عنوان"): string {
  return renderToStaticMarkup(<StateView description="شرح" kind={kind} title={title} />);
}

describe("the label above a screen's own title", () => {
  it("has kinds to check, so the assertions below are not vacuous", () => {
    expect(STATE_KINDS.length).toBeGreaterThanOrEqual(10);
    expect(labelOf(render("empty"))).toBe("بدون داده");
  });

  it("does not put 'no data' above a completed action", () => {
    const html = render("success", "گذرواژه تغییر کرد");

    expect(labelOf(html)).toBe("انجام شد");
    expect(html).not.toContain("بدون داده");
  });

  it("does not put 'no data' above an explanation either", () => {
    // The bank-configuration detail screen explains why there is no "new version" form.
    // There is data on that screen — the table of versions sits directly above the note.
    expect(labelOf(render("info"))).not.toBe("بدون داده");
  });

  it("announces both politely, as a status and not as an alert", () => {
    // A confirmation that interrupted a screen reader the way an error does would be
    // teaching people that completing something is a fault.
    for (const kind of ["success", "info"] as const) {
      const html = render(kind);
      expect(html).toContain('role="status"');
      expect(html).not.toContain('role="alert"');
    }
  });

  it("gives every kind a label of its own", () => {
    // The guard on the fix. Two kinds sharing a label is the defect in a different
    // place: the label would again say something the kind did not mean.
    const labels = STATE_KINDS.map((kind) => labelOf(render(kind)));

    for (const label of labels) expect(label.length).toBeGreaterThan(0);
    expect(new Set(labels).size).toBe(STATE_KINDS.length);
  });
});
