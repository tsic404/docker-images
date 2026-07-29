FROM ubuntu:latest AS fetcher
ARG VERSION=develop
WORKDIR /workspace
RUN apt-get update && apt-get install -y git && rm -rf /var/lib/apt/lists/*
RUN git clone --branch ${VERSION} --depth=1 https://github.com/hsliuping/TradingAgents-CN.git .

FROM node:22-alpine AS build
ARG VERSION=develop

ENV NODE_ENV=production
WORKDIR /app/frontend

RUN corepack enable && corepack prepare yarn@1.22.22 --activate

COPY --from=fetcher /workspace/frontend/package.json /workspace/frontend/yarn.lock /workspace/frontend/.yarnrc ./

RUN yarn install --frozen-lockfile --production=false --network-timeout 300000

COPY --from=fetcher /workspace/frontend/ ./
COPY --from=fetcher /workspace/assets /app/frontend/public/assets
COPY --from=fetcher /workspace/docs /app/docs

RUN yarn vite build

FROM nginx:alpine AS runtime
ARG VERSION=develop

WORKDIR /usr/share/nginx/html

COPY --from=build /app/frontend/dist .
COPY --from=fetcher /workspace/docker/nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]
