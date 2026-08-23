/**
 * The admin app's own authentication wiring.
 *
 * Deliberately per-app rather than shared. `UI-ISO-001` requires that neither
 * bundle contain the other's endpoint path, and the cheapest way to guarantee that
 * is for neither bundle ever to name one. A shared module holding both routes
 * would put the other audience's login path into this bundle's JavaScript, where a mistake in
 * a `if (audience === ...)` branch could reach it.
 *
 * The route is the audience — DOC-CONFLICT-023's decision — so there is no
 * `user_type` field to send and nothing here selects a domain.
 *
 * Credentials are never stored. The session arrives as a `__Host-` prefixed
 * HTTP-only cookie the browser holds and this code cannot read; the CSRF token
 * arrives as a readable companion cookie and is echoed in a header, which is the
 * part a cross-site form cannot set.
 */

import { createApiTransport } from "@gold/api-client";
import type { AuthAdapter, SessionSnapshot } from "@gold/auth-client";

const CSRF_COOKIE = "__Host-gp_admin_csrf";

/** Read from `document.cookie`, which is why this one is not HttpOnly. */
export function readCsrfToken(source: string = globalThis.document?.cookie ?? ""): string | undefined {
  for (const part of source.split(";")) {
    const [name, ...rest] = part.trim().split("=");
    if (name === CSRF_COOKIE) return rest.join("=") || undefined;
  }
  return undefined;
}

const transport = createApiTransport({ getCsrfToken: () => readCsrfToken() });

export type LoginInput = Readonly<{ identifier: string; password: string }>;

/**
 * The one failure message, for every reason.
 *
 * The backend answers a single `UNAUTHENTICATED` for an unknown number, a wrong
 * password, a suspended account and a locked one. Rendering anything more
 * specific here would undo that on the client — and the client has no more
 * information anyway, so any extra detail would be invented.
 */
export const GENERIC_LOGIN_FAILURE = "invalid_credentials";

export async function login(input: LoginInput, signal?: AbortSignal): Promise<void> {
  try {
    await transport.request({
      method: "POST",
      path: "/auth/admin/login",
      body: { identifier: input.identifier, password: input.password },
      // Spread rather than `signal,`: `exactOptionalPropertyTypes` treats an
      // explicit `undefined` as a different thing from an absent key, and the
      // transport's type says absent.
      ...(signal ? { signal } : {}),
    });
  } catch (error) {
    // The cause is kept for a developer console and never rendered. The screen
    // shows one message for every reason, matching the single `UNAUTHENTICATED`
    // the backend answers with — `normalizeApiError` is for parsing a response
    // body, not for a caught throwable, so the original is attached as-is.
    throw new Error(GENERIC_LOGIN_FAILURE, { cause: error });
  }
}

export const adminAuthAdapter: AuthAdapter = {
  async loadSession(signal) {
    try {
      const response = await transport.request({
        method: "GET",
        path: "/auth/me",
        ...(signal ? { signal } : {}),
      });
      // The transport answers an envelope; the payload is `data`. Narrowed
      // through `unknown` because the generated types describe the contract and
      // this adapter reads two fields of it — asserting the whole shape would
      // duplicate the generated type and drift from it.
      const body = response.data as {
        session: { expires_at: string };
        user: { id: string; audience: string; permissions: readonly string[] };
      };

      return {
        state: "authenticated",
        expiresAt: body.session.expires_at,
        identity: {
          subjectId: body.user.id,
          displayName: body.user.id,
          domain: "internal",
          // Consumed for navigation only. The backend is authoritative
          // (`12_Security_RBAC_Audit.md:625-626`), so a hidden item is not a
          // control and a shown one is not a grant — `UI-NAV-001` proves a hidden
          // action still fails server-side when called directly.
          permissions: body.user.permissions,
        },
      } satisfies SessionSnapshot;
    } catch {
      return { state: "unauthenticated" };
    }
  },

  async logout(signal) {
    await transport.request({
      method: "POST",
      path: "/auth/logout",
      ...(signal ? { signal } : {}),
    });
  },

  async reauthenticate({ actionClass, challengeResponse, resourceType, resourceId, signal }) {
    // The endpoint M3 slice 7 built, reached for the first time by M7's screens slice 2.
    //
    // This threw for four milestones and the message said exactly why:
    // `resource_type`/`resource_id` are required by the approved baseline, no admin screen
    // performed a critical action, and sending a placeholder would have bound a context to
    // nothing. The approval screen is the caller that comment was waiting for — it knows which
    // version the manager is deciding.
    //
    // `purpose` is the command id, which is what the approve and reject dialogs pass as their
    // action class. The two are deliberately different purposes: a step-up obtained to refuse a
    // batch must not be spendable on authorising it.
    const response = await transport.request<{
      recent_auth_reference: string;
      expires_at: string;
    }>({
      method: "POST",
      path: "/auth/reauthenticate",
      body: {
        password: challengeResponse,
        purpose: actionClass,
        resource_type: resourceType,
        resource_id: resourceId,
      },
      ...(signal ? { signal } : {}),
    });

    return {
      reference: response.data.recent_auth_reference,
      actionClass,
      expiresAt: response.data.expires_at,
      resourceType,
      resourceId,
    };
  },
};
