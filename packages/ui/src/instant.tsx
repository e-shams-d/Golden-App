import type { HTMLAttributes } from "react";

import { BidiText } from "./bidi-text";

const BUSINESS_TIME_ZONE = "Asia/Tehran";
// What document 21 §4.5 writes before the exact value.
const EXACT_LABEL = "زمان دقیق سامانه";
// An ISO string names one moment only when it says which offset it is in.
const ZONED = /(?:[zZ]|[+-]\d{2}:?\d{2})$/;

let persianFormat: Intl.DateTimeFormat | undefined;

/**
 * An instant as a person in Tehran reads it: the Jalali date and the time on the clock, in
 * Persian digits — `۱۴۰۵/۰۲/۰۶، ساعت ۱۳:۴۵`, which is document 21 §4.5's own example. `null` for
 * anything that does not name one instant, including an ISO string without a zone, which a
 * browser would quietly read in its own.
 *
 * Assembled from the parts ICU returns rather than from its whole string, so the separator is
 * the one the document writes rather than ICU's comma. The calendar is ICU's — the same tables
 * the backend's Jalali conversion is held to (`tests/fixtures/jalali_new_years_icu.txt`) — so a
 * date the platform reads from a bank file and a date a screen shows come from one calendar.
 */
export function formatInstant(value: string): string | null {
  if (!ZONED.test(value)) return null;
  const instant = new Date(value);
  if (Number.isNaN(instant.getTime())) return null;
  persianFormat ??= new Intl.DateTimeFormat("fa-IR-u-ca-persian-nu-arabext", {
    timeZone: BUSINESS_TIME_ZONE,
    hourCycle: "h23",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
  const parts = persianFormat.formatToParts(instant);
  const part = (type: Intl.DateTimeFormatPartTypes): string =>
    parts.find((entry) => entry.type === type)?.value ?? "";
  return `${part("year")}/${part("month")}/${part("day")}، ساعت ${part("hour")}:${part("minute")}`;
}

export type InstantProps = Readonly<{
  value: string;
  className?: string;
}> &
  Omit<HTMLAttributes<HTMLElement>, "children" | "title">;

/**
 * A timestamp from the API, shown as document 21 §4.5 asks: readable first, exact on demand.
 *
 * The exact server value stays on the element — `dateTime` for machines, the title for a person
 * checking an audit detail — because §4.5 requires it preserved. F-40: every screen printed the
 * raw UTC string, so a goldsmith who received a message at 10:30 read "07:00".
 *
 * A value that names no instant is shown as it came, left to right, rather than guessed at.
 */
export function Instant({ value, className, ...props }: InstantProps) {
  const readable = formatInstant(value);
  if (readable === null) {
    // `BidiText` takes `className?: string`, which under `exactOptionalPropertyTypes` is not the
    // same as accepting `undefined`; pass it only when there is one.
    return (
      <BidiText {...props} {...(className === undefined ? {} : { className })}>
        {value}
      </BidiText>
    );
  }
  return (
    <time {...props} className={className} dateTime={value} title={`${EXACT_LABEL}: ${value}`}>
      {readable}
    </time>
  );
}
