FROM node:24.18.0-bookworm-slim AS builder

ENV PNPM_HOME=/pnpm \
    PATH=/pnpm:$PATH \
    NEXT_TELEMETRY_DISABLED=1

RUN corepack enable \
    && corepack prepare pnpm@11.15.1 --activate

WORKDIR /workspace
COPY package.json pnpm-workspace.yaml pnpm-lock.yaml turbo.json tsconfig.base.json ./
COPY apps ./apps
COPY packages ./packages

RUN pnpm install --frozen-lockfile

ARG NEXT_PUBLIC_API_BASE_URL=/api/v1
ENV NEXT_PUBLIC_API_BASE_URL=$NEXT_PUBLIC_API_BASE_URL \
    SECURITY_HSTS_ENABLED=false
RUN pnpm --filter @gold/admin-web build

FROM node:24.18.0-bookworm-slim AS runtime

ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    HOSTNAME=0.0.0.0 \
    PORT=3000

# The runtime only ever runs the standalone server, so the npm that ships in
# the base image is unused weight. Dropping it also removes its bundled
# dependency tree (tar, undici, brace-expansion) from the shipped image.
RUN rm -rf /usr/local/lib/node_modules/npm /usr/local/bin/npm /usr/local/bin/npx

RUN groupadd --gid 10001 app \
    && useradd --uid 10001 --gid app --no-create-home --shell /usr/sbin/nologin app \
    && mkdir -p /app \
    && chown app:app /app

WORKDIR /app
COPY --from=builder --chown=app:app /workspace/apps/admin-web/.next/standalone ./
COPY --from=builder --chown=app:app /workspace/apps/admin-web/.next/static ./apps/admin-web/.next/static
COPY --from=builder --chown=app:app /workspace/apps/admin-web/public ./apps/admin-web/public

USER app
EXPOSE 3000
STOPSIGNAL SIGTERM
CMD ["node", "apps/admin-web/server.js"]
