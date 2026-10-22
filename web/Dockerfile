# syntax=docker/dockerfile:1.7
FROM node:22.12-alpine AS build
WORKDIR /src
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY . .
RUN npm run build && rm -f dist/config.json

# nginx 1.30 (linha estável) na variante sem root: o mestre roda como uid 101, escuta na 8080, pid e temporários em /tmp.
FROM nginxinc/nginx-unprivileged:1.30.6-alpine
COPY nginx.conf.template /etc/nginx/templates/default.conf.template
COPY --chmod=755 docker-entrypoint.d/40-config-json.sh /docker-entrypoint.d/40-config-json.sh
COPY --from=build /src/dist /usr/share/nginx/html
# só o config.json é gravável pelo nginx (gerado na subida); o resto do site continua do root e só leitura
USER root
RUN install -o 101 -g 101 -m 644 /dev/null /usr/share/nginx/html/config.json
USER 101
ENV NGINX_ENVSUBST_FILTER="APP_DOMAIN|AUTH_URL"
EXPOSE 8080
HEALTHCHECK --interval=15s --timeout=3s CMD wget -qO- http://127.0.0.1:8080/ >/dev/null || exit 1
