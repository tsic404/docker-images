# Fetcher stage: download adnanh/webhook official release binary (Go single-file, per-arch)
FROM ubuntu:latest AS fetcher
ARG VERSION=2.8.3
WORKDIR /workspace
RUN apt-get update && apt-get install -y curl ca-certificates && rm -rf /var/lib/apt/lists/*
# adnanh/webhook 2.8.3 official release binary (arch selected via uname at build time):
#   amd64: https://github.com/adnanh/webhook/releases/download/2.8.3/webhook-linux-amd64.tar.gz
#   arm64: https://github.com/adnanh/webhook/releases/download/2.8.3/webhook-linux-arm64.tar.gz
# 解压后安装到 /usr/local/bin/webhook
RUN set -eux && \
    UNAME_ARCH="$(uname -m)" && \
    case "${UNAME_ARCH}" in \
        x86_64) ARCH="amd64" ;; \
        aarch64) ARCH="arm64" ;; \
        *) echo "Unsupported architecture: ${UNAME_ARCH}" && exit 1 ;; \
    esac && \
    curl -fsSL "https://github.com/adnanh/webhook/releases/download/${VERSION}/webhook-linux-${ARCH}.tar.gz" -o webhook.tar.gz && \
    tar -xzf webhook.tar.gz && \
    rm webhook.tar.gz && \
    mv webhook-linux-${ARCH}/webhook /workspace/webhook && \
    chmod +x /workspace/webhook && \
    test -x /workspace/webhook

# Runtime stage: python + curl/jq 运行时（供同步脚本使用）
FROM python:3.12-slim
ARG VERSION=2.8.3

RUN apt-get update && apt-get install -y --no-install-recommends curl jq ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY --from=fetcher /workspace/webhook /usr/local/bin/webhook

# 非 root 运行：创建 uid 1000 webhook 用户（参考 almir/docker-webhook）
RUN groupadd --gid 1000 webhook \
    && useradd --uid 1000 --gid webhook --shell /usr/sbin/nologin -d /etc/webhook --create-home webhook

# hooks.json 与同步脚本不封装进镜像，运行时通过 volume 挂载（-v <dir>:/etc/webhook）
WORKDIR /etc/webhook

USER webhook

EXPOSE 9000
CMD ["/usr/local/bin/webhook", "-verbose", "-hooks=/etc/webhook/hooks.json", "-hotreload"]
