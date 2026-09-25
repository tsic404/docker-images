# syntax=docker/dockerfile:1
#
# 飞牛影视（trim.media）独立镜像 —— 多阶段、双架构（linux/amd64 + linux/arm64）
#
#   应用本体：构建时从飞牛应用中心接口取指定版本的 .tpk，校验 MD5、AES-256-CFB 解密、解包
#   系统文件：x86 取官方 ISO 里的 TRIMFS.TGZ（只读约 490MB 即断流）；arm64 取 rock-5b 设备镜像
#   运行期  ：单个 Go 静态二进制（入口 run：假 rpcbroker + 真实 mediasrv + 首次初始化），
#             镜像内不含 Python
#
# 取包/取系统文件用 Python（构建期，不进最终镜像）；Go 部分在构建机架构上原生编译、
# 交叉产出目标架构二进制，所以**取包阶段不需要 QEMU**（arm64 运行时的 apt 安装仍需 binfmt/QEMU）。
#
# 构建：docker build --build-arg VERSION=<应用版本> .（CI 会自动传入 VERSION）

ARG VERSION=0.9.8-1

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
COPY main.go broker.go passwd.go run.go ./
RUN GOOS=${TARGETOS} GOARCH=${TARGETARCH} \
        go build -trimpath -ldflags="-s -w" -o /out/trimmedia . \
 && /out/trimmedia mkpasswd --secret t --password 123456 | grep -q '^\$argon2id\$v=19\$m=65536,t=3,p=1\$'

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
COPY build/patch-ui.py /src/patch-ui.py
RUN python /src/appcenter.py --version "${VERSION}" --arch "${TARGETARCH}" -o /app \
 && ls -la /app/payload | head

# 隐藏登录页的「使用 NAS 登录」按钮：独立部署没有 NAS 可登，留着只会点出「服务异常」。
# 实测**删除**该元素会让整个登录页渲染成「网络异常」（语法/接口/控制台均无异常），
# 因此改为保留元素 + style 隐藏。补丁锚定按钮独有的属性序列，断言唯一命中，
# 且不依赖压缩后的变量名（失败即构建失败，不会静默漏补）。
RUN python /src/patch-ui.py /app/payload/static/assets

###############################################################################
# 阶段 3：取飞牛系统文件（Python，跑在构建机上）
#   amd64 -> 官方 ISO 里的 TRIMFS.TGZ，HTTP Range 流式，取齐即断流（约 490MB）
#   arm64 -> 官方 ARM 设备镜像 rock-5b（GPT/ext4），btrfs restore 直接取 /usr/trim（无需 root/挂载）
###############################################################################
FROM --platform=$BUILDPLATFORM python:3.12-slim AS trimfs
ARG TARGETARCH
# 可选：指定系统文件来源（本地 ISO / ARM 设备镜像的路径或 URL）。
# 注意：留空自动发现时走官方镜像站的**明文 HTTP**，且上游未提供校验和；
#       对完整性有要求请显式传本地/自建镜像。
# 留空即自动发现官方最新版；内网镜像或离线构建时可以覆盖。
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
LABEL org.opencontainers.image.title="fnOS trim.media (飞牛影视)" \
      org.opencontainers.image.description="飞牛影视独立部署镜像：应用本体取自飞牛应用中心，飞牛 RPC 依赖由 Go 桩程序模拟" \
      org.opencontainers.image.version="${VERSION}" \
      org.opencontainers.image.source="https://github.com/tsic404/docker-images"

ENV DEBIAN_FRONTEND=noninteractive \
    LANG=C.UTF-8 \
    TZ=Asia/Shanghai \
    LD_LIBRARY_PATH=/usr/trim/lib/mediasrv/lib:/usr/trim/lib \
    MEDIA_DIRS=/vol1/1000/media \
    LOG_LEVEL=info

# DEBUG=1 或 LOG_LEVEL=debug 可打开逐请求的调试日志（默认只输出启动信息与错误）

# mediasrv / 飞牛 ffmpeg 的系统依赖（由 ldd + dpkg -S 在飞牛系统上枚举得到）
# 另加：libwebp7（trim-media 需要）、字体（字幕渲染）、VAAPI（硬解）
# GPU 相关驱动按架构装：Intel 的驱动只有 x86 有，arm64 跳过
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
      fonts-dejavu-core fonts-wqy-microhei fontconfig tzdata ca-certificates \
      curl sqlite3 \
 && if [ "${TARGETARCH}" = "amd64" ]; then \
        apt-get install -y --no-install-recommends \
          intel-opencl-icd clinfo intel-media-va-driver i965-va-driver; \
    fi \
 && rm -rf /var/lib/apt/lists/*

# 飞牛系统文件（mediasrv + 自带 ffmpeg/lib + GPU 能力库 + gpu_device_info.json）
COPY --from=trimfs /fnos/ /

# 应用本体 + 包元数据（对齐飞牛 /var/apps/<app> 布局）
COPY --from=app /app/payload/ /usr/local/apps/@appcenter/trim.media/
COPY --from=app /app/pkg/manifest /app/pkg/ICON.PNG /var/apps/trim.media/
COPY --from=app /app/pkg/config /app/pkg/cmd /app/pkg/wizard /var/apps/trim.media/

COPY --from=gobuild /out/trimmedia /usr/trim/trimmedia
COPY seed-admin.sh /usr/trim/seed-admin.sh
RUN chmod +x /usr/trim/trimmedia /usr/trim/seed-admin.sh

# 飞牛系统文件里的 soname 软链由安装时的 ldconfig 生成，这里补上：
#   /usr/trim/lib              libhwinfo.so.0 / libigputop.so.0 等在 ISO 里是 0 字节占位
#   /usr/trim/lib/mediasrv/lib arm64 的 librockchip_mpp.so.0 的 SONAME 是 .so.1、
#                              librga.so.2.1.0 的 SONAME 是 .so.2（文件名与 soname 不同名）
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
    /usr/trim/trimmedia mkpasswd --secret test --password 123456 | grep -q '^\$argon2id\$v=19\$m=65536,t=3,p=1\$'; \
    echo "自检通过"

# 三个卷，各司其职（不要把整个 /vol1 声明为卷，否则会把媒体目录一起遮住）：
#   /vol1/1000/media                 媒体文件（飞牛用户路径格式 /vol<卷>/<uid>/<共享名>）
#   /vol1/@appmeta/trim.media        应用元数据（mediasrv.conf + 转码缓存）
#   /vol1/mediadata                  应用状态（database/trimmedia.db：媒体库、条目、用户）
#
# 注意：声明为 VOLUME 的路径会被 Docker 自动建**匿名卷**，即使 -v 挂载了父目录 /vol1
# 也会被遮住。所以要用宿主目录持久化，必须**逐个显式挂载**，例如：
#   -v /mnt/nas/media:/vol1/1000/media
#   -v /mnt/nas/meta:/vol1/@appmeta/trim.media
#   -v /mnt/nas/data:/vol1/mediadata
VOLUME ["/vol1/mediadata", "/vol1/@appmeta/trim.media", "/vol1/1000/media"]
EXPOSE 8005

# 硬件转码（可选，Intel/AMD GPU）：必须同时给三样东西，缺一不可 ——
#   --device /dev/dri              设备节点（并放开 cgroup 权限）
#   -v /dev/dri:/dev/dri           整目录绑定，mediasrv 靠 /dev/dri/by-path 解析 card path，
#                                  只给 --device 不会带上 by-path 子目录，会报
#                                  "couldn't get card path" 然后退回软解
#   -v /sys:/sys:ro                sysfs（解析 /sys/class/drm/cardN 的设备信息）
# 再加 -e GPU_ENABLE=true 打开硬解（默认 false）。实测日志：
#   [info] gpu in working, device 'UHD Graphics 630', card_path '/dev/dri/card0'
#   [info] gpu enable: true, selected sequence: 1
#
# arm64（Rockchip RK3588 / rock-5b）走的是 **rkmpp**，不是 VAAPI，设备节点也不同：
#   --device /dev/mpp_service     MPP 编解码（librockchip_mpp，随 /usr/trim 一起进镜像）
#   --device /dev/rga             RGA 2D 加速（librga）
#   --device /dev/dri             Mali GPU / DRM
#   --device /dev/dma_heap        DMA-BUF 分配（部分内核必需）
# arm64 的 soname 与文件名不一致（librockchip_mpp.so.0 的 SONAME 是 .so.1、
# librga.so.2.1.0 的 SONAME 是 .so.2），已由上面的 ldconfig 补好软链；
# 构建期自检会对 dri/ 与 libvulkan_*.so 逐个 ldd，缺库直接构建失败。
# 注意 arm64 的 /usr/trim 里**没有** dri/（RK3588 走 rkmpp 而非 VAAPI），
# 循环对缺失目录是容忍的，不会因此报错。
# arm64 说明：已用官方 rock-5b 镜像（1.2.0302）解包核对过 /usr/trim 实际内容 ——
#   bin/mediasrv、lib/mediasrv/{ffmpeg,ffprobe} 均在（提取脚本已保证其非空且 755），
#   lib/mediasrv/lib/ 下有 librockchip_mpp.so.0 与 librga.so.2.1.0，无 dri/ 与 vainfo。
#   整条 arm64 构建尚未跑通（本地只验证了提取环节），首次 CI 构建仍建议留意。

HEALTHCHECK --interval=30s --timeout=5s --start-period=90s --retries=3 \
    CMD curl -fsS -o /dev/null "http://127.0.0.1:${TRIM_SERVICE_PORT:-8005}/" || exit 1

ENTRYPOINT ["/usr/trim/trimmedia", "run"]
