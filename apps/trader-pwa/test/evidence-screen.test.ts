import { readFileSync, existsSync } from "node:fs";

import { describe, expect, it } from "vitest";

import { traderNavigation } from "../src/navigation";

/**
 * Covers: UI-FILE-006.
 *
 * The question no component test asks: does a screen import this. M3 shipped five
 * mechanisms that were complete, tested and imported nowhere — the security stamp, the
 * step-up store, `loadSession`, `stateForError`, `logout` — and every one had unit tests
 * that called it directly, which is exactly why the suite never noticed.
 *
 * So this asserts the chain ends somewhere a person can reach: both components are
 * imported by a page, the page exists on disk, and the navigation item that leads to it
 * points at a route that is really there.
 */

const SCREEN = new URL("../app/evidence/page.tsx", import.meta.url);

describe("the evidence screen", () => {
  it("imports both file components", () => {
    // Not a substring search for the names anywhere: an import is what makes the
    // component part of the bundle, and a mention in a comment is not.
    const source = readFileSync(SCREEN, "utf8");
    const imports = source
      .split("\n")
      .filter((line) => line.startsWith("import"))
      .join("\n");

    expect(imports).toContain("FileUploadPanel");
    expect(imports).toContain("SecureFileViewer");
    expect(imports).toContain("@gold/ui");
  });

  it("uses them rather than only importing them", () => {
    // Slice 2 learned this from the other side: an unused import satisfied a caller gate
    // for machinery nothing invoked. The JSX is the use.
    const source = readFileSync(SCREEN, "utf8");
    expect(source).toContain("<FileUploadPanel");
    expect(source).toContain("<SecureFileViewer");
  });

  it("is reachable from the navigation, and the route exists", () => {
    // The trader app shipped three navigation items pointing at routes with no page, all
    // answering 404. `navigation.test.ts` guards that generally; this pins the specific
    // item this slice added, because a screen nobody can reach is a screen with no caller
    // by another name.
    const item = traderNavigation.find((entry) => entry.href === "/evidence");
    expect(item).toBeDefined();

    const page = new URL("../app/evidence/page.tsx", import.meta.url);
    expect(existsSync(page)).toBe(true);
  });

  it("the file components touch no browser storage or cache", () => {
    // UI-FILE-004. Document 12 forbids sensitive files in browser storage or a cache, and
    // a service worker is exactly the thing that would otherwise decide to keep a
    // downloaded receipt.
    //
    // Asserted from here rather than from `@gold/ui`, whose tsconfig has no Node types —
    // a source scan needs to read files, and adding `@types/node` to that package to
    // assert an absence would be a dependency bought for a grep. The claim is about the
    // components either way.
    //
    // Matched on **use**, not mention: the first version searched for the bare names and
    // failed on the viewer's own docstring, which names them to say they are forbidden.
    // That is the same shape as `test_reserved_scan_status.py` refusing a value its own
    // explanation spells out.
    const components = [
      new URL("../../../packages/ui/src/secure-file-viewer.tsx", import.meta.url),
      new URL("../../../packages/ui/src/file-upload-panel.tsx", import.meta.url),
    ];

    for (const component of components) {
      const text = readFileSync(component, "utf8");
      for (const forbidden of [
        "localStorage.",
        "sessionStorage.",
        "indexedDB.",
        "caches.open",
        "window.localStorage",
      ]) {
        expect(text.includes(forbidden), `${component.pathname} uses ${forbidden}`).toBe(false);
      }
    }
  });

  it("fixes the upload purpose rather than letting the screen choose", () => {
    // A screen that could name any purpose could name one the trader has no business
    // using — `bank_statement`, say, which is internal-only. Fixing it in the module the
    // screen calls makes that unavailable rather than merely unlikely.
    const evidence = readFileSync(new URL("../src/evidence.ts", import.meta.url), "utf8");
    expect(evidence).toContain('append("purpose", "incoming_payment_receipt")');

    const screen = readFileSync(SCREEN, "utf8");
    expect(screen).not.toContain("purpose");
  });
});
