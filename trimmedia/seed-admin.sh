#!/bin/bash
# 首次启动初始化：等应用把库建好后，写入 sys_secret / media_server / 权限 / admin 用户。
#
# 口令存储格式（飞牛影视自己的规则，实测得出）：
#   passwd = "$argon2id$v=19$m=65536,t=3,p=1$<b64(salt16)>$<b64(argon2id)>"
#   argon2id 的输入 = sys_secret + sha256hex(明文口令)
# 哈希由 trimmedia mkpasswd 计算（Go 原生，镜像里不再需要 Python）。
set -euo pipefail

TRIM_BROKER=${TRIM_BROKER:-/usr/trim/trimmedia}

# 支持环境变量（命令行参数优先，便于容器直接 -e 注入）：
#   ADMIN_USER       管理员用户名（默认 admin）
#   ADMIN_PASSWORD   管理员口令（默认 123456）
DB=""; META=""; USER="${ADMIN_USER:-admin}"; PASSWORD="${ADMIN_PASSWORD:-123456}"; TIMEOUT=180
while [ $# -gt 0 ]; do
    case "$1" in
        --db) DB="$2"; shift 2 ;;
        --meta) META="$2"; shift 2 ;;
        --user) USER="$2"; shift 2 ;;
        --password) PASSWORD="$2"; shift 2 ;;
        --timeout) TIMEOUT="$2"; shift 2 ;;
        *) echo "未知参数：$1" >&2; exit 2 ;;
    esac
done
[ -n "$DB" ] && [ -n "$META" ] || { echo "需要 --db 与 --meta" >&2; exit 2; }

log() { echo "[seed] $*"; }

# 单引号双写，避免用户名/路径里的 ' 破坏 SQL
sqlq() { printf '%s' "${1//\'/\'\'}"; }

# 等应用把库建好
deadline=$(( $(date +%s) + TIMEOUT ))
until [ -s "$DB" ] && sqlite3 "$DB" "select 1 from user limit 1" >/dev/null 2>&1; do
    [ "$(date +%s)" -lt "$deadline" ] || { log "等待数据库超时：$DB"; exit 1; }
    sleep 2
done
sleep 3

now_ms=$(( $(date +%s) * 1000 ))
q() { sqlite3 "$DB" "$1"; }

# 1) sys_secret：口令哈希的盐值前缀（飞牛系统写的，独立部署需自备一个稳定值）
if [ -z "$(q "select value from sys_metadata where key='sys_secret'")" ]; then
    SECRET=$(head -c 32 /dev/urandom | od -An -tx1 | tr -d ' \n')
    q "insert or replace into sys_metadata(key,value,private) values('sys_secret','$SECRET',1)"
    log "生成 sys_secret"
fi
SECRET=$(q "select value from sys_metadata where key='sys_secret'")

# 2) media_server：有记录 = 应用认为「系统已初始化」
if [ "$(q "select count(*) from media_server")" = "0" ]; then
    GUID=$(cat /proc/sys/kernel/random/uuid | tr -d -)
    q "insert into media_server(guid,name,lan,meta_dir,file_monitor,region,
       direct_link_enable,direct_link_allowed_level,direct_link_allowed_drives,create_time,update_time)
       values('$GUID','MediaHub','zh-CN','$META',1,'CN',1,0,'',$now_ms,$now_ms)"
    log "写入 media_server"
fi

# 3) 权限字典
for perm in mdb_manager user_manager metadata_manager server_manager task_manager; do
    q "insert or ignore into permission(permission,create_time,update_time) values('$perm',$now_ms,$now_ms)"
done

# 4) admin 用户
#
# 不写 user_source：那是「关联 NAS 管理员帐号」的标记（客户端按 source==='Trim-NAS' 判定，
# 有这行就在用户列表里显示成 NAS 账号）。独立部署没有 NAS 可关联，写了只会显示一个
# 并不存在的 NAS 关联。
HASH=$(printf '%s' "$PASSWORD" | MKPASSWD_SECRET="$SECRET" "$TRIM_BROKER" mkpasswd --password-stdin)
if [ "$(q "select count(*) from user where username='$(sqlq "$USER")'")" = "0" ]; then
    GUID=$(cat /proc/sys/kernel/random/uuid | tr -d -)
    q "insert into user(guid,username,passwd,lan,last_login_time,is_admin,media_permission,status,create_time,update_time)
       values('$GUID','$(sqlq "$USER")','$HASH','zh-CN',0,1,2,1,$now_ms,$now_ms)"
    log "创建用户 $USER（guid=$GUID）"
elif [ "${SEED_RESET_PASSWORD:-0}" = "1" ]; then
    q "update user set passwd='$HASH',status=1,is_admin=1,media_permission=2 where username='$(sqlq "$USER")'"
    log "用户 $USER 已存在，已按 ADMIN_PASSWORD 重置口令"
else
    q "update user set status=1,is_admin=1,media_permission=2 where username='$(sqlq "$USER")'"
    log "用户 $USER 已存在（口令保持不变；要重置设 SEED_RESET_PASSWORD=1）"
fi
