#!/usr/bin/env bash
# =============================================================================
# status.sh — 查看服务状态与后端健康检查（sh）
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

echo "==> 容器状态"
$COMPOSE $COMPOSE_FILES ps

echo
echo "==> 后端健康检查"
if curl -fsS http://127.0.0.1:8000/healthz >/dev/null 2>&1; then
  echo "  api (8000): OK  -> $(curl -fsS http://127.0.0.1:8000/healthz)"
else
  echo "  api (8000): 未就绪 / 不可达"
fi

echo
echo "==> 最近日志（api）"
$COMPOSE $COMPOSE_FILES logs --tail=20 api 2>/dev/null || true
