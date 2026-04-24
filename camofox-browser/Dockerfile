# Builder stage: clone source and download camoufox binary
FROM ubuntu:latest AS builder

# Combined version format: {camofox-browser-tag}_{camoufox-tag}
ARG VERSION=v1.6.0_v135.0.1-beta.24

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
# VERSION format: v1.6.0_v135.0.1-beta.24
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

# Runtime stage
FROM node:20-slim AS camofox-browser

# Combined version format: {camofox-browser-tag}_{camoufox-tag}
ARG VERSION=v1.6.0_v135.0.1-beta.24

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
    libegl1-mesa \
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
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy package.json and install dependencies
COPY --from=builder /workspace/camofox-browser/package.json ./
RUN npm install --production

# Copy application source
COPY --from=builder /workspace/camofox-browser/server.js ./
COPY --from=builder /workspace/camofox-browser/camofox.config.json ./
COPY --from=builder /workspace/camofox-browser/lib/ ./lib/
COPY --from=builder /workspace/camofox-browser/plugins/ ./plugins/
COPY --from=builder /workspace/camofox-browser/scripts/ ./scripts/

# Install camoufox browser binary
RUN mkdir -p /root/.cache/camoufox
COPY --from=builder /workspace/camoufox/ /root/.cache/camoufox/

# Create version.json for camoufox
RUN set -eux && \
    CAMOUFOX_VERSION="${VERSION##*_}" && \
    CAMOUFOX_VER="${CAMOUFOX_VERSION#v}" && \
    echo "{\"version\":\"${CAMOUFOX_VER}\",\"release\":\"${CAMOUFOX_VERSION}\"}" > /root/.cache/camoufox/version.json

COPY --from=builder /workspace/camofox-browser/scripts/install-plugin-deps.sh /tmp/install-plugin-deps.sh
RUN /tmp/install-plugin-deps.sh && rm /tmp/install-plugin-deps.sh

ENV NODE_ENV=production
ENV CAMOFOX_PORT=9377

EXPOSE 9377

CMD ["sh", "-c", "node --max-old-space-size=${MAX_OLD_SPACE_SIZE:-128} server.js"]