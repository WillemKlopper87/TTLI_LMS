# Next 16 standalone build. Three stages so the runtime image carries
# neither the toolchain nor the full node_modules tree.
#
# Build context is the REPO ROOT, not apps/web: this app consumes
# @ttli/api-client as `file:../../packages/api-client`, so that package
# has to be inside the context. See infra/docker-compose.prod.yml.
#
# Digest-pinned (report M7), all three stages the same tag/digest — a
# mutable tag lets whoever controls it change what a production build
# actually pulls. Re-resolve deliberately (not on a schedule) with:
#   docker buildx imagetools inspect node:24-slim
FROM node:24-slim@sha256:ba849c60be29959425b8734d57b8b4b7d56f98edd9504c9af091d5281095a71e AS deps
WORKDIR /repo
COPY packages/api-client/package.json packages/api-client/package-lock.json ./packages/api-client/
RUN cd packages/api-client && npm ci
COPY apps/web/package.json apps/web/package-lock.json ./apps/web/
RUN cd apps/web && npm ci

FROM node:24-slim@sha256:ba849c60be29959425b8734d57b8b4b7d56f98edd9504c9af091d5281095a71e AS build
WORKDIR /repo
COPY --from=deps /repo/packages/api-client/node_modules ./packages/api-client/node_modules
COPY --from=deps /repo/apps/web/node_modules ./apps/web/node_modules
COPY packages/api-client ./packages/api-client
COPY apps/web ./apps/web
# --webpack (package.json's build script): Turbopack cannot resolve the
# @ttli/api-client symlink — see apps/web/next.config.ts for the upstream
# issue numbers. BUILD_STANDALONE switches on `output: "standalone"`,
# which is opt-in because `next start` (used by the Playwright gate)
# cannot serve a standalone build.
ENV BUILD_STANDALONE=1
# Baked at build time (see apps/api/Dockerfile's identical ARG for why:
# a runtime env var could be overridden by whoever writes .env.prod, and
# the whole point of this is knowing what was actually built). NEXT_
# PUBLIC_ so the admin platform page can read it client-side with no
# extra API round-trip just to show a version string.
ARG GIT_SHA=unknown
ENV NEXT_PUBLIC_APP_VERSION=$GIT_SHA
RUN cd apps/web && npm run build

FROM node:24-slim@sha256:ba849c60be29959425b8734d57b8b4b7d56f98edd9504c9af091d5281095a71e AS runtime
# The base image bundles its own npm CLI (with its own vendored deps --
# brace-expansion, tar, ip-address) at /usr/local/lib/node_modules/npm;
# report M7's Trivy pass flagged CVEs in those exact vendored versions.
# Nothing at runtime calls npm/npx (CMD below runs the standalone server
# directly), so the whole CLI is dead weight here -- removing it drops
# those CVEs along with some image size, rather than waiting on upstream
# to rebuild node:24-slim with a newer bundled npm.
RUN rm -rf /usr/local/lib/node_modules/npm /usr/local/bin/npm /usr/local/bin/npx /usr/local/bin/corepack
RUN useradd --create-home --uid 10001 app
WORKDIR /app
ENV NODE_ENV=production PORT=3010 HOSTNAME=0.0.0.0
# The standalone bundle carries its own minimal node_modules; static and
# public are copied beside it exactly as Next's docs prescribe.
COPY --from=build /repo/apps/web/.next/standalone ./
COPY --from=build /repo/apps/web/.next/static ./apps/web/.next/static
COPY --from=build /repo/apps/web/public ./apps/web/public
USER app
EXPOSE 3010
# API_URL must point at the API service (compose/Container Apps env) —
# every browser request reaches the API through this BFF, never directly.
CMD ["node", "apps/web/server.js"]
