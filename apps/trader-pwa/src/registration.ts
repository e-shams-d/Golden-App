/**
 * Applying to become a trader — the platform's only unauthenticated write.
 *
 * Per-app, like `src/auth.ts` and `src/profile.ts`, and for the same reason: `UI-ISO-001`
 * requires this bundle to contain no admin endpoint path, and the cheapest guarantee is
 * that it never names one.
 *
 * **Why there is a phone check on the client at all.** The endpoint answers
 * `{accepted: true, pending_approval: true}` to three different situations — a real
 * registration, a phone number already registered, and a number that is not an Iranian
 * mobile at all (`app/api/v1/traders.py:253-256`). The first two are identical on purpose:
 * distinguishing them would turn a public endpoint into a membership oracle for the
 * centre's customer list. The third is swallowed for the same reason, and that is the one
 * with a cost — somebody who mistypes their number is told they are in the queue and waits
 * for a decision on an application that does not exist.
 *
 * Nothing on the server can fix that without answering a question it has decided not to
 * answer. The client can, because the shape of a phone number is not a secret: whether
 * `0912…` is a well-formed Iranian mobile is computable offline by anyone, so checking it
 * here reveals nothing that was being withheld. Membership stays the server's to refuse.
 *
 * **This is not a control.** The server normalises and decides; if these two rules ever
 * disagree the server wins. What this buys is a person being told about their own typo.
 *
 * **On the duplication.** This rule exists twice, in two languages, which is a drift
 * hazard and is named as one rather than hidden. The direction of drift is not symmetric:
 * a client *stricter* than the server refuses a number that would have worked, which is a
 * user locked out by our copy of the rule; a client *looser* merely returns to today's
 * behaviour, where the server swallows it. So when in doubt this file accepts. The
 * cases in `test/registration.test.ts` are lifted from the server's own docstring for
 * exactly this reason — if the server's rule moves, they are what should fail.
 */

import { createApiTransport } from "@gold/api-client";

import { readCsrfToken } from "./auth";

const transport = createApiTransport({ getCsrfToken: () => readCsrfToken() });

/** Persian and Arabic-Indic digits onto ASCII, before anything else looks at the string.
 *
 * An Iranian keyboard produces `۰۹۱۲…` by default, so a goldsmith typing their own number
 * into a Persian interface is the ordinary path and not an edge case. A check that only
 * understood ASCII would reject the country's most common input and read, from outside,
 * as "the site says my number is wrong".
 */
export function foldDigits(value: string): string {
  return value.replace(/[۰-۹]/g, (digit) =>
    String.fromCharCode(digit.charCodeAt(0) - 0x06f0 + 0x30),
  ).replace(/[٠-٩]/g, (digit) =>
    String.fromCharCode(digit.charCodeAt(0) - 0x0660 + 0x30),
  );
}

// Everything a human might put between digits, plus the marks pasted Persian text carries
// invisibly. Written as escapes rather than literals for the reason the server's copy
// gives: most of these render as nothing, and a literal here would be an unreviewable
// blank that a later edit could delete without anyone noticing.
const SEPARATORS = /[\s\-().]|[‌-\u200F]|[\u202A-\u202E]|﻿/g;

// `9` then nine digits, on operator prefixes 90-99. Written locally with a leading `0`,
// internationally as +98.
const MOBILE_NATIONAL = /^9\d{9}$/;

/**
 * The E.164 form, or `null` when this is not an Iranian mobile number.
 *
 * The server's equivalent raises rather than returning an optional, because in Python an
 * `Optional` gets `or ""`-ed into a lookup that then matches nothing. TypeScript's
 * `strictNullChecks` makes the caller handle the `null` at the type level, so the return
 * shape that is dangerous there is checked here.
 */
export function normalisePhone(value: string): string | null {
  let folded = foldDigits(value).replace(SEPARATORS, "").trim();
  if (!folded) return null;

  // Order matters: `0098` must be tried before `0`, and `98` before it too.
  for (const prefix of ["+98", "0098", "98", "0"]) {
    if (folded.startsWith(prefix)) {
      folded = folded.slice(prefix.length);
      break;
    }
  }

  return MOBILE_NATIONAL.test(folded) ? `+98${folded}` : null;
}

export type RegistrationInput = Readonly<{
  displayName: string;
  contactFullName: string;
  primaryPhone: string;
  password: string;
  legalName?: string | undefined;
}>;

/**
 * Send the application.
 *
 * The phone number is sent **as the person typed it**, not as `normalisePhone` returned
 * it. The server normalises again on the way in, and it is the server's normalisation
 * that decides which row `UNIQUE (phone_number)` collides with — sending our
 * already-folded form would make this bundle's copy of the rule part of the identity, so
 * a drift here would create a second account for one person rather than being corrected.
 */
export async function registerTrader(
  input: RegistrationInput,
  signal?: AbortSignal,
): Promise<void> {
  await transport.request({
    method: "POST",
    path: "/traders/register",
    body: {
      display_name: input.displayName,
      primary_phone: input.primaryPhone,
      contact_full_name: input.contactFullName,
      password: input.password,
      ...(input.legalName ? { legal_name: input.legalName } : {}),
    },
    ...(signal ? { signal } : {}),
  });
}
