#!/usr/bin/env bash
# =============================================================================
# run-local.sh — 本地预演线上拓扑（基础 compose + web 覆盖，含 nginx 前端网关）
#
# 作用：在本地用「和 ECS 完全一样」的 docker compose 配置（含 nginx 反代与前端）
#       拉起全栈，提前验证打包产物 + 网关能不能跑通，避免上云才发现问题。
#       本地 start_online.bat 不带 nginx，本脚本补上这一步。
#
# 用法（仓库根目录）：
#   bash scripts/run-local.sh          # 构建并后台启动 + 等待健康 + 打印地址
#   bash scripts/run-local.sh stop     # 停止并移除容器（数据卷保留）
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# 定位包含 docker-compose.yml 的目录（兼容仓库根 / 解压后的部署包）
if   [ -f "$SCRIPT_DIR/server/docker-compose.yml" ]; then SRV="$SCRIPT_DIR/server"
elif [ -f "$SCRIPT_DIR/../server/docker-compose.yml" ]; then SRV="$SCRIPT_DIR/../server"
elif [ -f "$PWD/server/docker-compose.yml" ]; then SRV="$PWD/server"
else echo "✗ 找不到 server/docker-compose.yml（请在仓库根或部署包根运行）"; exit 1
fi
cd "$SRV"

# 本地若无 .env，先从示例复制（compose 的 env_file 必须存在）
if [ ! -f .env ] && [ -f .env.example ]; then
  cp .env.example .env
  echo "⚠ 已从 .env.example 复制 .env，建议按需修改 JWT_SECRET / LICENSE_PRIVATE_KEY_PEM 等后再启动"
fi

# 容器引擎
if docker compose version >/dev/null 2>&1; then COMPOSE="docker compose"
elif command -v docker-compose >/dev/null 2>&1; then COMPOSE="docker-compose"
else echo "✗ 未找到 docker compose / docker-compose"; exit 1
fi

COMPOSE_FILES="-f docker-compose.yml -f docker-compose.web.yml"
ACTION="${1:-up}"

if [ "$ACTION" = "stop" ] || [ "$ACTION" = "down" ]; then
  echo "==> 停止并移除容器（数据卷保留）"
  $COMPOSE $COMPOSE_FILES down
  echo "✓ 已停止。"
  exit 0
fi

echo "==> 构建并启动（基础 + web 覆盖，含 nginx）。首次构建耗时较长…"
$COMPOSE $COMPOSE_FILES up -d --build

echo "==> 等待后端健康检查 http://127.0.0.1:8000/healthz …"
ready=0
for i in $(seq 1 90); do
  if curl -fsS http://127.0.0.1:8000/healthz >/dev/null 2>&1; then
    ready=1; echo "✓ 后端已就绪 (${i} 次轮询)"; break
  fi
  sleep 2
done
[ "$ready" -ne 1 ] && { echo "✗ 后端未就绪，日志："; $COMPOSE $COMPOSE_FILES logs --tail=40 api; exit 1; }

echo
echo "==> 本地预演已就绪（与 ECS 拓扑一致）"
echo "    前端(client) : http://127.0.0.1/            (nginx 站点根)"
echo "    管理端(admin): http://127.0.0.1/admin/"
echo "    后端 API     : http://127.0.0.1/v1          (文档 /v1/docs)"
echo "    后端直连     : http://127.0.0.1:8000"
echo "  停止：bash scripts/run-local.sh stop"
