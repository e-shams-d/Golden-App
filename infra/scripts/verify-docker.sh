#!/usr/bin/env sh
set -eu

repository_root=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
cd "$repository_root"

if ! command -v docker >/dev/null 2>&1; then
    printf '%s\n' "Docker Engine with Compose v2 is required." >&2
    exit 1
fi
if ! command -v git >/dev/null 2>&1; then
    printf '%s\n' \
        "Git is required to bind release metadata to the clean-clone commit." >&2
    exit 1
fi
if ! command -v curl >/dev/null 2>&1; then
    printf '%s\n' "curl is required for local HTTP smoke checks." >&2
    exit 1
fi
if [ ! -f .env ]; then
    printf '%s\n' \
        "Create a private .env from .env.example before Docker verification." >&2
    exit 1
fi

dotenv_value() {
    variable_name=$1
    if ! value=$(
        awk -v variable_name="$variable_name" '
            {
                line = $0
                sub(/\r$/, "", line)
                pattern = "^[ \t]*" variable_name "[ \t]*="
                if (line ~ pattern) {
                    count += 1
                    sub(pattern "[ \t]*", "", line)
                    sub(/[ \t]*$/, "", line)
                    value = line
                }
            }
            END {
                if (count != 1) {
                    exit 2
                }
                printf "%s", value
            }
        ' .env
    ); then
        printf '%s\n' \
            "$variable_name must have exactly one assignment in the private .env file." >&2
        return 1
    fi
    if [ -z "$value" ]; then
        printf '%s\n' "$variable_name must not be empty in the private .env file." >&2
        return 1
    fi
    printf '%s' "$value"
}

assert_url_safe_credential() {
    variable_name=$1
    minimum_length=$2
    value=$(dotenv_value "$variable_name")
    case "$value" in
        [Cc][Hh][Aa][Nn][Gg][Ee]-[Mm][Ee]*|*[!A-Za-z0-9._~-]*)
            printf '%s\n' \
                "$variable_name must contain only URL-safe characters." >&2
            return 1
            ;;
    esac
    if [ "${#value}" -lt "$minimum_length" ]; then
        printf '%s\n' \
            "$variable_name must be at least $minimum_length characters." >&2
        return 1
    fi
}

for controlled_name in \
    POSTGRES_PASSWORD \
    APP_DB_PASSWORD \
    MIGRATION_DB_PASSWORD \
    REDIS_PASSWORD \
    OPERATIONS_HEALTH_TOKEN \
    RELEASE_COMMIT; do
    if env | grep -q "^${controlled_name}="; then
        printf '%s\n' \
            "$controlled_name is inherited from the process and would override .env." \
            "Remove that process variable before verification." >&2
        exit 1
    fi
done

for credential_name in \
    POSTGRES_PASSWORD \
    APP_DB_PASSWORD \
    MIGRATION_DB_PASSWORD \
    REDIS_PASSWORD; do
    assert_url_safe_credential "$credential_name" 16
done
assert_url_safe_credential OPERATIONS_HEALTH_TOKEN 32

expected_commit=$(git rev-parse HEAD)
if ! printf '%s\n' "$expected_commit" | grep -Eq '^[0-9a-f]{40}$'; then
    printf '%s\n' "Could not resolve the clean-clone Git commit." >&2
    exit 1
fi
configured_commit=$(dotenv_value RELEASE_COMMIT)
if [ "$configured_commit" != "$expected_commit" ]; then
    printf '%s\n' \
        "RELEASE_COMMIT in .env must exactly equal the clean-clone Git SHA." >&2
    exit 1
fi

verification_project_name=${M1_VERIFY_PROJECT_NAME:-gold-platform-m1-verify}
if ! printf '%s\n' "$verification_project_name" |
    grep -Eq '^[a-z0-9][a-z0-9_-]*$'; then
    printf '%s\n' \
        "M1_VERIFY_PROJECT_NAME contains unsupported characters." >&2
    exit 1
fi
verification_http_port=${M1_VERIFY_HTTP_PORT:-18080}
case "$verification_http_port" in
    ''|*[!0-9]*)
        printf '%s\n' \
            "M1_VERIFY_HTTP_PORT must be an integer between 1 and 65535." >&2
        exit 1
        ;;
esac
if [ "$verification_http_port" -lt 1 ] || [ "$verification_http_port" -gt 65535 ]; then
    printf '%s\n' \
        "M1_VERIFY_HTTP_PORT must be an integer between 1 and 65535." >&2
    exit 1
fi

LOCAL_DATA_ROOT="../../.local/m1-verify/$verification_project_name"
HTTP_PORT=$verification_http_port
export LOCAL_DATA_ROOT HTTP_PORT

compose() {
    docker compose \
        --project-name "$verification_project_name" \
        --env-file .env \
        -f infra/compose/compose.local.yml \
        "$@"
}

stack_started=0
database_sentinel_created=0
storage_sentinel_created=0
persistence_sentinel=

# Container logs are never printed: they can carry .env values, and this script
# runs in CI where its output is world-readable to anyone with repository access.
# On failure they are written to a gitignored directory instead, with every
# credential this script knows about replaced first, so a failure is diagnosable
# without a maintainer having to reproduce the whole stack locally to see why a
# container was unhealthy.
DIAGNOSTIC_SECRETS="POSTGRES_PASSWORD APP_DB_PASSWORD MIGRATION_DB_PASSWORD REDIS_PASSWORD OPERATIONS_HEALTH_TOKEN"

capture_diagnostics() {
    # Deliberately not under .local/. Compose bind-mounts the data root, so
    # Docker creates .local as root, and the unprivileged user running this
    # script then cannot add a sibling directory there. On a fresh CI runner
    # .local does not exist yet and the write would succeed, which is the shape
    # that passes in CI and fails on the machine that signs the acceptance off.
    # The repository root is owned by whoever checked it out, so this always
    # works. Repository-root relative because this runs in the shell;
    # LOCAL_DATA_ROOT's ../../ prefix is resolved by Compose against the compose
    # file instead and must not be copied here.
    diagnostics_dir=".verify-diagnostics/$verification_project_name"
    if ! mkdir -p "$diagnostics_dir" 2>/dev/null; then
        printf '%s\n' "Could not create $diagnostics_dir; skipping log capture." >&2
        return 0
    fi

    redaction_script=$(
        for secret_name in $DIAGNOSTIC_SECRETS; do
            secret_value=$(dotenv_value "$secret_name" 2>/dev/null) || continue
            [ -n "$secret_value" ] || continue
            printf 's|%s|<redacted:%s>|g\n' \
                "$(printf '%s' "$secret_value" | sed 's/[|\\&]/\\&/g')" "$secret_name"
        done
    )

    for service in $(compose config --services 2>/dev/null); do
        target="$diagnostics_dir/$service.log"
        if [ -n "$redaction_script" ]; then
            compose logs --no-color --timestamps "$service" 2>&1 |
                sed "$redaction_script" >"$target" 2>/dev/null || true
        else
            compose logs --no-color --timestamps "$service" >"$target" 2>&1 || true
        fi
    done
    compose ps -a >"$diagnostics_dir/compose-ps.txt" 2>&1 || true

    printf '%s\n' \
        "Container logs written to $diagnostics_dir with known credentials redacted." >&2
    printf '%s\n' \
        "They are not printed here because this output is not a private channel." >&2
}

cleanup() {
    result=$?
    trap - EXIT HUP INT TERM
    if [ "$result" -ne 0 ] && [ "$stack_started" -eq 1 ]; then
        capture_diagnostics
    fi
    if \
        [ "$stack_started" -eq 1 ] &&
        { [ "$database_sentinel_created" -eq 1 ] ||
            [ "$storage_sentinel_created" -eq 1 ]; }; then
        printf '%s\n' "Removing non-financial persistence sentinels..."
        if ! remove_persistence_sentinels; then
            if [ "$result" -eq 0 ]; then
                result=1
            else
                printf '%s\n' "Persistence-sentinel cleanup also failed." >&2
            fi
        fi
    elif \
        [ "$database_sentinel_created" -eq 1 ] ||
        [ "$storage_sentinel_created" -eq 1 ]; then
        printf '%s\n' \
            "A non-financial persistence sentinel may remain because the stack is stopped." >&2
    fi
    if [ "$stack_started" -eq 1 ]; then
        printf '%s\n' \
            "Stopping the verification stack without deleting data volumes..."
        if ! compose down; then
            if [ "$result" -eq 0 ]; then
                result=1
            else
                printf '%s\n' "Stack cleanup also failed." >&2
            fi
        fi
    fi
    exit "$result"
}
trap cleanup EXIT
trap 'exit 129' HUP
trap 'exit 130' INT
trap 'exit 143' TERM

assert_one_shot_succeeded() {
    service=$1
    container_id=$(compose ps --all -q "$service")
    if [ -z "$container_id" ]; then
        printf '%s\n' \
            "The $service one-shot service did not create a container." >&2
        return 1
    fi
    exit_code=$(docker inspect --format '{{.State.ExitCode}}' "$container_id")
    if [ "$exit_code" != 0 ]; then
        printf '%s\n' \
            "The $service one-shot service did not complete successfully." >&2
        return 1
    fi
}

assert_long_running_services() {
    running_services=$(compose ps --services --status running)
    for service in \
        nginx \
        trader-pwa \
        admin-web \
        backend \
        worker \
        scheduler \
        postgres \
        redis; do
        if ! printf '%s\n' "$running_services" | grep -Fx "$service" >/dev/null 2>&1; then
            printf '%s\n' "Expected service is not running: $service." >&2
            return 1
        fi
    done
}

assert_application_isolation() {
    for service in \
        nginx \
        trader-pwa \
        admin-web \
        backend \
        worker \
        scheduler \
        migrate; do
        container_id=$(compose ps --all -q "$service")
        configured_user=$(docker inspect --format '{{.Config.User}}' "$container_id")
        case "$configured_user" in
            ''|0|0:0|root)
                printf '%s\n' \
                    "$service must use an explicit non-root runtime user." >&2
                return 1
                ;;
        esac
    done

    for service in \
        trader-pwa \
        admin-web \
        backend \
        worker \
        scheduler \
        postgres \
        redis; do
        container_id=$(compose ps -q "$service")
        bindings=$(docker inspect --format '{{json .HostConfig.PortBindings}}' "$container_id")
        case "$bindings" in
            null|'{}')
                ;;
            *)
                printf '%s\n' "$service must not publish a host port." >&2
                return 1
                ;;
        esac
    done
}

assert_container_health_checks() {
    container_ids=$(compose ps --all -q)
    if [ -z "$container_ids" ]; then
        printf '%s\n' "Could not inspect Docker Compose container health." >&2
        return 1
    fi

    checked_services=
    for container_id in $container_ids; do
        has_health_check=$(
            docker inspect \
                --format '{{if .Config.Healthcheck}}configured{{else}}none{{end}}' \
                "$container_id"
        )
        if [ "$has_health_check" != configured ]; then
            continue
        fi
        service=$(
            docker inspect \
                --format '{{index .Config.Labels "com.docker.compose.service"}}' \
                "$container_id"
        )
        health_status=$(
            docker inspect --format '{{.State.Health.Status}}' "$container_id"
        )
        if [ "$health_status" != healthy ]; then
            printf '%s\n' \
                "Container health check is not healthy for service $service." >&2
            return 1
        fi
        checked_services="${checked_services}
$service"
    done

    for service in \
        nginx \
        trader-pwa \
        admin-web \
        backend \
        postgres \
        redis; do
        if ! printf '%s\n' "$checked_services" |
            grep -Fx "$service" >/dev/null 2>&1; then
            printf '%s\n' \
                "Required container health check was not inspected: $service." >&2
            return 1
        fi
    done
}

wait_for_container_health_checks() {
    attempts=90
    while [ "$attempts" -gt 0 ]; do
        if assert_container_health_checks >/dev/null 2>&1; then
            return 0
        fi
        attempts=$((attempts - 1))
        sleep 2
    done
    printf '%s\n' \
        "Timed out waiting for all configured container health checks." >&2
    return 1
}

assert_storage_init_security() {
    container_id=$(compose ps --all -q storage-init)
    if [ -z "$container_id" ]; then
        printf '%s\n' "Could not resolve the storage-init container." >&2
        return 1
    fi

    configured_user=$(docker inspect --format '{{.Config.User}}' "$container_id")
    case "$configured_user" in
        0|0:0|root)
            ;;
        *)
            printf '%s\n' \
                "storage-init must explicitly use its reviewed root exception." >&2
            return 1
            ;;
    esac
    read_only_root=$(
        docker inspect --format '{{.HostConfig.ReadonlyRootfs}}' "$container_id"
    )
    if [ "$read_only_root" != true ]; then
        printf '%s\n' "storage-init must use a read-only root filesystem." >&2
        return 1
    fi

    # Docker 25+/Compose v2 may report capabilities in CAP_-prefixed form.
    cap_add=$(
        docker inspect \
            --format '{{range .HostConfig.CapAdd}}{{println .}}{{end}}' \
            "$container_id" | sed 's/^CAP_//'
    )
    for capability in CHOWN DAC_OVERRIDE FOWNER; do
        if ! printf '%s\n' "$cap_add" |
            grep -Fx "$capability" >/dev/null 2>&1; then
            printf '%s\n' \
                "storage-init is missing reviewed capability $capability." >&2
            return 1
        fi
    done
    if printf '%s\n' "$cap_add" |
        grep -Ev '^(CHOWN|DAC_OVERRIDE|FOWNER)?$' >/dev/null 2>&1; then
        printf '%s\n' \
            "storage-init has a capability outside the reviewed exception." >&2
        return 1
    fi

    cap_drop=$(
        docker inspect \
            --format '{{range .HostConfig.CapDrop}}{{println .}}{{end}}' \
            "$container_id" | sed 's/^CAP_//'
    )
    if ! printf '%s\n' "$cap_drop" | grep -Fx ALL >/dev/null 2>&1; then
        printf '%s\n' "storage-init must drop all capabilities first." >&2
        return 1
    fi
    security_options=$(
        docker inspect \
            --format '{{range .HostConfig.SecurityOpt}}{{println .}}{{end}}' \
            "$container_id"
    )
    if ! printf '%s\n' "$security_options" |
        grep -Fx 'no-new-privileges:true' >/dev/null 2>&1; then
        printf '%s\n' "storage-init must enable no-new-privileges." >&2
        return 1
    fi
}

smoke_target() {
    port=$1
    host_name=$2
    path=$3
    curl \
        --fail \
        --silent \
        --show-error \
        --max-time 5 \
        --header "Host: $host_name" \
        "http://127.0.0.1:$port$path" \
        >/dev/null 2>&1
}

wait_for_http_targets() {
    port=$1
    attempts=90
    while [ "$attempts" -gt 0 ]; do
        pending=
        if ! smoke_target "$port" trader.localhost /nginx-health; then
            pending="${pending} Nginx"
        fi
        if ! smoke_target "$port" trader.localhost /api/v1/health/live; then
            pending="${pending} backend-liveness"
        fi
        if ! smoke_target "$port" trader.localhost /api/v1/health/ready; then
            pending="${pending} backend-readiness"
        fi
        if ! smoke_target "$port" trader.localhost /; then
            pending="${pending} trader-app"
        fi
        if ! smoke_target "$port" admin.localhost /; then
            pending="${pending} admin-app"
        fi
        if [ -z "$pending" ]; then
            return 0
        fi
        attempts=$((attempts - 1))
        sleep 2
    done
    printf '%s\n' "Timed out waiting for HTTP checks:$pending." >&2
    return 1
}

restricted_health_target() {
    path=$1
    compose exec -T backend python -c '
import os
import sys
import urllib.request

request = urllib.request.Request(
    "http://127.0.0.1:8000" + sys.argv[1],
    headers={"X-Operations-Token": os.environ["OPERATIONS_HEALTH_TOKEN"]},
)
with urllib.request.urlopen(request, timeout=5) as response:
    if response.status != 200:
        raise SystemExit(1)
' "$path" >/dev/null 2>&1
}

wait_for_restricted_health_targets() {
    attempts=90
    while [ "$attempts" -gt 0 ]; do
        if \
            restricted_health_target /api/v1/health/dependencies &&
            restricted_health_target /api/v1/health/workers; then
            return 0
        fi
        attempts=$((attempts - 1))
        sleep 2
    done
    printf '%s\n' \
        "Timed out waiting for restricted dependency/worker health checks." >&2
    return 1
}

assert_release_metadata() {
    port=$1
    expected=$2
    metadata=$(
        curl \
            --fail \
            --silent \
            --show-error \
            --max-time 5 \
            --header "Host: trader.localhost" \
            "http://127.0.0.1:$port/api/v1/meta/release"
    )
    if ! compose exec -T backend python -c '
import json
import sys

metadata = json.loads(sys.argv[1])
if metadata.get("commit") != sys.argv[2]:
    raise SystemExit(1)
' "$metadata" "$expected" >/dev/null 2>&1; then
        printf '%s\n' \
            "Release metadata commit does not match the clean-clone Git SHA." >&2
        return 1
    fi
}

invoke_postgres_sql() {
    sql=$1
    compose exec -T postgres sh -eu -c \
        'psql --set=ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" --command "$1"' \
        _ "$sql"
}

write_persistence_sentinels() {
    sentinel=$1
    persistence_sentinel=$sentinel
    sql="
CREATE SCHEMA IF NOT EXISTS m1_verification;
CREATE TABLE IF NOT EXISTS m1_verification.persistence_probe (
    probe_key text PRIMARY KEY,
    probe_value text NOT NULL
);
INSERT INTO m1_verification.persistence_probe (probe_key, probe_value)
VALUES ('$sentinel', 'present')
ON CONFLICT (probe_key) DO UPDATE SET probe_value = EXCLUDED.probe_value;
"
    if ! invoke_postgres_sql "$sql"; then
        printf '%s\n' \
            "Could not write the PostgreSQL persistence sentinel." >&2
        return 1
    fi
    database_sentinel_created=1

    if ! compose exec -T backend python -c '
from pathlib import Path
import sys

path = Path("/app/storage") / f".m1-persistence-{sys.argv[1]}"
path.write_text(
    "present\n",
    encoding="ascii",
)
' "$sentinel"; then
        printf '%s\n' "Could not write the storage persistence sentinel." >&2
        return 1
    fi
    storage_sentinel_created=1
}

assert_persistence_sentinels() {
    sentinel=$1
    query="
SELECT probe_value
FROM m1_verification.persistence_probe
WHERE probe_key = '$sentinel';
"
    database_value=$(
        compose exec -T postgres sh -eu -c \
            'psql --set=ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" --tuples-only --no-align --command "$1"' \
            _ "$query"
    )
    database_value=$(printf '%s' "$database_value" | tr -d '\r\n')
    if [ "$database_value" != present ]; then
        printf '%s\n' \
            "The PostgreSQL persistence sentinel did not survive container recreation." >&2
        return 1
    fi

    if ! compose exec -T backend python -c '
from pathlib import Path
import sys

path = Path("/app/storage") / f".m1-persistence-{sys.argv[1]}"
if path.read_text(encoding="ascii").strip() != "present":
    raise SystemExit(1)
' "$sentinel"; then
        printf '%s\n' \
            "The storage persistence sentinel did not survive container recreation." >&2
        return 1
    fi
}

remove_persistence_sentinels() {
    if [ -z "${persistence_sentinel:-}" ]; then
        return 0
    fi

    if [ "$storage_sentinel_created" -eq 1 ]; then
        if ! compose exec -T backend python -c '
from pathlib import Path
import sys

path = Path("/app/storage") / f".m1-persistence-{sys.argv[1]}"
path.unlink(missing_ok=True)
' "$persistence_sentinel"; then
            printf '%s\n' \
                "Could not remove the storage persistence sentinel." >&2
            return 1
        fi
        storage_sentinel_created=0
    fi

    if [ "$database_sentinel_created" -eq 1 ]; then
        if ! invoke_postgres_sql "
DELETE FROM m1_verification.persistence_probe
WHERE probe_key = '$persistence_sentinel';
"; then
            printf '%s\n' \
                "Could not remove the PostgreSQL persistence sentinel." >&2
            return 1
        fi
        database_sentinel_created=0
    fi
    persistence_sentinel=
}

write_image_evidence() {
    printf '%s\n' \
        "Container image evidence (IDs and available immutable digests):"
    for service in \
        nginx \
        trader-pwa \
        admin-web \
        backend \
        worker \
        scheduler \
        migrate \
        storage-init \
        postgres \
        redis; do
        container_id=$(compose ps --all -q "$service")
        if [ -z "$container_id" ]; then
            printf '%s\n' "Could not resolve the $service container." >&2
            return 1
        fi
        image_id=$(docker inspect --format '{{.Image}}' "$container_id")
        repo_digests=$(
            docker image inspect --format '{{json .RepoDigests}}' "$image_id"
        )
        if [ "$repo_digests" = null ] || [ "$repo_digests" = '[]' ]; then
            repo_digests='<none-for-local-build>'
        fi
        printf '%s\n' \
            "$service image_id=$image_id repo_digests=$repo_digests"
    done
}

docker compose version

existing_containers=$(compose ps --all -q)
if [ -n "$existing_containers" ]; then
    printf '%s\n' \
        "The isolated verification project '$verification_project_name' already has containers." \
        "Inspect and stop it explicitly before retrying; this verifier will not take it over." >&2
    exit 1
fi

printf '%s\n' "Validating the Docker Compose model..."
compose config --quiet

printf '%s\n' "Building the application images..."
compose build

printf '%s\n' "Starting the local stack..."
stack_started=1
compose up -d --no-build

assert_one_shot_succeeded migrate
assert_one_shot_succeeded storage-init
assert_long_running_services
assert_application_isolation
assert_storage_init_security

ingress_binding=$(compose port nginx 8080)
ingress_port=${ingress_binding##*:}
case "$ingress_port" in
    ''|*[!0-9]*)
        printf '%s\n' "The Nginx host port mapping is missing or invalid." >&2
        exit 1
        ;;
esac

wait_for_http_targets "$ingress_port"
wait_for_restricted_health_targets
wait_for_container_health_checks
assert_release_metadata "$ingress_port" "$expected_commit"

persistence_sentinel="${expected_commit}-$$-$(date +%s)"
printf '%s\n' \
    "Writing non-financial PostgreSQL and storage persistence sentinels..."
write_persistence_sentinels "$persistence_sentinel"

printf '%s\n' \
    "Recreating the verification stack without deleting persistent data..."
compose down
stack_started=0
stack_started=1
compose up -d --no-build

assert_one_shot_succeeded migrate
assert_one_shot_succeeded storage-init
assert_long_running_services
assert_application_isolation
assert_storage_init_security

ingress_binding=$(compose port nginx 8080)
ingress_port=${ingress_binding##*:}
case "$ingress_port" in
    ''|*[!0-9]*)
        printf '%s\n' "The Nginx host port mapping is missing or invalid." >&2
        exit 1
        ;;
esac
wait_for_http_targets "$ingress_port"
wait_for_restricted_health_targets
wait_for_container_health_checks
assert_release_metadata "$ingress_port" "$expected_commit"
assert_persistence_sentinels "$persistence_sentinel"
remove_persistence_sentinels
write_image_evidence

printf '%s\n' "Docker Compose service status:"
compose ps

printf '%s\n' \
    "automated Docker gates passed. Maintained security scans, SBOMs," \
    "CI evidence, and owner acceptance are still separate required gates."
