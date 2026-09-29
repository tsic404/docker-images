#!/bin/bash
# jellyplex-watched/version.sh
#
# 版本语义：镜像构建的是 fork tsic404/JellyPlex-Watched（比上游 luigi311 多飞牛影视
# TrimMedia 支持）。该仓库没有 tag、也没有 release，只有 main 分支，所以版本号取
# main 头 commit 的完整 sha，形如 main-<sha40>：
#   - main 一动版本号就变，CI 即重建；
#   - 版本号本身就是可用的 git ref，镜像内容与版本号一一对应（可复现）。
#
# 输出（供 CI 写入 $GITHUB_OUTPUT）：
#   current_version / last_version / should_build / build_reason
#
# 查不到时输出 last_version 并 return 1：CI 的这一步会失败，不会拿着空 VERSION 去构建。

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/../.functions/utils.sh"

# 新项目：LAST_VERSION 置空，首次 CI 检测到版本即构建（构建成功后由 CI 写回）
LAST_VERSION=""
OWNER="tsic404"
REPO="JellyPlex-Watched"
BRANCH="main"
API="https://api.github.com"

# 取分支头 commit 的完整 sha（公开仓库，token 仅用于提高速率限制）
query_head_sha() {
    local headers=(-H 'Accept: application/vnd.github.sha')
    if [[ -n "${GITHUB_TOKEN:-}" ]]; then
        headers+=(-H "Authorization: Bearer ${GITHUB_TOKEN}")
    fi
    curl -fsS "${headers[@]}" "${API}/repos/${OWNER}/${REPO}/commits/${BRANCH}"
}

emit() {
    echo "current_version=$1"
    echo "last_version=${LAST_VERSION}"
    echo "should_build=$2"
    echo "build_reason=$3"
}

main() {
    log_info "检测 ${OWNER}/${REPO} 的新版本（当前记录：${LAST_VERSION:-未构建}）"

    local sha
    if ! sha=$(query_head_sha) || [[ ! "$sha" =~ ^[0-9a-f]{40}$ ]]; then
        log_error "查询 ${BRANCH} 分支头 commit 失败"
        emit "${LAST_VERSION}" false query_failed
        return 1
    fi

    local current_version="main-${sha}"

    if [[ "$current_version" == "$LAST_VERSION" ]]; then
        log_info "版本未变化：${current_version}，跳过构建"
        emit "$current_version" false unchanged
        return 0
    fi

    log_success "发现新版本：${current_version}（原 ${LAST_VERSION:-未构建}）"
    emit "$current_version" true new_version
}

main "$@"
