#!/bin/bash
# .functions/github.sh
# GitHub API相关的公共函数库
# 只提供基础工具，不包含业务逻辑

set -euo pipefail

# 加载工具函数
source "$(dirname "${BASH_SOURCE[0]}")/utils.sh"

# 查询GitHub仓库的所有tags（返回JSON格式）
# 参数: owner repo
# 返回: JSON数组，包含tag名称和提交日期
query_github_tags() {
    local owner="$1"
    local repo="$2"
    
    # GraphQL查询
    local query='{
  repository(owner: "%s", name: "%s") {
    refs(refPrefix: "refs/tags/", first: 50, orderBy: {field: TAG_COMMIT_DATE, direction: DESC}) {
      nodes {
        name
        target {
          ... on Commit {
            committedDate
          }
          ... on Tag {
            target {
              ... on Commit {
                committedDate
              }
            }
          }
        }
      }
    }
  }
}'
    
    local formatted_query
    formatted_query=$(printf "$query" "$owner" "$repo")
    
    local curl_cmd="curl -s -H \"Content-Type: application/json\" https://api.github.com/graphql"
    
    if [[ -n "${GITHUB_TOKEN:-}" ]]; then
        curl_cmd="curl -s -H \"Authorization: Bearer ${GITHUB_TOKEN}\" -H \"Content-Type: application/json\" https://api.github.com/graphql"
    fi
    
    local response
    response=$(echo "$formatted_query" | jq -n --arg q "$(cat)" '{query: $q}' | eval "$curl_cmd" -d @- 2>/dev/null) || {
        log_error "GitHub API请求失败"
        return 1
    }
    
    if [[ -z "$response" ]]; then
        log_error "GitHub API返回空响应"
        return 1
    fi

    # 提取tag信息
    echo "$response" | jq -r '
      .data.repository.refs.nodes[] | 
      .name as $name | 
      (.target.committedDate // .target.target.committedDate) as $date |
      select($date != null) |
      {"name": $name, "date": $date}
    ' | jq -s '.'
}

# 将ISO日期转换为时间戳
# 参数: iso_date
iso_to_timestamp() {
    local iso_date="$1"
    
    # 尝试GNU date格式
    if date -d "$iso_date" +%s >/dev/null 2>&1; then
        date -d "$iso_date" +%s
    # 尝试BSD date格式 (macOS)
    elif date -j -f "%Y-%m-%dT%H:%M:%SZ" "$iso_date" +%s >/dev/null 2>&1; then
        date -j -f "%Y-%m-%dT%H:%M:%SZ" "$iso_date" +%s
    else
        log_error "无法解析日期: $iso_date"
        return 1
    fi
}

# 获取N天前的时间戳
# 参数: days
days_ago_timestamp() {
    local days="$1"
    
    # 尝试GNU date
    if date -d "${days} days ago" +%s >/dev/null 2>&1; then
        date -d "${days} days ago" +%s
    # 尝试BSD date (macOS)
    elif date -v -${days}d +%s >/dev/null 2>&1; then
        date -v -${days}d +%s
    else
        log_error "无法计算${days}天前的时间戳"
        return 1
    fi
}

# 过滤tags，只返回指定日期之前的tags
# 参数: tags_json cutoff_timestamp
# 返回: 过滤后的JSON数组
filter_tags_before_date() {
    local tags_json="$1"
    local cutoff_timestamp="$2"
    
    echo "$tags_json" | jq --arg cutoff "$cutoff_timestamp" '
      map(select(
        (.date | fromdateiso8601) <= ($cutoff | tonumber)
      ))
    '
}

# 获取最新的tag（按日期排序的第一个）
# 参数: tags_json
get_latest_tag() {
    local tags_json="$1"
    echo "$tags_json" | jq -r '.[0].name // empty'
}

# 如果直接执行，显示用法
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    echo "GitHub工具函数库"
    echo "用法:"
    echo "  1. 作为函数库: source $(basename "$0")"
    echo "  2. 测试函数: $(basename "$0") <owner> <repo>"
    echo ""
    echo "可用函数:"
    echo "  - query_github_tags <owner> <repo>"
    echo "  - iso_to_timestamp <iso_date>"
    echo "  - days_ago_timestamp <days>"
    echo "  - filter_tags_before_date <tags_json> <cutoff_timestamp>"
    echo "  - get_latest_tag <tags_json>"
    
    # 测试功能
    if [[ $# -eq 2 ]]; then
        echo ""
        echo "测试查询 $1/$2 的tags..."
        query_github_tags "$1" "$2" | jq '. | length' | xargs echo "找到tags数量:"
    fi
fi
