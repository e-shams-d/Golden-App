import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { Instant, formatInstant } from "../src";

/**
 * F-40. Every screen printed a timestamp exactly as the API sent it — `2026-10-14T07:00:00Z` —
 * so a goldsmith who received a message at 10:30 read "07:00", on the Gregorian calendar, in
 * Latin digits. Document 21 §4.5 gives the intended form, and
 * `apps/admin-web/test/timestamps-are-readable.test.ts` holds this to the document's own example.
 *
 * Every expectation here was measured from Node's ICU (78.3, tz 2026b) before it was written.
 */
describe("an instant, read in Tehran", () => {
  it("is the Jalali date and the clock in Tehran, in Persian digits", () => {
    expect(formatInstant("2026-10-14T07:00:00Z")).toBe("۱۴۰۵/۰۷/۲۲، ساعت ۱۰:۳۰");
    expect(formatInstant("2026-10-14T07:00:00.123456+00:00")).toBe("۱۴۰۵/۰۷/۲۲، ساعت ۱۰:۳۰");
  });

  it("turns the year at midnight in Tehran, not in UTC", () => {
    expect(formatInstant("2026-03-20T20:29:00Z")).toBe("۱۴۰۴/۱۲/۲۹، ساعت ۲۳:۵۹");
    expect(formatInstant("2026-03-20T20:31:00Z")).toBe("۱۴۰۵/۰۱/۰۱، ساعت ۰۰:۰۱");
  });

  it("takes the offset from the time-zone database, so 2021's summer time is right", () => {
    expect(formatInstant("2021-06-01T07:30:00Z")).toBe("۱۴۰۰/۰۳/۱۱، ساعت ۱۲:۰۰");
  });

  it("refuses a value that names no single instant", () => {
    for (const value of ["", "2026-10-14", "2026-10-14T10:30", "not a date"]) {
      expect(formatInstant(value), value).toBeNull();
    }
  });
});

describe("the element", () => {
  it("keeps the exact server value beside the readable one", () => {
    const html = renderToStaticMarkup(<Instant value="2026-10-14T07:00:00Z" />);

    expect(html).toBe(
      '<time dateTime="2026-10-14T07:00:00Z" title="زمان دقیق سامانه: 2026-10-14T07:00:00Z">' +
        "۱۴۰۵/۰۷/۲۲، ساعت ۱۰:۳۰</time>",
    );
  });

  it("shows a value it cannot read as it came, left to right, without guessing", () => {
    const html = renderToStaticMarkup(<Instant value="2026-10-14T10:30" />);

    expect(html).toContain('dir="ltr"');
    expect(html).toContain(">2026-10-14T10:30<");
    expect(html).not.toContain("<time");
  });
});
