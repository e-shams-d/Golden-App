"""Provider-neutral M1 repository safety checks.

This script intentionally uses only the Python standard library so it can run before
application dependencies are installed. It validates static safety invariants; it does
not replace application tests, Docker Compose validation, or image scanning.
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def repository_files() -> list[Path]:
    ignored_directories = {
        ".agents",
        ".git",
        ".local",
        ".mypy_cache",
        ".venv",
        ".next",
        ".pytest_cache",
        ".ruff_cache",
        ".turbo",
        "__pycache__",
        "Implementation Docs",
        "docs",
        "node_modules",
    }
    files: list[Path] = []
    for current, directories, filenames in os.walk(ROOT, followlinks=False):
        directories[:] = [
            name for name in directories if name not in ignored_directories
        ]
        files.extend(Path(current, filename) for filename in filenames)
    return files


def service_block(compose_text: str, service: str) -> str:
    pattern = re.compile(
        rf"(?ms)^  {re.escape(service)}:\s*\n(?P<body>(?:    .*\n|\s*\n)*)"
    )
    match = pattern.search(compose_text)
    return match.group("body") if match else ""


def main() -> int:
    errors: list[str] = []
    required_paths = [
        "apps/trader-pwa",
        "apps/admin-web",
        "services/backend",
        "services/backend/app/storage/local.py",
        "packages/api-client",
        "packages/api-client/src/generated/openapi.d.ts",
        "packages/ui",
        "packages/config",
        "pnpm-lock.yaml",
        "infra/compose/compose.local.yml",
        "infra/postgres/init/010-create-runtime-roles.sh",
        # The init hook is a thin wrapper over these; they are replayed on every
        # stack start because docker-entrypoint-initdb.d never runs again on an
        # existing volume. Deleting either silently stops provisioning.
        "infra/postgres/bootstrap/010-required-extensions.sql",
        "infra/postgres/bootstrap/020-runtime-roles.sql",
        "infra/nginx/nginx.conf",
        "services/backend/uv.lock",
        "services/backend/openapi/v1.json",
        "services/backend/scripts/export_openapi.py",
        "infra/scripts/scan_secrets.py",
        "infra/scripts/verify-native.ps1",
        "infra/scripts/verify-docker.ps1",
        "tests/contract",
        "tests/e2e",
        "tests/security",
    ]

    for relative in required_paths:
        if not (ROOT / relative).exists():
            errors.append(f"missing required path: {relative}")

    files = repository_files()
    text_files: list[tuple[Path, str]] = []
    for path in files:
        try:
            text_files.append((path, path.read_text(encoding="utf-8")))
        except (UnicodeDecodeError, OSError):
            continue

    for path, text in text_files:
        relative = path.relative_to(ROOT).as_posix()
        if re.search(r"(?im)^\s*(?:image|from)\s*[: ]\s*\S*:latest(?:\s|$)", text):
            errors.append(f"unversioned latest image reference: {relative}")
        if "/var/run/docker.sock" in text and relative != "infra/scripts/validate_repository.py":
            errors.append(f"Docker socket reference is forbidden: {relative}")
        for match in re.finditer(
            r"(?im)^\s*(NEXT_PUBLIC_[A-Z0-9_]*(?:SECRET|PASSWORD|TOKEN|PRIVATE_KEY|API_KEY)[A-Z0-9_]*)\s*=",
            text,
        ):
            errors.append(f"sensitive public environment variable {match.group(1)}: {relative}")

    gitignore_path = ROOT / ".gitignore"
    if gitignore_path.exists():
        gitignore_text = gitignore_path.read_text(encoding="utf-8")
        if re.search(r"(?m)^storage/$", gitignore_text):
            errors.append("root runtime storage ignore must be anchored as /storage/")

    root_package_path = ROOT / "package.json"
    if root_package_path.exists() and "pnpm test:a11y" not in root_package_path.read_text(
        encoding="utf-8"
    ):
        errors.append("root check gate must execute accessibility tests")
    if root_package_path.exists() and "pnpm openapi:check" not in root_package_path.read_text(
        encoding="utf-8"
    ):
        errors.append("root check gate must verify generated OpenAPI artifacts")

    compose_path = ROOT / "infra/compose/compose.local.yml"
    if compose_path.exists():
        compose_text = compose_path.read_text(encoding="utf-8")
        services_text = compose_text.split("\nservices:\n", 1)[1].split("\nnetworks:\n", 1)[0]
        service_names = re.findall(r"(?m)^  ([a-z0-9][a-z0-9-]*):\s*$", services_text)
        for service in service_names:
            body = service_block(services_text, service)
            if not body and service in {"postgres", "redis"}:
                errors.append(f"missing Compose service: {service}")
            elif service != "nginx" and re.search(r"(?m)^    ports:\s*$", body):
                errors.append(f"{service} must not publish host ports; Nginx is ingress")
        if not re.search(r"(?ms)^  nginx:.*?^    ports:\s*$", compose_text):
            errors.append("Nginx must be the explicit local ingress")
        for network in ("app_net", "data_net"):
            network_pattern = re.compile(
                rf"(?ms)^  {network}:\s*\n(?:    .*\n|\s*\n)*?^    internal:\s*true\s*$"
            )
            if not network_pattern.search(compose_text):
                errors.append(f"Compose network must be internal: {network}")
        if "--requirepass" not in service_block(services_text, "redis"):
            errors.append("local Redis must require the environment-provided password")
        backend_body = service_block(services_text, "backend")
        if "OPERATIONS_HEALTH_TOKEN" not in backend_body:
            errors.append("backend must receive the restricted health-probe token")
        for dependency in ("migrate", "storage-init"):
            if not service_block(services_text, dependency):
                errors.append(f"missing one-shot Compose service: {dependency}")
            if not re.search(
                rf"(?ms)^      {re.escape(dependency)}:\s*\n"
                r"^        condition: service_completed_successfully\s*$",
                backend_body,
            ):
                errors.append(f"backend must wait for successful {dependency}")
        worker_body = service_block(services_text, "worker")
        if "--queues=default" in worker_body:
            errors.append("worker must not consume an undeclared default queue")
        for queue in ("files", "exports", "notifications", "reports", "maintenance", "ai"):
            if queue not in worker_body:
                errors.append(f"worker does not consume configured queue: {queue}")
        postgres_body = service_block(services_text, "postgres")
        # Three identities, not two. The worker runs the same code as the API but
        # is reached differently and fails differently; one shared login makes a
        # row written by a scheduled task indistinguishable in pg_stat_activity
        # from one written by a request.
        for role_variable in ("APP_DB_USER", "MIGRATION_DB_USER", "WORKER_DB_USER"):
            if role_variable not in postgres_body:
                errors.append(f"PostgreSQL runtime role separation missing: {role_variable}")
        worker_body = service_block(services_text, "worker")
        if "WORKER_DB_USER" not in worker_body:
            errors.append("worker must connect as the worker role, not the application role")

    dockerfiles = [path for path in files if path.name.endswith("Dockerfile")]
    for path in dockerfiles:
        dockerfile_text = path.read_text(encoding="utf-8")
        if not re.search(r"(?im)^USER\s+\S+", dockerfile_text):
            errors.append(f"Docker runtime user is not explicit: {path.relative_to(ROOT)}")

        # **A shipped image must not carry the package manager its base ships with.**
        #
        # The node images have dropped npm since M1; the python image had not dropped pip, and that
        # asymmetry was found by an image scan rather than by reading either file. The finding class
        # is worth naming because it is invisible to every other gate: pip and npm are *language*
        # packages the base provides and no lockfile mentions, so `trivy fs` over the repository
        # sees nothing while `trivy image` reports a HIGH with a published fix — and the remedy
        # is deleting something unused rather than upgrading anything.
        #
        # Matched on the base name rather than per stage, because a multi-stage file's builder
        # legitimately uses pip to install uv. The removal only has to appear somewhere here; what
        # proves it took effect is the Dockerfile's own `! python -c "import pip"`, which runs where
        # this check cannot — inside the build.
        bases = re.findall(r"(?im)^FROM\s+(\S+)", dockerfile_text)
        if any(base.startswith("python:") for base in bases) and (
            "site-packages/pip" not in dockerfile_text
        ):
            errors.append(
                f"python-based image ships pip into the runtime: {path.relative_to(ROOT)}"
            )
        if any(base.startswith("node:") for base in bases) and (
            "node_modules/npm" not in dockerfile_text
        ):
            errors.append(
                f"node-based image ships npm into the runtime: {path.relative_to(ROOT)}"
            )

        for line_number, line in enumerate(dockerfile_text.splitlines(), 1):
            if not line.upper().startswith("FROM "):
                continue
            image = line.split()[1]
            if ":" not in image and "@sha256:" not in image:
                errors.append(
                    f"unversioned Docker base image: {path.relative_to(ROOT)}:{line_number}"
                )

    for app in ("trader-pwa", "admin-web"):
        config_path = ROOT / "apps" / app / "next.config.ts"
        if config_path.exists():
            config_text = config_path.read_text(encoding="utf-8")
            if 'output: "standalone"' not in config_text:
                errors.append(f"Next standalone output missing: {app}")
            if "outputFileTracingRoot" not in config_text:
                errors.append(f"monorepo tracing root missing: {app}")
        vitest_path = ROOT / "apps" / app / "vitest.config.ts"
        if not vitest_path.exists() or "test/**/*.test.ts" not in vitest_path.read_text(
            encoding="utf-8"
        ):
            errors.append(f"Vitest must exclude Playwright specifications: {app}")

    nginx_local_path = ROOT / "infra" / "nginx" / "conf.d" / "local.conf"
    if nginx_local_path.exists():
        nginx_text = nginx_local_path.read_text(encoding="utf-8")
        protected_locations = re.findall(
            r"(?ms)^    location \^~ /(?:api|files)/ \{\n(?P<body>.*?)^    \}",
            nginx_text,
        )
        if len(protected_locations) != 4:
            errors.append("expected API/file locations for both Nginx virtual hosts")
        for body in protected_locations:
            for header in (
                "Cache-Control",
                "X-Content-Type-Options",
                "Referrer-Policy",
                "Permissions-Policy",
            ):
                if f"add_header {header} " not in body:
                    errors.append(f"Nginx protected location does not set {header}")

    if errors:
        print("M1 repository validation failed:")
        for error in errors:
            print(f"- {error}")
        return 1

    print(
        f"M1 static safety checks passed: {len(files)} files, "
        f"{len(dockerfiles)} Dockerfiles, no forbidden exposure markers."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
