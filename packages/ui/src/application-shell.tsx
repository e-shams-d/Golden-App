import type { ReactNode } from "react";

import { Icon, type IconName } from "./icon";

export type NavigationItem = Readonly<{
  href: string;
  label: string;
  /**
   * The permission that must be held for this item to appear.
   *
   * **Not a control.** `12_Security_RBAC_Audit.md:625-626` makes the server authoritative,
   * so a hidden item is not a denial and a shown one is not a grant — the route refuses
   * the call either way, and `UI-NAV-001`'s second half is what proves it. What this buys
   * is a person not being shown four screens that will turn them away.
   *
   * Optional because an item everybody reaches needs no permission, and making it required
   * would force one to be invented for the dashboard.
   */
  permission?: string;
  /**
   * The icon beside the label, never instead of it.
   *
   * Optional so an item can ship before somebody has chosen one, and never a substitute for
   * the text: `Icon` renders `aria-hidden`, so an item with only an icon would have no
   * accessible name at all — and on a bottom navigation bar, a rebus.
   */
  icon?: IconName;
}>;

/**
 * The items a holder of these permissions should see.
 *
 * Lives here rather than in each app because both apps need it and the rule is identical;
 * *which* permission gates *which* item is per-app and stays in each app's navigation
 * module, where the reasoning about that deployment's roles belongs.
 */
export function visibleNavigation(
  navigation: readonly NavigationItem[],
  permissions: readonly string[],
): readonly NavigationItem[] {
  const held = new Set(permissions);
  return navigation.filter((item) => item.permission === undefined || held.has(item.permission));
}

export type ApplicationShellProps = Readonly<{
  appName: string;
  navigationLabel: string;
  navigation: readonly NavigationItem[];
  variant: "trader" | "admin";
  children: ReactNode;
  headerContext?: ReactNode;
  skipToContentLabel: string;
}>;

export function ApplicationShell({
  appName,
  navigationLabel,
  navigation,
  variant,
  children,
  headerContext,
  skipToContentLabel,
}: ApplicationShellProps) {
  const isTrader = variant === "trader";

  return (
    <div className="min-h-dvh bg-[var(--surface-subtle)] text-[var(--ink-950)]">
      <a
        className="fixed start-4 top-3 z-50 -translate-y-24 rounded-lg bg-[var(--ink-950)] px-4 py-2 text-white focus:translate-y-0"
        href="#main-content"
      >
        {skipToContentLabel}
      </a>
      <header className="border-b border-[var(--border)] bg-[var(--surface)] px-[var(--space-page)] py-4">
        <div className="mx-auto flex max-w-screen-2xl items-center justify-between gap-4">
          <p className="text-lg font-black">{appName}</p>
          {headerContext ? <div className="text-sm text-[var(--ink-600)]">{headerContext}</div> : null}
        </div>
      </header>
      <div
        className={
          isTrader
            ? "mx-auto max-w-3xl pb-24"
            : "mx-auto grid max-w-screen-2xl gap-0 lg:grid-cols-[17rem_1fr]"
        }
      >
        {!isTrader ? (
          <nav
            aria-label={navigationLabel}
            className="border-b border-[var(--border)] bg-[var(--surface)] p-4 lg:min-h-[calc(100dvh-4.5rem)] lg:border-b-0 lg:border-l"
          >
            <ul className="grid grid-cols-2 gap-2 sm:grid-cols-4 lg:grid-cols-1">
              {navigation.map((item) => (
                <li key={item.href}>
                  <a
                    className="flex items-center gap-3 rounded-lg px-3 py-3 font-bold hover:bg-[var(--gold-50)] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--focus)]"
                    href={item.href}
                  >
                    {item.icon ? <Icon name={item.icon} /> : null}
                    <span>{item.label}</span>
                  </a>
                </li>
              ))}
            </ul>
          </nav>
        ) : null}
        <main className="p-[var(--space-page)]" id="main-content" tabIndex={-1}>
          {children}
        </main>
      </div>
      {isTrader ? (
        <nav
          aria-label={navigationLabel}
          className="fixed inset-x-0 bottom-0 z-40 border-t border-[var(--border)] bg-[var(--surface)] px-2 py-2"
        >
          <ul className="mx-auto flex max-w-3xl items-stretch justify-around gap-1">
            {navigation.map((item) => (
              <li key={item.href}>
                <a
                  className="flex min-h-14 flex-col items-center justify-center gap-1 rounded-lg px-1 text-center text-xs font-bold hover:bg-[var(--gold-50)] focus-visible:outline-2 focus-visible:outline-[var(--focus)]"
                  href={item.href}
                >
                  {item.icon ? <Icon name={item.icon} size={22} /> : null}
                  <span>{item.label}</span>
                </a>
              </li>
            ))}
          </ul>
        </nav>
      ) : null}
    </div>
  );
}
