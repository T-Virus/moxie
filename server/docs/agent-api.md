# Agent + 类型化 Skill 编排层（/v1/agent-runs）

## 1. 定位

为全新客户端提供三种写作模式的统一入口：`hot`（跟热门）、`reference`（参考改编）、`custom`（按 brief 定制）。
本层只新增 `server/app/agents/` 与 `/v1/agent-runs`，**不改** `/v1/tasks` 的既有行为，也不改 `src/`、`web/`、`data/`。

核心原则：

- **图是确定性的**：节点、依赖、并发层、重试次数全部写死在 `app/agents/graph.py`；LLM 只用于「意图→计划参数」（当前由请求体显式给出）与 skill 内部生成，**不允许 LLM 决定下一步**。
- **skill 是纯函数**：Pydantic 强类型入参/出参，不读写数据库与存储，可独立单测；模型调用统一走 `services/model_gateway.py`（支持 BYOK / 平台密钥 / `MODEL_STUB`）。
- **可续跑**：每个节点完成后写 `agent_run_steps` checkpoint；worker 重启只补跑未完成节点。
- **可人工介入**：`review` 命中高危问题时暂停（仅 `reference/custom`），`resume` 携带修改或确认后继续；`hot` 不产生 `interrupt`，直接跑完。
- **长文本分段**：`reference` 的拆解节点按字数/章数自动分段，段级 checkpoint、段级重试与段级 SSE 进度，全书章节连续编号。

## 2. 目录结构

```
server/app/agents/
├── contracts.py        # StrictModel、SkillContext、call_json
├── genres.py           # 题材目录
├── graph.py            # NodeSpec / Graph / 三张 DAG / 拓扑分层
├── registry.py         # 技能注册表与版本号
├── engine.py           # 拓扑执行、同层并发、重试、checkpoint、分段执行、暂停
├── segmenter.py        # reference 分段规划 + 跨段章节重编号/角色势力合并
├── artifacts.py        # outline.md / chapters.json / story_bible.json / hot_research.json / hot_preview.md / decomposed.json
├── store.py            # 运行 CRUD、取消、恢复、详情序列化、额度块
└── skills/
    ├── genre_research.py
    ├── outline_decompose.py
    ├── adaptation.py
    ├── outline.py
    ├── chapter_expand.py
    ├── character_graph.py
    └── review.py
```

## 3. 技能清单与版本

| 技能 | 版本 | 作用 | 复用 |
| --- | --- | --- | --- |
| `genre_research` | 1.0.0 | 同题材热门作品特征与前三章概括 | 无可信检索源时只用模型知识，`sources` 标注 `model_inference` |
| `outline_decompose` | 1.0.0 | 上传大纲/正文拆解（按段调用，跨段合并） | `app/prompts/decompose.py`（薄封装 `src/decompose.py`），含本地拆解兜底 |
| `adaptation` | 1.0.0 | 去抄袭改编（换名/换设定/改写正文） | `app/prompts/adapt.py`（薄封装 `src/adapt.py`），含 `local_adapt` 兜底 |
| `outline` | 1.0.0 | 分章大纲规划 | 汇总调研/拆解/改编素材 |
| `chapter_write` | 1.0.0 | 逐章正文写作（章级节点 `chapter_expand` 使用） | 引擎按章调用；模型缺失时确定性兜底，正文非空 |
| `chapter_summarize` | 1.0.0 | 逐章概括（80-200 字 + 冲突 + 钩子） | 章级节点 `chapter_summarize` 使用；模型缺失时确定性兜底 |
| `lore_extract` | 1.0.0 | 角色卡 / 势力表 / 道具功法统一抽取 | 章级节点 `character_graph` 使用；字段齐全，空输入有默认设定 |
| `hot_preview` | 1.0.0 | 前三章概览（150-300 字梗概 + 主线冲突 + 人物关系） | 基于前三章正文/大纲，模型失败时确定性兜底 |
| `review` | 1.0.0 | 签约体检与改写建议 | 模型结果 + 本地确定性检查合并 |

> 旧技能 `chapter_expand`、`character_graph` 仍保留类与注册名以兼容自定义图；三种内置图分别改用 `chapter_write` / `lore_extract`。

### 3.1 章级节点

标记 `chaptered=True` 的节点由引擎按 builder 给出的 `chapters` 逐章执行：

| 行为 | 说明 |
| --- | --- |
| checkpoint | `agent_run_steps.node_key = <node_id>:ch:NNN`；已完成章跳过 |
| 单章重试 | 单章失败只重试当前章（节点 `retries=1`，最多 2 次），不影响其他章 |
| SSE | `第 n/m 章开始：<标题>`、`第 n/m 章完成`、断点续跑 `第 n/m 章已完成，断点续跑跳过` |
| 额度 | `chapter_write` 预占 `adapt_chapters`（按章数）并按实际字数结算 `managed_chars`；不足返回错误码 `quota_exceeded` |
| 计量 | 每次模型调用 `usage_events` 幂等键含 `node/ch/a<attempt>`；`/metrics` 记章数与字数 |

> 热门调研的检索适配位：`GenreResearchSkill` 只消费 `works` 与 `sources`；接入真实搜索时替换数据来源即可，**不得伪造引用/榜单**。

## 4. 三种模式的图

`hot`
```
genre_research → outline → chapter_expand(chapter_write，3 章)
  → hot_preview ┐
  → chapter_summarize(chaptered) → character_graph(lore_extract) → review
```
> `review` 只记录风险与建议，任何模式都不会 `paused` 等待人工确认，运行直接 `succeeded`；`hot` 正文/概括/概览均固定 3 章，`summary.chapters_count=3`。

`reference`
```
outline_decompose(source_key，分段) → adaptation → outline
  → chapter_expand(chapter_write，全部改编章节) → chapter_summarize(chaptered)
  → character_graph(lore_extract) → review
```

`custom`
```
outline → chapter_expand(chapter_write，大纲目标章数) → chapter_summarize(chaptered)
  → character_graph(lore_extract) → review
```

章节写作、概括、设定抽取按图序串行；`hot_preview` 可与 `chapter_summarize` 同层并发。节点默认 1 次重试（最多 2 次尝试），章级节点按章重试。

### 4.1 reference 分段拆解（`outline_decompose`）

`reference` 的拆解节点标记为 `segmented=True`，由 `agents/segmenter.py` 规划后逐段调用同一技能；技能本身不再截断正文（已移除旧的 `text[:20000]` / `[:16000]`）。

| 配置项 | 默认值 | 说明 |
| --- | --- | --- |
| `AGENT_SEGMENT_CHARS` | `6000` | 单段目标字数，与 `runners/decompose.py` 的 `chunk_chars` 对齐 |
| `AGENT_SEGMENT_CHAPTERS` | `2` | 单段最多章数，与 runner 的 `chunk_chapters` 对齐 |
| `AGENT_OUTLINE_SINGLE_SEGMENT_CHARS` | `20000` | 无章回结构且不超过该字数 → 视为结构化大纲，整本单段（不硬切碎） |
| `AGENT_MAX_SOURCE_CHARS` | `600000` | 单本正文上限（≈100 段 × 6000 字）；超出显式失败，不截断 |
| `AGENT_MAX_SEGMENTS` | `100` | 规划段数上限；超出显式失败 |

行为约定：

- **切点**：优先章首，其次段落/换行；无换行的超长段兜底在句末标点（`。！？；…`）切分，不切断句子。切段后各段原文按序拼接与源文完全一致。
- **段级产物**：`<书名>/<run_id>/segments/seg-001.json` …，逐段落盘；全部完成后合并为 `decomposed.json`（含 `segmentation` 与 `segments` 元数据）。
- **段级 checkpoint**：`agent_run_steps.node_key = outline_decompose:seg:NNN`。重跑时已完成段直接跳过（产物缺失视为损坏并重跑该段）；单段失败只重试当前段（节点 `retries=1`，最多 2 次），不影响已完成段。
- **跨段合并**：章节按段序拼接并全局重编号 `1..N`；角色/势力/道具同名或别名合并（保留 `aliases`）；`summary.chapters_count` 取全书拆解章节数。
- **成本记账**：每段每次模型调用单独写 `usage_events`，幂等键含 `seg` 序号；`tokens_total/cost_cents` 按段累加，不会因分段绕过 `books_month`（每次运行仍只预占 1 本）。

错误码（运行失败时写入 `GET /v1/agent-runs/{id}` 的 `error.code`）：

| 错误码 | 触发 |
| --- | --- |
| `source_too_large` | 解码后字符数 > `AGENT_MAX_SOURCE_CHARS` |
| `source_too_many_segments` | 规划段数 > `AGENT_MAX_SEGMENTS` |
| `source_empty` | 源文件没有可拆解内容 |
| `segment_failed` | 某一段重试耗尽；`resume(retry_failed)` 只重跑失败段及后续段 |

> 上传接口上限 30MB 是文件层面；Agent 参考写作另有 60 万字符的正文上限。按 6000 字/段与单次模型调用 20-40s 估算，100 段接近 worker 单任务可接受上限，超过请拆分文件或调大 `AGENT_SEGMENT_CHARS`。

## 5. 状态机

```
queued ──worker──> running ──全部节点完成──> succeeded
   │                 │
   │                 ├──节点重试耗尽──> failed ──resume(retry_failed)──> queued
   │                 └──用户停止──────> paused ──resume──> queued   └──cancel──> canceled
```

- `queued/paused` 取消：立即 `canceled` 并释放预占额度。
- `running` 取消：置协作式 `cancel_requested`，在下一个节点边界停止并释放额度；分段节点在段边界检查，已完成的段保留 checkpoint。
- 所有模式 `review` 高危都不进入 `paused`，风险与建议写入 `run.meta` 与事件流，运行继续到 `succeeded`；任务执行过程中不存在需要用户确认的环节。
- `failed` 恢复：`{"retry_failed": true}` 重新预占 `books_month`，**只重置失败节点**，已完成节点复用 checkpoint。
- `paused` 恢复：用户主动停止的运行直接续跑；历史审查暂停的运行仍兼容 `{"approval": true}` 或 `{"input":{"chapter_no","content"}}`。
- 非 `paused/failed` 调 `resume` 一律 `409 invalid_state`。

## 6. 接口

前缀 `/v1`，Bearer 鉴权；除 `GET /v1/genres` 外均按账号隔离，越权返回 `404`。

### 6.1 题材目录

```bash
curl -s http://127.0.0.1:8010/v1/genres
```

```json
{"items":[{"id":"xuanyi","name":"悬疑","audience":["male","female","all"],"tags":["推理","反转","罪案"]}],"custom_allowed":true}
```

### 6.2 创建运行

```bash
curl -s -X POST http://127.0.0.1:8010/v1/agent-runs \
  -H "Authorization: Bearer $TOKEN" \
  -H "Idempotency-Key: my-run-001" \
  -H "Content-Type: application/json" \
  -d '{
    "mode": "reference",
    "title": "夜雨改编样书",
    "audience": "male",
    "length": "short",
    "genre": {"id": "xuanyi", "name": "悬疑"},
    "source_key": "uploads/12/abcd.txt",
    "brief": "保留悬疑骨架，换名换设定。"
  }'
```

```json
{"run_id":"40a52fc3-...","status":"queued","mode":"reference","created_at":"2026-11-05T04:20:29+00:00","created":true,"enqueued":false}
```

返回恒为 `201`；同一 `Idempotency-Key` 重复提交返回同一 `run_id`（`created:false`），不重复预占额度。

校验与错误：

| 场景 | HTTP | code |
| --- | --- | --- |
| `reference` 缺 `source_key` | 422 | `source_key_required` |
| `source_key` 不属于当前账号/不存在 | 404 | `source_not_found` |
| 开启版权闸门但未带 `X-Rights-Confirmed: true` | 422 | `rights_confirmation_required` |
| 无有效订阅 | 403 | `subscription_required` |
| `books_month` 额度不足 | 402 | `quota_exceeded` |
| 字段非法 | 422 | `invalid_request` |

BYOK（可选）：创建与续跑均可带 `X-BYOK-Key: <你的模型 API Key>`。服务端只把 Key 写入 Redis
`agent:byok:<run_id>`（TTL 1 小时），worker 使用后即丢弃；不落库、不写日志、不出现在任何响应中。
未带该头时使用平台托管 Key。

高级选项（可选，`custom` / `reference`）：

```json
"options": {
  "target_chapters": 20,
  "sequel_chapters": 5,
  "adaptation_style": "都市高武 · 爽感直给，短句为主",
  "adaptation_extra": "主角改为女性，加入直播元素"
}
```

- `target_chapters`：目标章数；留空按篇幅默认（长篇 12 / 短篇 6）。
- `sequel_chapters`：在目标章数之后追加的续写章数。
- `adaptation_style` / `adaptation_extra`：仅 `reference` 生效，分别控制改编文风与额外要求。
- 选项原样保存在 `run.meta.options`，详情接口通过 `options` 字段回显。

### 6.3 列表与详情

```bash
curl -s "http://127.0.0.1:8010/v1/agent-runs?limit=20&offset=0" -H "Authorization: Bearer $TOKEN"
curl -s "http://127.0.0.1:8010/v1/agent-runs/$RUN_ID" -H "Authorization: Bearer $TOKEN"
```

列表查询参数（全部可选，不传即不过滤；组合为 AND）：

| 参数 | 取值 | 说明 |
|---|---|---|
| `mode` | `hot` / `reference` / `custom` | 写作模式；客户端「全部」= 不传 |
| `audience` | `male` / `female` | 目标读者 |
| `length` | `long` / `short` | 篇幅 |
| `genre` | 题材 id 或中文名（如 `xuanyi` / `悬疑`） | 与创建时一致；不存在时返回空列表，不报错 |
| `limit` | 1–100，默认 20 | 分页大小 |
| `offset` | ≥0，默认 0 | 偏移 |

- 非法枚举（如 `mode=all`、`audience=all`、`length=medium`）返回 `422`；
- 排序固定 `created_at` 倒序；
- 响应 `total` 为**过滤后**的总数，`items` 为当前页；`next_offset` 在还有下一页时给出。

详情关键字段：

```json
{
  "run_id": "...",
  "mode": "reference",
  "status": "paused",
  "progress": 80,
  "stages": [{"id":"outline_decompose","name":"参考作品拆解","state":"succeeded","started_at":"...","finished_at":"..."}],
  "current_stage": "review",
  "quota": {"metric":"books_month","limit":4,"used":1,"reserved":0},
  "artifacts": [{"name":"chapters.json","kind":"json","size":6162}],
  "summary": {"logline":"...","chapters_count":3,"characters_count":2},
  "error": null,
  "tokens_total": 3788,
  "cost_cents": 0
}
```

### 6.4 SSE 事件流

```bash
curl -N "http://127.0.0.1:8010/v1/agent-runs/$RUN_ID/events?since=0" -H "Authorization: Bearer $TOKEN"
```

```
data: {"seq": 1, "stage": "run", "level": "info", "message": "运行已创建：mode=reference，预占 books_month=1", "at": "2026-11-05T04:20:29.545239+00:00"}
data: {"seq": 2, "stage": "run", "level": "info", "message": "开始执行（第 1 次尝试，mode=reference）", "at": "..."}
data: {"seq": 3, "stage": "outline_decompose", "level": "info", "message": "参考作品拆解 开始执行", "at": "..."}
data: {"seq": 4, "stage": "outline_decompose", "level": "info", "message": "分段拆解开始：共 9 段，54125 字（novel 模式）", "at": "..."}
data: {"seq": 5, "stage": "outline_decompose", "level": "info", "message": "第 1/9 段开始拆解（6000 字）", "at": "..."}
data: {"seq": 6, "stage": "outline_decompose", "level": "info", "message": "第 1/9 段完成：2 章，输入 6000 字", "at": "..."}
data: {"seq": 7, "stage": "outline_decompose", "level": "info", "message": "第 2/9 段开始拆解（6000 字）", "at": "..."}
data: {"seq": 8, "stage": "outline_decompose", "level": "info", "message": "第 2/9 段完成：2 章，输入 6000 字", "at": "..."}
data: {"seq": 9, "stage": "outline_decompose", "level": "info", "message": "分段结果合并完成：9 段，12 章", "at": "..."}
data: {"seq": 10, "stage": "outline_decompose", "level": "info", "message": "参考作品拆解 完成（312ms）", "at": "..."}
data: {"seq": 11, "stage": "adaptation", "level": "info", "message": "去抄袭改编 开始执行", "at": "..."}
data: {"seq": 12, "stage": "adaptation", "level": "info", "message": "去抄袭改编 完成（28ms）", "at": "..."}
event: end
data: {"status": "closed", "since": 13}
```

- `seq` 单调递增，`since` 断线重连只取更大的 `seq`。
- 分段节点额外输出段级进度：`第 n/m 段开始拆解`、`第 n/m 段完成`；断点续跑时输出 `第 n/m 段已完成，断点续跑跳过`。
- 运行进入 `succeeded/failed/canceled/paused` 后流自动结束；`paused` 期间客户端可展示人工介入 UI，拒绝后重新连接。`hot` 不会出现 `paused`。
- 单连接最长保持 60s（`SSE_MAX_TICKS`），超时后按 `since` 重连即可。

### 6.5 取消 / 恢复

```bash
curl -s -X POST "http://127.0.0.1:8010/v1/agent-runs/$RUN_ID/cancel" -H "Authorization: Bearer $TOKEN"

curl -s -X POST "http://127.0.0.1:8010/v1/agent-runs/$RUN_ID/resume" \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"approval": true}'

curl -s -X POST "http://127.0.0.1:8010/v1/agent-runs/$RUN_ID/resume" \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"input":{"chapter_no":1,"content":"改写后的第一章..."}}'

curl -s -X POST "http://127.0.0.1:8010/v1/agent-runs/$RUN_ID/resume" \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"retry_failed": true}'
```

`approval`、`input`、`retry_failed` 至少提供一项，否则 `422`。

### 6.6 产物

```bash
curl -s "http://127.0.0.1:8010/v1/agent-runs/$RUN_ID/artifacts/chapters.json" -H "Authorization: Bearer $TOKEN"
curl -s "http://127.0.0.1:8010/v1/agent-runs/$RUN_ID/artifacts/outline.md" -H "Authorization: Bearer $TOKEN"
```

- `.json` 直接返回内容；`.md` 返回 `{name,size,url,expires_in}`，`url` 与 `/v1/artifacts/download` 复用同一预签名实现。
- 文件名白名单：`outline.md`、`volumes.json`、`chapters.json`、`chapters_full.json`、`manuscript.md`、
  `chapter_summaries.json`、`characters.json`、`factions.json`、`items.json`、`story_bible.json`、
  `hot_research.json`、`hot_preview.md`、`decomposed.json`。
- `reference` 的 `decomposed.json` 是全书拆解结果（含 `segmentation`/`segments`），`chapters.json` 是改编并逐章写作后的最终章节；`summary.chapters_count` 与 `chapter_summaries` / `manuscript` 章数一致。
- `hot` 固定 3 章（正文、概括、`hot_preview.md`）；`custom` 按大纲目标章数。
- 新增产物字段：
  - `chapters_full.json`：`{book_title, chapters:[{no,title,content}]}`
  - `manuscript.md`：`# 第N章 标题` 分节，逐章正文连贯
  - `chapter_summaries.json`：`{book_title, chapters:[{chapter_no,title,summary(80-200),conflict,hook,word_count,chapter_id,scene,hook_type,emotion,tension,payoff,setup,points,roles,factions,items}]}`
  - `characters.json`：`{book_title, characters:[{name,alias,gender,age,role,affiliation,identity,personality,appearance,goal,arc,arc_detail,pov_chapters,relations,first_chapter}]}`
  - `factions.json`：`{book_title, factions:[{name,type,category,leader,members,territory,stance,goal,relations,first_chapter}]}`
  - `items.json`：`{book_title, items:[{name,category,grade,owner,holder,faction,effect,cost,origin,payoff,chapters,first_chapter,notes}]}`
  - `volumes.json`：`{book_title, volumes:[{no,title,summary,conflict,chapter_from,chapter_to,theme,core_event,conflict_axis,end_hook,arc,tension_profile}]}`
- 段级中间产物：`<书名>/<run_id>/segments/seg-NNN.json`（不走下载接口，仅用于断点续跑与审计）；章级 checkpoint 只落 `agent_run_steps`。
- 存储前缀与 `/v1/tasks` 一致：`<书名>/<run_id>/`。

### 6.7 整本交付包

```bash
curl -s -OJ "http://127.0.0.1:8010/v1/agent-runs/$RUN_ID/export" -H "Authorization: Bearer $TOKEN"
```

- 返回 `application/zip`，一次下载即可归档/投稿；无产物时返回 `409 run_not_ready`。
- 包内结构：`正文/正文.md`、`正文/正文.txt`、`章纲/章纲.md`、`设定/{角色,势力,道具功法,设定集}.json`、
  `体检/体检报告.md`、`AIGC声明.txt`、`原始产物/*`、`manifest.json`、`交付说明.md`。
- AIGC 标注默认附带；`manifest.json` 记录书名、作者、章数/字数、导出时间、AIGC 与权利声明。
- 该接口返回二进制，加入加密中间件豁免列表（与封面/产物下载一致）。

## 7. 计量与额度

- 创建运行预占 `books_month = 1`（与一次拆解任务口径一致）；成功结算，失败/取消释放。
- 章级节点 `chapter_write` 预占 `adapt_chapters = 章节数`，按章实际字数结算 `managed_chars`；超限返回 `quota_exceeded`（不产生空文件）。
- 每次模型调用写 `usage_events`（`metric=model_token`），幂等键含 `run/node/attempt`；分段节点额外包含 `seg` 序号，章级节点包含 `ch` 序号，重试产生的真实成本不会被吞掉。
- `/metrics` 新增：
  - `moxie_agent_chapters_total{mode}`
  - `moxie_agent_chapter_chars_total{mode}`
  - `moxie_agent_runs_started_total{mode}`
  - `moxie_agent_runs_total{status,mode}`
  - `moxie_agent_run_duration_seconds_total{mode}`
  - `moxie_agent_run_tokens_total`
  - `moxie_skill_calls_total{skill,status}`
  - `moxie_skill_duration_seconds_total{skill}`
  - `moxie_agent_queue_depth`

## 8. 执行方式

- 有 Redis/RQ：`POST /v1/agent-runs` 自动投递 `app.worker.worker.run_agent_job`。
- 无 Redis：运行保持 `queued`，执行一次 `python -m app.worker.worker --once` 即可本地跑一条（优先普通任务，其次 Agent 运行）。
- BYOK：Redis 键 `agent:byok:<run_id>`（TTL 1h，不落库、不写日志）；未命中时使用平台密钥。

## 9. 与 `/v1/tasks` 的关系

| 维度 | `/v1/tasks`（既有） | `/v1/agent-runs`（新增） |
| --- | --- | --- |
| 粒度 | 单个拆解/改编/审查任务 | 一条多节点写作流水线 |
| 编排 | runner 内顺序/分段 | 确定性 DAG + 同层并发 + 节点重试 |
| 断点 | 段级 `task_steps` | 节点级 `agent_run_steps` |
| 人工介入 | 无 | `review` 高危暂停 + `resume`（`hot` 不暂停） |
| 产物 | `<书名>/<task_id>/` | `<书名>/<run_id>/`（同前缀规则） |
| 额度 | `books_month` / `adapt_chapters` / `review_month` | `books_month`（每次运行 1 本） |

两者共用：账号/设备/License、订阅与额度、存储与预签名、模型网关、RQ worker、审计、`/metrics`。`/v1/tasks` 的接口与行为保持不变。

## 10. 测试覆盖

`server/tests/test_agent_runs.py` 覆盖：

- 三种模式创建与 stub 端到端（reference 5 节点全成功，3 章产物）
- 超长全文（≥5 万字、≥10 章）分段拆解：全部章节、跨段连续编号、角色同名合并、段级 SSE 顺序
- 段级 checkpoint：前两段完成后第 3 段失败；`resume(retry_failed)` 跳过已完成段，只重跑失败段及后续段
- 单段失败重试只作用于当前段（节点 `retries=1`）
- 分段阈值显式失败：`source_too_large`，不静默截断
- `hot` 全程无 `paused`，`hot_preview.md` 固定 3 章且每章梗概 150-300 字
- `reference` 仍支持 `paused → resume(approval)`
- 幂等键（同一 run、不重复预占）
- 无订阅 `403 subscription_required`、额度不足 `402 quota_exceeded`
- reference 缺 `source_key` `422`、源文件越权 `404`
- SSE `seq` 单调、事件去重、阶段齐全
- 取消 queued 运行并释放额度
- 高危 review 暂停 → `resume(approval)` 成功
- `resume(input)` 把人工改写落到 `chapters.json` 后重跑 review
- 非法状态 `resume` → `409`
- 越权访问详情/取消/恢复/产物 → `404`
- `max_steps=2` 中断后从下一节点续跑（前两个节点不重跑）
- 节点失败重试（1 次失败后成功、节点 `attempts=2`）
- 运行失败后 `resume(retry_failed)` 只重跑失败节点

本地端到端实测（SQLite + 本地存储 + `MODEL_STUB`，54,125 字 / 12 章）：reference `succeeded`，12 段、12 章、0.91s、22,829 tokens、16 分；hot `succeeded`，3 章概览、0.27s、3,798 tokens、3 分，全程无 `paused`。

运行：

```bash
cd server
python -m pytest -o addopts="" -q
```

## 11. 运行详情内容字段（实现追加说明）

> 本节为联调后追加，仅补充 `GET /v1/agent-runs/{id}` 已实际返回的字段；不改动第 6.3 节已有字段名与语义。

客户端工作台需要直接渲染章节 / 角色 / 势力 / 道具功法 / 章节概括 / 大纲，为避免为渲染再走一次签名下载，详情响应在原有字段基础上追加 `chapters`、`characters`、`factions`、`items`、`chapter_summaries`、`outline`。这些字段保留**技能产出的原始结构**，由客户端做类型映射；节点尚未产出时返回 `[]` / `{}`，客户端显示占位而不是报错。`summary` 同步追加 `word_count`、`items_count`、`updated_at`（最近章节完成时间）。

```json
{
  "chapters": [
    {
      "chapter": 1,
      "title": "第一章标题",
      "summary": "本章概括",
      "content": "本章正文…",
      "word_count": 1200,
      "beats": ["情节点1", "情节点2"]
    }
  ],
  "characters": [
    {
      "name": "角色名",
      "alias": "别名",
      "gender": "男/女/未知",
      "role": "主角/配角/反派",
      "affiliation": "所属势力",
      "identity": "身份",
      "personality": "性格描述",
      "appearance": "外貌",
      "goal": "目标",
      "arc": "人物弧线",
      "relations": [{"target": "角色B", "type": "对手"}],
      "first_chapter": 1
    }
  ],
  "factions": [
    {
      "name": "势力名",
      "type": "门派/家族/组织/国家",
      "leader": "首领",
      "members": ["角色A", "角色B"],
      "territory": "地盘",
      "stance": "正/邪/中立",
      "goal": "诉求",
      "relations": [{"target": "势力B", "type": "敌对"}],
      "first_chapter": 1
    }
  ],
  "items": [
    {
      "name": "道具名",
      "category": "道具/功法/武器/丹药/其他",
      "grade": "品阶",
      "owner": "归属",
      "effect": "作用",
      "cost": "代价",
      "first_chapter": 1,
      "notes": "备注"
    }
  ],
  "chapter_summaries": [
    {
      "chapter_no": 1,
      "title": "第一章标题",
      "summary": "80-200 字概括",
      "conflict": "核心冲突",
      "hook": "章末钩子",
      "word_count": 1200
    }
  ],
  "outline": {
    "logline": "一句话故事",
    "theme": "主题",
    "story_bible": {"protagonist": "主角", "supporting": "配角", "antagonist": "对手"},
    "chapters": [{"chapter": 1, "title": "…", "summary": "…"}]
  }
}
```

字段来源与降级规则：

| 字段 | 数据来源（按优先级） | 为空时 |
| --- | --- | --- |
| `chapters` | `chapter_expand.chapters` → `adaptation.chapters` | `[]` |
| `characters` | `character_graph.characters` → `outline_decompose.characters` → 用 `outline.story_bible` 的 `protagonist/supporting/antagonist` 生成 `{name}` | `[]` |
| `factions` | `character_graph.factions` → `adaptation.factions` → `outline_decompose.factions` | `[]` |
| `items` | `character_graph.items` → `adaptation.items` → `outline_decompose.items` | `[]` |
| `chapter_summaries` | `chapter_summarize.chapters` | `[]` |
| `summary.word_count` | 各章 `word_count` 之和 | `0` |
| `summary.items_count` | `items.length` | `0` |
| `summary.updated_at` | 最近的章级 checkpoint `finished_at` | 运行 `updated_at` |
| `outline.logline` | `outline.logline` | `""` |
| `outline.theme` | `outline.theme` | `""` |
| `outline.story_bible` | `outline.story_bible` | `{}` |
| `outline.chapters` | `outline.chapters` | `[]` |

注意：

- `chapters` 的序号字段是 `chapter`（不是 `no`），字数体积字段是 `word_count`（不是 `words`）；客户端映射层负责转换。
- `factions`、`items`、`characters`、`chapter_summaries` 均为数组；旧拆解数据里的 `factions` 可能是对象（按势力名聚合），客户端两种都需兼容。
- `chapter_summaries.length` 必须等于 `chapters.length`；`manuscript.md` 与 `chapters_full.json` 章数一致。
- 这些字段与产物文件内容一致；`.json` 产物仍可直接下载，`.md` 产物仍走 `{name,size,url,expires_in}` 二次拉取。

### 11.1 阶段聚合与分章/分段节点（第二轮联调追加）

`stages` 的 `state` 不再只读节点级 checkpoint，而是按 `node_id` 聚合该节点的所有 checkpoint：

- 分章节点（`chapter_expand`、`chapter_summarize`）子步骤 key 为 `node:ch:NNN`，节点级 base row `node` 也可能存在；
- 分段节点（`outline_decompose`）子步骤 key 为 `node:seg:NNN`；
- 聚合规则：任一子步骤 `failed` → `failed`；全部 `done` → `succeeded`；存在 `running/done` 且未全部完成 → `running`；无子步骤 → `pending`；
- `started_at` 取子步骤最小值；`finished_at` 仅在 `succeeded` 时取最大值，避免未完成阶段显示虚假完成时间；
- `current_stage` 取第一个非 `succeeded` 的节点。

`outputs` / 详情中的章节合并只取**子步骤**（`node_key != node_id`），避免 base row 与 `ch:NNN` 重复导致章节翻倍：

```python
rows = [row for row in node_rows[node.id] if row.node_key != node.id]
merged = []
for row in rows:
    merged.extend(row.output.get("chapters") or [])
```

`summary` 追加两个计数（客户端仅作展示，不作配额依据）：

| 字段 | 含义 | 为空/缺省时 |
| --- | --- | --- |
| `summary.segments_count` | 分段拆解段数，优先 `outline_decompose.segmentation.segments`，否则统计 `outline_decompose:seg:*` checkpoint 数 | `0` |
| `summary.preview_chapters_count` | 预览章数（热门写作先出少量样章） | `0` |

### 11.2 套餐三档与下架（第二轮联调追加）

`GET /v1/plans` 只返回 `active=1` 的套餐，价格单位为**分**，按下单价升序：

```json
{"plans": [
  {"code": "experience", "name": "体验版", "price_month_cents": 990, "price_year_cents": 9900,
   "entitlements": [{"key": "books_month", "limit": 1, "unit": "book"}]},
  {"code": "creator", "name": "创作版", "price_month_cents": 2990, "price_year_cents": 29900,
   "entitlements": [{"key": "books_month", "limit": 5, "unit": "book"}]},
  {"code": "professional", "name": "专业版", "price_month_cents": 6990, "price_year_cents": 69900,
   "entitlements": [{"key": "books_month", "limit": 15, "unit": "book"}]}
]}
```

- 客户端展示：`990 → ¥9.9`、`2990 → ¥29.9`、`6990 → ¥69.9`（`formatMoney` 统一按分转元）；
- 月度额度取自 `entitlements` 中 `key=books_month` 的 `limit`（不在套餐顶层平铺）；
- 下架套餐（`active=0`）不出现在公开列表；对下架 `code` 下单返回 **HTTP 409 `plan_unavailable`**；
- 运行详情的 `quota` 与订阅接口的 `books_month/used/reserved` 使用同一数值口径，前端文案「本月可创作 共 N 本」直接读 `limit`。

### 11.3 工作台可选字段（第三轮联调追加）

以下字段全部为**可选字段**，缺失时返回空字符串/空数组/`{}`/`null`，不影响既有字段与契约；客户端遇到为空值时继续显示「—」。

**章节级**（`chapters` 与 `chapter_summaries` 同名字段）：

| 字段 | 类型 | 含义 | 为空时 |
| --- | --- | --- | --- |
| `chapter_id` | string | 章节稳定 id，形如 `ch-001` | `""` |
| `scene` | string | 本章主要场景 | `""` |
| `hook_type` | string | 章末钩子类型（悬念/危机/转折/情感） | `""` |
| `emotion` | string | 情绪基调 | `""` |
| `tension` | int | 张力等级 0–10 | `0` |
| `payoff` | string | 本章兑现 | `""` |
| `setup` | string | 本章铺垫 | `""` |
| `points` | string[] | 情节要点 | `[]` |
| `roles` | string[] | 本章出场人物 | `[]` |
| `factions` | string[] | 本章出场势力 | `[]` |
| `items` | string[] | 本章出场道具 | `[]` |

**卷级**（详情顶层 `volumes` 与 `outline.volumes`，产物 `volumes.json`）：

| 字段 | 类型 | 含义 |
| --- | --- | --- |
| `no` | int | 卷序号，从 1 开始 |
| `title` | string | 卷名 |
| `summary` | string | 卷主题概述 |
| `conflict` | string | 本卷核心矛盾 |
| `chapter_from` / `chapter_to` | int | 章区间（闭区间） |
| `theme` | string | 卷主题 |
| `core_event` | string | 核心事件 |
| `conflict_axis` | string | 矛盾轴 |
| `end_hook` | string | 卷末钩子 |
| `arc` | string | 人物弧光 |
| `tension_profile` | string | 节奏曲线，如 `3→5→7` |

分卷按每 3 章一卷；不足 3 章的尾卷独立成卷，只有 1 卷时同样输出完整结构。卷区间必须连续覆盖 `1..N`，否则服务端回退为确定性分卷。

**人物**（`characters[]` 追加）：

| 字段 | 类型 | 含义 | 为空时 |
| --- | --- | --- | --- |
| `age` | int \| null | 年龄 | `null` |
| `arc_detail` | object | `{type,start_state,turning_points,end_state,final_fate}` | `{}` |
| `pov_chapters` | int[] | 视角章节 | `[]` |

> 兼容说明：客户端人物页读取 `characters[].arc`，当其为对象时渲染为弧光详情。因此服务端将结构化弧光同时写入 `arc`（对象）与 `arc_detail`（同内容），字段名与客户端类型保持一致；模型返回字符串 `arc` 时会被解析为弧光阶段。

**势力**（`factions[]` 追加）：

| 字段 | 类型 | 含义 | 为空时 |
| --- | --- | --- | --- |
| `goal` | string | 势力诉求（独立字段） | `""` |
| `category` | string | 大类（门派/家族/组织/国家） | 取 `type` |
| `relations[].strength` | float \| null | 关系强度 0–1 | `null` |
| `relations[].public` | bool \| null | 是否公开 | `null` |

**道具功法**（`items[]` 追加）：

| 字段 | 类型 | 含义 | 为空时 |
| --- | --- | --- | --- |
| `payoff` | string | 后期作用 | `""` |
| `origin` | string | 来源 | `""` |
| `holder` | string | 当前持有者 | 取 `owner` |
| `faction` | string | 归属势力 | `""` |
| `chapters` | int[] | 出现章节 | 至少含 `first_chapter` |

**大纲级**（`outline` 追加，`outline` 为空时对应字段为 `[]`/`{}`）：

| 字段 | 类型 | 含义 |
| --- | --- | --- |
| `opening` | object | `{strategy,first_image,golden_finger_demo}`，`golden_finger_demo` 为首次演示章节号 |
| `worldview` | object[] | `[{group,points:[{text,chapters}]}]` |
| `map_levels` | string[] | 地图层级 |
| `map_regions` | object[] | `[{name,parent,kind,desc,chapters}]` |
| `map_scenes` | object[] | `[{chapter,region,characters,factions,items,event}]` |
| `signing_check` | object | `{score,risk,suggestions,issues}`，按大纲结构确定性计算，不虚构评分 |
| `completeness_check` | object | `{missing_fields,unfilled_payoff,unrecovered,arc_missing,no_hook}` |

说明：

- `signing_check.score` 与 `risk` 来自结构体检（logline/主题/章数/钩子/叙事阶段），缺失项会进入 `issues`。
- `completeness_check.unfilled_payoff` / `unrecovered` 在大纲阶段没有兑现台账时保持 `[]`，不填充假数据。
- 真实模型路径由 `outline` / `chapter_write` / `chapter_summarize` / `lore_extract` 的 prompt 抽取；`MODEL_STUB` 下由服务端按同一结构确定性产出，便于联调与测试。
