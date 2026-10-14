const BUSINESS_TIME_ZONE = "Asia/Tehran";
const DAY = 24 * 60 * 60 * 1000;
const WALL_CLOCK = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})(?::(\d{2}))?$/;

let tehranFormat: Intl.DateTimeFormat | undefined;

/** Tehran's wall clock at an instant, written as if it were a UTC time so it can be compared. */
function tehranWallClockAt(instant: number): number {
  tehranFormat ??= new Intl.DateTimeFormat("en-US", {
    timeZone: BUSINESS_TIME_ZONE,
    hourCycle: "h23",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
  const parts = tehranFormat.formatToParts(new Date(instant));
  const read = (type: Intl.DateTimeFormatPartTypes): number =>
    Number(parts.find((part) => part.type === type)?.value);
  return Date.UTC(
    read("year"),
    read("month") - 1,
    read("day"),
    read("hour"),
    read("minute"),
    read("second"),
  );
}

/**
 * The UTC instant a wall clock in Tehran names, as an ISO string — or `null` when it names none,
 * or two.
 *
 * `<input type="datetime-local">` submits `2026-10-14T10:30`: a wall clock with no zone. ADR-006
 * point 4 has the interface send the API a UTC instant, and the business zone is Asia/Tehran
 * whatever zone the browser is in — an operator copies the time printed on a Tehran bank's
 * receipt. Sent as typed, the database read it as UTC and stored the bank's 10:30 as 14:00 in
 * Tehran (F-39); the API now refuses a timestamp without a zone.
 *
 * The offset comes from the browser's time-zone database, never a constant: Iran kept daylight
 * saving until 2022, and ADR-006 point 3 forbids a fixed offset. A wall clock in the hour the
 * clocks skipped, or the hour they repeated, is refused — the rule the backend applies to a bank
 * file's clock.
 */
export function tehranWallClockToInstant(local: string): string | null {
  const match = WALL_CLOCK.exec(local.trim());
  if (match === null) return null;
  const [year = 0, month = 0, day = 0, hour = 0, minute = 0, second = 0] = match
    .slice(1)
    .map((part) => (part === undefined ? 0 : Number(part)));
  const wall = Date.UTC(year, month - 1, day, hour, minute, second);
  // `Date.UTC` rolls 30 February over into March rather than refusing it.
  const written = new Date(wall);
  if (
    written.getUTCFullYear() !== year ||
    written.getUTCMonth() !== month - 1 ||
    written.getUTCDate() !== day ||
    written.getUTCHours() !== hour ||
    written.getUTCMinutes() !== minute ||
    written.getUTCSeconds() !== second
  ) {
    return null;
  }

  // Every offset Tehran had within a day either side, and the instant each would make. No change
  // of offset lies further from a wall clock than that.
  const candidates = new Set(
    [wall - DAY, wall, wall + DAY].map((probe) => wall - (tehranWallClockAt(probe) - probe)),
  );
  const [only, ...others] = [...candidates].filter(
    (instant) => tehranWallClockAt(instant) === wall,
  );
  return only !== undefined && others.length === 0 ? new Date(only).toISOString() : null;
}
