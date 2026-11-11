# 备份与恢复（ops/backup）

| 文件 | 用途 | 依赖 |
| --- | --- | --- |
| `pg_dump.sh` | Postgres 逻辑备份（custom format + gzip + 可选 GPG） | `pg_dump` |
| `minio_sync.sh` | MinIO/S3 产物镜像到本地 | `mc` |
| `sqlite_drill.py` | SQLite + 本地存储备份/恢复演练（自动校验） | Python 标准库 |
| `restore-drill.md` | 完整恢复演练步骤与验收清单 | — |

## 常用命令

```bash
# Postgres 备份（保留 14 天）
PGHOST=127.0.0.1 PGUSER=moxie PGPASSWORD=*** PGDATABASE=moxie \
  ./ops/backup/pg_dump.sh

# MinIO 产物同步
MINIO_ENDPOINT=http://127.0.0.1:9000 MINIO_ACCESS_KEY=*** MINIO_SECRET_KEY=*** \
S3_BUCKET=moxie ./ops/backup/minio_sync.sh

# 无 Docker 的 SQLite + 本地存储演练
python ops/backup/sqlite_drill.py
```

产物默认写入 `ops/backups/`（已在 `.gitignore` 中排除，避免用户数据入库）。

## 本地演练结果

本机无 `pg_dump` / `mc` / Docker，已执行 `sqlite_drill.py` 并记录结果（见 `docs/engineering.md`）。
Postgres / MinIO 步骤需在具备相应工具的环境执行。
