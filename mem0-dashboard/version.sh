#!/bin/bash
# mem0-dashboard/version.sh
# Version detection for mem0 dashboard — shares the same repo and tags as mem0 server

set -euo pipefail

# Load shared functions
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/../.functions/github.sh"
source "${SCRIPT_DIR}/../.functions/version.sh"

# Image specific configuration
LAST_VERSION=v2.0.0
OWNER="mem0ai"
REPO="mem0"
DAYS_BEFORE=3

# mem0 uses v-prefixed semver tags
filter_mem0_tags() {
    local tags_json="$1"

    echo "$tags_json" | jq '
      map(select(
        .name | test("^v[0-9]+\\.[0-9]+\\.[0-9]+$")
      ))
    '
}

main() {
    log_info "Detecting new versions for $OWNER/$REPO (dashboard)"

    local all_tags
    all_tags=$(query_github_tags "$OWNER" "$REPO") || {
        log_error "Failed to query GitHub tags"
        echo "current_version="
        echo "should_build=false"
        echo "build_reason=query_failed"
        return 1
    }

    local filtered_tags
    filtered_tags=$(filter_mem0_tags "$all_tags")

    local cutoff_timestamp
    cutoff_timestamp=$(days_ago_timestamp "$DAYS_BEFORE") || {
        log_error "Failed to calculate cutoff timestamp"
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
        log_warning "No stable version found (${DAYS_BEFORE} days ago)"
        echo "current_version="
        echo "should_build=false"
        echo "build_reason=no_stable_version"
        return 0
    fi

    echo "current_version=${current_version}"
    echo "last_version=${LAST_VERSION}"
}

main "$@"
