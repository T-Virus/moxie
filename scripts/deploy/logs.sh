#!/usr/bin/env bash
# =============================================================================
# logs.sh — 查看 / 跟随服务日志（ECS）
#
# 用法（部署包根目录）：
#   ./logs.sh                 # 所有服务最新日志
#   ./logs.sh -f              # 跟随（实时）所有服务
#   ./logs.sh api             # 只看 api
#   ./logs.sh -f worker       # 实时跟随 worker
#
# 服务名：api / worker / scheduler / postgres / redis / minio / nginx
# =============================================================================
set -euo pipefail
cd "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if docker compose version >/dev/null 2>&1; then COMPOSE="docker compose"
elif command -v docker-compose >/dev/null 2>&1; then COMPOSE="docker-compose"
else echo "✗ 未找到 docker compose / docker-compose"; exit 1
fi
COMPOSE_FILES="-f server/docker-compose.yml -f server/docker-compose.web.yml"

FOLLOW=""
if [ "${1:-}" = "-f" ] || [ "${1:-}" = "--follow" ]; then FOLLOW="-f"; shift; fi

exec $COMPOSE $COMPOSE_FILES logs ${FOLLOW} "$@"
