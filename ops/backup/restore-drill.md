# 备份与恢复演练步骤

本文档描述墨写服务端（Postgres + MinIO/S3 + 本地磁盘 fallback）的恢复演练流程。
演练目标：在隔离环境用备份恢复出一套可登录、可查询任务、可下载产物的服务，并记录 RPO/RTO。

## 0. 准备

- 工具：`pg_dump` / `pg_restore` / `psql`（postgresql-client）、`mc`（MinIO Client）、Docker（可选）
- 备份产物：`ops/backups/postgres/*.dump.gz`、`ops/backups/minio/<bucket>/`
- 隔离环境：不要在生产库上做恢复演练；使用新的数据库（如 `moxie_restore`）与新的 bucket

## 1. 数据库恢复（Postgres）

```bash
# 1.1 解压并校验备份完整性
gunzip -c ops/backups/postgres/moxie-20261104-120000.dump.gz > /tmp/moxie.dump
sha256sum -c ops/backups/postgres/moxie-20261104-120000.dump.gz.sha256

# 1.2 建空库（隔离实例）
createdb -h 127.0.0.1 -U moxie moxie_restore

# 1.3 并行恢复（custom format 支持多 worker）
pg_restore -h 127.0.0.1 -U moxie -d moxie_restore \
  --no-owner --no-privileges --clean --if-exists -j 4 /tmp/moxie.dump

# 1.4 基础校验
psql -h 127.0.0.1 -U moxie -d moxie_restore -c "\dt"
psql -h 127.0.0.1 -U moxie -d moxie_restore -c "select count(*) from accounts;"
psql -h 127.0.0.1 -U moxie -d moxie_restore -c "select count(*) from tasks;"
```

> 若使用 Docker Compose 的 Postgres：
> `docker compose -f server/docker-compose.yml exec -T postgres pg_dump -U moxie moxie | gzip > backup.dump.gz`
> 恢复时把文件 `docker cp` 进容器后执行 `pg_restore`。

把恢复后的服务指向新库（只改环境变量，不改代码）：

```bash
DATABASE_URL=postgresql+psycopg://moxie:密码@127.0.0.1:5432/moxie_restore \
AUTO_CREATE_TABLES=false \
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

## 2. 产物恢复（MinIO / S3）

```bash
# 2.1 恢复到一个新的 bucket（避免覆盖生产）
mc mb myminio/moxie-restore
mc mirror --overwrite ops/backups/minio/moxie myminio/moxie-restore

# 2.2 抽查对象
mc ls -r myminio/moxie-restore | head -n 20
```

服务端切换：`STORAGE_BACKEND=s3`、`S3_BUCKET=moxie-restore`，或本地 fallback 时使用
`STORAGE_BACKEND=local` + `STORAGE_LOCAL_DIR=<恢复后的本地产物目录>`。
`storage.py` 的 local 与 s3 接口行为一致，切换不需要改代码。

## 3. 本地 fallback / SQLite 演练（无需 Docker）

```bash
python ops/backup/sqlite_drill.py
```

脚本会：创建样例库 → 在线备份 → 删除原库与产物 → 从备份恢复 → 校验行数与文件 SHA-256。
预期最后一行输出 `PASS：SQLite + 本地存储备份/恢复演练通过`。

## 4. 功能验收清单

恢复后逐项验证：

- [ ] `GET /healthz` 返回 200
- [ ] `GET /readyz` 数据库可用
- [ ] 注册 / 登录成功（`POST /v1/auth/register`、`POST /v1/auth/login`）
- [ ] 额度接口返回与备份前一致（`GET /v1/entitlements`）
- [ ] 任务详情可查（`GET /v1/tasks/{id}`）
- [ ] 产物下载可用（`GET /v1/artifacts/{task_id}/{name}` 或预签名 URL）
- [ ] 日志中无明文提示词 / 密钥

## 5. 记录模板

| 项目 | 记录 |
| --- | --- |
| 备份时间 | 2026-11-04 22:30 |
| 备份大小 | 例：DB 12.4 MB / 产物 86 MB |
| 恢复开始 / 结束 | 例：22:35 / 22:41 |
| RTO | 例：6 分钟 |
| RPO | 等于备份周期（建议 ≤ 24h，重要数据可 6h） |
| 数据校验 | 行数一致、抽样任务与产物可下载 |
| 结论 | PASS / FAIL + 待办 |

## 6. 演练频率建议

- 每月一次：SQLite/本地 fallback 演练（脚本自动，低成本）
- 每季度一次：Postgres + MinIO 全链路演练（隔离环境）
- 每次大版本发布前：至少做一次数据库恢复校验

## 7. 已知限制

- 本机未安装 `pg_dump` / `mc` / Docker 时，只能跑 SQLite 演练；Postgres/MinIO 步骤需在具备工具的环境执行。
- 备份文件含用户数据，传输与落盘应加密（`GPG_RECIPIENT`）并限制访问权限。
