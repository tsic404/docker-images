#!/bin/bash
# .functions/version.sh
# 版本比较相关的公共函数库
# 只提供基础工具，不包含业务逻辑

set -euo pipefail

# 比较版本号
# 参数: version1 version2
# 返回: 0=相同, 1=version1>version2, 2=version1<version2
compare_versions() {
    local version1="$1"
    local version2="$2"
    
    if [[ "$version1" == "$version2" ]]; then
        return 0
    fi
    
    # 移除v前缀用于比较
    version1="${version1#v}"
    version2="${version2#v}"
    
    # 简单的版本比较（适用于语义化版本）
    local IFS=.
    local i ver1 ver2
    read -ra ver1 <<< "$version1"
    read -ra ver2 <<< "$version2"
    
    for ((i=0; i<${#ver1[@]}; i++)); do
        if [[ -z ${ver2[i]:-} ]]; then
            return 1
        fi
        if ((10#${ver1[i]} > 10#${ver2[i]})); then
            return 1
        fi
        if ((10#${ver1[i]} < 10#${ver2[i]})); then
            return 2
        fi
    done
    
    return 0
}

# 检查版本是否更新
# 参数: current_version last_version
# 返回: 0=需要更新, 1=不需要更新
is_version_updated() {
    local current_version="$1"
    local last_version="$2"
    
    if [[ -z "$current_version" ]]; then
        return 1
    fi
    
    if [[ -z "$last_version" ]]; then
        return 0  # 第一次运行，需要构建
    fi
    
    compare_versions "$current_version" "$last_version"
    local cmp_result=$?
    
    case $cmp_result in
        0)
            # 版本相同
            return 1
            ;;
        1)
            # current > last，需要更新
            return 0
            ;;
        2)
            # current < last，版本回退
            return 1
            ;;
        *)
            return 1
            ;;
    esac
}

# 提取语义化版本的主要部分
# 参数: version
# 返回: major.minor.patch
get_semver_parts() {
    local version="$1"
    version="${version#v}"  # 移除v前缀
    
    # 提取数字部分
    local major minor patch
    major=$(echo "$version" | grep -o '^[0-9]*')
    minor=$(echo "$version" | grep -o '^[0-9]*\.[0-9]*' | cut -d. -f2)
    patch=$(echo "$version" | grep -o '^[0-9]*\.[0-9]*\.[0-9]*' | cut -d. -f3)
    
    echo "$major $minor $patch"
}

# 过滤tags，只返回语义化版本
# 参数: tags_json
# 返回: 过滤后的JSON数组
filter_semver_tags() {
    local tags_json="$1"
    
    echo "$tags_json" | jq '
      map(select(
        .name | test("^v?[0-9]+\\.[0-9]+\\.[0-9]+")
      ))
    '
}

# 如果直接执行，显示用法
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    echo "版本比较工具函数库"
    echo "用法:"
    echo "  1. 作为函数库: source $(basename "$0")"
    echo "  2. 测试版本比较: $(basename "$0") <version1> <version2>"
    echo ""
    echo "可用函数:"
    echo "  - compare_versions <version1> <version2>"
    echo "  - is_version_updated <current_version> <last_version>"
    echo "  - get_semver_parts <version>"
    echo "  - filter_semver_tags <tags_json>"
    
    # 测试功能
    if [[ $# -eq 2 ]]; then
        echo ""
        compare_versions "$1" "$2"
        local result=$?
        case $result in
            0) echo "$1 和 $2 相同" ;;
            1) echo "$1 比 $2 新" ;;
            2) echo "$1 比 $2 旧" ;;
        esac
    fi
fi