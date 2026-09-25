#!/bin/bash
# trimmedia/version.sh
#
# 版本语义：镜像只跟随**影视应用本体**的版本（云端 trim.media 的 lastVersion，
# 形如 0.9.8-1，即 semver + 可选的 -修订号）。飞牛系统文件（mediasrv/ffmpeg）
# 取自官方镜像，不参与版本号 —— 否则系统小版本一动就要重建。
#
# 输出（供 CI 写入 $GITHUB_OUTPUT）：
#   current_version=<云端当前版本>
#   last_version=<上次构建的版本>
#   should_build=true|false
#   build_reason=...
#
# 只有确认「云端版本更新」才输出新版本；查不到 / 回退时保持 last_version，
# 避免把镜像打回旧版本（CI 是按 current != last 判断是否构建的）。

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/../.functions/utils.sh"

LAST_VERSION=0
APP_NAME="trim.media"
API="https://aps.fnnas.com/api/v1"
OS_VERSION="${TRIM_OS_VERSION:-1.2.0701}"
MACHINE_ID="${TRIM_MACHINE_ID:-0000000000000000000000000000000000000000}"

# 云端接口请求头即鉴权
cloud_post() {
    local path="$1" body="$2" platform="$3"
    curl -fsS -X POST "${API}${path}" \
        -H 'Content-Type: application/json' \
        -H "trim-machine-id: ${MACHINE_ID}" \
        -H "trim-os-version: ${OS_VERSION}" \
        -H "trim-platform: ${platform}" \
        -H "trim-timestamp: $(( $(date +%s) * 1000 ))" \
        -d "${body}"
}

# 取某平台可见的 trim.media 版本；失败时输出空串
query_app_version() {
    local platform="$1" resp
    resp=$(cloud_post "/app/list" '{}' "$platform") || return 1
    echo "$resp" | jq -r --arg n "$APP_NAME" \
        '.data.list[] | select(.appName == $n) | .lastVersion' | head -1
}

# 版本比较（GNU sort -V）：$1 > $2 返回 0
version_gt() {
    [[ "$1" == "$2" ]] && return 1
    [[ "$(printf '%s\n%s\n' "$1" "$2" | sort -V | tail -1)" == "$1" ]]
}

emit() {
    echo "current_version=$1"
    echo "last_version=${LAST_VERSION}"
    echo "should_build=$2"
    echo "build_reason=$3"
}

main() {
    log_info "检测 ${APP_NAME} 的新版本（当前记录：${LAST_VERSION}）"

    local v_x86 v_arm current
    if ! v_x86=$(query_app_version x86) || [[ -z "$v_x86" ]]; then
        log_error "查询云端 x86 版本失败"
        emit "${LAST_VERSION}" false query_failed
        return 1
    fi
    if ! v_arm=$(query_app_version arm) || [[ -z "$v_arm" ]]; then
        log_error "查询云端 arm 版本失败"
        emit "${LAST_VERSION}" false query_failed
        return 1
    fi

    # 两个架构的版本应当一致；不一致说明云端发布到一半，先不构建
    if [[ "$v_x86" != "$v_arm" ]]; then
        log_warning "x86=${v_x86} 与 arm=${v_arm} 版本不一致，跳过本次构建"
        emit "${LAST_VERSION}" false arch_version_mismatch
        return 0
    fi
    current="$v_x86"

    # 语义校验：MAJOR.MINOR.PATCH 或 MAJOR.MINOR.PATCH-REV
    if [[ ! "$current" =~ ^[0-9]+\.[0-9]+\.[0-9]+(-[0-9]+)?$ ]]; then
        log_error "云端返回了非预期的版本号：${current}"
        emit "${LAST_VERSION}" false bad_version_format
        return 1
    fi

    if version_gt "$current" "$LAST_VERSION"; then
        log_success "发现新版本：${current}（原 ${LAST_VERSION}）"
        emit "$current" true new_version
    elif [[ "$current" == "$LAST_VERSION" ]]; then
        log_info "版本未变化：${current}，跳过构建"
        emit "$current" false unchanged
    else
        log_warning "云端版本 ${current} 低于已构建的 ${LAST_VERSION}，跳过（不回退）"
        emit "${LAST_VERSION}" false downgrade_ignored
    fi
}

main "$@"
