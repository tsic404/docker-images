# Builder stage: clone source and download camoufox binary
FROM ubuntu:latest AS builder

# Combined version format: {camofox-browser-tag}_{camoufox-tag}
ARG VERSION=v1.9.1_v135.0.1-beta.24

WORKDIR /workspace

# Install build dependencies
RUN apt-get update && apt-get install -y \
    git \
    curl \
    unzip \
    ca-certificates \
    locales \
    && rm -rf /var/lib/apt/lists/* \
    && sed -i '/en_US.UTF-8/s/^# //g' /etc/locale.gen \
    && locale-gen

ENV LANG=en_US.UTF-8
ENV LANGUAGE=en_US:en
ENV LC_ALL=en_US.UTF-8

# Parse combined version and extract individual versions
# VERSION format: v1.9.1_v135.0.1-beta.24
RUN set -eux && \
    CAMOFOX_BROWSER_VERSION="${VERSION%%_*}" && \
    CAMOUFOX_VERSION="${VERSION##*_}" && \
    echo "CAMOFOX_BROWSER_VERSION=${CAMOFOX_BROWSER_VERSION}" >> /tmp/versions && \
    echo "CAMOUFOX_VERSION=${CAMOUFOX_VERSION}" >> /tmp/versions

# Clone camofox-browser repository
RUN set -eux && \
    . /tmp/versions && \
    git clone --branch ${CAMOFOX_BROWSER_VERSION} --depth=1 \
        https://github.com/jo-inc/camofox-browser.git camofox-browser

# Download camoufox browser binary
# Camoufox tag format: v135.0.1-beta.24
# Download URL: https://github.com/daijro/camoufox/releases/download/{tag}/camoufox-{version}-lin.{arch}.zip
RUN set -eux && \
    . /tmp/versions && \
    # Determine architecture using uname
    UNAME_ARCH="$(uname -m)" && \
    case "${UNAME_ARCH}" in \
        x86_64) ARCH="x86_64" ;; \
        aarch64) ARCH="arm64" ;; \
        *) echo "Unsupported architecture: ${UNAME_ARCH}" && exit 1 ;; \
    esac && \
    # Extract version string from tag (remove leading 'v')
    CAMOUFOX_VER="${CAMOUFOX_VERSION#v}" && \
    DOWNLOAD_URL="https://github.com/daijro/camoufox/releases/download/${CAMOUFOX_VERSION}/camoufox-${CAMOUFOX_VER}-lin.${ARCH}.zip" && \
    echo "Downloading camoufox from: ${DOWNLOAD_URL}" && \
    mkdir -p /workspace/camoufox && \
    curl -fsSL "${DOWNLOAD_URL}" -o /workspace/camoufox/camoufox.zip && \
    unzip -q /workspace/camoufox/camoufox.zip -d /workspace/camoufox && \
    chmod -R 755 /workspace/camoufox && \
    rm /workspace/camoufox/camoufox.zip && \
    test -f /workspace/camoufox/camoufox-bin && echo "Camoufox installed successfully"

# yt-dlp is installed and verified by the enabled youtube plugin hook below
# (plugins/youtube/post-install.sh, pinned version + sha256), matching upstream.

# Runtime stage
FROM node:22-trixie-slim AS camofox-browser

# Combined version format: {camofox-browser-tag}_{camoufox-tag}
ARG VERSION=v1.9.1_v135.0.1-beta.24

# Pinned yt-dlp version + SHA256 (mirrors upstream v1.15.0)
# Consumed by plugins/youtube/post-install.sh via install-plugin-deps.sh below
ARG YT_DLP_VERSION=2026.08.19
ARG YT_DLP_SHA256=1fa6733c37ea6fb51c99ad8fe785e7b7e5f3246c9b980230329d4fb72ed8d4d6

# Install dependencies for Camoufox (Firefox-based)
RUN apt-get update && apt-get install -y \
    # Firefox dependencies
    libgtk-3-0 \
    libdbus-glib-1-2 \
    libxt6 \
    libasound2 \
    libx11-xcb1 \
    libxcomposite1 \
    libxcursor1 \
    libxdamage1 \
    libxfixes3 \
    libxi6 \
    libxrandr2 \
    libxrender1 \
    libxss1 \
    libxtst6 \
    # Mesa OpenGL/EGL for WebGL support (software rendering via llvmpipe)
    # Without these, Firefox cannot create WebGL contexts — a major bot detection signal
    libegl1 \
    libgl1-mesa-dri \
    libgbm1 \
    # Xvfb virtual display — runs Camoufox as if on a real desktop (better anti-detection)
    xvfb \
    # Fonts
    fonts-liberation \
    fonts-noto-color-emoji \
    fontconfig \
    # Utils
    ca-certificates \
    curl \
    unzip \
    # yt-dlp runtime dependency
    python3-minimal \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy package.json, lockfile, and scripts first for better Docker caching
COPY --from=builder /workspace/camofox-browser/package.json ./
COPY --from=builder /workspace/camofox-browser/package-lock.json ./
COPY --from=builder /workspace/camofox-browser/scripts/ ./scripts/
# better-sqlite3 has no prebuild for this node:22-trixie-slim combination, so npm ci
# falls back to node-gyp rebuild, which fails with "not found: make". Install a
# toolchain for the build and purge it in the same layer so it does not land in
# the image.
RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential python3 \
    && npm ci --omit=dev \
    && apt-get purge -y --auto-remove build-essential \
    && rm -rf /var/lib/apt/lists/*

# Copy application source
COPY --from=builder /workspace/camofox-browser/server.js ./
COPY --from=builder /workspace/camofox-browser/camofox.config.json ./
# lib/ and mcp/ must BOTH ship: plugins/persistence/index.js imports
# ../../lib/persistence.js and ../../lib/cookies.js; vnc imports lib/auth.js and
# lib/tmp-cleanup.js; youtube imports lib/request-utils.js. lib/cookies.js is a
# compatibility re-export from ../mcp/lib/cookies.mjs, so mcp/ must ship even
# though the MCP server itself is not run here. Without either, the persistence
# plugin dies at load with ERR_MODULE_NOT_FOUND, the server starts anyway,
# /health keeps reporting ok, and no profile is ever written — i.e. the
# container silently loses the durable-profile feature it exists to provide.
COPY --from=builder /workspace/camofox-browser/lib/ ./lib/
COPY --from=builder /workspace/camofox-browser/mcp/ ./mcp/
COPY --from=builder /workspace/camofox-browser/plugins/ ./plugins/
# v1.14.0 source's plugins/youtube/post-install.sh still downloads "latest"
# yt-dlp without verification; override with the v1.15.0 pinned + sha256-verified
# version (remove this COPY once LAST_VERSION reaches v1.15.0, the source then
# carries the pinned script itself).
COPY plugins/youtube/post-install.sh /app/plugins/youtube/post-install.sh
# Copy new files added in v1.9+
COPY --from=builder /workspace/camofox-browser/plugin.ts ./
COPY --from=builder /workspace/camofox-browser/plugin.js ./
COPY --from=builder /workspace/camofox-browser/tsconfig.json ./
COPY --from=builder /workspace/camofox-browser/openclaw.plugin.json ./

# Install camoufox browser binary
RUN mkdir -p /root/.cache/camoufox
COPY --from=builder /workspace/camoufox/ /root/.cache/camoufox/

# Create version.json for camoufox (matching upstream format)
# CAMOUFOX_VERSION format: v135.0.1-beta.24
# Need to extract version=135.0.1, release=beta.24
RUN set -eux && \
    CAMOUFOX_VERSION="${VERSION##*_}" && \
    # Remove 'v' prefix: v135.0.1-beta.24 → 135.0.1-beta.24
    CAMOUFOX_VER="${CAMOUFOX_VERSION#v}" && \
    # Split at '-': 135.0.1-beta.24 → version=135.0.1, release=beta.24
    CAMOUFOX_VERSION_NUM="${CAMOUFOX_VER%%-*}" && \
    CAMOUFOX_RELEASE="${CAMOUFOX_VER#*-}" && \
    echo "{\"version\":\"${CAMOUFOX_VERSION_NUM}\",\"release\":\"${CAMOUFOX_RELEASE}\"}" > /root/.cache/camoufox/version.json

# Run plugin dependency installation script
# youtube's post-install.sh installs and sha256-verifies the pinned yt-dlp
# (YT_DLP_VERSION / YT_DLP_SHA256 injected from the ARGs above)
RUN YT_DLP_VERSION=${YT_DLP_VERSION} YT_DLP_SHA256=${YT_DLP_SHA256} scripts/install-plugin-deps.sh

ENV NODE_ENV=production
ENV CAMOFOX_PORT=9377

EXPOSE 9377

CMD ["sh", "-c", "node --max-old-space-size=${MAX_OLD_SPACE_SIZE:-128} server.js"]

# Optional: rebuild plugin deps after adding third-party plugins
# Usage: docker build --target with-plugins -t camofox-browser .
FROM camofox-browser AS with-plugins
COPY --from=builder /workspace/camofox-browser/plugins/ ./plugins/
# Re-apply the pinned youtube post-install.sh override: the builder plugins/
# copy above restores the v1.14.0 unpinned script (remove once LAST_VERSION
# reaches v1.15.0, same rule as the camofox-browser stage).
COPY plugins/youtube/post-install.sh /app/plugins/youtube/post-install.sh
COPY --from=builder /workspace/camofox-browser/camofox.config.json ./
COPY --from=builder /workspace/camofox-browser/scripts/install-plugin-deps.sh /tmp/install-plugin-deps.sh
RUN /tmp/install-plugin-deps.sh && rm /tmp/install-plugin-deps.sh