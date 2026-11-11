#!/usr/bin/env bash
# =============================================================================
# restore.sh — ECS 一键恢复（数据库 + 产物卷）
#
# 用法（部署包根目录）：
#   ./restore.sh                        # 恢复 backups/ 下最新一份
#   ./restore.sh 20261111-120000        # 恢复指定时间戳
#   BACKUP_DIR=/data/backups ./restore.sh 20261111-120000
#
# 注意：
#   - 会 DROP 并重建目标数据库，不可回退，请先确认备份可用。
#   - 恢复后建议重启 api/worker/scheduler 以加载新数据。
# =============================================================================
set -euo pipefail
cd "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if docker compose version >/dev/null 2>&1; then COMPOSE="docker compose"
elif command -v docker-compose >/dev/null 2>&1; then COMPOSE="docker-compose"
else echo "✗ 未找到 docker compose / docker-compose"; exit 1
fi
COMPOSE_FILES="-f server/docker-compose.yml -f server/docker-compose.web.yml"
ENV_FILE="server/.env"

get_env() { local v; v="$(grep -m1 "^${1}=" "$ENV_FILE" 2>/dev/null | cut -d= -f2-)"; v="${v#\"}"; v="${v%\"}"; printf '%s' "$v"; }

BACKUP_ROOT="${BACKUP_DIR:-backups}"
STAMP="${1:-}"
if [ -z "$STAMP" ]; then
  STAMP="$(ls -1 "$BACKUP_ROOT" 2>/dev/null | grep -E '^[0-9]{8}-[0-9]{6}$' | sort | tail -1)"
fi
if [ -z "$STAMP" ] || [ ! -f "$BACKUP_ROOT/$STAMP/db.dump" ]; then
  echo "✗ 未指定有效备份（BACKUP_DIR=$BACKUP_ROOT, STAMP=$STAMP），需存在 db.dump"; exit 1
fi
SRC="$BACKUP_ROOT/$STAMP"
echo "==> 恢复来源：$SRC"

if [ ! -f "$ENV_FILE" ]; then echo "✗ 未找到 $ENV_FILE，请先 ./preflight.sh 或 ./start.sh 生成"; exit 1; fi
DB_URL="$(get_env DATABASE_URL)"
DB_USER="$(printf '%s' "$DB_URL" | sed -E 's#^[a-z+]+://([^:/]+):.*#\1#')"
DB_PASS="$(printf '%s' "$DB_URL" | sed -E 's#^[a-z+]+://[^:]+:([^@]+)@.*#\1#')"
DB_NAME="$(printf '%s' "$DB_URL" | sed -E 's#.*/([^?]+).*#\1#')"

echo "==> 终止连接并重建数据库 $DB_NAME"
$COMPOSE $COMPOSE_FILES exec -T -e "PGPASSWORD=$DB_PASS" postgres psql -U "$DB_USER" -d postgres -c \
  "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname='$DB_NAME' AND pid<>pg_backend_pid();" >/dev/null
$COMPOSE $COMPOSE_FILES exec -T -e "PGPASSWORD=$DB_PASS" postgres psql -U "$DB_USER" -d postgres -c "DROP DATABASE IF EXISTS \"$DB_NAME\";" >/dev/null
$COMPOSE $COMPOSE_FILES exec -T -e "PGPASSWORD=$DB_PASS" postgres psql -U "$DB_USER" -d postgres -c "CREATE DATABASE \"$DB_NAME\" OWNER \"$DB_USER\";" >/dev/null

echo "==> pg_restore -> $DB_NAME（从 stdin 传入备份文件）"
$COMPOSE $COMPOSE_FILES exec -T -e "PGPASSWORD=$DB_PASS" postgres sh -c "pg_restore -U $DB_USER -d $DB_NAME --no-owner --no-privileges" < "$SRC/db.dump"

if [ -f "$SRC/artifacts.tar.gz" ]; then
  echo "==> 恢复产物卷 artifactdata"
  if $COMPOSE $COMPOSE_FILES exec -T api tar xzf - -C /var/lib/moxie/artifacts < "$SRC/artifacts.tar.gz" 2>/dev/null; then
    echo "    产物卷已恢复"
  else
    echo "    [warn] 产物卷恢复失败，可手动解包 $SRC/artifacts.tar.gz 到 /var/lib/moxie/artifacts"
  fi
else
  echo "==> 无 artifacts.tar.gz，跳过产物卷恢复"
fi

echo
echo "✓ 恢复完成。建议重启服务："
echo "    $COMPOSE $COMPOSE_FILES restart api worker scheduler"
