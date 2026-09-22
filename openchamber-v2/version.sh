#!/bin/bash
# openchamber-v2/version.sh
# Version detection for OpenChamber v2 (OpenCode v2 branch).
#
# The v2 line has no semver tags yet — it lives on the
# `opencode-v2-refactoring` branch (published upstream as the rolling
# `v2-preview` pre-release). We track the branch HEAD commit SHA, so a new
# image is built every time the v2 branch advances.

set -euo pipefail

# Load shared functions (log_* helpers)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/../.functions/github.sh"

# Image specific configuration
# New project: LAST_VERSION empty → first CI run always builds
LAST_VERSION=fe5981a8bdde8afdd33c67b67ce2a89c6cddcad0
OWNER="openchamber"
REPO="openchamber"
BRANCH="opencode-v2-refactoring"

# Query the HEAD commit SHA of a branch.
# Parameter: owner repo branch
# Returns: full 40-hex commit SHA
query_branch_head_sha() {
    local owner="$1"
    local repo="$2"
    local branch="$3"

    local curl_cmd="curl -fsSL"
    if [[ -n "${GITHUB_TOKEN:-}" ]]; then
        curl_cmd="curl -fsSL -H \"Authorization: Bearer ${GITHUB_TOKEN}\""
    fi

    eval "$curl_cmd" "https://api.github.com/repos/${owner}/${repo}/commits/${branch}" \
        | jq -r '.sha // empty'
}

main() {
    log_info "Detecting new version for openchamber v2 (${OWNER}/${REPO}@${BRANCH})"

    local current_version
    current_version=$(query_branch_head_sha "$OWNER" "$REPO" "$BRANCH") || {
        log_error "Failed to query branch head SHA"
        echo "current_version="
        echo "should_build=false"
        echo "build_reason=query_failed"
        return 1
    }

    # Sanity check: must be a full 40-hex commit SHA
    if ! [[ "$current_version" =~ ^[0-9a-f]{40}$ ]]; then
        log_error "Unexpected branch head SHA: '${current_version}'"
        echo "current_version="
        echo "should_build=false"
        echo "build_reason=bad_sha_format"
        return 1
    fi

    log_info "opencode-v2-refactoring head: ${current_version}"

    echo "current_version=${current_version}"
    echo "last_version=${LAST_VERSION:-}"

    if [[ -z "$LAST_VERSION" ]] || [[ "$current_version" != "$LAST_VERSION" ]]; then
        echo "should_build=true"
    else
        echo "should_build=false"
    fi
}

main "$@"
