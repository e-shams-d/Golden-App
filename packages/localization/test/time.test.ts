import { describe, expect, it } from "vitest";

import { tehranWallClockToInstant } from "../src";

// Every expectation below was measured from Node's own time-zone data (ICU 78.3, tz 2026b), not
// remembered: Tehran is +03:30 today, was +04:30 in the summer of 2021, skipped 00:00-00:59 on
// 22 March 2021 and repeated 23:00-23:59 on 21 September 2021.
describe("a wall clock typed in Tehran", () => {
  it("is the instant it names in Tehran, not in UTC", () => {
    // F-39: sent as typed, this was stored as 10:30 UTC — 14:00 in Tehran.
    expect(tehranWallClockToInstant("2026-10-14T10:30")).toBe("2026-10-14T07:00:00.000Z");
    expect(tehranWallClockToInstant("2026-10-14T10:30:15")).toBe("2026-10-14T07:00:15.000Z");
  });

  it("takes its offset from the time-zone database, so summer time before 2022 is right", () => {
    expect(tehranWallClockToInstant("2021-06-01T12:00")).toBe("2021-06-01T07:30:00.000Z");
    expect(tehranWallClockToInstant("2023-06-01T12:00")).toBe("2023-06-01T08:30:00.000Z");
  });

  it("is refused in the hour the clocks skipped, which never happened", () => {
    expect(tehranWallClockToInstant("2021-03-22T00:30")).toBeNull();
  });

  it("is refused in the hour the clocks repeated, which happened twice", () => {
    expect(tehranWallClockToInstant("2021-09-21T23:30")).toBeNull();
  });

  it("is still read on either side of a change", () => {
    expect(tehranWallClockToInstant("2021-03-21T23:30")).toBe("2021-03-21T20:00:00.000Z");
    expect(tehranWallClockToInstant("2021-03-22T01:30")).toBe("2021-03-21T21:00:00.000Z");
    expect(tehranWallClockToInstant("2021-09-21T22:30")).toBe("2021-09-21T18:00:00.000Z");
    expect(tehranWallClockToInstant("2021-09-22T00:30")).toBe("2021-09-21T21:00:00.000Z");
  });

  it("is refused when it is not a wall clock at all", () => {
    for (const typed of [
      "",
      "10:30",
      "2026-10-14",
      "2026-02-30T10:00",
      "2026-10-14T24:00",
      "2026-10-14T10:30Z",
    ]) {
      expect(tehranWallClockToInstant(typed), typed).toBeNull();
    }
  });
});
