#!/usr/bin/env bash
# 墨写服务端 Postgres 逻辑备份（pg_dump custom format + gzip + 可选 GPG 加密）
#
# 用法：
#   PGHOST=127.0.0.1 PGUSER=moxie PGPASSWORD=... PGDATABASE=moxie \
#     ./ops/backup/pg_dump.sh
#   DATABASE_URL=postgresql://moxie:secret@127.0.0.1:5432/moxie ./ops/backup/pg_dump.sh
#
# 可选环境变量：
#   BACKUP_DIR       备份输出目录，默认 ops/backups/postgres
#   RETENTION_DAYS   保留天数，默认 14（0 表示不清理）
#   GPG_RECIPIENT    填写后使用 gpg --encrypt --recipient 加密
#
# 产物：<BACKUP_DIR>/moxie-YYYYmmdd-HHMMSS.dump.gz[.gpg] + .sha256
set -euo pipefail

BACKUP_DIR="${BACKUP_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)/ops/backups/postgres}"
RETENTION_DAYS="${RETENTION_DAYS:-14}"
STAMP="$(date +%Y%m%d-%H%M%S)"
OUT="${BACKUP_DIR}/moxie-${STAMP}.dump.gz"

mkdir -p "${BACKUP_DIR}"

if ! command -v pg_dump >/dev/null 2>&1; then
  echo "[x] 未找到 pg_dump，请安装 postgresql-client 或使用 docker exec 运行本脚本" >&2
  exit 127
fi

echo "[backup] pg_dump -> ${OUT}"
# custom format 支持 pg_restore 并行恢复；-Z9 由 pg_dump 内部压缩，再统一 gzip 一层兼容旧流程
pg_dump --format=custom --no-owner --no-privileges --compress=9 "${PGDATABASE:-moxie}" | gzip -9 > "${OUT}.tmp"
mv "${OUT}.tmp" "${OUT}"

if [[ -n "${GPG_RECIPIENT:-}" ]]; then
  command -v gpg >/dev/null 2>&1 || { echo "[x] GPG_RECIPIENT 已设置但未找到 gpg" >&2; exit 127; }
  gpg --batch --yes --encrypt --recipient "${GPG_RECIPIENT}" "${OUT}"
  rm -f "${OUT}"
  OUT="${OUT}.gpg"
fi

sha256sum "${OUT}" > "${OUT}.sha256"
echo "[backup] 完成：${OUT}"
echo "[backup] 校验：cat ${OUT}.sha256 | sha256sum -c"

if [[ "${RETENTION_DAYS}" != "0" ]]; then
  find "${BACKUP_DIR}" -type f \( -name 'moxie-*.dump.gz*' -o -name 'moxie-*.gpg*' \) \
    -mtime "+${RETENTION_DAYS}" -print -delete || true
fi
