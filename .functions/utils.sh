#!/bin/bash
# .functions/utils.sh
# 通用工具函数库

set -euo pipefail

# 颜色输出
readonly RED='\033[0;31m'
readonly GREEN='\033[0;32m'
readonly YELLOW='\033[1;33m'
readonly BLUE='\033[0;34m'
readonly CYAN='\033[0;36m'
readonly MAGENTA='\033[0;35m'
readonly NC='\033[0m' # No Color

# 日志级别
readonly LOG_LEVEL_DEBUG=0
readonly LOG_LEVEL_INFO=1
readonly LOG_LEVEL_WARN=2
readonly LOG_LEVEL_ERROR=3

# 默认日志级别
LOG_LEVEL=${LOG_LEVEL:-$LOG_LEVEL_INFO}

# 带时间戳的日志函数
log() {
    local level="$1"
    local color="$2"
    local message="$3"
    local timestamp
    timestamp=$(date '+%Y-%m-%d %H:%M:%S')

    if [[ "$level" -ge "$LOG_LEVEL" ]]; then
        printf '%b[%s] %s%b\n' "$color" "$timestamp" "$message" "$NC" >&2
    fi
}

log_debug() {
    log "$LOG_LEVEL_DEBUG" "$CYAN" "[DEBUG] $1"
}

log_info() {
    log "$LOG_LEVEL_INFO" "$BLUE" "[INFO] $1"
}

log_success() {
    log "$LOG_LEVEL_INFO" "$GREEN" "[SUCCESS] $1"
}

log_warning() {
    log "$LOG_LEVEL_WARN" "$YELLOW" "[WARNING] $1"
}

log_error() {
    log "$LOG_LEVEL_ERROR" "$RED" "[ERROR] $1" >&2
}

# 检查命令是否存在
check_command() {
    local cmd="$1"
    if ! command -v "$cmd" &> /dev/null; then
        log_error "命令未找到: $cmd"
        return 1
    fi
    return 0
}

# 检查必需的命令
check_required_commands() {
    local commands=("$@")
    local missing=()
    
    for cmd in "${commands[@]}"; do
        if ! check_command "$cmd"; then
            missing+=("$cmd")
        fi
    done
    
    if [[ ${#missing[@]} -gt 0 ]]; then
        log_error "缺少必需的命令: ${missing[*]}"
        return 1
    fi
    
    log_info "所有必需命令已安装"
    return 0
}

# 安全执行命令，失败时退出
safe_run() {
    local cmd="$*"
    log_debug "执行命令: $cmd"
    
    if eval "$cmd"; then
        log_debug "命令执行成功"
        return 0
    else
        local exit_code=$?
        log_error "命令执行失败 (退出码: $exit_code): $cmd"
        return $exit_code
    fi
}

# 重试命令
retry() {
    local max_attempts="$1"
    local delay="$2"
    shift 2
    local cmd="$*"
    
    local attempt=1
    while [[ $attempt -le $max_attempts ]]; do
        log_info "尝试 $attempt/$max_attempts: $cmd"
        
        if eval "$cmd"; then
            log_success "命令执行成功 (尝试 $attempt)"
            return 0
        fi
        
        if [[ $attempt -lt $max_attempts ]]; then
            log_warning "命令失败，${delay}秒后重试..."
            sleep "$delay"
        fi
        
        ((attempt++))
    done
    
    log_error "命令在 $max_attempts 次尝试后仍然失败: $cmd"
    return 1
}

# 验证文件存在
check_file_exists() {
    local file="$1"
    if [[ ! -f "$file" ]]; then
        log_error "文件不存在: $file"
        return 1
    fi
    log_debug "文件存在: $file"
    return 0
}

# 验证目录存在
check_dir_exists() {
    local dir="$1"
    if [[ ! -d "$dir" ]]; then
        log_error "目录不存在: $dir"
        return 1
    fi
    log_debug "目录存在: $dir"
    return 0
}

# 创建目录（如果不存在）
ensure_dir() {
    local dir="$1"
    if [[ ! -d "$dir" ]]; then
        log_info "创建目录: $dir"
        mkdir -p "$dir"
    fi
}

# 获取脚本所在目录
get_script_dir() {
    local source="${BASH_SOURCE[0]}"
    while [[ -L "$source" ]]; do
        local dir="$(cd -P "$(dirname "$source")" && pwd)"
        source="$(readlink "$source")"
        [[ $source != /* ]] && source="$dir/$source"
    done
    echo "$(cd -P "$(dirname "$source")" && pwd)"
}

# 获取Git仓库根目录
get_git_root() {
    local dir="${1:-.}"
    git -C "$dir" rev-parse --show-toplevel 2>/dev/null
}

# 检查是否在Git仓库中
is_git_repo() {
    local dir="${1:-.}"
    git -C "$dir" rev-parse --git-dir &> /dev/null
}

# 获取当前Git分支
get_current_branch() {
    local dir="${1:-.}"
    git -C "$dir" branch --show-current
}

# 获取Git远程URL
get_git_remote_url() {
    local remote="${1:-origin}"
    local dir="${2:-.}"
    git -C "$dir" remote get-url "$remote" 2>/dev/null
}

# 验证GitHub令牌
validate_github_token() {
    if [[ -z "${GITHUB_TOKEN:-}" ]]; then
        log_warning "GITHUB_TOKEN未设置"
        return 1
    fi
    
    # 简单验证令牌格式
    if [[ ! "$GITHUB_TOKEN" =~ ^gh[pousr]_[A-Za-z0-9_]+$ ]] && [[ ${#GITHUB_TOKEN} -ne 40 ]]; then
        log_warning "GITHUB_TOKEN格式可能无效"
        return 1
    fi
    
    log_debug "GITHUB_TOKEN已设置"
    return 0
}

# 生成随机字符串
generate_random_string() {
    local length="${1:-8}"
    tr -dc 'a-zA-Z0-9' < /dev/urandom | head -c "$length"
}

# 获取系统信息
get_system_info() {
    echo "=== 系统信息 ==="
    echo "主机名: $(hostname)"
    echo "系统: $(uname -s)"
    echo "内核: $(uname -r)"
    echo "架构: $(uname -m)"
    echo "时间: $(date)"
    
    if [[ -f /etc/os-release ]]; then
        echo "发行版: $(grep PRETTY_NAME /etc/os-release | cut -d= -f2 | tr -d '\"')"
    fi
}

# 测量命令执行时间
measure_time() {
    local start end duration
    start=$(date +%s.%N)
    
    # 执行命令
    "$@"
    local exit_code=$?
    
    end=$(date +%s.%N)
    duration=$(echo "$end - $start" | bc)
    
    log_info "执行时间: ${duration}秒"
    return $exit_code
}

# 进度条显示
progress_bar() {
    local current="$1"
    local total="$2"
    local width="${3:-50}"
    
    local percentage=$((current * 100 / total))
    local filled=$((current * width / total))
    local empty=$((width - filled))
    
    printf "\r["
    printf "%${filled}s" "" | tr ' ' '='
    printf "%${empty}s" "" | tr ' ' ' '
    printf "] %3d%%" "$percentage"
    
    if [[ $current -eq $total ]]; then
        printf "\n"
    fi
}

# 如果直接执行，显示用法
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    echo "通用工具函数库"
    echo "用法: source $(basename "$0")"
    echo ""
    echo "可用函数:"
    echo "  log_info/debug/success/warning/error - 日志函数"
    echo "  check_required_commands - 检查必需命令"
    echo "  safe_run - 安全执行命令"
    echo "  retry - 重试命令"
    echo "  get_script_dir - 获取脚本目录"
    echo "  get_git_root - 获取Git根目录"
    echo "  measure_time - 测量执行时间"
    echo "  progress_bar - 显示进度条"
fi