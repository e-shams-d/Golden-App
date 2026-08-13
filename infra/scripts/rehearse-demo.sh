#!/usr/bin/env sh
# Stand up a fresh deployment, seed the two identities, and walk the onboarding path in a
# real browser. One command, so that "does the demonstration still work" is a question
# with an answer rather than an afternoon.
#
# This is NOT part of any verification gate. `verify-native.sh` and `verify-docker.sh`
# decide whether the repository is sound; this decides whether a person can be shown the
# platform, which is a different question and needs a stack the gates do not assume.
#
# Three host-level facts are handled here because each cost a diagnosis the first time:
#
#   1. Every `docker compose` call must see the same `LOCAL_DATA_ROOT`. Without it compose
#      resolves a different bind mount, decides the service configuration changed, and
#      recreates the backend mid-run — which surfaces as a 502 from nginx with the
#      backend's own log showing it shutting down while a request was in flight.
#
#   2. `curl` must bypass any proxy for loopback. A VPN client exporting
#      `http_proxy=127.0.0.1:10808` will answer 503 itself, and the request never reaches
#      nginx — the access log stays silent, which makes it look like the stack is broken.
#
#   3. The browser, not curl, drives the signed-in steps. The session cookie carries the
#      `__Host-` prefix and curl refuses to store a prefixed cookie received over plain
#      HTTP; Chromium stores it because it treats `localhost` as a trustworthy origin.
set -eu

REPOSITORY_ROOT=$(CDPATH='' cd -- "$(dirname -- "$0")/../.." && pwd)
cd "$REPOSITORY_ROOT"

if [ ! -f .env ]; then
    printf '%s\n' "Create a private .env from .env.example first." >&2
    exit 1
fi

LOCAL_DATA_ROOT=${LOCAL_DATA_ROOT:-../../.local/demo}
HTTP_PORT=${HTTP_PORT:-8080}
PROJECT=${COMPOSE_PROJECT_NAME:-golden-demo}
export LOCAL_DATA_ROOT HTTP_PORT

compose() {
    docker compose --project-name "$PROJECT" --env-file .env \
        -f infra/compose/compose.local.yml "$@"
}

BUSINESS_NAME='طلافروشی نمونه'
PHONE="0912$(od -An -N4 -tu4 /dev/urandom | tr -d ' \n' | cut -c1-7)"
TRADER_PASSWORD="Rehearsal-trader-$(date +%s)"
ADMIN_USER="rehearsal_admin"
ADMIN_PASSWORD="Rehearsal-admin-$(date +%s)"

printf '\n== a fresh deployment ==\n'
# From empty on purpose. The bootstrap command refuses once any staff account exists —
# correctly — so a rehearsal that reused a database could never exercise the step an
# operator actually performs on installation day.
compose down --remove-orphans >/dev/null 2>&1 || true
docker run --rm -v "${REPOSITORY_ROOT}/.local/demo:/target" alpine:3.21 \
    sh -c 'rm -rf /target/postgres /target/storage' >/dev/null 2>&1 || true
compose up -d >/dev/null
printf '  waiting for the stack to report healthy'
attempts=0
while [ "$attempts" -lt 60 ]; do
    healthy=$(compose ps --format '{{.Status}}' | grep -c healthy || true)
    [ "$healthy" -ge 6 ] && break
    printf '.'
    attempts=$((attempts + 1))
    sleep 2
done
printf '\n  %s services healthy\n' "$healthy"
[ "$healthy" -ge 6 ] || { printf '%s\n' "the stack did not become healthy" >&2; exit 1; }

printf '\n== a goldsmith applies ==\n'
# Through the API: there is no registration screen yet, and pretending otherwise in a
# rehearsal would hide the one manual step a demonstration still has.
printf '  '
curl --noproxy '*' --silent --show-error --max-time 20 \
    --header 'Host: trader.localhost' --header 'Content-Type: application/json' \
    --data "{\"display_name\":\"${BUSINESS_NAME}\",\"primary_phone\":\"${PHONE}\",\"contact_full_name\":\"مالک نمونه\",\"password\":\"${TRADER_PASSWORD}\"}" \
    "http://127.0.0.1:${HTTP_PORT}/api/v1/traders/register"
printf '\n  phone %s\n' "$PHONE"

printf '\n== the centre creates its first administrator ==\n'
printf '%s' "$ADMIN_PASSWORD" | compose run --rm --no-deps -T backend \
    python -m app.cli.create_first_admin --username "$ADMIN_USER" \
    --full-name 'Rehearsal Administrator' --role business_admin 2>/dev/null \
    | sed 's/^/  /'

printf '\n== walking the path in Chromium ==\n'
cd apps/admin-web
DEMO_PHONE="$PHONE" \
DEMO_TRADER_PASSWORD="$TRADER_PASSWORD" \
DEMO_ADMIN_USER="$ADMIN_USER" \
DEMO_ADMIN_PASSWORD="$ADMIN_PASSWORD" \
DEMO_BUSINESS_NAME="$BUSINESS_NAME" \
    pnpm exec playwright test --config=playwright.demo.config.ts

printf '\nThe onboarding path works end to end. The stack is left running on port %s;\n' "$HTTP_PORT"
printf 'stop it with: docker compose --project-name %s --env-file .env -f infra/compose/compose.local.yml down\n' "$PROJECT"
