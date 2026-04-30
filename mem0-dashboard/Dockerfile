FROM ubuntu:latest as fetcher
ARG VERSION=main
WORKDIR /workspace
RUN apt-get update && apt-get install -y git patch curl
RUN git clone --branch ${VERSION} --depth=1 https://github.com/mem0ai/mem0.git

# Build stage
FROM node:20-alpine AS builder

RUN apk add --no-cache libc6-compat
WORKDIR /app

# Copy dependency files
COPY --from=fetcher /workspace/mem0/server/dashboard/package.json ./
COPY --from=fetcher /workspace/mem0/server/dashboard/pnpm-lock.yaml ./

# Install dependencies with pnpm
RUN corepack enable pnpm && pnpm install --frozen-lockfile

# Copy application source
COPY --from=fetcher /workspace/mem0/server/dashboard/ .

# Build-time env placeholders (replaced at runtime by entrypoint.sh)
ENV NEXT_TELEMETRY_DISABLED=1
ENV NEXT_PUBLIC_API_URL=NEXT_PUBLIC_API_URL
ENV NEXT_PUBLIC_INSTANCE_NAME=NEXT_PUBLIC_INSTANCE_NAME

RUN npm run build

# Production stage
FROM node:20-alpine AS runner

WORKDIR /app

ENV NODE_ENV=production
ENV NEXT_TELEMETRY_DISABLED=1

RUN addgroup --system --gid 1001 nodejs && \
    adduser --system --uid 1001 nextjs

# Copy built artifacts
COPY --from=builder /app/public ./public
COPY --from=builder --chown=nextjs:nodejs /app/.next/standalone ./
COPY --from=builder --chown=nextjs:nodejs /app/.next/static ./.next/static

# Copy entrypoint
COPY --from=fetcher /workspace/mem0/server/dashboard/entrypoint.sh /home/nextjs/entrypoint.sh
RUN chmod +x /home/nextjs/entrypoint.sh

USER nextjs

EXPOSE 3000

ENV PORT=3000
ENV HOSTNAME="0.0.0.0"

ENTRYPOINT ["/home/nextjs/entrypoint.sh"]
CMD ["node", "server.js"]
