# Сайт: сборка фронта и Caddy, который раздаёт её и проксирует /api.
FROM node:24-alpine AS build
WORKDIR /src
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
# Страница и API — один домен: запросы идут на /api того же сайта.
ENV REACT_APP_API_URL=/api \
    GENERATE_SOURCEMAP=false
RUN npm run build

FROM caddy:2-alpine
COPY deploy/Caddyfile /etc/caddy/Caddyfile
COPY --from=build /src/build /srv
