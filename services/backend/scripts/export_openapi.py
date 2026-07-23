"""Export or verify the canonical, deterministic OpenAPI v1 artifact."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from pydantic_settings import BaseSettings, PydanticBaseSettingsSource

BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = BACKEND_ROOT.parents[1]
DEFAULT_OUTPUT = BACKEND_ROOT / "openapi" / "v1.json"

if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.api.contract import API_CONTRACT_VERSION  # noqa: E402
from app.core.config import Settings  # noqa: E402
from app.main import create_app  # noqa: E402


class ContractSettings(Settings):
    """Settings source that cannot consume dotenv, host env, or file secrets."""

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        del settings_cls, env_settings, dotenv_settings, file_secret_settings
        return (init_settings,)


def build_schema() -> dict[str, Any]:
    """Build OpenAPI without host configuration or dependency connections."""

    settings = ContractSettings(
        app_env="test",
        service_name="backend-api",
        app_debug=False,
        log_level="CRITICAL",
        release_version="contract-export",
        release_commit="unknown",
        business_timezone="Asia/Tehran",
        internal_timezone="UTC",
        database_url="postgresql+psycopg://contract:contract@localhost/contract",
        redis_url="redis://:contract@localhost:6379/0",
        local_storage_root=(REPOSITORY_ROOT / ".local" / "contract-storage").resolve(),
        operations_health_token=None,
    )
    schema = create_app(settings).openapi()
    validate_schema(schema)
    return schema


def validate_schema(schema: dict[str, Any]) -> None:
    """Fail closed when the generated document violates the M1 contract boundary."""

    if not str(schema.get("openapi", "")).startswith("3.1."):
        raise ValueError("OpenAPI 3.1 is required")
    if schema.get("info", {}).get("version") != API_CONTRACT_VERSION:
        raise ValueError("OpenAPI contract version is not canonical")

    paths = schema.get("paths")
    if not isinstance(paths, dict) or not paths:
        raise ValueError("OpenAPI must contain at least one path")
    invalid_paths = sorted(path for path in paths if not path.startswith("/api/v1/"))
    if invalid_paths:
        raise ValueError(f"OpenAPI paths outside /api/v1: {', '.join(invalid_paths)}")

    operation_ids: list[str] = []
    for path_item in paths.values():
        if not isinstance(path_item, dict):
            continue
        for method, operation in path_item.items():
            if method not in {"get", "post", "put", "patch", "delete", "options", "head"}:
                continue
            operation_id = operation.get("operationId") if isinstance(operation, dict) else None
            if not isinstance(operation_id, str) or not operation_id:
                raise ValueError("Every OpenAPI operation requires an explicit operationId")
            operation_ids.append(operation_id)
    if len(operation_ids) != len(set(operation_ids)):
        raise ValueError("OpenAPI operationId values must be unique")


def render_schema() -> str:
    """Return canonical UTF-8 JSON text with stable ordering and a final newline."""

    return json.dumps(
        build_schema(),
        allow_nan=False,
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    ) + "\n"


def render_schema_bytes() -> bytes:
    """Return the exact bytes committed as the canonical contract artifact."""

    return render_schema().encode("utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--write", action="store_true", help="write the canonical artifact")
    mode.add_argument("--check", action="store_true", help="fail if the artifact is stale")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    output = args.output.resolve()
    rendered = render_schema_bytes()

    if args.write:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(rendered)
        print(f"Wrote deterministic OpenAPI contract: {output.relative_to(REPOSITORY_ROOT)}")
        return 0

    try:
        existing = output.read_bytes()
    except FileNotFoundError:
        print(f"OpenAPI contract is missing: {output}", file=sys.stderr)
        return 1
    if existing != rendered:
        print(
            "OpenAPI contract is stale; run `pnpm openapi:generate` and review the diff.",
            file=sys.stderr,
        )
        return 1
    print(f"OpenAPI contract is current: {output.relative_to(REPOSITORY_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
