# syntax=docker/dockerfile:1.7
FROM node:22.12-alpine AS build
WORKDIR /src
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY . .
RUN npm run build && rm -f dist/config.json

FROM nginx:1.27.3-alpine
COPY nginx.conf.template /etc/nginx/templates/default.conf.template
COPY docker-entrypoint.d/40-config-json.sh /docker-entrypoint.d/40-config-json.sh
COPY --from=build /src/dist /usr/share/nginx/html
RUN chmod +x /docker-entrypoint.d/40-config-json.sh
ENV NGINX_ENVSUBST_FILTER="APP_DOMAIN|AUTH_URL"
EXPOSE 8080
HEALTHCHECK --interval=15s --timeout=3s CMD wget -qO- http://127.0.0.1:8080/ >/dev/null || exit 1
