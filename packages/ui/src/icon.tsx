/**
 * The interface's icons, as inline SVG.
 *
 * **Inline rather than an icon font or a package.** Three reasons, and the first is not
 * negotiable: the applications' security headers forbid loading anything from another
 * origin, and this platform deploys where the icon CDNs are unreachable anyway. The second
 * is that an icon font renders as a missing-glyph box when it fails, which on a
 * right-to-left financial screen is indistinguishable from a rendering bug. The third is
 * size — the whole set below is smaller than the smallest icon package's entry point.
 *
 * **Every icon is `aria-hidden`.** None of them carries meaning on its own; each sits
 * beside a Persian label that says what it is. An icon with an accessible name would be
 * read aloud twice, and an icon *without* a visible label is a rebus — the screen would be
 * asking somebody to guess.
 *
 * `currentColor` throughout, so an icon takes the colour of the text it sits with and a
 * disabled or hovered state needs no second rule.
 */

import type { SVGProps } from "react";

export type IconName =
  | "home"
  | "account"
  | "traders"
  | "staff"
  | "roles"
  | "dashboard"
  | "check"
  | "cross"
  | "pause"
  | "play"
  | "key"
  | "plus"
  | "refresh"
  | "logout"
  | "upload"
  | "requests"
  | "beneficiaries";

/** The runtime list, so a test can iterate what exists rather than restate it. */
export const ICON_NAMES = [
  "home",
  "account",
  "traders",
  "staff",
  "roles",
  "dashboard",
  "check",
  "cross",
  "pause",
  "play",
  "key",
  "plus",
  "refresh",
  "logout",
  "upload",
  "requests",
  "beneficiaries",
] as const satisfies readonly IconName[];

// Stroked rather than filled, at a uniform 1.75 width: a mixed set reads as icons borrowed
// from three places, which is how an interface starts looking assembled rather than made.
const PATHS: Readonly<Record<IconName, string>> = {
  home: "M3 10.5 12 3l9 7.5M5.5 9.5V20h13V9.5M9.5 20v-6h5v6",
  account: "M12 12a4 4 0 1 0 0-8 4 4 0 0 0 0 8ZM4.5 20a7.5 7.5 0 0 1 15 0",
  traders: "M3 21h18M5 21V8l7-4 7 4v13M9.5 21v-5h5v5M9 11.5h.01M15 11.5h.01",
  staff: "M9 12a3.5 3.5 0 1 0 0-7 3.5 3.5 0 0 0 0 7ZM2.5 20a6.5 6.5 0 0 1 13 0M17 8.5a3 3 0 1 1 0 6M18 20a6 6 0 0 0-1.5-4",
  roles: "M12 3l7.5 3.5v5c0 4.5-3 8-7.5 9.5-4.5-1.5-7.5-5-7.5-9.5v-5L12 3ZM9 12l2 2 4-4",
  dashboard: "M4 4h7v7H4V4ZM13 4h7v4h-7V4ZM13 10h7v10h-7V10ZM4 13h7v7H4v-7Z",
  check: "M4.5 12.5 9 17l10.5-10.5",
  cross: "M6 6l12 12M18 6 6 18",
  pause: "M9.5 5v14M14.5 5v14",
  play: "M7 4.5v15l13-7.5-13-7.5Z",
  key: "M14 10a4 4 0 1 1-8 0 4 4 0 0 1 8 0ZM14 10h7M18.5 10v3.5M21 10v2.5",
  plus: "M12 5v14M5 12h14",
  refresh: "M20 12a8 8 0 1 1-2.5-5.8M20 4v4h-4",
  logout: "M15 4h4a1 1 0 0 1 1 1v14a1 1 0 0 1-1 1h-4M11 16l4-4-4-4M15 12H4",
  // An arrow into a tray: the file goes to the platform, not from it. Distinct from
  // , which adds a record somebody typed rather than bytes they had.
  upload: "M12 16V4M8 8l4-4 4 4M4 16v3a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1v-3",
  // M5 slice 8. A sheet with lines and a currency mark: a payment request is a document
  // somebody wrote, which is what distinguishes it from `upload`'s bytes and `dashboard`'s
  // tiles.
  requests: "M6.5 3h11a1 1 0 0 1 1 1v16a1 1 0 0 1-1 1h-11a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1ZM9 8h6M9 12h6M9 16h3",
  // A person beside a bank column: the destination of a payment is somebody with an account,
  // and `account` already means "your own profile" in this set.
  beneficiaries: "M9 11a3 3 0 1 0 0-6 3 3 0 0 0 0 6ZM3.5 20a5.5 5.5 0 0 1 11 0M16 20V9.5M20 20V9.5M15 9.5h6L18 7l-3 2.5Z",
};

export type IconProps = Omit<SVGProps<SVGSVGElement>, "children"> &
  Readonly<{ name: IconName; size?: number }>;

export function Icon({ name, size = 20, ...rest }: IconProps) {
  return (
    <svg
      aria-hidden="true"
      fill="none"
      focusable="false"
      height={size}
      stroke="currentColor"
      strokeLinecap="round"
      strokeLinejoin="round"
      strokeWidth={1.75}
      viewBox="0 0 24 24"
      width={size}
      {...rest}
    >
      <path d={PATHS[name]} />
    </svg>
  );
}
