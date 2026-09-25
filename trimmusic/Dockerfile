# syntax=docker/dockerfile:1
#
# 飞牛音乐（trim.music）独立镜像 —— 多阶段、双架构（linux/amd64 + linux/arm64）
#
#   应用本体：构建时从飞牛应用中心取指定版本的 .tpk，校验 MD5、AES-256-CFB 解密、解包
#   系统文件：mediasrv 是扫库/播放的硬依赖；x86 取官方 ISO 里的 TRIMFS.TGZ（只读约 490MB 即断流），
#             arm64 取 rock-5b 设备镜像
#   运行期  ：单个 Go 静态二进制（假 rpcbroker + 应用中心桩 + open-gateway 桩 + unix→TCP 反代 +
#             首次初始化 + 入口），镜像内不含 Python
#
# 依赖的服务（全部由上面的桩模拟）：
#   /run/trim_app_cgi/rpcbroker                    TRPC：7 个服务 + trimAccessStat + getAppAuthorizedDir
#   /run/com.trim.app.center.sock                  HTTP(auth-path) + TRPC
#   /var/run/trim_open_gateway_apiscope.socket     POST /api/v1/trimapp → {"data":{"paths":[...]}}
#   /var/run/mediasrv.socket                       真实 mediasrv（转码/元数据/流式播放）
#   /var/run/trim_music.socket                     音乐自身（HTTP over unix socket）
#
# 关键点：音乐目录必须用飞牛用户路径格式 /vol<卷>/<uid>/<共享名>，
#         否则应用判定只读（permission: ro）并反复要求"授权文件夹"。
#
# 构建：docker build --build-arg VERSION=<应用版本> .（CI 会自动传入 VERSION）

ARG VERSION=1.0.10

###############################################################################
# 阶段 1：Go 运行期二进制（原生编译 + 交叉产出）
###############################################################################
FROM --platform=$BUILDPLATFORM golang:alpine AS gobuild
ARG TARGETOS
ARG TARGETARCH
ENV GOPROXY=https://goproxy.cn,direct \
    CGO_ENABLED=0
WORKDIR /src
COPY go.mod go.sum ./
RUN go mod download
COPY main.go broker.go gateway_stub.go proxy.go passwd.go run.go ./
RUN GOOS=${TARGETOS} GOARCH=${TARGETARCH} \
        go build -trimpath -ldflags="-s -w" -o /out/trimmusic . \
 && /out/trimmusic mkpasswd --password 123456 | grep -q '^\$2a\$12\$'

###############################################################################
# 阶段 2：取应用本体（Python，跑在构建机上；按目标架构向云端要对应构建）
###############################################################################
FROM --platform=$BUILDPLATFORM python:3.12-slim AS app
ARG VERSION
ARG TARGETARCH
RUN apt-get update \
 && apt-get install -y --no-install-recommends ca-certificates \
 && rm -rf /var/lib/apt/lists/* \
 && pip install --no-cache-dir cryptography
COPY build/appcenter.py /src/appcenter.py
RUN python /src/appcenter.py --app-name trim.music --app-id 333 --bin trim-music \
        --version "${VERSION}" --arch "${TARGETARCH}" -o /app \
 && ls -la /app/payload | head

###############################################################################
# 阶段 3：取飞牛系统文件（mediasrv，扫库/播放必需）
###############################################################################
FROM --platform=$BUILDPLATFORM python:3.12-slim AS trimfs
ARG TARGETARCH
ARG TRIMFS_ISO=""
ARG TRIMFS_ARM_IMG=""
RUN apt-get update \
 && apt-get install -y --no-install-recommends ca-certificates btrfs-progs \
 && rm -rf /var/lib/apt/lists/*
COPY build/trimfs-iso.py build/trimfs-arm.py /src/
RUN case "${TARGETARCH}" in \
        amd64) set -- ; [ -n "${TRIMFS_ISO}" ] && set -- --iso "${TRIMFS_ISO}"; \
               python /src/trimfs-iso.py "$@" -o /fnos ;; \
        arm64) set -- ; [ -n "${TRIMFS_ARM_IMG}" ] && set -- --img "${TRIMFS_ARM_IMG}"; \
               python /src/trimfs-arm.py "$@" --device rock-5b -o /fnos ;; \
        *) echo "不支持的架构：${TARGETARCH}"; exit 1 ;; \
    esac \
 && test -x /fnos/usr/trim/bin/mediasrv \
 && du -sh /fnos

###############################################################################
# 阶段 4：运行时（Debian 12 bookworm，双架构）
###############################################################################
FROM debian:12-slim

ARG VERSION
ARG TARGETARCH
# arm64 的 libmali 变体必须与内核 mali.ko 匹配，选错 OpenCL 会静默失效：
#   Armbian current / Ubuntu-Rockchip 6.1 LTS -> g24p0（当前默认）
#   Armbian vendor 内核（6.1.x-vendor-rk35xx）/ 厂商 BSP -> g13p0
# 注意 g13p0 在 v1.9-1-20260312-bd33ee2 之后的上游 release 里已被移除，
# 若要用 g13p0 得固定到那个 tag 并同步改 SHA256。
ARG LIBMAli_DEB_URL=https://github.com/tsukumijima/libmali-rockchip/releases/download/v1.9-1-20260923-ec78b74/libmali-valhall-g610-g24p0-gbm_1.9-1_arm64.deb
ARG LIBMAli_DEB_SHA256=1432646b23750cedea0f19a276e6d19d6e620805bf5564b41efa575468cab0c4
LABEL org.opencontainers.image.title="fnOS trim.music (飞牛音乐)" \
      org.opencontainers.image.description="飞牛音乐独立部署镜像：应用本体取自飞牛应用中心，RPC/网关依赖由 Go 桩程序模拟" \
      org.opencontainers.image.version="${VERSION}" \
      org.opencontainers.image.source="https://github.com/tsic404/docker-images"

ENV DEBIAN_FRONTEND=noninteractive \
    LANG=C.UTF-8 \
    TZ=Asia/Shanghai \
    LD_LIBRARY_PATH=/usr/trim/lib/mediasrv/lib:/usr/trim/lib \
    MEDIA_DIRS=/vol1/1000/music \
    TRIM_PROXY_ADDR=:8006 \
    LOG_LEVEL=info

# DEBUG=1 或 LOG_LEVEL=debug 可打开逐请求的调试日志（默认只输出启动信息与错误）

# mediasrv / 飞牛 ffmpeg 的系统依赖 + libzmq5（音乐的 RPC 需要）+ sqlite3（seed 写库）
# GPU 驱动按架构装：Intel 的只有 x86 有
RUN sed -i 's/^Components: main$/Components: main contrib non-free non-free-firmware/' \
        /etc/apt/sources.list.d/debian.sources 2>/dev/null || true \
 && apt-get update \
 && apt-get install -y --no-install-recommends \
      libacl1 libbluray2 libbsd0 libcairo2 libffi8 libgmp10 libgnutls30 libhogweed6 \
      libicu72 libidn2-0 libjemalloc2 libmd0 libmp3lame0 libmpg123-0 libnettle8 \
      libnuma1 libogg0 libopenmpt0 libopus0 libp11-kit0 libpci3 libpixman-1-0 \
      libpng16-16 libssl3 libtasn1-6 libtheora0 libudev1 libudfread0 libunistring2 \
      libvorbis0a libvorbisenc2 libvorbisfile3 libvpx7 libwebp7 libwebpmux3 \
      libx11-6 libx264-164 libx265-199 libxau6 libxcb-render0 libxcb-shm0 libxcb1 \
      libxcb-dri2-0 libxcb-dri3-0 libxcb-glx0 libxcb-randr0 libxcb-sync1 \
      libxcb-present0 libxcb-xfixes0 libxshmfence1 libelf1 \
      libxdmcp6 libxext6 libxml2 libxrender1 libzvbi0 libstdc++6 libdrm2 \
      ocl-icd-libopencl1 \
      libva2 libva-drm2 vainfo \
      libzmq5 \
      fonts-dejavu-core fonts-wqy-microhei fontconfig tzdata ca-certificates \
      curl sqlite3 \
 && if [ "${TARGETARCH}" = "amd64" ]; then \
        apt-get install -y --no-install-recommends \
          intel-opencl-icd clinfo intel-media-va-driver i965-va-driver; \
    fi \
 && if [ "${TARGETARCH}" = "arm64" ]; then \
        # RK3588 的 OpenCL 由 ARM libmali 提供，Debian 仓库里没有这个包。\
        # 变体须与内核 mali.ko 匹配：Armbian current / Ubuntu-Rockchip 6.1 LTS 用\
        # g24p0（默认），vendor 内核 / 厂商 BSP 用 g13p0，改上面的 ARG 即可。\
        # 依赖 libc6/libdrm2/libgcc-s1/libstdc++6 上面已装好；包里的固件在容器里不生效\
        # （固件由宿主机内核加载），留着无害。\
        apt-get install -y --no-install-recommends curl \
        && curl -fsSL -o /tmp/libmali.deb "${LIBMAli_DEB_URL}" \
        && echo "${LIBMAli_DEB_SHA256}  /tmp/libmali.deb" | sha256sum -c - \
        && dpkg -i /tmp/libmali.deb \
        && rm -f /tmp/libmali.deb; \
    fi \
 && rm -rf /var/lib/apt/lists/*

# 飞牛系统文件（mediasrv + 自带 ffmpeg/lib + GPU 能力库）
COPY --from=trimfs /fnos/ /

# 应用本体 + 包元数据
COPY --from=app /app/payload/ /usr/local/apps/@appcenter/trim.music/
COPY --from=app /app/pkg/manifest /app/pkg/ICON.PNG /var/apps/trim.music/
COPY --from=app /app/pkg/config /app/pkg/cmd /app/pkg/wizard /var/apps/trim.music/

# 去掉登录页的「使用 NAS 登录」按钮：独立部署没有 NAS 可登，留着只会点出错误。
# 按钮由组件属性 showNasLogin 控制（默认 !0），把默认值改成 !1 即可；
# 用标识符通配，避免压缩后变量名变化导致补丁失效。
# 断言必须检查「确实替换过」——只断言无残留的话，一旦上游改了写法，sed 一次都不匹配
# 却依然构建成功，补丁静默失效。
RUN set -eux; \
    hit=0; \
    for f in /usr/local/apps/@appcenter/trim.music/static/assets/*.js; do \
        if grep -qE 'showNasLogin:[A-Za-z_$][A-Za-z0-9_$]*=!0' "$f"; then \
            sed -i -E 's/(showNasLogin:)([A-Za-z_$][A-Za-z0-9_$]*)=!0/\1\2=!1/g' "$f"; \
            hit=$((hit+1)); \
        fi; \
    done; \
    [ "$hit" -ge 1 ]; \
    ! grep -rlE 'showNasLogin:[A-Za-z_$][A-Za-z0-9_$]*=!0' /usr/local/apps/@appcenter/trim.music/static/assets/; \
    echo "已移除登录页的 NAS 登录按钮（$hit 个文件）"

COPY --from=gobuild /out/trimmusic /usr/trim/trimmusic
COPY seed-admin.sh /usr/trim/seed-admin.sh
RUN chmod +x /usr/trim/trimmusic /usr/trim/seed-admin.sh

# 官方 ISO 里 libhwinfo / libigputop 的 soname 是占位，软链由 ldconfig 生成
RUN printf '%s\n' /usr/trim/lib /usr/trim/lib/mediasrv/lib > /etc/ld.so.conf.d/fnos.conf \
 && ldconfig

# 自检：mediasrv / ffmpeg / 硬件加速驱动依赖必须齐全 + 口令哈希可用，否则构建失败
# 逐项检查而不是串起来，缺什么直接打出来（arm64 的 /usr/trim 内容与 x86 不同）
RUN set -eux; \
    for b in /usr/trim/bin/mediasrv /usr/trim/lib/mediasrv/ffmpeg; do \
        if [ ! -e "$b" ]; then echo "缺少文件: $b"; ls -la "$(dirname "$b")" || true; exit 1; fi; \
        if [ ! -x "$b" ]; then echo "不可执行: $b"; ls -la "$b"; exit 1; fi; \
        ldd "$b" | grep -q 'not found' && { echo "缺失依赖: $b"; ldd "$b" | grep 'not found'; exit 1; } || true; \
    done; \
    for d in /usr/trim/lib/mediasrv/lib/dri/*.so /usr/trim/lib/mediasrv/lib/libvulkan_*.so; do \
        [ -e "$d" ] || continue; \
        ldd "$d" | grep -q 'not found' && { echo "缺失依赖: $d"; ldd "$d" | grep 'not found'; exit 1; } || true; \
    done; \
    /usr/trim/trimmusic mkpasswd --password 123456 | grep -q '^\$2a\$12\$'; \
    echo "自检通过"

# 三个卷，各司其职（不要把整个 /vol1 声明为卷，否则会把媒体目录一起遮住）：
#   /vol1/1000/music                 媒体文件（飞牛用户路径格式 /vol<卷>/<uid>/<共享名>）
#   /vol1/@appmeta/trim.music        应用元数据（mediasrv.conf + 转码缓存）
#   /var/apps/trim.music             应用状态（var/db/music.db：用户、音乐库、曲目）
VOLUME ["/vol1/1000/music", "/vol1/@appmeta/trim.music", "/var/apps/trim.music"]
EXPOSE 8006

# arm64 的 OpenCL 说明（RK3588）：
#   RK3588 的 OpenCL 由 ARM libmali 提供，Debian 仓库里没有这个包，本镜像在
#   arm64 分支构建时用官方 release 的 .deb 装上（带 SHA256 校验，见 runtime 阶段的
#   LIBMAli_DEB_URL/SHA256）。变体必须与内核里的 mali.ko 匹配：
#     Armbian current / Ubuntu-Rockchip 6.1 LTS        -> g24p0（当前默认）
#     Armbian vendor 内核（6.1.x-vendor-rk35xx）/ 厂商 BSP -> g13p0
#   不匹配时 ffmpeg 会报 "Failed to get number of OpenCL platforms: -1001"，
#   只影响 HDR tonemap，不影响 rkmpp 解码。
#   包里的 /lib/firmware/mali_csffw.bin 在容器里不生效（固件由宿主机内核加载）。
#   若节点内核需要另一个变体又不想重构建，可从宿主机覆盖挂载（见 StatefulSet 注释）。

HEALTHCHECK --interval=30s --timeout=5s --start-period=90s --retries=3 \
    CMD curl -fsS -o /dev/null "http://127.0.0.1:${TRIM_PROXY_ADDR##*:}/music/login" || exit 1

ENTRYPOINT ["/usr/trim/trimmusic", "run"]
