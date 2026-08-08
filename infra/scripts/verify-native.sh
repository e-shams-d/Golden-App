#!/usr/bin/env sh
set -eu

repository_root=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
cd "$repository_root"

require_command() {
    command_name=$1
    install_hint=$2
    if ! command -v "$command_name" >/dev/null 2>&1; then
        printf '%s\n' "$command_name is required. $install_hint" >&2
        exit 1
    fi
}

assert_exact_version() {
    label=$1
    expected=$2
    shift 2

    if ! actual=$("$@" 2>&1); then
        printf '%s\n' "Unable to read the $label version." >&2
        exit 1
    fi

    if [ "$actual" != "$expected" ]; then
        printf '%s\n' \
            "$label version mismatch. Expected '$expected', found '$actual'." >&2
        exit 1
    fi

    printf '%s\n' "$label version: $actual"
}

require_command node "Install the version pinned in .nvmrc."
require_command uv "Install the repository-pinned uv version."
require_command pnpm "Enable the repository-pinned pnpm version through Corepack."

printf '%s\n' "Verifying the exact repository toolchain..."
assert_exact_version "Node.js" "v24.18.0" node --version
assert_exact_version "pnpm" "11.15.1" pnpm --version

if ! uv_version=$(uv --version 2>&1); then
    printf '%s\n' "Unable to read the uv version." >&2
    exit 1
fi
case "$uv_version" in
    uv\ 0.8.22|uv\ 0.8.22\ *)
        printf '%s\n' "uv version: $uv_version"
        ;;
    *)
        printf '%s\n' \
            "uv version mismatch. Expected 'uv 0.8.22', found '$uv_version'." >&2
        exit 1
        ;;
esac

printf '%s\n' "Synchronizing the frozen backend environment..."
uv sync --project services/backend --frozen --group dev

assert_exact_version "Python" "Python 3.12.13" \
    uv run --project services/backend --frozen python --version

printf '%s\n' "Running provider-neutral repository checks..."
uv run --project services/backend --frozen \
    python infra/scripts/validate_repository.py

secret_scanner=infra/scripts/scan_secrets.py
if [ -f "$secret_scanner" ]; then
    printf '%s\n' "Running the repository secret scanner..."
    uv run --project services/backend --frozen python "$secret_scanner"
else
    printf '%s\n' \
        "No repository-local secret scanner is present; the CI provider must supply this gate."
fi

printf '%s\n' "Running backend lint, type, and test gates..."
# The target list lives in one file that this script and verify-native.ps1 both
# read. It used to be written out in each, and the two drifted without either
# reporting anything — see the comment at the top of that file.
lint_targets=$(grep -vE '^\s*(#|$)' infra/verification/lint_targets.txt | tr '\n' ' ')
if [ -z "$lint_targets" ]; then
    printf '%s\n' "infra/verification/lint_targets.txt is empty or unreadable." >&2
    exit 1
fi
# Unquoted on purpose: the file is a list of paths and word splitting is how they
# become separate arguments.
# shellcheck disable=SC2086
uv run --project services/backend --frozen \
    ruff check --config services/backend/pyproject.toml $lint_targets
uv run --project services/backend --frozen \
    mypy --config-file services/backend/pyproject.toml services/backend/app
# tests/integration is listed explicitly because an explicit path argument
# overrides testpaths entirely. Those tests skip when
# INTEGRATION_ADMIN_DATABASE_URL is unset, so a developer without PostgreSQL
# still gets a clean run; CI sets it and they fail rather than skip.
uv run --project services/backend --frozen \
    pytest -c services/backend/pyproject.toml tests/backend tests/integration

printf '%s\n' "Installing the frozen frontend dependency graph..."
pnpm install --frozen-lockfile

printf '%s\n' "Checking the committed OpenAPI contract..."
pnpm openapi:check

printf '%s\n' \
    "Running frontend safety, lint, type, test, build, and accessibility gates..."
pnpm validate:static
pnpm check:public-env
pnpm lint
pnpm typecheck
pnpm test
pnpm build
pnpm test:a11y

printf '%s\n' "Native M1 verification passed."
