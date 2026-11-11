#!/usr/bin/env bash
# =============================================================================
# start.sh — ECS 上一键部署 + 启动（sh）
#   1. 检查 docker / docker compose
#   2. 若 server/.env 缺失，从 .env.example 复制并提示后退出（首次需手填密钥）
#   3. docker compose up -d --build（首次会构建镜像，耗时数分钟）
#   4. 轮询 /healthz 等待后端就绪
# =============================================================================
set -euo pipefail

cd "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# --- 依赖检查 ---
need_cmd() { command -v "$1" >/dev/null 2>&1 || { echo "✗ 缺少命令: $1，请先安装"; exit 1; }; }
need_cmd docker

if docker compose version >/dev/null 2>&1; then
  COMPOSE="docker compose"
elif command -v docker-compose >/dev/null 2>&1; then
  COMPOSE="docker-compose"
else
  echo "✗ 未找到 docker compose 或 docker-compose，请先安装 docker compose v2"
  exit 1
fi

# 基础 compose + Web 网关覆盖文件（nginx 仅在 ECS 加载，本地 start_online.bat 不含）
COMPOSE_BASE="server/docker-compose.yml"
COMPOSE_WEB="server/docker-compose.web.yml"
COMPOSE_FILES="-f $COMPOSE_BASE -f $COMPOSE_WEB"
if [ ! -f "$COMPOSE_BASE" ] || [ ! -f "$COMPOSE_WEB" ]; then
  echo "✗ 未找到 compose 文件（需 $COMPOSE_BASE 与 $COMPOSE_WEB），请确认在部署包根目录运行"
  exit 1
fi

# --- 首次生成 .env ---
if [ ! -f server/.env ]; then
  echo "⚠ 未发现 server/.env，已从 server/.env.example 复制。"
  echo "  请编辑 server/.env 补全 JWT_SECRET / LICENSE_PRIVATE_KEY_PEM / CORS_ALLOW_ORIGINS 等"
  echo "  生产环境配置校验失败会拒绝启动（详见 server/README.md）。"
  cp server/.env.example server/.env
  chmod 600 server/.env
  echo "  修改完成后，再次运行 ./start.sh"
  exit 1
fi

# --- 启动 ---
echo "==> 拉取/构建镜像并启动（首次构建耗时较长，请耐心等待）"
$COMPOSE $COMPOSE_FILES up -d --build

echo "==> 等待后端健康检查 http://127.0.0.1:8000/healthz ..."
ready=0
for i in $(seq 1 90); do
  if curl -fsS http://127.0.0.1:8000/healthz >/dev/null 2>&1; then
    ready=1
    echo "✓ 后端已就绪 (${i} 次轮询)"
    break
  fi
  sleep 2
done
if [ "$ready" -ne 1 ]; then
  echo "✗ 后端在预期时间内未就绪，查看日志："
  $COMPOSE $COMPOSE_FILES logs --tail=50 api
  exit 1
fi

echo
echo "==> 服务状态"
$COMPOSE $COMPOSE_FILES ps

echo
echo "  前端(client) : http://<服务器IP>/"
echo "  管理端(admin): http://<服务器IP>/admin/"
echo "  后端 API     : http://<服务器IP>/v1   (文档 /v1/docs 或 :8000/docs)"
echo "  （Web 网关由 compose 的 nginx 服务提供，已托管 client/ 并反代 /v1）"
echo "  停止     : ./stop.sh"
echo "  状态     : ./status.sh"
