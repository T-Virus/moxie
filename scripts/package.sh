#!/usr/bin/env bash
# =============================================================================
# package.sh — 一键打包「墨写」全项目为可部署到 ECS 的离线包
#
# 运行环境：需要 Node.js(npm) 与 bash（Windows 可用 Git Bash / WSL）。
# 产出：
#   build/moxie-deploy/            统一部署目录（可直接 scp 到 ECS）
#   build/moxie-deploy-<时间戳>.tar.gz  压缩包
#
# 设计要点：docker-compose.yml 使用相对于 server/ 的挂载路径
#   (../dist, ../mobile/dist, ../src, ../input)，因此打包产物必须保持
#   仓库顶层布局，compose 才能原样工作。
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
OUT_DIR="$ROOT_DIR/build"
BUNDLE_DIR="$OUT_DIR/moxie-deploy"
TIMESTAMP="$(date +%Y%m%d-%H%M%S)"

echo "==> 仓库根目录: $ROOT_DIR"

# 若上次残留，先清掉，保证干净
rm -rf "$BUNDLE_DIR"
mkdir -p "$BUNDLE_DIR"

# ---------------------------------------------------------------------------
# 1) 构建前端（有 package.json 的 Vite 工程）
#    云端前端：client -> client/dist（nginx 站点根 /），admin -> admin/dist（/admin）
#    桌面端 UI：web -> web/dist（非云端，不托管）；mobile 无 package.json，仅占位
#    根 dist/ 留空，供 compose 挂载给后端做离线安装包下载
# ---------------------------------------------------------------------------
build_frontend() {
  local name="$1" src="$2" dest="$3"
  if [ ! -f "$src/package.json" ]; then
    echo "[-] 跳过 $name（无 package.json）"
    return 0
  fi
  echo "==> 构建前端: $name  ($src -> $dest)"
  ( cd "$src" && { npm ci 2>/dev/null || npm install; } && npm run build )
  mkdir -p "$dest"
  # 拷贝整目录内容（保留 index.html / assets）
  tar -C "$src/dist" -cf - . | tar -C "$dest" -xf -
  echo "    完成 -> $dest"
}

# 云端前端：
#   client -> client/dist（站点根路径 /，调同源 /v1）
#   admin  -> admin/dist（挂 /admin，调同源 /v1）
# web 是桌面端配套 UI（调 /api 到桌面 webapp:8765），非云端 UI，仅顺带构建到 web/dist，
# 不由 nginx 托管；如不需要可注释掉下面一行以省编译时间。
build_frontend "client" "$ROOT_DIR/client" "$BUNDLE_DIR/client/dist"
build_frontend "admin"  "$ROOT_DIR/admin"  "$BUNDLE_DIR/admin/dist"
build_frontend "web"    "$ROOT_DIR/web"    "$BUNDLE_DIR/web/dist"
# mobile 无 package.json（产物来自其他工具链），仅占位确保挂载目录存在
mkdir -p "$BUNDLE_DIR/mobile/dist"
# 离线安装包目录（compose 挂载 ../dist 给后端下载用），留空占位
mkdir -p "$BUNDLE_DIR/dist"

# ---------------------------------------------------------------------------
# 2) 拷贝后端 server/（排除缓存、虚拟环境、测试、日志，保持轻量）
# ---------------------------------------------------------------------------
echo "==> 拷贝后端 server/"
mkdir -p "$BUNDLE_DIR/server"
tar -C "$ROOT_DIR/server" \
  --exclude='__pycache__' --exclude='*.pyc' \
  --exclude='.venv' --exclude='venv' \
  --exclude='node_modules' --exclude='tests' --exclude='logs' \
  --exclude='*.egg-info' \
  -cf - . | tar -C "$BUNDLE_DIR/server" -xf -

# ---------------------------------------------------------------------------
# 3) 拷贝提示词/规则库 src/（compose 以只读挂载 ../src）
# ---------------------------------------------------------------------------
echo "==> 拷贝 src/（提示词/规则库，只读）"
mkdir -p "$BUNDLE_DIR/src"
tar -C "$ROOT_DIR/src" --exclude='__pycache__' --exclude='*.pyc' \
  -cf - . | tar -C "$BUNDLE_DIR/src" -xf -

# ---------------------------------------------------------------------------
# 4) 任务源输入目录（空，按需放入待处理文件）
# ---------------------------------------------------------------------------
mkdir -p "$BUNDLE_DIR/input"

# ---------------------------------------------------------------------------
# 5) 拷贝启停脚本（来自 scripts/deploy/）
# ---------------------------------------------------------------------------
echo "==> 拷贝启停/运维脚本与 nginx 配置"
for s in start stop status preflight backup restore logs; do
  cp "$SCRIPT_DIR/deploy/$s.sh" "$BUNDLE_DIR/$s.sh"
done
mkdir -p "$BUNDLE_DIR/nginx"
cp "$SCRIPT_DIR/deploy/nginx/default.conf" "$BUNDLE_DIR/nginx/default.conf"
cp "$SCRIPT_DIR/deploy/nginx/default.https.conf" "$BUNDLE_DIR/nginx/default.https.conf"
chmod +x "$BUNDLE_DIR"/*.sh

# ---------------------------------------------------------------------------
# 6) 生成部署说明
# ---------------------------------------------------------------------------
cat > "$BUNDLE_DIR/DEPLOY.md" <<'EOF'
# 墨写 部署包说明（moxie-deploy）

## 目录结构（与 docker-compose 相对挂载一致）
```
moxie-deploy/
├─ server/              # 后端：Dockerfile / docker-compose.yml / docker-compose.web.yml(nginx 覆盖) / requirements.txt / app / alembic / .env.example
├─ client/dist/         # 云端客户端前端（compose 的 nginx 服务挂载为站点根 /）
├─ admin/dist/          # 云端管理端前端（挂载为 /admin）
├─ web/dist/            # 桌面端配套 UI（非云端，未托管，仅供本地桌面端使用）
├─ dist/                # 离线安装包目录（compose 挂载给后端下载用，留空）
├─ mobile/dist/         # 移动端产物占位（可选）
├─ src/                 # 提示词/规则库（只读，compose 挂载 ../src）
├─ input/               # 任务源输入目录（空，按需放文件）
├─ nginx/default.conf   # Web 网关配置（client 根 + admin /admin + 反代 /v1）
├─ start.sh             # 一键部署+启动（sh）
├─ stop.sh              # 停止（sh）
└─ status.sh            # 查看状态（sh）
```

## 服务组成（docker compose）
基础文件 docker-compose.yml：api / worker / scheduler / postgres / redis / minio
Web 网关覆盖文件 docker-compose.web.yml：nginx（与基础文件叠加加载）
- nginx 托管 client 前端(根路径) 与 admin 前端(/admin)，并把 /v1、/healthz、/docs、
  /openapi.json、/redoc、/metrics、/static、/uploads、/downloads 反代到 api 容器(8000)。
- 前端(client/admin)统一用同源 /v1 调接口，无需额外跨域配置。
- 本地 start_online.bat 只加载基础文件，不会启动 nginx；线上 ECS 由 start.sh 叠加 web 文件。

## 前置条件（ECS）
- Docker Engine + docker compose v2（或 docker-compose v1）。
- 安全组放行：80（Web 网关，对外访问前端/接口）、8000（API 直连，可选）、9000/9001（MinIO，可选）。
- 建议 2C4G 以上；首次构建镜像会拉取 python:3.12-slim 并装依赖，耗时数分钟。

## 部署步骤
```bash
# 本地：已用 package.sh 生成 moxie-deploy-<时间戳>.tar.gz
scp moxie-deploy-*.tar.gz root@<ECS_IP>:/opt/
ssh root@<ECS_IP>
  mkdir -p /opt/moxie && cd /opt/moxie
  tar -xzf /opt/moxie-deploy-*.tar.gz --strip-components=1
  # 先校验 compose（基础 + web 覆盖）
  docker compose -f server/docker-compose.yml -f server/docker-compose.web.yml config >/dev/null && echo "compose OK"
  ./start.sh
```

## 首次启动
- `start.sh` 若发现 `server/.env` 缺失，会自动从 `server/.env.example` 复制并退出，
  请编辑 `server/.env` 补全至少：JWT_SECRET（≥32 位）、DATABASE_URL（若不用默认）、
  CORS_ALLOW_ORIGINS、以及生产必需的 LICENSE_PRIVATE_KEY_PEM 等，再重新运行 `./start.sh`。
- 生产启动会做配置校验（见 server/README.md 的 legal-gates），示例口令会被拒绝。
- 改 Web 端口：在 server/.env 设置 `WEB_PORT`（默认 80）。

## 访问地址
- 前端(client) : http://<服务器IP>/
- 管理端(admin): http://<服务器IP>/admin/
- 后端 API     : http://<服务器IP>/v1  （文档 /v1/docs 或 :8000/docs）

## 运维脚本（部署包内，均为 sh）
- \`./preflight.sh\`            启动前校验生产配置（JWT/License/Payload/CORS/DB/S3 等），加 \`--gen-secrets\` 可自动生成缺失密钥
- \`./status.sh\`              容器状态 + 后端健康检查 + 最近日志
- \`./logs.sh [-f] [服务]\`     查看/实时跟随日志（如 \`./logs.sh -f worker\`）
- \`./backup.sh\`              备份数据库 + 产物卷 + .env 到 \`backups/<时间戳>/\`
- \`./restore.sh [时间戳]\`     从备份恢复（会 DROP 重建数据库，先确认备份可用）
- \`./stop.sh\` / \`./start.sh\` 停止 / 启动（start 会自动叠加 web 网关）
- 本地预演（仓库内）：\`bash scripts/run-local.sh\`（用基础+web 覆盖拉起和 ECS 一致的全栈，含 nginx）

## 数据持久化
- Postgres(pgdata)、Redis(redisdata)、MinIO(miniodata)、产物(artifactdata) 均为命名卷，
  `stop.sh` / `down` 不会删除数据；只有 `docker compose down -v` 才会清空。

## 安全要点（上线前必做）
- **改掉所有默认口令**：JWT_SECRET、DATABASE_URL 里的密码、MINIO_ROOT_PASSWORD/S3_SECRET_KEY 全部换掉；含 `change-me` 会被启动拒绝。生成强密码：`openssl rand -base64 24`。
- **必须开 HTTPS**：默认 nginx 是 HTTP，登录令牌(JWT)会明文传输。启用 `server/nginx/default.https.conf` 并放证书到 `server/nginx/certs/`（详见 INSTALL.md 第 8 节），否则不要长期公网暴露。
- **端口只开 80/443**：安全组/防火墙**绝不**对公网开放 5432(Postgres)/6379(Redis)/9000(MinIO)/8000(API)，这些只在容器内部互通。
- **CORS 不用 `*`**：`CORS_ALLOW_ORIGINS` 填具体域名。
- **`.env` 已自动 chmod 600**（仅属主可读）；`backup.sh` 产出的 `env.env` 同样含全部密钥，请异地/加密保存。
- **备份异地**：`backups/` 要下载到本地或对象存储，只在服务器本地不算安全。
- **慎用 `down -v`**：会删除数据库卷。SSH 建议改用密钥登录并装 fail2ban。

## 升级
1. 本地重新运行 `package.sh` 生成新包。
2. ECS 上：`cd /opt/moxie && ./stop.sh`，覆盖目录后 `./start.sh`（镜像会按新代码重建）。
EOF

# ---------------------------------------------------------------------------
# 7) 生成压缩包
# ---------------------------------------------------------------------------
echo "==> 生成压缩包"
( cd "$OUT_DIR" && tar -czf "moxie-deploy-$TIMESTAMP.tar.gz" "moxie-deploy" )

echo
echo "==> 打包完成"
echo "    部署目录 : $BUNDLE_DIR"
echo "    压缩包   : $OUT_DIR/moxie-deploy-$TIMESTAMP.tar.gz"
echo "    大小     : $(du -sh "$OUT_DIR/moxie-deploy-$TIMESTAMP.tar.gz" | cut -f1)"
echo
echo "    下一步：scp 压缩包到 ECS，解压后执行 ./start.sh"
