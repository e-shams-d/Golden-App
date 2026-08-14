import { t, type MessageKey } from "@gold/localization";
import { STATE_KINDS, StateView, type StateKind } from "@gold/ui";
import Link from "next/link";
import { notFound } from "next/navigation";

// From the package rather than restated here. The literal list was written when there were
// five kinds; slice 10C added three, and a hand-kept copy is how a kind ships with no page
// to look at it on — which is also how the accessibility sweep stops covering it.
const stateKinds = STATE_KINDS;

export function generateStaticParams() {
  return stateKinds.map((kind) => ({ kind }));
}

export default async function FoundationStatePage({
  params,
}: Readonly<{ params: Promise<{ kind: string }> }>) {
  const { kind } = await params;
  if (!isStateKind(kind)) notFound();

  return (
    <div className="p-[var(--space-page)]">
      <StateView
        actions={
          <Link className="rounded-lg border border-current px-4 py-3 font-bold" href="/">
            {kind === "conflict" ? t("common.refresh") : t("common.backToHome")}
          </Link>
        }
        description={t(`state.${kind}.description` as MessageKey)}
        kind={kind}
        requestId={kind === "error" ? t("foundation.requestIdExample") : undefined}
        title={t(`state.${kind}.title` as MessageKey)}
      />
    </div>
  );
}

function isStateKind(value: string): value is StateKind {
  return (stateKinds as readonly string[]).includes(value);
}
