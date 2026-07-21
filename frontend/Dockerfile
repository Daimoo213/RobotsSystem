FROM node:26-alpine AS builder

ARG APP
RUN test "$APP" = "pm" -o "$APP" = "om"

WORKDIR /app
RUN corepack enable
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml tsconfig.base.json ./
COPY apps ./apps
COPY packages ./packages
RUN pnpm install --frozen-lockfile \
    && pnpm --filter "@robots/$APP" build \
    && cp -R "apps/$APP/dist" /out

FROM nginx:1.27-alpine AS runtime

COPY deploy/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=builder /out /usr/share/nginx/html
EXPOSE 80
