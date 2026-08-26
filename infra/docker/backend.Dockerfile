FROM python:3.12.13-slim-bookworm AS builder

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    UV_LINK_MODE=copy

RUN python -m pip install uv==0.8.22

WORKDIR /app
COPY services/backend/pyproject.toml services/backend/uv.lock services/backend/README.md ./
COPY services/backend/app ./app
COPY services/backend/alembic ./alembic
COPY services/backend/alembic.ini ./alembic.ini

RUN uv sync --frozen --no-dev --no-editable

FROM python:3.12.13-slim-bookworm AS runtime

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# **The runtime image carries no package manager**, which is the rule the node images have followed
# since M1 and this one had not. `admin-web.Dockerfile:49` drops npm with the same reasoning in
# almost the same words — "the runtime only ever runs the standalone server, so the npm that ships in
# the base image is unused weight" — so the Python side was an omission rather than a different
# judgement, and the two now agree.
#
# Nothing here uses the system `pip`: the
# application runs from `/app/.venv/bin`, which `uv sync` built in the builder stage and which does
# not contain pip either. What the base image ships is therefore dead weight — and dead weight that
# shows up in every image vulnerability scan, because a `pip` advisory is a finding in a
# *language* package the base provides and our lockfile never mentions. `trivy fs` over the
# repository cannot see it; `trivy image` can, which is how gate 6 fails while gate 5 passes.
#
# Removing it is the durable fix rather than tracking pip's version through base-image releases, and
# that was measured rather than assumed: `python:3.12.13` and `python:3.12.14` **both ship pip
# 25.0.1**, so the patch bump this was first written as would have moved only `ca-certificates` and
# left any pip advisory exactly where it was.
#
# The base therefore stays at 3.12.13 deliberately. `infra/scripts/verify-native.sh:61` asserts the
# toolchain is exactly `Python 3.12.13` and `.python-version` pins it, so bumping the image alone
# would leave the tests running on one interpreter and production on another — and bumping the
# toolchain to match is not available: `uv python install 3.12.14` answers "No download found", uv is
# pinned at 0.8.22 by `[tool.uv] required-version`, and its manifest does not carry that release.
#
# A runtime image that cannot install software is also the smaller attack surface, which is the
# reason worth keeping even after the advisory is gone.
#
# **Asserted, not assumed.** The `! python -c "import pip"` fails the build if the removal missed —
# a silent no-op here would leave the finding in place and the comment above claiming otherwise.
RUN rm -rf /usr/local/lib/python3.12/site-packages/pip \
    /usr/local/lib/python3.12/site-packages/pip-*.dist-info \
    /usr/local/bin/pip /usr/local/bin/pip3 /usr/local/bin/pip3.12 \
    && ! python -c "import pip" 2>/dev/null

RUN groupadd --gid 10001 app \
    && useradd --uid 10001 --gid app --no-create-home --shell /usr/sbin/nologin app \
    && mkdir -p /app/storage \
    && chown -R app:app /app

WORKDIR /app
COPY --from=builder --chown=app:app /app/.venv /app/.venv
COPY --chown=app:app services/backend/app ./app
COPY --chown=app:app services/backend/alembic ./alembic
COPY --chown=app:app services/backend/alembic.ini services/backend/pyproject.toml ./

USER app
EXPOSE 8000
STOPSIGNAL SIGTERM
CMD ["uvicorn", "app.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]
