#!/bin/bash
# openchamber-v2/version.sh
# Version detection for OpenChamber v2 (OpenCode v2 branch).
#
# The v2 line has no semver tags yet — it lives on the
# `opencode-v2-refactoring` branch (published upstream as the rolling
# `v2-preview` pre-release). We track the branch HEAD commit and derive a
# CalVer-style version from that commit's committer time (UTC), so a new
# image is built every time the v2 branch advances and the version string
# stays human-readable instead of being a raw commit SHA.

set -euo pipefail

# Load shared functions (log_* helpers)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/../.functions/github.sh"

# Image specific configuration
# Last CI-built version under the time-based scheme. The previously built
# commit fe5981a8… was committed at 2026-09-22T15:28:21Z → 2026.09.22.152821.
LAST_VERSION=2026.09.22.152821
OWNER="openchamber"
REPO="openchamber"
BRANCH="opencode-v2-refactoring"

# Query the HEAD commit SHA and committer date of a branch.
# Parameter: owner repo branch
# Output: "sha<tab>committer_date_iso"
query_branch_head() {
    local owner="$1"
    local repo="$2"
    local branch="$3"

    local curl_cmd="curl -fsSL"
    if [[ -n "${GITHUB_TOKEN:-}" ]]; then
        curl_cmd="curl -fsSL -H \"Authorization: Bearer ${GITHUB_TOKEN}\""
    fi

    eval "$curl_cmd" "https://api.github.com/repos/${owner}/${repo}/commits/${branch}" \
        | jq -r '"\(.sha)\t\(.commit.committer.date // "")"'
}

# Format an ISO timestamp into a version string YYYY.MM.DD.HHMMSS (UTC).
# Parameter: iso_date
format_version_date() {
    local iso_date="$1"

    # GNU date (Linux)
    if date -u -d "$iso_date" +%Y.%m.%d.%H%M%S >/dev/null 2>&1; then
        date -u -d "$iso_date" +%Y.%m.%d.%H%M%S
    # BSD date (macOS)
    elif date -j -f "%Y-%m-%dT%H:%M:%SZ" "$iso_date" +%Y.%m.%d.%H%M%S >/dev/null 2>&1; then
        date -j -f "%Y-%m-%dT%H:%M:%SZ" "$iso_date" +%Y.%m.%d.%H%M%S
    else
        log_error "无法解析提交时间: ${iso_date}"
        return 1
    fi
}

main() {
    log_info "Detecting new version for openchamber v2 (${OWNER}/${REPO}@${BRANCH})"

    local head_info head_sha commit_date
    head_info=$(query_branch_head "$OWNER" "$REPO" "$BRANCH") || {
        log_error "Failed to query branch head"
        echo "current_version="
        echo "should_build=false"
        echo "build_reason=query_failed"
        return 1
    }
    head_sha="${head_info%%$'\t'*}"
    commit_date="${head_info#*$'\t'}"

    # Sanity check: must be a full 40-hex commit SHA
    if ! [[ "$head_sha" =~ ^[0-9a-f]{40}$ ]]; then
        log_error "Unexpected branch head SHA: '${head_sha}'"
        echo "current_version="
        echo "should_build=false"
        echo "build_reason=bad_sha_format"
        return 1
    fi
    if [[ -z "$commit_date" ]]; then
        log_error "Missing committer date for ${head_sha}"
        echo "current_version="
        echo "should_build=false"
        echo "build_reason=missing_commit_date"
        return 1
    fi

    local current_version
    current_version=$(format_version_date "$commit_date") || {
        echo "current_version="
        echo "should_build=false"
        echo "build_reason=date_format_failed"
        return 1
    }

    log_info "opencode-v2-refactoring head: ${head_sha} (${commit_date}) → ${current_version}"

    echo "current_version=${current_version}"
    # The Dockerfile fetcher needs the exact commit ref; emit it separately
    # so the build pins the precise commit while the tag stays CalVer.
    echo "current_sha=${head_sha}"
    echo "last_version=${LAST_VERSION:-}"

    if [[ -z "$LAST_VERSION" ]] || [[ "$current_version" != "$LAST_VERSION" ]]; then
        echo "should_build=true"
    else
        echo "should_build=false"
    fi
}

main "$@"