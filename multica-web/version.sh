#!/bin/bash
# multica/version.sh
# 使用公共函数库，但自己决定过滤规则

set -euo pipefail

# 加载公共函数
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/../.functions/github.sh"
source "${SCRIPT_DIR}/../.functions/version.sh"

# 镜像特定配置
LAST_VERSION=v0.2.16
OWNER="multica-ai"
REPO="multica"
DAYS_BEFORE=0

# multica特定的tag过滤函数
# multica使用v前缀的语义化版本，但可能有不同的规则
filter_multica_tags() {
    local tags_json="$1"

    echo "$tags_json" | jq '
      map(select(
        .name | test("^v[0-9]+\\.[0-9]+\\.[0-9]+$")
      ))
    '
}

main() {
    log_info "检测 $OWNER/$REPO 的新版本"

    local all_tags
    all_tags=$(query_github_tags "$OWNER" "$REPO") || {
        log_error "查询GitHub tags失败"
        echo "current_version="
        echo "should_build=false"
        echo "build_reason=query_failed"
        return 1
    }

    local filtered_tags
    filtered_tags=$(filter_multica_tags "$all_tags")

    local cutoff_timestamp
    cutoff_timestamp=$(days_ago_timestamp "$DAYS_BEFORE") || {
        log_error "计算截止时间失败"
        echo "current_version="
        echo "should_build=false"
        echo "build_reason=date_calc_failed"
        return 1
    }

    local stable_tags
    stable_tags=$(filter_tags_before_date "$filtered_tags" "$cutoff_timestamp")

    local current_version
    current_version=$(get_latest_tag "$stable_tags")

    if [[ -z "$current_version" ]]; then
        log_warning "未找到符合条件的稳定版本（${DAYS_BEFORE}天前）"
        echo "current_version="
        echo "should_build=false"
        echo "build_reason=no_stable_version"
        return 0
    fi

    echo "current_version=${current_version}"
    echo "last_version=${LAST_VERSION}"

}

# 运行主函数
main "$@"
