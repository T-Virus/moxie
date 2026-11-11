# Moxie Agent 客户端（独立 Web 客户端）

**结论：** `client/` 是一套与旧 `web/` 完全独立的 Vue 3 + Vite + TypeScript 客户端，默认运行在 **5190** 端口，**全部数据走在线服务端接口**（`server/`），不在浏览器保存业务数据；筛选、草稿、作者名、发布状态等纯 UI 状态仍保留在本地。`npm run typecheck` 通过。

---

## 1. 快速开始

```powershell
cd client
npm install
npm run dev        # http://localhost:5190
```

启动前先运行 `server/`（默认 `127.0.0.1:8000`）。开发期由 Vite 把 `/v1` 代理到后端，不改服务端 CORS 白名单。

其他命令：

```powershell
npm run typecheck  # vue-tsc --noEmit
npm run build      # 产物在 client/dist
npm run preview    # 预览构建产物，端口 5190
```

### 环境变量

| 变量 | 默认值 | 作用 |
| --- | --- | --- |
| `VITE_API_BASE` | `/v1` | 接口前缀；生产可填 `https://api.example.com/v1` |
| `VITE_API_PROXY` | `http://127.0.0.1:8000` | 开发期 `/v1` 代理目标 |
| `VITE_MAX_UPLOAD_MB` | `20` | 上传文件前端预校验上限（MB） |

> 仓库内 `.env` 只含上述非敏感配置，不含任何密钥；本地覆盖请写 `.env.local`（已在 `.gitignore`）。

---

## 2. 目录结构

```
client/
├─ .env / .env.example       # 接口前缀、代理、上传上限
├─ index.html                # data-URI favicon，避免 404
├─ package.json              # 独立依赖与脚本
├─ tsconfig.json             # strict + noUnusedLocals
├─ vite.config.ts            # 端口 5190、strictPort、/v1 代理
└─ src/
   ├─ main.ts / App.vue / router.ts / types.ts
   ├─ styles/
   │  ├─ tokens.css          # 颜色、圆角、间距、字号、阴影 token
   │  └─ base.css            # 页面骨架、按钮/输入/卡片/徽标、响应式
   ├─ components/
   │  ├─ SegmentedTabs.vue   # 三 Tab（tablist + 方向键切换）
   │  ├─ GenrePicker.vue     # 预设题材下拉 + 自定义输入
   │  ├─ FileUploadChip.vue  # 文件类型/大小校验、文件名与大小展示、移除
   │  └─ AppDialog.vue       # 确认弹窗（Esc 关闭、自动聚焦）
   ├─ views/
   │  ├─ Home.vue            # 首页：三 Tab + 深色创作面板 + 校验
   │  ├─ Auth.vue            # 登录 / 注册
   │  ├─ Plans.vue           # 套餐、订阅状态、到期时间、额度
   │  ├─ Runs.vue            # 我的作品（历史运行）
   │  └─ Workspace.vue       # 工作台（阶段 / 内容 / 实时日志 / 产物）
   ├─ services/
   │  ├─ config.ts           # 环境变量集中出口
   │  ├─ http.ts             # ApiError、401 单飞刷新、下载
   │  ├─ agentApi.ts         # Agent 全套接口（全部走在线服务端）
   │  ├─ authApi.ts          # 登录注册 + 错误码中文提示
   │  └─ billingApi.ts       # 套餐 / 订阅 / 额度
   ├─ stores/session.ts      # 当前账号状态
   └─ utils/
      ├─ format.ts           # 模式/状态/阶段文案、字节、时间
      └─ download.ts         # Blob 下载
```

---

## 3. 页面与交互清单

### 首页 `/`

- 顶部三段 Tab：**热门写作 / 参考写作 / 大神写作**，`role="tablist"`，支持左右方向键切换；占位文案随 Tab 变化（如大神写作「输入书名，世界观与人物全部自定义」）。
- 中部深色渐变发光创作面板：大输入框（书名必填，右侧「必填」小标）+ 圆形上箭头发送按钮。
- 选项行：男频/女频、长篇/短篇、题材（预设下拉按频向过滤 + 自定义输入，显示「预设 · 自定义」）。
- 仅「参考写作」显示「+」上传：`.txt/.md/.markdown`、非空、≤ `VITE_MAX_UPLOAD_MB` 才接受；选中后显示文件名与大小、可移除/替换；隐藏 input 带 `aria-describedby` 说明。
- 校验不通过（缺书名、参考写作未选文件）时发送按钮禁用，并在面板下方就近提示（`role="alert"`）。
- 提交时先上传（若需要）再创建任务，带过渡遮罩；失败保留表单内容（草稿写入 sessionStorage）可重试。
- 未登录也可填写表单；提交时跳转登录并在登录后恢复草稿。

### 登录 / 注册 `/login`

- 邮箱 + 密码，客户端校验；错误码中文提示：401「账号或密码错误」、409「该邮箱已注册」、422 校验提示、429「操作过于频繁」、403 账号停用、网络错误。
- 登录成功后按 `next` 参数回到原页面。

### 套餐与订阅 `/plans`

- 未登录显示引导去登录（带 `next` 回跳）。
- 已登录展示：当前订阅（状态中文化、到期时间、剩余天数、到期不续费标记）、账期、额度卡片（已用/预占/上限/进度条）、3 张套餐卡（当前套餐高亮，购买按钮标注「购买暂未开放」）。
- 部分接口失败时显示可读错误与重试，不白屏。

### 我的作品 `/runs`

- 历史运行卡片：模式、状态、时间、进度、一句话故事；可「进入工作台」。
- 空态、未登录提示；列表数据全部来自服务端。

### 工作台 `/runs/:id`

- 左侧：5 个阶段节点（待开始/进行中/完成/失败）与阶段时间；任务状态、进度、额度。
- 中间：内容 Tab「章节 / 角色 / 势力 / 大纲摘要」，章节可展开正文；服务端未返回内容时显示占位与「刷新内容」，不空白。
- 右侧：实时日志（SSE 增量追加）；连接状态徽标（实时/轮询/断开）；**暂停滚动**（暂停后提示新日志条数，可继续）。
- 操作：**中断确认**（等待人工确认时可用；弹窗支持「仅确认通过」或「保存修改并继续」，可编辑章节正文）、**取消任务**（确认弹窗）、**下载产物**（带 Authorization，Blob 保存）、**刷新内容**。
- SSE 不可用时自动降级为 1.8s 轮询并在界面提示。

### 无障碍

- 全部按钮原生 `<button>`，可键盘触发；Tab 支持方向键；下拉支持 Enter/Esc/点击外部关闭；弹窗 `role="dialog"` + `aria-modal` + Esc。
- 上传控件有 `aria` 描述；错误提示 `role="alert"`；状态徽标文字与颜色并用。

---

## 4. 与接口契约的对应关系

| 契约 | 客户端方法（`src/services/agentApi.ts`） | 说明 |
| --- | --- | --- |
| `GET /v1/genres` | `fetchGenres()` | 题材预设由服务端下发；失败时页面显示可读错误 |
| `POST /v1/agent-runs` | `createRun(payload)` | 自动生成 `Idempotency-Key`（`crypto.randomUUID()`）；body 字段与契约一致 |
| `POST /v1/uploads` | `uploadSource(file)` | `FormData` 字段名 `file`；413/415 映射中文提示 |
| `GET /v1/agent-runs/{id}` | `getRun(id)` | 轮询与初始加载共用 |
| `GET /v1/agent-runs/{id}/events?since=` | `streamRunEvents(...)` | `fetch` + `ReadableStream` 手写 SSE（`EventSource` 无法带 Bearer）；解析 `data:` JSON，忽略心跳；缺失时工作台降级轮询 |
| `POST /v1/agent-runs/{id}/cancel` | `cancelRun(id)` | 工作台取消确认后调用 |
| `POST /v1/agent-runs/{id}/resume` | `resumeRun(id, payload)` | 两种形态：`{approval:true}` 或 `{input:{chapter_no,content}}` |
| `GET /v1/agent-runs/{id}/artifacts/{name}` | `downloadArtifact(id, name)` | 带 Authorization 拉取 Blob 后保存 |
| `GET /v1/plans` | `fetchPlans()`（`billingApi.ts`） | 套餐卡片 |
| `GET /v1/subscriptions/current` | `fetchCurrentSubscription()` | 404 `no_subscription` 归一化为「未订阅」 |
| `GET /v1/entitlements` | `fetchEntitlements()` | 额度余额与进度 |
| `/v1/auth/login`、`/register`、`/me`、`/logout` | `authApi.ts` | 401 单飞刷新（`ensureRefresh`）；错误体 `{error:{code,message,request_id}}` 统一归一化 |

**列表接口**：`GET /v1/agent-runs?limit=50`（服务端已提供），支持状态 / 模式 / 关键词等筛选参数；客户端不在本地缓存历史运行，换设备或清缓存后仍以服务端数据为准。

---

## 5. 数据来源

- 账号、题材、套餐、订阅、额度、运行记录、章节/角色/势力/道具/大纲、产物与上传源文件全部来自 `server/` 接口，服务端统一写入数据库。
- 浏览器只保留纯 UI 状态：筛选条件、首页草稿、作者名、发布状态等，不保存任何业务数据副本。
- SSE 断线自动降级为轮询；所有降级只影响展示方式，不改变数据来源。

---

## 6. 构建与浏览器实测

| 项目 | 结果 |
| --- | --- |
| `npm run typecheck` | 通过（vue-tsc，strict） |
| `npm run build` | 通过：68 modules，CSS 37.39 kB（gzip 7.19 kB），JS 181.86 kB（gzip 68.10 kB） |
| 首页三 Tab 切换 / 占位文案 | PASS |
| 空表单、缺书名、参考写作缺文件 → 禁用 + 就近提示 | PASS |
| 上传校验与文件名/大小/移除 | PASS |
| 登录 401 中文提示 / 登录成功 | PASS |
| 题材预设下拉点选 | PASS |
| 创建任务进入工作台 | PASS |
| SSE 日志增量（3 → 6）、连接状态「实时」 | PASS |
| 暂停滚动 + 新日志计数 | PASS |
| 5 个阶段节点、章节展开、角色/势力/大纲切换 | PASS |
| 中断确认 → 已完成、5 个产物 | PASS |
| 产物下载（`outline.md`，423 bytes） | PASS |
| 作品列表包含新任务、可再次进入 | PASS |
| 套餐 3 卡、当前订阅、未登录引导 | PASS |
| 1440 / 390 宽度无横向溢出 | PASS |
| 桌面端与移动端控制台 error | 0 |

截图自查目录（系统临时目录，不入库）：`C:\Users\LW\AppData\Local\Temp\mx_client_shots`（首页三种 Tab、上传态、登录、工作台运行/等待确认/完成、弹窗、作品列表、套餐、移动端）。

---

## 7. 已知限制

1. **强依赖服务端**：客户端不含任何 mock 或本地业务数据，`server/` 不可达时登录、列表、工作台均显示可读错误；开发期用 Vite `/v1` 代理。
2. **内容字段属可选扩展**：给定契约的 `GET /v1/agent-runs/{id}` 未列出章节正文/角色/势力/大纲，客户端按可选字段 `chapters/characters/factions/outline` 对接（服务端当前实现会返回）；缺失时显示「内容暂未返回」+「刷新内容」。
3. **历史列表分页**：列表来自 `GET /v1/agent-runs`，服务端分页参数变化时需要同步客户端 `runFilterQuery()`。
4. **运行中页面靠轮询兜底**：SSE 不可用时降级为 1.8s 轮询；刷新页面后重新拉取服务端状态，不依赖本地定时器。
5. **支付未接入**：套餐页只展示与状态查询，「购买暂未开放」，未接支付下单/回调。
6. **上传限制双份**：前端按 `VITE_MAX_UPLOAD_MB` 预校验，服务端仍可能有自己的上限；服务端 413/415 已映射中文提示。
7. **生产部署跨域**：开发期靠 Vite `/v1` 代理；生产需同域反代或把前端域名加入后端 CORS 白名单，并用 `VITE_API_BASE` 指向真实地址。

---

## 8. 真实后端联调（追加说明）

> 本节为与 `server/` 真实后端端到端联调后追加，只补充实际实现与映射规则，不改动上文已有字段名。

### 启动方式

客户端默认即在线模式，仓库内 `.env` 已指向 `/v1`；需要改端口时用本地覆盖文件：

```powershell
cd client
# .env.local（已被 .gitignore 忽略）
# VITE_API_PROXY=http://127.0.0.1:8013
npm run dev -- --port 5191
```

服务端（示例端口 8013；不要占用已有 8010/8765）：

```powershell
cd server
$env:DATABASE_URL="sqlite:///./tmp-e2e.db"
$env:AUTO_CREATE_TABLES="true"
$env:REDIS_ENABLED="false"
$env:STORAGE_BACKEND="local"
$env:MODEL_STUB="true"
$env:STORAGE_PUBLIC_BASE_URL="http://127.0.0.1:8013"
$env:CORS_ALLOW_ORIGINS="http://127.0.0.1:5191,http://localhost:5191"
.venv\Scripts\python.exe -m uvicorn app.main:app --port 8013
# 无 Redis 时手动推进队列：
.venv\Scripts\python.exe -m app.worker.worker --once
```

`vite.config.ts` 的 `/v1` 代理由 `VITE_API_PROXY` 决定，开发期不需要改服务端 CORS；但**产物签名下载 URL 是绝对地址**，由 `STORAGE_PUBLIC_BASE_URL` 生成，必须与浏览器可达的后端地址一致，否则下载会 404/连接失败。

### 状态枚举与字段映射

| 维度 | 服务端 | 客户端 |
| --- | --- | --- |
| 运行状态 | `queued / running / paused / succeeded / failed / canceled` | 同名（`RunStatus`） |
| 阶段状态 | `pending / running / done / failed / skipped` | `done` 映射为 `succeeded`（`StageState`） |
| 创建返回 | `{run_id,status,mode,created_at,created}` | 直接使用，忽略额外的 `enqueued` |
| 章节 | `chapter / title / summary / content / word_count` | `no / title / summary / content / words` |
| 角色 | `name / role / gender / personality / stance / faction` | 同名，缺字段留空 |
| 势力 | 对象（按势力名聚合）或数组 | `recordList()` 统一转为列表，两形态兼容 |
| 大纲 | `logline / theme / story_bible / chapters` | `logline / themes / beats` |

映射集中在 `src/services/agentApi.ts` 的 `normalizeRunDetail()`；服务端尚未产出的字段返回 `[]` / `{}`，工作台显示占位（「内容暂未返回」+「刷新内容」）而不是报错。

### 版权确认头

参考写作（`mode=reference`）会把用户上传的作品用于改编，服务端版权闸门要求显式确认：`createRun()` 对 reference **自动附带 `X-Rights-Confirmed: true`**。缺少该头会返回 `422 rights_confirmation_required`；该闸门在生产不可关闭，客户端不提供绕过开关。

### SSE 结束与重连

- 服务端在 `data: {...}` 后以 `event: end` 结束；进入 `succeeded / failed / canceled / paused` 后流自动关闭。
- 客户端收到流结束后先 `GET /v1/agent-runs/{id}` 取最终状态：
  - 终态 → 停止连接并显示「已结束」；
  - `paused` → 展示中断确认 UI，等待用户 resume；
  - 其余（连接被 60s 上限截断）→ 按最后 `seq` 以 `since` 重连续传。
- 不再出现终态下每 2s 空转重连的问题。

### 产物下载

- `.json`：`GET /v1/agent-runs/{id}/artifacts/chapters.json` 直接返回内容，客户端保存原始文本。
- `.md`：接口返回 `{name,size,url,expires_in}` 元数据；`apiDownload()` 识别 JSON 响应后对 `url` 二次 `fetch`（不带 Authorization，签名 URL 自带鉴权），再以 Blob 保存为 `name`。
- 首次请求带 Bearer；若返回 `401` 走统一刷新逻辑。

### 真实联调结果（MODEL_STUB）

- 注册/登录、无订阅创建运行 → `403 subscription_required`（页面提示「请先在套餐页开通」）。
- 参考写作：上传 `.txt` → `POST /v1/uploads` 返回 `source_key` → 带版权头创建 run → worker 推进 → 5 阶段完成、SSE 增量日志、章节/角色/势力/大纲、`chapters.json`/`outline.md` 下载。
- 热门写作 4 阶段、大神写作 4 阶段，状态流转与产物结构正确（内容为 stub 占位）。
- 中断/恢复：review 高危暂停 → 页面提交修改 `/resume` → 状态回到 `queued → running → succeeded`。
- 取消、作品列表回访、整页刷新后状态一致；1440 / 390 宽度无横向溢出，控制台 0 error。

### 真实模式仍存在的限制

1. **内容质量**：`MODEL_STUB=true` 只验证结构与状态流转，产出的章节/角色是占位文本；真实模型质量需接入平台密钥或 BYOK 后再评估。
2. **暂停触发**：stub 下 review 不会自然判定高危，暂停链路的浏览器实测使用了测试专用 worker 注入；生产需真实模型 + 真实审查规则。
3. **支付 / 邮件**：订阅开通仍无支付回调，测试用 mock provider 直接开通；SMTP/短信未接。
4. **跨域部署**：生产需正确配置 `CORS_ALLOW_ORIGINS` 与 `STORAGE_PUBLIC_BASE_URL`（或同域反代），否则签名下载会失败；开发期靠 Vite 代理规避。
5. **历史列表**：真实模式按 `GET /v1/agent-runs?limit=50` 获取，接口失败时才回退本机记录。

---

## 9. 工作台数据与筛选映射（第二轮联调追加）

> 本节只追加第二轮真实链路核对后的字段映射与显示规则，不改动上文已有字段名。

### 工作台 7 Tab 数据来源

| Tab | 数据来源 | 说明 |
| --- | --- | --- |
| 作品信息 | `summary` + `chapters` | `chapters_count / word_count / items_count / updated_at` |
| 工作台大纲 | `outline.md` 产物 | 解析为章节列表，另提供纯文本/富文本切换 |
| 角色卡 | `characters` | 卡片 + 抽屉详情，支持姓名/别名搜索、势力/类型过滤 |
| 势力表 | `factions` | 表格 + 窄屏卡片，支持立场过滤、成员展开 |
| 道具功法 | `items` | 类别/品阶/归属/效果/代价/说明 |
| 章节概括 | `chapter_summaries`（为空回退 `chapters`） | 按 `no` 升序，与正文一一对应 |
| 作品正文 | `chapters_full.json` / `manuscript.md` | 目录跳转、字号行距、导出全本 |

### 字段映射（`normalizeRunDetail`）

| 服务端原始字段 | 客户端字段 | 规则 |
| --- | --- | --- |
| `characters[].role` | `type` | 角色类型（主角/配角/反派） |
| `characters[].identity` | `role` | 身份 |
| `characters[].affiliation` / `faction` | `faction` | 所属势力 |
| `characters[].camp` / `stance` | `camp` | 阵营 |
| `characters[].relations[{target,type}]` | `relations: string[]` | 转为「目标（关系）」 |
| `characters[].description` 缺省 | `description` | 回退 `appearance · arc`，再回退 `personality · goal` |
| `characters[].gender` | 原样显示 | `male/男→男`、`female/女→女`，`未知` 等中文枚举透传，不改成「其他」 |
| `factions[].members[]`（字符串或对象） | `members[{name,role,relation}]` | 字符串转对象；对象读取 `name/role/identity` |
| `factions[].relations[{target,type}]` | `members[].relation` | 关系合入同名成员；只有关系无名单时补成成员 |
| `factions[].type` / `category` | `type` | 兼容旧拆解数据 |
| `factions[].members_count` | `members_count` | 仅服务端提供或成员非空时赋值；否则留空，页面显示「—」而不是 0 |
| `factions[].goal` / `desc` | `description` | 无 `description` 时的回退 |
| `items[].category` / `kind` | `category` | stub 用 `kind`，真实技能用 `category` |
| `items[].description` | `description` | 依次回退 `notes`（真实）→ `desc`（stub）→ `effect` |
| `items[].grade/owner/effect/cost` | 同名 | 品阶/归属/效果/代价 |
| `chapters[].chapter` / `no` | `no` | 序号统一为 `no` |
| `chapters[].word_count` / `words` | `words` | 字数统一为 `words` |
| `chapter_summaries[].chapter_no` / `chapter` / `no` | `no` | 按 `no` 升序，保证与正文对应 |
| `chapter_summaries[].word_count` | `words` | — |
| `summary.word_count` | 作品信息「总字数」 | 大于 0 时直接显示；否则章节字数求和；仍为 0 显示「—」 |
| `summary.items_count` | 作品信息「道具功法」 | 缺省时回退 `items.length`；无值显示「—」 |
| `summary.updated_at` | 作品信息「最近更新」时间 | 优先 `summary.updated_at`，再 `run.updated_at`、`created_at`、阶段时间 |

### 列表筛选与「共 N 部」

- 筛选条参数与后端同名：`mode / audience / length / genre`，组合为 AND；
- 点「全部」或清除筛选时**不拼接任何参数**，实际请求为 `GET /agent-runs?limit=50`；
- 命中数优先取后端 `total`（未分页总数），后端未返回时才回退当前页 `items.length`；
- 筛选状态同步到 URL query 与 `sessionStorage`，刷新后保持。

### 套餐显示

- 公开列表三档：`experience / creator / professional`，客户端 `ALLOWED_PLAN_CODES` 只保留这三档，避免服务端新增/下架项导致整页空白；
- 价格单位是分：`990 → ¥9.9`、`2990 → ¥29.9`、`6990 → ¥69.9`；
- `books_month` 从 `entitlements` 读取，与订阅/额度接口一致（专业版 15 本）。
