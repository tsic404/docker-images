#!/bin/bash
# homeassistant/version.sh
# 使用公共函数库，但自己决定过滤规则

set -euo pipefail

# 加载公共函数
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/../.functions/github.sh"
source "${SCRIPT_DIR}/../.functions/version.sh"

# 镜像特定配置
LAST_VERSION=2026.4.2
OWNER="home-assistant"
REPO="core"
DAYS_BEFORE=3

# 主逻辑 - 每个项目自己决定如何过滤和选择版本
main() {

    local all_tags
    all_tags=$(query_github_tags "$OWNER" "$REPO") || {
        log_error "查询GitHub tags失败"
        echo "current_version="
        echo "should_build=false"
        return 1
    }

    local semver_tags
    semver_tags=$(filter_semver_tags "$all_tags")

    local cutoff_timestamp
    cutoff_timestamp=$(days_ago_timestamp "$DAYS_BEFORE") || {
        log_error "计算截止时间失败"
        echo "current_version="
        echo "should_build=false"
        return 1
    }

    local stable_tags
    stable_tags=$(filter_tags_before_date "$semver_tags" "$cutoff_timestamp")

    local current_version
    current_version=$(get_latest_tag "$stable_tags")

    if [[ -z "$current_version" ]]; then
        log_warning "未找到符合条件的稳定版本（${DAYS_BEFORE}天前）"
        echo "current_version="
        echo "should_build=false"
        return 0
    fi

    echo "current_version=${current_version}"
    echo "last_version=${LAST_VERSION}"
}

# 运行主函数
main "$@"