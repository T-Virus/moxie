#!/usr/bin/env bash
# =============================================================================
# preflight.sh — 启动前校验生产配置，并可生成缺失密钥
#
# 用法（部署包根目录）：
#   ./preflight.sh                # 只检查 server/.env 是否满足生产启动闸门
#   ./preflight.sh --gen-secrets  # 对缺失的密钥用 openssl 自动生成并写入 .env
#
# 校验项依据 server/.env.example 与 app 的生产配置闸门（validate_production_settings）：
#   JWT_SECRET / LICENSE_PRIVATE_KEY_PEM / PAYLOAD_CRYPTO_PRIVATE_KEY_PEM /
#   CORS_ALLOW_ORIGINS / DATABASE_URL / S3 与 MinIO 凭据 / 支付 mock / 临时密钥
# =============================================================================
set -euo pipefail
cd "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# 容器引擎（仅用于提示；本脚本不依赖 docker）
if docker compose version >/dev/null 2>&1; then COMPOSE="docker compose"
elif command -v docker-compose >/dev/null 2>&1; then COMPOSE="docker-compose"
else COMPOSE=""
fi
COMPOSE_FILES="-f server/docker-compose.yml -f server/docker-compose.web.yml"

ENV_FILE="server/.env"
EXAMPLE="server/.env.example"
GEN_SECRETS=0
[ "${1:-}" = "--gen-secrets" ] && GEN_SECRETS=1

if [ ! -f "$EXAMPLE" ]; then echo "✗ 未找到 $EXAMPLE"; exit 1; fi
if [ ! -f "$ENV_FILE" ]; then
  cp "$EXAMPLE" "$ENV_FILE"
  chmod 600 "$ENV_FILE"
  echo "⚠ 已从 $EXAMPLE 复制出 $ENV_FILE，请补全后再校验（或加 --gen-secrets 自动生成密钥）。"
fi

# 读取 .env（去掉首尾双引号；多行 PEM 的 \n 保持字面）
get_env() {
  local k="$1" v
  v="$(grep -m1 "^${k}=" "$ENV_FILE" 2>/dev/null | cut -d= -f2-)"
  v="${v#\"}"; v="${v%\"}"
  printf '%s' "$v"
}
# 写入/替换 .env 中的键值。用临时文件 + printf 原样写入，避免 sed 替换串误把
# PEM 里的字面 \n（私钥换行表示）解释成真实换行，或损坏反斜杠。
set_env() {
  local k="$1" v="$2" tmp
  tmp="${ENV_FILE}.tmp.$$"
  grep -v "^${k}=" "$ENV_FILE" > "$tmp" || true
  printf '%s\n' "${k}=\"${v}\"" >> "$tmp"
  mv "$tmp" "$ENV_FILE"
  chmod 600 "$ENV_FILE"
}
pem_to_oneline() { sed ':a;N;$!ba;s/\n/\\n/g' "$1"; }

ERR=0
ok()   { echo "  ✓ $1"; }
bad()  { echo "  ✗ $1"; ERR=1; }

echo "==> 校验生产配置 ($ENV_FILE)"
ENV_VAL="$(get_env ENV)"
JWT="$(get_env JWT_SECRET)"
LIC="$(get_env LICENSE_PRIVATE_KEY_PEM)"
PAY="$(get_env PAYLOAD_CRYPTO_PRIVATE_KEY_PEM)"
CORS="$(get_env CORS_ALLOW_ORIGINS)"
DB="$(get_env DATABASE_URL)"
S3B="$(get_env STORAGE_BACKEND)"
S3AK="$(get_env S3_ACCESS_KEY)"
S3SK="$(get_env S3_SECRET_KEY)"
MINIOPW="$(get_env MINIO_ROOT_PASSWORD)"
PAYMOCK="$(get_env PAYMENTS_MOCK_ENABLED)"
PAYFAKE="$(get_env PAYMENTS_FAKE_ENABLED)"
LICEPI="$(get_env LICENSE_ALLOW_EPHEMERAL_KEY)"
PENC="$(get_env PAYLOAD_ENCRYPTION_ENABLED)"

# --- 逐项检查 ---
if [ -n "$JWT" ] && [ "${#JWT}" -ge 32 ] && [[ "$JWT" != *change-me* ]]; then ok "JWT_SECRET 已设置且长度>=32"
else bad "JWT_SECRET 必须设置、长度>=32 且不能含 change-me 占位"; fi

if [ -n "$LIC" ] && [[ "$LIC" != *change-me* ]] && [[ "$LIC" == *BEGIN* ]]; then ok "LICENSE_PRIVATE_KEY_PEM 已设置(Ed25519)"
else bad "LICENSE_PRIVATE_KEY_PEM 必须设置生产 Ed25519 私钥（缺失则启动失败）"; fi

if [[ "$PENC" == "true" ]]; then
  if [ -n "$PAY" ] && [[ "$PAY" == *BEGIN* ]]; then ok "PAYLOAD_CRYPTO_PRIVATE_KEY_PEM 已设置(P-256)"
  else bad "PAYLOAD_ENCRYPTION_ENABLED=true，但 PAYLOAD_CRYPTO_PRIVATE_KEY_PEM 缺失"; fi
fi

if [ -n "$CORS" ] && [ "$CORS" != "*" ]; then ok "CORS_ALLOW_ORIGINS 已设置且非通配"
else bad "CORS_ALLOW_ORIGINS 必须设置具体来源（禁止 *，生产启动会校验）"; fi

if [ -n "$DB" ] && [[ "$DB" != *change-me* ]] && [[ "$DB" != sqlite* ]]; then ok "DATABASE_URL 已配置(非 SQLite/非占位)"
else bad "DATABASE_URL 必须指向 Postgres 且口令不能是 change-me 占位"; fi

if [[ "$S3B" == "s3" ]]; then
  [ "$S3AK" != "minioadmin" ] && [ "$S3SK" != "change-me-minio-secret" ] \
    && ok "STORAGE_BACKEND=s3 凭据非示例值" || bad "s3 后端凭据仍为 minioadmin/change-me 示例"
fi
[ "$MINIOPW" != "change-me-minio-secret" ] \
  && ok "MINIO_ROOT_PASSWORD 非示例值" || bad "MINIO_ROOT_PASSWORD 仍是 change-me 示例"

if [[ "$ENV_VAL" == "production" ]]; then
  [ "${PAYMOCK:-false}" = "false" ] && ok "PAYMENTS_MOCK_ENABLED=false" || bad "生产环境 PAYMENTS_MOCK_ENABLED 必须为 false"
  [ "${PAYFAKE:-false}" = "false" ] && ok "PAYMENTS_FAKE_ENABLED=false" || bad "生产环境 PAYMENTS_FAKE_ENABLED 必须为 false"
  [ "${LICEPI:-false}" = "false" ] && ok "LICENSE_ALLOW_EPHEMERAL_KEY=false" || bad "生产环境 LICENSE_ALLOW_EPHEMERAL_KEY 必须为 false"
fi

# --- 自动生成缺失密钥 ---
if [ "$GEN_SECRETS" -eq 1 ]; then
  echo
  echo "==> 生成缺失密钥（openssl）"
  if ! command -v openssl >/dev/null 2>&1; then
    echo "✗ 未找到 openssl，无法自动生成密钥，请手动填写"; ERR=1
  else
    TMP="$(mktemp -d)"
    if [ -z "$JWT" ] || [[ "$JWT" == *change-me* ]]; then
      set_env JWT_SECRET "$(openssl rand -hex 32)"; echo "  + 已生成 JWT_SECRET"
    fi
    if [ -z "$LIC" ] || [[ "$LIC" != *BEGIN* ]]; then
      openssl genpkey -algorithm ed25519 -out "$TMP/lic.pem" 2>/dev/null
      set_env LICENSE_PRIVATE_KEY_PEM "$(pem_to_oneline "$TMP/lic.pem")"; echo "  + 已生成 LICENSE_PRIVATE_KEY_PEM (Ed25519)"
    fi
    if [[ "$PENC" == "true" ]] && { [ -z "$PAY" ] || [[ "$PAY" != *BEGIN* ]]; }; then
      openssl ecparam -name prime256v1 -genkey -noout -out "$TMP/pay.pem" 2>/dev/null
      set_env PAYLOAD_CRYPTO_PRIVATE_KEY_PEM "$(pem_to_oneline "$TMP/pay.pem")"; echo "  + 已生成 PAYLOAD_CRYPTO_PRIVATE_KEY_PEM (P-256)"
    fi
    # 数据库口令（DATABASE_URL 中的占位口令）—— 启动闸门要求非 change-me
    if [[ "$DB" == *change-me* ]]; then
      DBPW="$(openssl rand -base64 18 | tr -dc 'A-Za-z0-9' | head -c 24)"
      NEWDB="$(printf '%s' "$DB" | sed -E 's#(://[^/:]+:)[^@]+(@)#\1'"$DBPW"'\2#')"
      set_env DATABASE_URL "$NEWDB"; echo "  + 已替换 DATABASE_URL 占位口令"
    fi
    # MinIO 根口令（启动闸门要求非 change-me；与 S3_SECRET_KEY 保持一致）
    if [[ "$MINIOPW" == *change-me* ]]; then
      MIPW="$(openssl rand -base64 18 | tr -dc 'A-Za-z0-9' | head -c 24)"
      set_env MINIO_ROOT_PASSWORD "$MIPW"; echo "  + 已生成 MINIO_ROOT_PASSWORD"
      if [[ "$S3SK" == *change-me* ]]; then
        set_env S3_SECRET_KEY "$MIPW"; echo "  + 已同步 S3_SECRET_KEY"
      fi
    fi
    rm -rf "$TMP"
    echo "  已写入 $ENV_FILE（请妥善保管，勿提交到仓库）"
  fi
fi

echo
if [ "$ERR" -ne 0 ]; then
  echo "✗ 校验未通过，请按上面提示补全 server/.env 后再运行 ./start.sh"
  [ "$GEN_SECRETS" -eq 0 ] && echo "  提示：可加 --gen-secrets 自动生成缺失密钥（JWT/License/Payload）"
  exit 1
fi
echo "✓ 配置校验通过，可运行 ./start.sh 启动。"
