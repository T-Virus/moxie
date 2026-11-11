# 源文件上传（客户端接入）

客户端不再需要把书稿放在服务端本机目录。先上传拿到 `source_key`，再创建任务即可。
服务端本机目录模式（`source_path` + `TASK_SOURCE_DIRS`）继续保留，作为可信运维入口。

## 1. 接口

| 方法 | 路径 | 说明 |
|---|---|---|
| `POST` | `/v1/uploads` | `multipart/form-data`，字段名 `file`；返回 `source_key` |
| `DELETE` | `/v1/uploads?key=<source_key>` | 删除自己的上传（任务产物不受影响） |

鉴权：`Authorization: Bearer <access_token>`（缺失返回 401 `unauthorized`）。

上传响应：

```json
{
  "source_key": "uploads/1/9f0c...-样本.txt",
  "filename": "样本.txt",
  "size": 123456,
  "content_type": "text/plain; charset=utf-8"
}
```

限制（`server/.env`，均有默认值）：

| 配置 | 默认 | 说明 |
|---|---|---|
| `UPLOAD_MAX_BYTES` | 30 MB | 超过返回 413 `source_too_large` |
| `UPLOAD_ALLOWED_EXTENSIONS` | `.txt,.md,.markdown,.csv,.json` | 其他返回 415 `unsupported_file_type` |
| `UPLOAD_RATE_LIMIT_PER_MINUTE` | 10 | 按账号限频，超限 429 `rate_limited` |
| `UPLOAD_RETENTION_DAYS` | 30 | scheduler 自动清理；0 = 不自动清理 |

## 2. curl 示例

```bash
BASE=http://127.0.0.1:8000
TOKEN=<access_token>

# 上传
curl -sS -X POST "$BASE/v1/uploads" \
  -H "Authorization: Bearer $TOKEN" \
  -F "file=@./样本.txt;type=text/plain"
# → {"source_key":"uploads/1/9f0c...-样本.txt", ...}

# 创建拆解任务（用 source_key，不再需要 source_path）
curl -sS -X POST "$BASE/v1/tasks" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Idempotency-Key: upload-demo-1" \
  -H "Content-Type: application/json" \
  -d '{
    "type": "decompose",
    "params": {
      "source_key": "uploads/1/9f0c...-样本.txt",
      "book": "样本",
      "mode": "reference",
      "limit": 3
    }
  }'

# 下载产物（沿用产物接口）
curl -sS "$BASE/v1/tasks/<task_id>/artifacts" -H "Authorization: Bearer $TOKEN"

# 主动删除上传源文件
curl -sS -X DELETE "$BASE/v1/uploads?key=uploads/1/9f0c...-样本.txt" \
  -H "Authorization: Bearer $TOKEN"
```

改编 / 审查任务同样把 `source_key` 放进 `params`：

```json
{"type": "adapt", "params": {"source_key": "uploads/1/xxx.json", "out_book": "新书"}}
```

## 3. 安全与归属

- 存储 key 形如 `uploads/<account_id>/<uuid>-<safe_name>`，账号前缀即归属边界；
- 上传文件名只取 basename，清洗路径分隔符、控制字符与前导点，杜绝目录穿越；
- 创建任务时校验 `source_key` 必须是「本账号的上传对象」或「本账号任务产物」：
  跨账号引用一律 404 `source_not_found`；
- 删除同理：跨账号返回 404 `upload_not_found`，不泄露对象是否存在；
- 对外只返回 `source_key`，不暴露 bucket / 磁盘路径；下载仍走已有产物接口与预签名。

## 4. 生命周期

| 场景 | 行为 |
|---|---|
| 任务失败 / 取消 | 上传源文件**保留**，便于修复后重跑；任务已完成的段与产物也不回滚 |
| 任务成功 | 上传源文件仍保留，直到显式删除或保留期到期；拆解产物内另有一份 `source.txt` |
| 显式删除 | `DELETE /v1/uploads?key=...`，只删上传对象，不影响已生成产物 |
| 自动清理 | scheduler 每轮 `cleanup_uploads`：超过 `UPLOAD_RETENTION_DAYS` 且未被 `queued/running` 任务引用才删除 |

路径模式（`source_path`）仍然只允许 `TASK_SOURCE_DIRS` 白名单内的文件；
`source_not_allowed` 只会在路径模式触发，上传模式不会出现该错误。

## 5. 客户端最小对接点

1. 首选上传：`POST /v1/uploads`（multipart，字段 `file`），保存返回的 `source_key`；
2. 创建任务时把 `source_key` 放进 `params`，可移除对 `source_path` 的依赖；
3. 错误处理按 `error.code` 分支：`401` 重新登录、`413` 提示文件过大、`415` 提示格式不支持、
   `429` 等待后重试、`404 source_not_found` 说明 key 失效或不属于当前账号；
4. 任务完成/取消后可调用删除接口回收上传源文件（可选；不删则按保留期自动清理）；
5. 无需改动任何下载逻辑：产物列表、预签名下载接口保持不变。
