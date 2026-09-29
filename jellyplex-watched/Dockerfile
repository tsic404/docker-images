# syntax=docker/dockerfile:1
#
# JellyPlex-Watched —— 在 jellyfin / plex / emby / 飞牛影视(TrimMedia) 之间同步观看记录
#
# 上游参考：Dockerfile.slim（ghcr.io/astral-sh/uv:bookworm-slim + uv sync 两段装依赖）
# 本仓库统一改成 fetcher 两阶段：源码在构建阶段 git clone，运行阶段 COPY --from=fetcher，
# 构建上下文里没有源码。
#
# 与上游的差异：
#   1. 源码取 fork tsic404/JellyPlex-Watched（比上游 luigi311 多飞牛影视支持），
#      按版本号（main 头 commit 的 sha）取，镜像内容与版本号一一对应；
#   2. 运行阶段用 python:3.13-slim-bookworm + pin 住的 uv 二进制，而不是 uv 镜像自带的
#      「uv 管理的 python 下载」：镜像内已有 3.13（满足 requires-python >=3.12），uv 不会再下一份；
#   3. 上游 `RUN --mount=type=bind,source=uv.lock,...` 改成从 fetcher 阶段 COPY 锁文件，
#      「先装依赖、后 COPY 源码」的缓存分层与其余 step 与上游保持一致。

ARG VERSION=main

###############################################################################
# 阶段 1：fetcher —— 取源码
###############################################################################
# 纯 git 操作，与目标架构无关，钉在构建机上跑，免得双架构各 clone 一遍（arm64 还是 QEMU 模拟）
FROM --platform=$BUILDPLATFORM ubuntu:latest AS fetcher
ARG VERSION
WORKDIR /workspace
RUN apt-get update && apt-get install -y --no-install-recommends git ca-certificates \
    && rm -rf /var/lib/apt/lists/*
# VERSION 两种形态：
#   main-<sha40>   CI 传入（见 version.sh），按 commit 精确取出
#   main           缺省值，取构建时 main 的头提交（不可复现，仅供本地手工构建）
RUN set -eux; \
    ref="${VERSION}"; \
    case "${VERSION}" in main-*) ref="${VERSION#main-}" ;; esac; \
    git init -q /workspace/jellyplex-watched; \
    cd /workspace/jellyplex-watched; \
    git remote add origin https://github.com/tsic404/JellyPlex-Watched.git; \
    git fetch -q --depth=1 origin "${ref}"; \
    git checkout -q FETCH_HEAD; \
    git --no-pager log -1 --format='source: %H %s'; \
    rm -rf .git test .github .vscode; \
    test -f main.py; test -f entrypoint.sh; test -f uv.lock; test -f pyproject.toml; test -f .python-version

###############################################################################
# 阶段 2：运行阶段
###############################################################################
FROM python:3.13-slim-bookworm
ARG VERSION

# uv 用来按 uv.lock 装依赖；版本需能读当前 lock（revision=3），且与镜像同代 glibc。
# 升级 fork 的 uv.lock 后若 CI 报锁文件版本不支持，改这里即可。
COPY --from=ghcr.io/astral-sh/uv:0.12.18 /uv /bin/uv

LABEL org.opencontainers.image.title="JellyPlex-Watched" \
      org.opencontainers.image.description="Sync watched status between jellyfin, plex, emby and 飞牛影视 locally" \
      org.opencontainers.image.version="${VERSION}" \
      org.opencontainers.image.source="https://github.com/tsic404/docker-images"

# PUID/PGID 决定容器内进程的身份（entrypoint.sh 在 root 下据此建用户并 gosu 降权）；
# YAML_FILE 是配置文件路径，entrypoint 会把 /app/sample.config.yaml 拷到同目录作模板。
ENV PUID=1000 \
    PGID=1000 \
    YAML_FILE=/app/config/config.yaml \
    PATH="/app/.venv/bin:$PATH" \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_CACHE_DIR=/tmp/.cache/uv \
    PYTHONUNBUFFERED=1

# tini 做 init（entrypoint 是 ENTRYPOINT 的第一环）、gosu 降权、dos2unix 处理换行符、
# passwd 提供 entrypoint 要用的 useradd/groupadd。
RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates \
        dos2unix \
        gosu \
        passwd \
        tini \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 先只装依赖，源码留到下一步 COPY，依赖层才能被缓存
# （等价于上游的 RUN --mount=type=bind,source=uv.lock,...，只是来源换成 fetcher）
COPY --from=fetcher \
    /workspace/jellyplex-watched/pyproject.toml \
    /workspace/jellyplex-watched/uv.lock \
    /workspace/jellyplex-watched/.python-version \
    /app/
RUN --mount=type=cache,target=/tmp/.cache/uv \
    uv sync --frozen --no-install-project --no-dev

# 源码（fetcher 里已剔掉 .git / test / .github / .vscode）
COPY --from=fetcher /workspace/jellyplex-watched/ /app/
RUN --mount=type=cache,target=/tmp/.cache/uv \
    uv sync --frozen --no-dev

RUN chmod +x /app/entrypoint.sh && dos2unix /app/entrypoint.sh

# 配置与状态都不进镜像，运行时挂载：
#   /app/config/config.yaml      配置（YAML_FILE 指向它；entrypoint 会往同目录写 sample.config.yaml）
#   /app/log.log  /app/mark.log  默认日志与同步标记文件（相对 CWD=/app，可在 YAML 里改到别处）
# 挂载文件的属主需要与 PUID/PGID 匹配（config.yaml 权限 0600 时尤其如此）。
ENTRYPOINT ["/bin/tini", "--", "/app/entrypoint.sh"]
CMD ["python", "-u", "main.py"]
