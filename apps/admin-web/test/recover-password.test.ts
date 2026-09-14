/**
 * The recovery screen, and the one thing it must not try to be helpful about.
 *
 * M0 slice F — the last operation in this application with no screen.
 *
 * **The route answers one 401 for three different causes on purpose.** An unknown username, a wrong
 * temporary password and an account that is not awaiting recovery are indistinguishable to the
 * caller, because distinguishing them would make this a status oracle for the centre's own staff at
 * the moment those accounts are most exposed — their credential is one somebody typed and
 * communicated. `12_Security_RBAC_Audit.md:403`, and the route's own docstring.
 *
 * A screen is where that guarantee is most likely to be undone, and undone with good intentions: a
 * message saying "wrong password" is friendlier and is a claim the server refused to make. Most of
 * this file is about that.
 *
 * Covers: UI-RECOVER-001.
 */

import { readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

const APP_ROOT = join(import.meta.dirname, "..");
const SCREEN = join(APP_ROOT, "app", "recover-password", "page.tsx");
const LOGIN = join(APP_ROOT, "app", "login", "page.tsx");
const MODULE = join(APP_ROOT, "src", "password.ts");
const MESSAGES = join(APP_ROOT, "..", "..", "packages", "localization", "src", "messages.ts");
const SWEEP = join(APP_ROOT, "tests", "a11y", "shell.spec.ts");

const read = (path: string): string => readFileSync(path, "utf8");

/** Comments stripped, for assertions about what the code does *not* do. */
const code = (path: string): string =>
  read(path)
    .replace(/\/\*[\s\S]*?\*\//g, "")
    .replace(/^\s*\/\/.*$/gm, "");

describe("the screen does not invent a diagnosis the server refused to give", () => {
  it("reports one refusal rather than branching on a guess", () => {
    const source = code(SCREEN);

    // 429 is named because it is actionable — waiting works. 401 is not diagnosable and must not be
    // presented as though it were.
    expect(source).toContain("recover.refused");
    expect(source).toContain("status === 429");
    expect(source).not.toContain("status === 401");
    expect(source).not.toContain("status === 404");
    expect(source).not.toContain("status === 403");
  });

  it("names no single cause in the refusal message", () => {
    const messages = read(MESSAGES);
    const start = messages.indexOf('"recover.refused"');
    expect(start).toBeGreaterThan(-1);
    const line = messages.slice(start, start + 500);

    // The message lists the three things to check. A message that picked one would be the oracle
    // the route spent a docstring refusing to be — and would be wrong two times in three.
    expect(line).toContain("نام کاربری");
    expect(line).toContain("گذرواژه موقت");
    expect(line).toContain("بازنشانی");
  });
});

describe("the screen matches the flow the route actually has", () => {
  it("sends three fields and no token", () => {
    const source = code(MODULE);
    const fn = source.slice(source.indexOf("export async function recoverAdminPassword"));

    // There is no token in this flow. The temporary password is what an administrator hands over,
    // and a field for a token would be a form with nothing to type into it — which is what the
    // `NO_SCREEN` entry wrongly claimed the whole screen would be.
    expect(fn).toContain("username");
    expect(fn).toContain("current_password");
    expect(fn).toContain("new_password");
    expect(fn).not.toContain("token");
  });

  it("does not pretend the person is signed in afterwards", () => {
    const source = code(SCREEN);

    // The response carries no session by design. A screen that redirected to the dashboard would
    // land on a 401 and read as the recovery having failed.
    expect(source).not.toContain("router.replace");
    expect(source).toContain("recover.goToLogin");
    expect(source).toContain("recover.doneDescription");
  });

  it("says in words that no sign-in happened", () => {
    const messages = read(MESSAGES);
    const start = messages.indexOf('"recover.doneDescription"');
    const line = messages.slice(start, start + 300);

    // "هنوز وارد نشده‌اید" — the denial is the content. A string that only said "done" would leave
    // the next sign-in reading as a second failure.
    expect(line).toContain("هنوز وارد نشده‌اید");
  });

  it("checks the repeated password, because the server has nothing to compare against", () => {
    const source = code(SCREEN);

    // The one piece of validation this screen owns, and it matters more here than on `/password`:
    // a typo leaves somebody holding a password they cannot reproduce and **no working credential
    // to try again with**.
    expect(source).toContain("next !== again");
    expect(source).toContain("recover.mismatch");
  });
});

describe("the screen is reachable by the person who needs it", () => {
  it("is linked from the login page", () => {
    // `recovery_required` refuses authentication, so somebody in that state arrives at the login
    // screen and can go nowhere else. A page nothing links to is reached only by typing a URL.
    expect(code(LOGIN)).toContain('href="/recover-password"');
  });

  it("keeps the link out of the shared login component", () => {
    const login = read(LOGIN);

    // `LoginForm` is rendered by the trader app too. A link inside it would put an admin path in
    // the trader bundle — `UI-ISO-001` — and offer a trader a flow that does not exist for them.
    expect(login).toContain("recover.fromLogin");
    const uiPackage = join(APP_ROOT, "..", "..", "packages", "ui", "src");
    const loginForm = readFileSync(join(uiPackage, "login-form.tsx"), "utf8");
    expect(loginForm).not.toContain("recover-password");
  });

  it("renders outside the admin shell", () => {
    const source = code(SCREEN);

    // The shell assumes a session: navigation gated on permissions, a session panel, a sign-out
    // button. Rendering it here would ask an unauthenticated page to describe a person it has no
    // way to know.
    expect(source).not.toContain("AdminShell");
  });

  it("is in the accessibility sweep", () => {
    // The only page in the sweep that renders its *working* state rather than a failure state, and
    // the only form in this application an unauthenticated person fills in.
    expect(read(SWEEP)).toContain('"/recover-password"');
  });
});

describe("the fields tell a password manager the truth", () => {
  it("labels the temporary password as the current one", () => {
    const source = code(SCREEN);

    // To a password manager this *is* the credential being replaced. `new-password` here would
    // offer to save the temporary one — the credential somebody else chose and communicated.
    expect(source).toContain('autoComplete="current-password"');
    expect(source.match(/autoComplete="new-password"/g)).toHaveLength(2);
  });

  it("hides every credential field", () => {
    const source = code(SCREEN);

    // Three password inputs, three `type="password"`. The username is deliberately not one.
    expect(source.match(/type="password"/g)).toHaveLength(3);
  });
});
