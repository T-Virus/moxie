#!/usr/bin/env bash
# =============================================================================
# backup.sh — ECS 一键备份（数据库 + 产物卷 + .env）
#
# 用法（部署包根目录）：
#   ./backup.sh                         # 默认备份到 backups/<时间戳>/
#   BACKUP_DIR=/data/backups ./backup.sh # 自定义备份根目录
#
# 产物：
#   <BACKUP_DIR>/<STAMP>/db.dump            Postgres 自定义格式逻辑备份
#   <BACKUP_DIR>/<STAMP>/artifacts.tar.gz   产物卷（artifactdata）打包
#   <BACKUP_DIR>/<STAMP>/env.env            生产 .env（含密钥！请妥善保护）
#   <BACKUP_DIR>/<STAMP>.sha256             校验和
#
# 说明：通过 docker compose exec 在容器内执行，无需宿主机安装 pg_dump/tar。
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
STAMP="$(date +%Y%m%d-%H%M%S)"
OUT="$BACKUP_ROOT/$STAMP"
mkdir -p "$OUT"

if [ ! -f "$ENV_FILE" ]; then echo "✗ 未找到 $ENV_FILE，请先 ./preflight.sh 或 ./start.sh 生成"; exit 1; fi

DB_URL="$(get_env DATABASE_URL)"
DB_USER="$(printf '%s' "$DB_URL" | sed -E 's#^[a-z+]+://([^:/]+):.*#\1#')"
DB_PASS="$(printf '%s' "$DB_URL" | sed -E 's#^[a-z+]+://[^:]+:([^@]+)@.*#\1#')"
DB_NAME="$(printf '%s' "$DB_URL" | sed -E 's#.*/([^?]+).*#\1#')"

echo "==> 备份数据库 $DB_USER@$DB_NAME"
$COMPOSE $COMPOSE_FILES exec -T -e "PGPASSWORD=$DB_PASS" postgres \
  pg_dump -U "$DB_USER" -d "$DB_NAME" -F c > "$OUT/db.dump"
echo "    db.dump: $(du -h "$OUT/db.dump" | cut -f1)"

echo "==> 备份产物卷 artifactdata"
if $COMPOSE $COMPOSE_FILES exec -T api tar czf - -C /var/lib/moxie/artifacts . > "$OUT/artifacts.tar.gz" 2>/dev/null; then
  echo "    artifacts.tar.gz: $(du -h "$OUT/artifacts.tar.gz" | cut -f1)"
else
  echo "    [warn] 产物卷备份失败（可能为空，或 api 镜像缺少 tar），跳过"
  rm -f "$OUT/artifacts.tar.gz"
fi

echo "==> 备份 .env（含生产密钥，请妥善保护）"
cp "$ENV_FILE" "$OUT/env.env"

( cd "$OUT" && sha256sum ./* > "../$STAMP.sha256" 2>/dev/null || true )
echo
echo "✓ 备份完成：$OUT"
echo "  校验：sha256sum -c $BACKUP_ROOT/$STAMP.sha256"
