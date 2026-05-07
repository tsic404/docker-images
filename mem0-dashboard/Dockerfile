FROM ubuntu:latest as fetcher
ARG VERSION=main
WORKDIR /workspace
RUN apt-get update && apt-get install -y git patch curl
RUN git clone --branch ${VERSION} --depth=1 https://github.com/mem0ai/mem0.git

# Base stage (from upstream)
FROM node:20-alpine AS base
RUN apk add --no-cache libc6-compat
WORKDIR /app

# Dependencies stage (adapted from upstream deps stage)
FROM base AS deps
# Copy dependency files from fetcher
COPY --from=fetcher /workspace/mem0/server/dashboard/package.json ./
COPY --from=fetcher /workspace/mem0/server/dashboard/pnpm-lock.yaml ./
# Install dependencies with pnpm (simplified - upstream has adaptive logic but only pnpm-lock.yaml exists)
RUN corepack enable pnpm && pnpm install --frozen-lockfile

# Builder stage (adapted from upstream builder stage)
FROM base AS builder
WORKDIR /app
# Copy node_modules from deps stage
COPY --from=deps /app/node_modules ./node_modules
# Copy application source from fetcher
COPY --from=fetcher /workspace/mem0/server/dashboard/ .

# Build-time env placeholders (replaced at runtime by entrypoint.sh)
ENV NEXT_TELEMETRY_DISABLED=1
ENV NEXT_PUBLIC_API_URL=NEXT_PUBLIC_API_URL
ENV NEXT_PUBLIC_INSTANCE_NAME=NEXT_PUBLIC_INSTANCE_NAME

RUN npm run build

# Production stage (adapted from upstream runner stage)
FROM base AS runner
WORKDIR /app

ENV NODE_ENV=production
ENV NEXT_TELEMETRY_DISABLED=1

RUN addgroup --system --gid 1001 nodejs && \
    adduser --system --uid 1001 nextjs

# Copy built artifacts from builder
COPY --from=builder /app/public ./public
COPY --from=builder --chown=nextjs:nodejs /app/.next/standalone ./
COPY --from=builder --chown=nextjs:nodejs /app/.next/static ./.next/static

# Copy entrypoint from fetcher
COPY --from=fetcher /workspace/mem0/server/dashboard/entrypoint.sh /home/nextjs/entrypoint.sh
RUN chmod +x /home/nextjs/entrypoint.sh

USER nextjs

EXPOSE 3000
ENV PORT=3000
ENV HOSTNAME="0.0.0.0"

ENTRYPOINT ["/home/nextjs/entrypoint.sh"]
CMD ["node", "server.js"]
