# 备份与恢复

脚本：`server/scripts/backup_restore.py`（仅标准库，SQLite / 本地存储可直接演练）。

```bash
cd server
python scripts/backup_restore.py backup  --out backups --keep 7
python scripts/backup_restore.py drill   --backup backups/backup-<ts>
python scripts/backup_restore.py restore --backup backups/backup-<ts> --force
```

## 1. 备份内容

```
backups/backup-<ts>/
├── db.sqlite            # SQLite 在线备份（sqlite3 backup API，含 integrity_check）
├── db.dump              # 或 PostgreSQL pg_dump -Fc 自定义格式
├── artifacts/           # STORAGE_BACKEND=local 时复制 STORAGE_LOCAL_DIR
├── minio-mirror.sh      # STORAGE_BACKEND=s3 时生成的 mc mirror 命令
└── manifest.json        # 时间、库类型、文件 sha256、存储后端、统计
```

- 默认 `STORAGE_BACKEND=db`：产物在 `stored_objects` 表内，数据库快照即完整备份，不会额外生成 `artifacts/`。
- SQLite：一致性快照（不锁库），备份后立即 `PRAGMA integrity_check`。
- PostgreSQL：`pg_dump -Fc`；需本机安装客户端。脚本检测不到 `pg_dump` 会直接报错退出，不会生成半成品备份。
- S3/MinIO：不内置云 SDK，生成 `mc mirror` 脚本，由运维在装好 `mc` 的机器执行。
- `--keep N` 只保留最近 N 份；`--dry-run` 只打印命令。

## 2. PostgreSQL 全量 + WAL

`pg_dump` 是**逻辑全量**，适合日常备份；需要时间点恢复（PITR）时额外开启 WAL 归档：

```conf
# postgresql.conf
wal_level = replica
archive_mode = on
archive_command = 'test ! -f /backup/wal/%f && cp %p /backup/wal/%f'
```

恢复顺序：

1. `pg_restore -c -d "$DATABASE_URL" backups/backup-<ts>/db.dump`（脚本已封装）；
2. PITR 场景：`pg_basebackup` 基线 + 回放 `/backup/wal` 到目标时间点（`recovery_target_time`）；
3. 校验：启动服务、`GET /readyz`、关键表行数、抽样订单/额度一致性。

WAL 归档目录需独立磁盘并纳入保留策略；`pg_dump` 与 WAL 任一路径缺失都不算完整灾备。

## 3. MinIO / S3

```bash
mc alias set backup https://minio.example.com ACCESS SECRET
mc mirror --overwrite backup/moxie-artifacts ./minio
# 恢复
mc mirror --overwrite ./minio backup/moxie-artifacts
```

建议对 bucket 开启版本控制；备份脚本生成的 `minio-mirror.sh` 只是命令模板，不包含密钥。

## 4. 恢复演练

`drill` 会：校验 manifest sha256 → 复制到临时目录 → `integrity_check` → 检查关键表 →
统计 artifacts 文件数，全部通过才输出 `[ok]`。

### 4.1 SQLite + 本地产物（已执行）

```text
$ python scripts/backup_restore.py backup --out tmp_backups --keep 0
[ok] 备份完成：...\tmp_backups\backup-20261104T153422Z

$ python scripts/backup_restore.py drill --backup tmp_backups/backup-20261104T153422Z
[ok] 恢复演练通过
  integrity_check=ok  tables=...  artifacts=1
  关键表行数={...}
  临时恢复目录=...（可人工确认后删除）
```

### 4.2 Docker Compose + 真实 PostgreSQL + MinIO（已执行，2026-11-04）

环境：Docker Desktop / WSL2，compose 服务 `postgres/redis/minio/api/worker/scheduler`，
`AUTO_CREATE_TABLES=false`，`alembic current` = `e5f6a7b8c9d0 (head)`。

数据库备份到新库：

```bash
# 1) 容器内 pg_dump（自定义格式）
docker compose exec -T postgres \
  sh -c "pg_dump -U moxie -d moxie -Fc -f /tmp/moxie.dump"   # 83,213 bytes

# 2) 恢复到一个全新的库
docker compose exec -T postgres \
  sh -c "dropdb -U moxie --if-exists moxie_restore && \
         createdb -U moxie moxie_restore && \
         pg_restore -U moxie -d moxie_restore /tmp/moxie.dump"

# 3) 行数对账（源库 / 恢复库完全一致）
accounts|3  audit_logs|21  devices|3  invoice_requests|0
orders|3    subscriptions|3  tasks|3  usage_events|6
```

恢复库抽样：`tasks.output_artifact` 仍指向 `e2e-book/<task_id>`，
`accounts.id/email/status/role` 与源库一致。

MinIO 产物备份与恢复：

```bash
# 备份桶 + 镜像
mc alias set local http://minio:9000 minioadmin ***
mc mb -p local/moxie-backup
mc mirror --overwrite local/moxie local/moxie-backup
# LIVE_OBJECTS=21  BACKUP_OBJECTS=21

# 模拟丢失一个产物后从备份桶恢复
mc rm local/moxie/e2e-book/<task>/chapters.json
# LIVE_AFTER_DELETE=20
mc mirror --overwrite local/moxie-backup local/moxie
# LIVE_RESTORED=21
# 恢复对象与备份对象 sha256 一致：
# 256f0c8c812c16f1e9a92294a6ac1712f29cde6bfdc55d73d8e7bb160997ca15
```

结论：数据库行数、任务产物引用、对象内容均校验通过；演练后删除临时库
`moxie_restore`、`/tmp/moxie.dump` 与备份桶。

## 5. 仍缺条件

- PITR（WAL 归档 + `pg_basebackup`）未演练，需要运维配置独立归档磁盘与监控；
- `mc mirror` 未开启跨机房/对象锁，生产建议开启 bucket 版本控制；
- 当前 compose 使用的 `S3_PUBLIC_ENDPOINT_URL=http://127.0.0.1:9000` 仅适合本机；
  生产需替换为浏览器可达的域名，否则预签名链接不可用（签名 host 必须与公开域名一致）。

