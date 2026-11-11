#!/usr/bin/env bash
# =============================================================================
# stop.sh — 停止全部服务（sh）
#   仅停止并移除容器；命名卷(pgdata/redisdata/miniodata/artifactdata)保留，数据不丢。
#   若需连数据一起清空，执行： docker compose down -v
# =============================================================================
set -euo pipefail

cd "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if docker compose version >/dev/null 2>&1; then
  COMPOSE="docker compose"
elif command -v docker-compose >/dev/null 2>&1; then
  COMPOSE="docker-compose"
else
  echo "✗ 未找到 docker compose 或 docker-compose"
  exit 1
fi

COMPOSE_FILES="-f server/docker-compose.yml -f server/docker-compose.web.yml"
if [ ! -f server/docker-compose.yml ] || [ ! -f server/docker-compose.web.yml ]; then
  echo "✗ 未找到 compose 文件，请确认在部署包根目录运行"
  exit 1
fi

echo "==> 停止并移除容器（数据卷保留）"
$COMPOSE $COMPOSE_FILES down
echo "✓ 已停止。需要清空数据请执行: $COMPOSE $COMPOSE_FILES down -v"
