# 客户端自动更新接口约定（桌面端）

> 本文只定义客户端需要的服务端契约，服务端尚未实现的部分按此补齐即可。
> 客户端实现见 `src/updater.py`，本机接口见 `src/webapp.py` 的 `/api/update/*`。
> 发布链脚本见 `ops/release/`（密钥、打包签名、本地验证），CI 见 `.github/workflows/release.yml`。

## 1. 版本清单（manifest）

推荐地址：`GET {base_url}/v1/updates/latest?platform=windows-x64&channel=stable`

也支持任意静态文件，例如 `https://download.example.com/moxie/version.json`（客户端对静态 URL 会忽略查询参数）。

响应示例：

```json
{
  "version": "1.1.0",
  "notes": "修复拆解长文本截断；新增 AIGC 标注导出。",
  "pub_date": "2026-11-04T08:00:00Z",
  "channel": "stable",
  "platforms": {
    "windows-x64": {
      "url": "https://download.example.com/moxie/Moxie-1.1.0-win-x64.zip",
      "size": 73400320,
      "sha256": "9f2c...（小写十六进制，64 字符）",
      "signature": "base64url(Ed25519 签名)",
      "key_id": "update-2026-01"
    }
  }
}
```

字段说明：

| 字段 | 必填 | 说明 |
| --- | --- | --- |
| `version` | 是 | 目标版本号，点分数字（`1.2.3`），客户端按段比较 |
| `notes` | 否 | 更新说明，展示给用户 |
| `pub_date` | 否 | 发布时间（ISO 8601） |
| `channel` | 否 | 渠道，当前客户端只使用 `stable` |
| `platforms` | 是 | 按平台给出安装包；也可直接平铺 `url/sha256/...`（单平台） |
| `platforms.*.url` | 是 | 安装包地址（绝对或相对 manifest 的 URL） |
| `platforms.*.size` | 否 | 字节数，用于下载进度与上限校验 |
| `platforms.*.sha256` | 是 | 安装包 SHA256（小写十六进制） |
| `platforms.*.signature` | 建议 | Ed25519 签名，见第 2 节 |
| `platforms.*.key_id` | 否 | 签名密钥编号，客户端可在 `public_keys` 里按编号取公钥 |

平台键：`windows-x64`（默认）、`windows-arm64`，由客户端按 `platform.machine()` 推断。

## 2. 签名规则

- 签名对象：`sha256` 字段的**小写十六进制字符串**（UTF-8 编码后 64 字节），不是安装包原文。
- 算法：Ed25519（与离线 License 同一套纯 Python 实现）。
- 编码：签名 base64url 无 padding；公钥同为 base64url 编码的 32 字节原始公钥。
- 客户端校验顺序：先算文件 SHA256 → 比对 `sha256` → 再验签（Constant-time 比对摘要）。

客户端配置 `config/update.json`：

```json
{
  "manifest_url": "https://api.example.com/v1/updates/latest",
  "channel": "stable",
  "public_key": "<base64url 32 字节>",
  "public_keys": { "update-2026-01": "<base64url 32 字节>" },
  "allow_unsigned": false
}
```

`allow_unsigned` 仅供内网/开发环境；正式环境必须为 `false`，无签名会被拒绝。

未单独配置 `manifest_url` 时，客户端会自动使用「云端服务地址 + `/v1/updates/latest`」；两边都没有则视为关闭自动更新。

## 3. 安装包格式

推荐 **zip**：解压后按相对路径覆盖应用目录，客户端会：

1. 解压到 `data/_system/updates/staged/<version>/`，拒绝 `..` 等越界路径；
2. 把要覆盖的现有文件备份到 `data/_system/updates/backup/<version>-<时间戳>/`；
3. 逐个原子替换；任一步失败自动从备份恢复并报错；
4. 写 `data/_system/updates/state.json` 记录生效版本；
5. 提示用户重启应用后生效（不强制杀进程）。

`exe` 安装包：客户端只下载与校验，`/api/update/apply` 返回 `installer_manual`，由用户手动运行；自动覆盖与回滚只对 zip 生效。

> Windows 注意：应用正在运行时，exe 等被占用的文件无法覆盖。若覆盖失败，客户端会自动从备份恢复并返回 `apply_failed`；
> 发布 zip 时建议不要把正在运行的 exe 放进覆盖清单，或提示用户退出应用后再安装。

## 4. 错误码（客户端本机接口）

| code | 含义 |
| --- | --- |
| `not_configured` | 未配置更新地址 |
| `manifest_invalid` | 清单不是合法 JSON 或缺少 `version` |
| `no_asset` | 清单里没有当前平台的安装包 |
| `download_failed` | 下载失败（网络/HTTP 非 2xx） |
| `checksum_mismatch` | SHA256 不一致，文件已删除 |
| `signature_required` | 清单要求签名但本机没有公钥/未允许无签名 |
| `signature_invalid` | Ed25519 验签失败 |
| `no_pending` | 没有已下载待安装的包 |
| `unsupported_package` | 不是 zip，不能自动覆盖 |
| `apply_failed` | 覆盖失败（已自动尝试回滚） |

## 5. 本机 HTTP 接口（桌面 Web 服务）

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/update/status` | 当前版本、待安装包、最近一次应用/回滚、配置 |
| POST | `/api/update/config` | 保存 `manifest_url/channel/public_key/public_keys/allow_unsigned` |
| POST | `/api/update/check` | 检查更新；断网时返回 `offline:true`、`available:false`，不弹错 |
| POST | `/api/update/download` | 下载 + SHA256 + 签名校验，落为 pending |
| POST | `/api/update/apply` | 覆盖安装（zip），提示重启；失败自动回滚 |
| POST | `/api/update/rollback` | 回滚到应用本次更新前的版本 |

启动时客户端会自动静默检查一次；断网、未配置、清单异常都不打扰用户，只有手动检查才展示原因。

## 6. 发布流程（静态清单 / CDN）

发布链不依赖服务端接口，任何能托管静态文件的 CDN、对象存储、GitHub Release 都可以。

### 6.1 本地或 CI 的固定步骤

```bash
# 1) 生成密钥（只做一次；私钥写入 CI secret）
python ops/release/gen_update_key.py --key-id update-2026-11

# 2) 构建前端（产物在 web/dist）
cd web && npm ci && npm run build && cd ..

# 3) 打包 + 签名（私钥 PEM 由环境变量注入，不落盘）
export MOXIE_UPDATE_PRIVATE_KEY_PEM="<CI secret 中的 PKCS#8 PEM>"
python ops/release/build_update.py \
  --version 1.2.3 \
  --source web/dist \
  --prefix web/dist \
  --output dist-release \
  --url-base https://cdn.example.com/moxie \
  --key-id update-2026-11 \
  --notes-file notes.md

# 4) 上传：整体同步 dist-release/ 到 CDN 根目录
#    静态服务需忽略查询参数（客户端会附加 ?platform=...&channel=...）
```

产物结构：

```
version.json                                   # 发布清单
latest.json                                    # 与 version.json 同内容，便于固定地址
packages/1.2.3/Moxie-1.2.3-windows-x64.zip     # 安装包
```

客户端最终拿到：

```
manifest_url = https://cdn.example.com/moxie/version.json
asset_url    = https://cdn.example.com/moxie/packages/1.2.3/Moxie-1.2.3-windows-x64.zip
```

`--prefix web/dist` 很重要：客户端按 zip 内相对路径覆盖应用根目录，省略前缀会把 `index.html`
覆盖到应用根目录而不是 `web/dist/`。

### 6.2 CI

`.github/workflows/release.yml` 在推送 `v*` tag 或手动触发时执行：

1. `npm ci && npm run build`；
2. `build_update.py` 打包签名；
3. 上传构建 artifact；
4. 发布 GitHub Release（默认分发方式），或配置 `vars.UPDATE_URL_BASE` 后同步 S3/CDN；
5. 缺少 `UPDATE_SIGNING_KEY_PEM` 时跳过签名与发布，并在 Summary 明确提示；
6. 未配置 `UPDATE_URL_BASE` 时用 GitHub Release 分发，缺少 S3 凭据只跳过对象存储；
7. 已配置 `UPDATE_URL_BASE` 但缺少 S3 凭据时跳过发布（避免上传指向空 CDN 的清单），只保留 artifact。

完整参数与 secrets 清单见 `ops/release/README.md`。

### 6.3 发布前检查

- `curl -fsS <manifest_url>` 返回合法 JSON，且 `version` 是本次版本；
- 清单里的 `url` 可直接下载，`size` 与 `sha256` 和 zip 一致；
- 用 `public_key` 验签通过（`python ops/release/verify_local.py` 可离线复现整条链）；
- 至少保留上一版本的 zip，便于手动回退排查。

## 7. 密钥轮换

客户端验证顺序：`public_keys[key_id]` → `public_key`。因此新密钥必须先进入客户端配置，才能用于签名。

推荐流程：

1. 生成新密钥（新 `key_id`，例如 `update-2027-01`），旧密钥继续留在 CI secret；
2. 用**旧私钥**发布一版客户端，`config/update.json` 的 `public_keys` 同时包含旧、新公钥；
3. 观察客户端升级覆盖（或灰度）后，把 CI secret 切到**新私钥**，后续清单使用新 `key_id`；
4. 至少保留旧公钥一个发布周期，确认无旧版本客户端后再移除。

注意：

- 客户端没有远程吊销机制；已安装的旧客户端仍会接受旧密钥签名，直到其配置被更新。
- 丢失私钥无法用同一 `key_id` 恢复；只能按上述流程轮换，并接受旧客户端无法再验证新清单。
- 私钥只存放于 CI secret；发布脚本只从环境变量读取，不写私钥文件。

## 8. 回滚与降级

- **客户端不会降级**：`updater._is_newer` 只接受更高版本号。把清单版本改回旧值，客户端会判定“已是最新”。
- **紧急回滚**：发布一个**更高的补丁版本**（例如故障版 `1.2.3` → 回滚版 `1.2.4`），内容使用旧版本产物；
  不要复用已发布过的版本号，否则 sha256 会与旧缓存冲突。
- **本机回滚**：`/api/update/rollback` 只能恢复到“本次更新前”的本地备份（`data/_system/updates/backup/...`），
  不是远程版本回退。
- 回滚后仍建议保留故障版本产物与清单，便于定位；不要立即删除 CDN 上的旧 zip。

## 9. CDN 缓存策略

| 对象 | 建议响应头 | 原因 |
| --- | --- | --- |
| `version.json` | `Cache-Control: public, max-age=300, must-revalidate` | 清单需要尽快生效 |
| `latest.json` | 同上 | 固定地址的别名 |
| `packages/<version>/*.zip` | `Cache-Control: public, max-age=31536000, immutable` | 路径含版本与平台，内容不变 |

- 发布后主动刷新/预热 `version.json`、`latest.json`；zip 走版本化路径，不需要刷新。
- 不要对清单使用 `immutable` 或超长 `max-age`，否则用户长时间看不到新版本。
- 客户端会在静态清单 URL 后追加 `?platform=...&channel=...`；CDN/静态服务器应忽略查询参数（Nginx、S3、GitHub Release 默认如此）。
- 使用 GitHub Release 的 `releases/latest/download/...` 时，地址会随最新 Release 变化；如需固定版本，使用
  `releases/download/<tag>/...`。
- 私有仓库的 Release 资产需要鉴权，当前客户端不带 token，只支持公开分发。

## 10. 清单字段与客户端契约核对

| 字段 | 客户端是否使用 | 说明 |
| --- | --- | --- |
| `version` | 是 | 点分数字比较；只升不降 |
| `notes` | 是 | 原样展示 |
| `pub_date` | 是 | 原样展示 |
| `channel` | 部分 | 读取并回显；不按渠道过滤清单 |
| `platforms` | 是 | 优先读取 `platforms[platform]`，缺失回退到平铺字段 |
| `url` / `size` / `sha256` / `signature` / `key_id` | 是 | 下载、大小校验、SHA256、验签、选公钥 |
| `min_os` | **否** | 客户端当前完全忽略；发布脚本只写入清单，不能依赖它拦截安装 |

发布脚本同时写平台映射与平铺字段，两种消费方式都兼容。其他边界：

- 清单上限 2MB、安装包上限 1GB，超限直接失败；
- `size` 非 0 时严格比对，大小不符返回 `download_failed`；
- 相对 `url` 会按清单 URL 解析，CDN 目录结构保持一致即可；
- `allow_unsigned=false` 时无签名包返回 `signature_required`，验签失败返回 `signature_invalid`。

