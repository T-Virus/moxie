#!/usr/bin/env bash
# 墨写产物存储同步：MinIO / S3 -> 本地备份目录（mc mirror）
#
# 用法：
#   MINIO_ALIAS=moxie MINIO_ENDPOINT=http://127.0.0.1:9000 \
#   MINIO_ACCESS_KEY=... MINIO_SECRET_KEY=... S3_BUCKET=moxie \
#     ./ops/backup/minio_sync.sh
#
# 可选：
#   BACKUP_DIR       默认 ops/backups/minio
#   MC_EXTRA_ARGS    mc mirror 额外参数（例如 "--exclude 'tmp/*'"）
#
# 说明：本脚本只做「云 -> 本地」的单向镜像，不删除本地已有文件；
#       需要严格镜像清理时显式加 --remove。
set -euo pipefail

BACKUP_DIR="${BACKUP_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)/ops/backups/minio}"
ALIAS="${MINIO_ALIAS:-moxie}"
ENDPOINT="${MINIO_ENDPOINT:-http://127.0.0.1:9000}"
ACCESS_KEY="${MINIO_ACCESS_KEY:?MINIO_ACCESS_KEY 未设置}"
SECRET_KEY="${MINIO_SECRET_KEY:?MINIO_SECRET_KEY 未设置}"
BUCKET="${S3_BUCKET:-moxie}"

if ! command -v mc >/dev/null 2>&1; then
  echo "[x] 未找到 mc（MinIO Client），请先安装：https://min.io/docs/minio/linux/reference/minio-mc.html" >&2
  exit 127
fi

mkdir -p "${BACKUP_DIR}/${BUCKET}"

echo "[mirror] 配置别名 ${ALIAS} -> ${ENDPOINT}"
mc alias set "${ALIAS}" "${ENDPOINT}" "${ACCESS_KEY}" "${SECRET_KEY}" --api S3v4 >/dev/null

echo "[mirror] ${ALIAS}/${BUCKET} -> ${BACKUP_DIR}/${BUCKET}"
# shellcheck disable=SC2086
mc mirror --overwrite ${MC_EXTRA_ARGS:-} "${ALIAS}/${BUCKET}" "${BACKUP_DIR}/${BUCKET}"

echo "[mirror] 完成；文件数：$(find "${BACKUP_DIR}/${BUCKET}" -type f | wc -l)"
