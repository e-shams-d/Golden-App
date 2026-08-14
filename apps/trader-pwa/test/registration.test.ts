import { readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

import { foldDigits, normalisePhone } from "../src/registration";

/**
 * The registration screen's client-side rules, and what it is allowed to say afterwards.
 *
 * Two different kinds of check live here, deliberately in one file because they are two
 * halves of the same claim.
 *
 * The **phone rules** are the mirror of `services/backend/app/security/identifiers.py`,
 * and the cases below are lifted from that module's own docstring rather than invented —
 * so if the server's rule moves, these are what should fail. The client copy is not a
 * control; it exists because the server answers an acceptance to an invalid number on
 * purpose, and somebody who mistypes their number would otherwise be told they are in a
 * queue they are not in.
 *
 * The **wording check** is the one that matters more. `POST /traders/register` answers
 * identically whether an application was created or the number was already registered,
 * because distinguishing them would be a membership oracle for the centre's customer
 * list. The screen is therefore told nothing it could use to tell the two apart, and any
 * message announcing a new account would be asserting something it cannot know. That is a
 * claim about text, so it is checked against the text.
 *
 * Covers: UI-REG-001, UI-REG-002.
 */

const APP_ROOT = join(import.meta.dirname, "..");

function source(...parts: string[]): string {
  return readFileSync(join(APP_ROOT, ...parts), "utf8");
}

describe("the phone number a goldsmith types", () => {
  it("accepts the spellings one person uses for one number", () => {
    // Every one of these is the same human. If they reached `trader_users.phone_number`
    // as different strings, `UNIQUE (phone_number)` would permit an account for each.
    for (const spelling of [
      "09123456789",
      "+989123456789",
      "00989123456789",
      "989123456789",
      "9123456789",
      "0912 345 6789",
      "0912-345-6789",
      "(0912) 345.6789",
    ]) {
      expect(normalisePhone(spelling), spelling).toBe("+989123456789");
    }
  });

  it("accepts Persian and Arabic-Indic digits, which are the ordinary input here", () => {
    // An Iranian keyboard produces these by default. A rule that only understood ASCII
    // would refuse the country's most common spelling and read as the site being broken.
    expect(normalisePhone("۰۹۱۲۳۴۵۶۷۸۹")).toBe("+989123456789");
    expect(normalisePhone("٠٩١٢٣٤٥٦٧٨٩")).toBe("+989123456789");
    // Mixed, which happens when a number is part-typed and part-pasted.
    expect(normalisePhone("۰۹۱۲345۶۷۸۹")).toBe("+989123456789");
  });

  it("survives the invisible marks pasted Persian text carries", () => {
    // Zero-width non-joiner, left-to-right mark and a byte-order mark. A person pasting
    // their number out of a message app brings these along without seeing them, and a
    // number refused for a character nobody can see is unexplainable to them.
    expect(normalisePhone("‌0912\u200E3456789﻿")).toBe("+989123456789");
  });

  it("refuses what is not an Iranian mobile number", () => {
    for (const rejected of [
      "", // nothing typed
      "   ",
      "02112345678", // Tehran landline
      "0812345678", // an operator prefix that is not 90-99
      "091234567", // too short
      "091234567890", // too long
      "0912345678a",
      "+449123456789", // a foreign number
    ]) {
      expect(normalisePhone(rejected), rejected).toBeNull();
    }
  });

  it("strips the longer country prefixes before the shorter ones", () => {
    // `0098…` must be tried before `0`, and `98…` before it too. Taking them in the wrong
    // order leaves a national number that is one prefix too long and refuses a valid
    // spelling — the server's copy carries the same note for the same reason.
    expect(normalisePhone("00989123456789")).toBe("+989123456789");
    expect(normalisePhone("989123456789")).toBe("+989123456789");
  });

  it("folds digits without touching anything else", () => {
    expect(foldDigits("۰۹۱۲")).toBe("0912");
    expect(foldDigits("طلا ۱۴")).toBe("طلا 14");
    expect(foldDigits("abc")).toBe("abc");
  });
});

describe("what the screen is allowed to say", () => {
  const page = source("app", "register", "page.tsx");
  const messages = readFileSync(
    join(APP_ROOT, "..", "..", "packages", "localization", "src", "messages.ts"),
    "utf8",
  );

  function message(key: string): string {
    const found = new RegExp(`"${key}": "([^"]*)"`).exec(messages);
    expect(found, `no message is defined for ${key}`).not.toBeNull();
    return found?.[1] ?? "";
  }

  it("defines the messages this test reads, so the checks below are not vacuous", () => {
    // Guard the guard. Every assertion under this heading searches a string pulled out of
    // `messages.ts` by a regular expression; a key that stopped matching would yield the
    // empty string, and "the empty string does not claim an account exists" is the most
    // comfortable green there is.
    expect(message("trader.register.doneTitle").length).toBeGreaterThan(5);
    expect(message("trader.register.done").length).toBeGreaterThan(20);
  });

  it("never tells a person their account was created", () => {
    // UI-REG-002. The endpoint answers the same thing to a real registration and to a
    // phone number already registered, so this screen genuinely does not know which
    // happened. Words that assert the creation of something would be inventing the half
    // of the answer the server withheld on purpose.
    const shown = message("trader.register.doneTitle") + " " + message("trader.register.done");

    for (const claim of [
      "حساب شما ساخته شد",
      "ثبت‌نام شما کامل شد",
      "حساب کاربری ایجاد شد",
      "عضو شدید",
    ]) {
      expect(shown, `the success message claims: ${claim}`).not.toContain(claim);
    }

    // And the positive half, because "does not contain four phrases" is also satisfied by
    // a message that says nothing: it has to point the reader at where the answer is.
    expect(shown).toContain("وارد شوید");
  });

  it("sends the number as typed, not as this bundle normalised it", () => {
    // The server normalises again on the way in, and it is the server's normalisation
    // that decides which row `UNIQUE (phone_number)` collides with. Sending the folded
    // form would make this copy of the rule part of the identity, so a drift here would
    // open a second account for one person instead of being corrected.
    expect(source("src", "registration.ts")).toContain("primary_phone: input.primaryPhone");
    expect(source("src", "registration.ts")).not.toContain(
      "primary_phone: normalisePhone",
    );
  });

  it("invents no password policy", () => {
    // UI-REG-001. `app/security/passwords.py:25` records that the platform deliberately
    // has no minimum length, no composition rules and no strength meter. A form adding its
    // own would be making that decision in the one place nobody would look for it, and
    // enforcing it only on people who arrive through the form.
    expect(page).not.toMatch(/password\.length\s*[<>]/);
    expect(page).not.toMatch(/minLength/);
  });

  it("names the trader register route and no admin path", () => {
    // UI-ISO-001, the same structural argument the login wiring makes: a path absent from
    // the module graph cannot reach the bundle.
    const wiring = source("src", "registration.ts");
    expect(wiring).toContain("/traders/register");
    expect(wiring).not.toContain("/admin");
    expect(page).not.toContain("/admin");
  });
});
