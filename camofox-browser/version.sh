#!/bin/bash
# camofox-browser/version.sh
# Version detection for camofox-browser + camoufox combined
# Format: {camofox-browser-tag}_{camoufox-tag}

set -euo pipefail

# Load shared functions
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/../.functions/github.sh"
source "${SCRIPT_DIR}/../.functions/version.sh"

# Image specific configuration
LAST_VERSION=v1.8.0_v135.0.1-beta.24

# camofox-browser project
CAMOFOX_BROWSER_OWNER="jo-inc"
CAMOFOX_BROWSER_REPO="camofox-browser"

# camoufox browser binary
CAMOUFOX_OWNER="daijro"
CAMOUFOX_REPO="camoufox"

DAYS_BEFORE=0

# Filter camofox-browser tags (simple semver)
filter_camofox_browser_tags() {
    local tags_json="$1"
    echo "$tags_json" | jq '
      map(select(.name | test("^v[0-9]+\\.[0-9]+\\.[0-9]+$")))
    '
}

# Filter camoufox tags (v{version}-{release} format, exclude special tags like v146-hardware)
filter_camoufox_tags() {
    local tags_json="$1"
    echo "$tags_json" | jq '
      map(select(.name | test("^v[0-9]+\\.[0-9]+(\\.[0-9]+)?-[a-z]+\\.[0-9]+$")))
    '
}

# Parse combined version string
# Input: v1.6.0+v135.0.1-beta.24
# Output: camofox_browser_version=v1.6.0, camoufox_version=v135.0.1-beta.24
parse_combined_version() {
    local combined="$1"
    local camofox_browser_version="${combined%%+*}"
    local camoufox_version="${combined##*+}"
    echo "camofox_browser_version=${camofox_browser_version}"
    echo "camoufox_version=${camoufox_version}"
}

main() {
    log_info "Detecting new versions for camofox-browser + camoufox"

    # Query camofox-browser tags
    local camofox_browser_tags
    camofox_browser_tags=$(query_github_tags "$CAMOFOX_BROWSER_OWNER" "$CAMOFOX_BROWSER_REPO") || {
        log_error "Failed to query camofox-browser tags"
        echo "current_version="
        echo "should_build=false"
        echo "build_reason=query_failed"
        return 1
    }

    local filtered_camofox_browser_tags
    filtered_camofox_browser_tags=$(filter_camofox_browser_tags "$camofox_browser_tags")

    # Query camoufox tags
    local camoufox_tags
    camoufox_tags=$(query_github_tags "$CAMOUFOX_OWNER" "$CAMOUFOX_REPO") || {
        log_error "Failed to query camoufox tags"
        echo "current_version="
        echo "should_build=false"
        echo "build_reason=query_failed"
        return 1
    }

    local filtered_camoufox_tags
    filtered_camoufox_tags=$(filter_camoufox_tags "$camoufox_tags")

    # Calculate cutoff timestamp
    local cutoff_timestamp
    cutoff_timestamp=$(days_ago_timestamp "$DAYS_BEFORE") || {
        log_error "Failed to calculate cutoff timestamp"
        echo "current_version="
        echo "should_build=false"
        echo "build_reason=date_calc_failed"
        return 1
    }

    # Filter stable tags
    local stable_camofox_browser_tags
    stable_camofox_browser_tags=$(filter_tags_before_date "$filtered_camofox_browser_tags" "$cutoff_timestamp")

    local stable_camoufox_tags
    stable_camoufox_tags=$(filter_tags_before_date "$filtered_camoufox_tags" "$cutoff_timestamp")

    # Get latest versions
    local camofox_browser_version
    camofox_browser_version=$(get_latest_tag "$stable_camofox_browser_tags")

    local camoufox_version
    camoufox_version=$(get_latest_tag "$stable_camoufox_tags")

    if [[ -z "$camofox_browser_version" ]]; then
        log_warning "No stable camofox-browser version found"
        echo "current_version="
        echo "should_build=false"
        echo "build_reason=no_camofox_browser_version"
        return 0
    fi

    if [[ -z "$camoufox_version" ]]; then
        log_warning "No stable camoufox version found"
        echo "current_version="
        echo "should_build=false"
        echo "build_reason=no_camoufox_version"
        return 0
    fi

    # Combine versions (use _ separator, + is not allowed in Docker tags)
    local current_version="${camofox_browser_version}_${camoufox_version}"

    log_info "camofox-browser: ${camofox_browser_version}"
    log_info "camoufox: ${camoufox_version}"
    log_info "combined: ${current_version}"

    echo "current_version=${current_version}"
    echo "last_version=${LAST_VERSION}"
    echo "camofox_browser_version=${camofox_browser_version}"
    echo "camoufox_version=${camoufox_version}"
}

main "$@"
