#!/bin/bash
# 首次启动初始化：等音乐应用把库建好后，写入 admin 用户与 app_state。
#
# 支持环境变量（命令行参数优先，便于容器直接 -e 注入）：
#   ADMIN_USER       管理员用户名（默认 admin）
#   ADMIN_PASSWORD   管理员口令（默认 123456）
#
# 口令存储格式（飞牛音乐自己的规则，实测得出，用 NAS 真实账号库值反向验证命中）：
#   passwd = bcrypt( sha256hex(明文口令), cost=12 )
#
# app_state 是应用判断"是否已初始化"的地方，不写它 Web UI 会停在欢迎页。
set -euo pipefail

TRIM_BROKER=${TRIM_BROKER:-/usr/trim/trimmusic}
DB=""
USER="${ADMIN_USER:-admin}"
PASSWORD="${ADMIN_PASSWORD:-123456}"
TIMEOUT=180

while [ $# -gt 0 ]; do
    case "$1" in
        --db) DB="$2"; shift 2 ;;
        --user) USER="$2"; shift 2 ;;
        --password) PASSWORD="$2"; shift 2 ;;
        --timeout) TIMEOUT="$2"; shift 2 ;;
        *) echo "未知参数：$1" >&2; exit 2 ;;
    esac
done
[ -n "$DB" ] || { echo "需要 --db（或用 DB 环境变量）" >&2; exit 2; }

log() { echo "[seed] $*"; }

deadline=$(( $(date +%s) + TIMEOUT ))
# 等应用建表**并跑完迁移**：user 表带上 shared_library_access_mode 列才算迁移完，
# 否则全新库上插入会报 "table user has no column named ..."（实测踩过）。
until [ -s "$DB" ] \
    && sqlite3 "$DB" "select 1 from user limit 1" >/dev/null 2>&1 \
    && [ "$(sqlite3 "$DB" "select count(*) from pragma_table_info('user') where name='shared_library_access_mode'" 2>/dev/null)" = "1" ] \
    && sqlite3 "$DB" "select 1 from shared_library_member limit 1" >/dev/null 2>&1; do
    [ "$(date +%s)" -lt "$deadline" ] || { log "等待数据库迁移超时：$DB"; exit 1; }
    sleep 2
done
sleep 2

q() { sqlite3 "$DB" "$1"; }
GUID=$(cat /proc/sys/kernel/random/uuid | tr -d -)

# 1) 管理员用户（bcrypt(sha256hex(明文))）
HASH=$(printf '%s' "$PASSWORD" | "$TRIM_BROKER" mkpasswd --password-stdin)
if [ "$(q "select count(*) from user where name='$USER'")" = "0" ]; then
    printf "insert into user(guid,name,name_latin_full,password,role,created_by,status,shared_library_access_mode,created_at,updated_at) values('%s','%s','%s','%s','admin','manual','active','all',datetime('now'),datetime('now'));\n" \
        "$GUID" "$USER" "$USER" "$HASH" | q "$(cat)"
    log "创建用户 $USER"
elif [ "${SEED_RESET_PASSWORD:-0}" = "1" ]; then
    printf "update user set password='%s',role='admin',status='active' where name='%s';\n" "$HASH" "$USER" | q "$(cat)"
    log "用户 $USER 已存在，已按 ADMIN_PASSWORD 重置口令"
else
    printf "update user set role='admin',status='active' where name='%s';\n" "$USER" | q "$(cat)"
    log "用户 $USER 已存在（口令保持不变；要重置设 SEED_RESET_PASSWORD=1）"
fi

# 2) app_state：应用据此判断已初始化
printf "insert or replace into app_state(id,k,v,created_at,updated_at) values
 (1,'initialized','true',datetime('now'),datetime('now')),
 (2,'server_guid','%s',datetime('now'),datetime('now')),
 (3,'server_name','fnos',datetime('now'),datetime('now')),
 (4,'server_lang','zh-CN',datetime('now'),datetime('now'));\n" "$GUID" | q "$(cat)"
log "写入 app_state"
