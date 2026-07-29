#!/bin/bash
# tradingagents-frontend/version.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/../.functions/github.sh"
source "${SCRIPT_DIR}/../.functions/version.sh"

LAST_VERSION=v1.1.0
OWNER="hsliuping"
REPO="TradingAgents-CN"
DAYS_BEFORE=3

filter_tradingagents_frontend_tags() {
    local tags_json="$1"
    echo "$tags_json" | jq '
      map(select(
        .name | test("^v[0-9]+\\.[0-9]+\\.[0-9]+$")
      ))
    '
}

main() {
    log_info "检测 $OWNER/$REPO (frontend) 的新版本"

    local all_tags
    all_tags=$(query_github_tags "$OWNER" "$REPO") || {
        log_error "查询GitHub tags失败"
        echo "current_version="
        echo "last_version=${LAST_VERSION}"
        return 1
    }

    local filtered_tags
    filtered_tags=$(filter_tradingagents_frontend_tags "$all_tags")

    local cutoff_timestamp
    cutoff_timestamp=$(days_ago_timestamp "$DAYS_BEFORE") || {
        log_error "计算截止时间失败"
        echo "current_version="
        echo "last_version=${LAST_VERSION}"
        return 1
    }

    local stable_tags
    stable_tags=$(filter_tags_before_date "$filtered_tags" "$cutoff_timestamp")

    local stable_version
    stable_version=$(get_latest_tag "$stable_tags")

    local branches
    branches=$(query_github_branches "$OWNER" "$REPO") || {
        log_error "查询GitHub branches失败"
        echo "current_version="
        echo "last_version=${LAST_VERSION}"
        return 1
    }

    local version_branch
    version_branch=$(echo "$branches" | grep -E '^v[0-9]+\.[0-9]+' | sort -V | tail -1 || true)

    local current_version=""
    if [[ -n "$stable_version" ]] && [[ -n "$version_branch" ]]; then
        local stable_ver="${stable_version#v}"
        local branch_ver="${version_branch#v}"
        if compare_versions "$stable_ver" "$branch_ver" | grep -q "^1$"; then
            current_version="$stable_version"
        else
            current_version="$version_branch"
        fi
    elif [[ -n "$stable_version" ]]; then
        current_version="$stable_version"
    elif [[ -n "$version_branch" ]]; then
        current_version="$version_branch"
    fi

    if [[ -z "$current_version" ]]; then
        log_warning "未找到符合条件的版本"
        echo "current_version="
        echo "last_version=${LAST_VERSION}"
        return 0
    fi

    echo "current_version=${current_version}"
    echo "last_version=${LAST_VERSION}"
}

main "$@"
