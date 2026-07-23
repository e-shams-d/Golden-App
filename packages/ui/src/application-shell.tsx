import type { ReactNode } from "react";

export type NavigationItem = Readonly<{
  href: string;
  label: string;
}>;

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
                    className="block rounded-lg px-3 py-3 font-bold hover:bg-[var(--gold-50)] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--focus)]"
                    href={item.href}
                  >
                    {item.label}
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
          <ul className="mx-auto grid max-w-3xl grid-cols-5 gap-1">
            {navigation.map((item) => (
              <li key={item.href}>
                <a
                  className="flex min-h-12 items-center justify-center rounded-lg px-1 text-center text-xs font-bold hover:bg-[var(--gold-50)] focus-visible:outline-2 focus-visible:outline-[var(--focus)]"
                  href={item.href}
                >
                  {item.label}
                </a>
              </li>
            ))}
          </ul>
        </nav>
      ) : null}
    </div>
  );
}
