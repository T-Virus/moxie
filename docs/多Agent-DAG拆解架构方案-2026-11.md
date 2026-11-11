# 多 Agent 固定 DAG 拆解架构方案（历史设计稿）

> ## v1.3 工程修正决议（2026-11-06，已落地）
>
> 本文 v1.2 及之前的「11 节点 / 41 Skill / 多 Agent 协作」内容**保留为历史设计参考，不再作为实施依据**。
> 修正原因：这些"Agent"实为固定 prompt 阶段函数，无自主性；拆分反而制造出 owner 写权、patch 仲裁、稳定 ID 等本不存在的协调问题。用户确认按**单编排器 + 阶段化 LLM 调用 + 确定性代码做传播与校验**修正，在三条硬约束下落地：
>
> 1. **多任务并行**：跨进程写集准入锁（`admit/release`）+ 全局额度；互斥按「写集交集」而非「同书同 stage」；跨书完全并行，同书执行串行以保证快照/回滚不被并发文件替换破坏。
> 2. **任意单节点可执行**：节点 = 现有 4 个可独立运行的 stage（`decompose / adapt / storymap / expand`）；依赖节点在计划中标为 `input`（从冻结快照读），不连带重跑上游；跑完按传播表标脏下游。
> 3. **数据一致性**：owner 唯一写权 + 写集越界整组回滚、人工锁定字段保护、输入指纹幂等跳过、冻结快照与 lineage 漂移检测、引用完整性/章号连续规则体检。
>
> **实际落盘**：`config/flow.json`（4 节点 + 2 条传播规则）、`src/flow.py`（编排器）、`scripts/flowctl.py`（CLI）、`tests/test_flow.py`（14 条回归断言，全过）、`src/webapp.py`（`POST /api/run` 接入写集准入；新增 `POST /api/flow/plan`、`POST /api/flow/check`；`PUT /api/chapters` 支持 `flow_locks` 上报）。
>
> **验证**：`python tests/test_flow.py`、`python scripts/flowctl.py validate|plan|check`。
>
> **重要更正**：v1.2 声称「配置已落盘、dagctl.py 已可运行、14 条断言全过」，但 `config/dag.json`、`config/skills.json`、`config/trend_schema.json`、`config/dependency_map.json`、`scripts/dagctl.py`、`scripts/build_standalone.py` 在仓库中均不存在。下文所有「已落实」「已可运行」等表述均以本决议为准。保留 `docs/outline_fields.json`（316 字段字典）作为字段命名参考，但不作为 owner 表的运行时依赖。

- 版本：v1.3（工程修正已落地）　日期：2026-11-06
- 输入：用户给定的流程设想（榜单发现 → 7 个拆解 Agent → 一致性审查 → 最终设计图谱；每个 Agent 细分 Skill；**每个节点与每个 Skill 都要能单独执行**，且单跑后关联数据同步；榜单阶段只从全网公开数据抓、不读原本书、只输出 Top20 排名阅读量）
- 历史配套文件（v1.2 声称存在，实际未落盘）：`config/dag.json`、`config/skills.json`、`config/trend_schema.json`、`config/dependency_map.json`、`scripts/dagctl.py`、`scripts/build_standalone.py`
- v1.1 变更：把「可单独执行」从布尔标记升级为完整契约（历史）。
- v1.2 变更：榜单 Agent 改为纯公开元数据采集、Top20 六列输出契约（历史）。

---

## 0. 结论先行

流程可行，但按现在的表述直接落地会踩三个坑，必须补上机制：

1. **「固定 DAG」和「每个可单独执行」是两件事**。DAG 应当只是**依赖声明**，不是执行脚本。执行时按 `run_mode` 决定：新书走拓扑全跑，改大纲走「change_set → 依赖传播 → 只重跑脏节点 → 审查 → 冻结」。否则「一键改大纲」会变成整本重拆 28 分钟。
2. **「多个 Agent 比对同步」不能让 Agent 互改数据**。必须引入 **owner 唯一原则**：每个字段只有一个节点拥有写权，其他节点只能引用或提交冲突；审查 Agent 只产 patch，由 owner 回写。否则两个 LLM 会互相覆盖、反复震荡。
3. **跨 Agent 引用不能再用名称当主键**。现有 `src/entities.py:424` 的 `_dedupe_entities` 以 `clean_name(name)` 为主键，改名要靠 `apply_renames` 全局替换（`:239`）。多 Agent 并行后这是最大的一致性风险，应引入稳定 ID（`char_id / fac_id / item_id / place_id / fs_id`），名称降级为展示字段。

另外两个必须前置的约束：**榜单 Agent 的版权边界**（只采公开元数据、不读原本书、不抓正文，只输出 Top20 排名阅读量）与**成本增速**（把一次 16 调用的拆解拆成 7 Agent × 多 Skill，若不合并调用会放大到 60~100 次）。榜单 5 个 Skill 全部为规则处理，不增加模型调用。

---

## 1. 现状对照（哪些能直接复用）

| 能力 | 现有实现 | 复用方式 |
|---|---|---|
| 桌面任务调度 | `src/webapp.py:99` `JOBS`、`:101` `JOB_LOCK`、`:127` `MAX_RUNNING_TASKS`、`:3614` `job["queue"]` 线性阶段链、`:168` 每 2 秒 `tasks.json` 快照、`interrupted/resumable` | 线性 queue 升级为拓扑队列；锁、额度、同书互斥（`:3590`）、续跑语义照用 |
| 云端步骤状态 | `server/app/models.py:332` `TaskStep(task_id, step_key)` + `meta` JSON；`RunContext.step()`（`server/app/worker/runners` 大量使用）跳过已完成步骤；`scheduler.py:66` `skip_locked` 租约回收 | `step_key` 直接存 `node_id` / `skill_id`，`meta` 存指纹、change_set、轮次，天然支持断点续跑 |
| 一致性同步（雏形） | `src/entities.py:485` `sync_document`、`:239` `apply_renames`、`:380` `apply_chapter_no_map`；`src/storymap.py:478` `fallback_conflicts` 的连续性冲突 | 作为审查 Agent 的**规则层**，新增 claim 交叉比对与仲裁层 |
| 提示词与模型绑定 | `src/prompts.py:31` `registry()`；`src/craft.py:111` `get()` + 5 个 `*_guide`；`config/studio.json:13` 10 个 `bindings`；`src/studio.py:44` `BIND_STAGES` | registry 从 `stage` 两级扩展为 `agent → skill` 三级；bindings 增加 `dag.*` key |
| 现有拆解产物 | `src/decompose.py:1407` `_write_outputs` 写 `decomposed.json` / `chapters.json`；`src/storymap.py:1148` 一次写 `storymap.json` | 作为节点产物的落盘目标；新增 `data/<book>/dag/<node>.json` 契约文件 |
| 字段字典 | `docs/outline_fields.json`（316 字段，含落盘位置与状态） | 直接作为 `owner_fields`、依赖矩阵、完整性校验的字段源 |

**明确不能用的**：`config/workflow.json` 的 `pipeline` 全仓只有只读引用与打包（`prompts.py:22`、`selftest.py`、`build_app.py`），没有任何执行器遍历它，是遗留的 ollama 旧管线配置。新 DAG 另起 `config/dag.json`，不复活它。

**需新增**：DAG 声明与拓扑解析、字段级 diff 与脏标记传播、产物指纹与 lineage、稳定实体 ID、桌面/云端统一状态机、Skill 级执行契约、审查回环。（`server/app/worker/worker.py:84` 取任务未用 `skip_locked`，多 worker 并发也要补。）

---

## 2. 分层 DAG 总览

```
L0  榜单发现 Agent（公开元数据 → Top20 排名/阅读量，不读原本书）
      └─ 独立产物，不触发下游传播 ──→ 选书与权利确认（人工 gate）
                              │
L1                     作品大纲 Agent（骨架）
                              │
L2        ┌────────┬──────────┼──────────┬─────────┐
       地图设定   势力表    角色池    道具功法   （并行组）
          └────────┴──────────┼──────────┴─────────┘
L3                    卷章概览 Agent
                              │
L4                    设计图谱 Agent（汇聚 / 派生）
                              │
L5              数据统一性审查修正 Agent ──┐
                              │          │ patch 回边（≤2 轮）
                              └──────────┘
L6                    冻结与交付（最终图谱 + 大纲文档）
```

节点共 11 个，其中含 LLM 的 8 个；榜单发现、选书 gate、交付为规则或人工节点。用户列的 7 个拆解 Agent 对应 `outline / geography / factions / characters / items / volumes / graph`。完整依赖与产物见 `config/dag.json` 的 `nodes[].depends_on`。

---

## 3. 节点与 Skill 契约

| 节点 | 依赖 | 细分 Skill | 主要产物 | 可单独跑 |
|---|---|---|---|---|
| `trend_discover` 榜单发现 | — | **`source_fetch` / `dimension_tag` / `metric_normalize` / `topn_output` / `rights_gate`** | `data/rankings/YYYY-MM-Top20.md/.json` | 是（独立产物） |
| `book_select` 选书 gate | trend | 无（人工 + 权利确认） | `meta.json` | 是 |
| `outline` 作品大纲 | select | **`book_meta` / `worldview` / `power_system` / `plot_spine` / `selling`** | `story_bible` 主体 | 是 |
| `geography` 地图设定 | outline | `regions` / `places` / `forbidden_zones` / `scene_anchor` | `storymap.map.*` | 是 |
| `factions` 势力表 | outline, geography | `faction_cards` / `faction_relations` / `polity` | `factions[]`、`factionNodes/Edges` | 是 |
| `characters` 角色池 | outline, factions | `char_cards` / `char_arc` / `char_relations` / `undercover` | `characters[]`、`nodes/edges` | 是 |
| `items` 道具功法 | outline, characters | `item_cards` / `grade_rules` / `item_flow` | `items[]`、`itemLinks` | 是 |
| `volumes` 卷章概览 | outline, geography, characters, items | `volume_plan` / `chapter_outline` / `beats` / `emotion_design` | `chapters[]`、`volumes[]` | 是 |
| `graph` 设计图谱 | 全部拆解节点 | `relation_graph` / `worldview_groups` / `foreshadow_ledger` / `time_emotion` / `map_graph` | `storymap.json` 草稿 | 是（rebuild） |
| `consistency` 统一性审查 | 全部 | `rule_check` / `cross_check` / `arbitrate` / `patch_write` / `recheck` | patch 文件、冲突清单 | 是（review_only） |
| `deliver` 冻结交付 | consistency | `graph_freeze` / `outline_doc` / `pitch_pack` | 最终图谱、大纲文档、投稿包 | 是 |

**Skill 已全部细分到字段级**，详见 `config/skills.json` 与 `docs/Skill细分与单独执行契约-2026-11.md`。每个 Skill 声明 `{fqid, agent, can_run_alone, entry, reads, writes, subtasks, output, on_missing, llm, call_mode, propagates_to, precheck, exit_state, idempotent}`：

| Agent | Skill 数 | 细分（逐条列出） |
|---|---:|---|
| `trend_discover` | 5 | `source_fetch` / `dimension_tag` / `metric_normalize` / `topn_output` / `rights_gate` |
| `outline` | 5 | `book_meta` / `worldview` / `power_system` / `plot_spine` / `selling` |
| `geography` | 4 | `regions` / `places` / `forbidden_zones` / `scene_anchor` |
| `factions` | 3 | `faction_cards` / `faction_relations` / `polity` |
| `characters` | 4 | `char_cards` / `char_arc` / `char_relations` / `undercover` |
| `items` | 3 | `item_cards` / `grade_rules` / `item_flow` |
| `volumes` | 4 | `volume_plan` / `chapter_outline` / `beats` / `emotion_design` |
| `graph` | 5 | `relation_graph` / `worldview_groups` / `foreshadow_ledger` / `time_emotion` / `map_graph` |
| `consistency` | 5 | `rule_check` / `cross_check` / `arbitrate` / `patch_write` / `recheck` |
| `deliver` | 3 | `graph_freeze` / `outline_doc` / `pitch_pack` |
| **合计** | **41** | **146 个 subtasks、71 条传播边，41/41 可单跑** |

`subtasks` 是 Skill 内部的**字段组/产出清单**（例如 `outline.worldview` 细分为：地理环境总述、社会结构概述、世界物理定律＋违反后果、时代与跨度、写作禁忌），**不是调度单元**——最小调度粒度固定为 Skill，否则调用数会从 39 涨到 150+。同一 Agent 内多个 Skill 在 `node/full` 模式**合并为一次 LLM 调用**；`skill` 模式才独立调用，这是控制成本的关键。

**写权边界已对齐**：`structure.beat.*` 归 `outline`，`volumes` 只保留派生的 `structure.beat_map`；`factions` 产 `faction_edge_candidates`、`characters` 产 `character_edge_candidates`，`storymap.edges/factionNodes` 由 `graph` 统一派生；`graph.time_emotion / map_graph` 只写 `*_view / *_index` 视图，`emotionCurve` 与 `storymap.map` 的 SSOT 仍归 `volumes / geography`。

**「作品大纲中的世界观 Skill」怎么单独执行**：`python scripts/dagctl.py plan --book 迷失蔚蓝 --target outline.worldview` → 从冻结快照读 `meta.json` + 原著分段 + `craft.decompose_guide` → 组装 prompt → 输出 `world.world / world_rules / era / taboos` 等字段 → schema 校验 → **只替换** `dag/outline.json#skills.worldview` 这一块（其余 4 个 Skill 版本不动）→ change_set → 查 `dependency_map` → 传播 `geography(patch) / factions(patch) / graph(rebuild)` → `consistency` 复检 → `deliver` 冻结。实测该计划：`llm_calls=1`、dirty 节点 5 个（`factions/geography/graph/consistency/deliver`），不触碰榜单发现、选书，也不重拆全书。

### 3.1 榜单 Agent：全网公开数据 Top20 输出契约

**边界**：抓取结果要能区分男频/女频、长篇/短篇、已完结/连载中；**直接从全网公开数据抓取，不读原本书**；**只输出排名 + 阅读量 Top20**。完整机器可读契约见 `config/trend_schema.json`。

三条硬规则：

1. **不读原本书**。榜单阶段完全不依赖 `data/<book>/`、原著全文或上传大纲，在 `book_select` 之前独立完成。后续拆解节点若要读原著，必须在选书 gate 之后另行取得授权。
2. **不抓正文**。只采榜单页 / 作品详情页的公开元数据；禁止正文、章节、试读、付费内容与付费榜单数据包。
3. **只输出 6 列**：`rank | title | reading_count | channel | length_class | serial_status`。作者、字数、题材、来源 URL、原始指标只留在内部快照用于溯源与标签判定，不进结果表；结果表也不得出现简介、人设、大纲、剧情分析。

三轴六标签（平台字段优先，缺失才推断并标 `inferred=true`）：

| 轴 | 取值 | 首选来源 | 兜底 |
|---|---|---|---|
| 频道 | 男频 / 女频 | 番茄 URL `channel=1/0`、起点女生榜、七猫男生/女生榜 | 题材推断，标 inferred |
| 篇幅 | 长篇 / 短篇 | 平台「长篇/短篇」标签 | `word_count <= 100000` 判短篇，标 inferred |
| 连载 | 已完结 / 连载中 | 完本/完结/连载等原值归一 | 取不到写 null，计入质量报告 |

数据源白名单（已核对公开页面，2026-11-05）：

| 源 | URL / 参数 | 公开指标 | 有阅读量数值 |
|---|---|---|---|
| 番茄阅读榜 | `fanqienovel.com/rank/{channel}_{type}_{cat_id}`，channel 0=女频/1=男频，type 2=阅读榜 | 在读数＝过去 14 天累计阅读人数 | **是** |
| 起点阅读指数榜 | `qidian.com/rank/readindex/`，移动端 `m.qidian.com` SSR 优先 | 阅读指数名次 | 否 |
| 起点月票/畅销/收藏/追读 | `qidian.com/rank/yuepiao|hotsales|collect/` | 月票、销量、收藏 | 否 |
| 七猫排行榜 | `qimao.com/paihang`，男生榜/女生榜切换 | 热度 | 否 |
| 公开第三方汇总 | 公众号 / 网文情报站公开文章 | 男女频在读量 TOP30、完结状态、字数 | 是（仅交叉校验，付费包不采） |

**实测发现（决定口径的关键）**：2026-11-05 抓起点阅读指数榜，页面确实给出 Top20 的完整书名、作者、题材、连载/完本状态，但**没有任何阅读量数值**；番茄「在读数」才是可公开获取的阅读人数。所以契约规定：只有 `metric_type=reading_count_14d` 的源写 `reading_count`，起点/七猫写 `null` 并标 `rank_only`；**月票、热度、推荐人数、收藏数一律不得冒充阅读量**，不同口径不得混排进同一张排序表。这一条是为了避免产出一张看似精确、实则臆造的榜单。

输出形态（默认 `overall` 单表，可切 `by_channel / by_length / by_status` 分表，每表 Top20）：

| rank | title | reading_count | channel | length_class | serial_status |
|---:|---|---:|---|---|---|
| 1 | 游戏入侵:抢男女主机缘会上瘾诶 | 932970 | 女频 | 长篇 | 已完结 |
| 2 | 四个孩子非亲生,姐宝男杀疯了 | 873318 | 女频 | 长篇 | 连载中 |
| 3 | 撕毁婚约后,年上首长失控被亲哭 | 736233 | 女频 | 长篇 | 已完结 |
| 4 | 别嫁他!未来女儿托梦求换爹 | 682712 | 女频 | 长篇 | 已完结 |
| 5 | 备用联系人 | 651460 | 女频 | 长篇 | 已完结 |

> 上表 5 行仅演示字段形态，取自 2026-11-03 公开第三方汇总的番茄女频在读榜快照，**不是本次采集产物、也不构成完整 Top20**；长篇标签为按字数阈值推断值。真实结果落 `data/rankings/YYYY-MM-Top20.md/.json`，内部快照落 `data/rankings/YYYY-MM.json`。

榜单 Agent 的 5 个细分 Skill 全部 `no_llm`、全部可单跑：`source_fetch → dimension_tag → metric_normalize → topn_output → rights_gate`。该节点 `propagate_default=false`，是独立产物——实测 `dagctl.py plan --target trend_discover.topn_output` 得到 `dirty=[]`、0 次模型调用，不触发任何下游拆解。查看与校验契约：`python scripts/dagctl.py trend --check --sample`。

---

## 4. 产物契约与单一事实源

每个节点输出一个契约文件 `data/<book>/dag/<node_id>.json`：

```
{
  "node_id": "outline", "schema_version": "1.0",
  "skills": {"worldview": {...}, "power_system": {...}},
  "input_fingerprints": {"book_select": "sha256:...", "outline.worldview": "sha256:..."},
  "output_hash": "sha256:...",
  "lineage": [{"node": "book_select", "version": 3}],
  "owner_fields": ["world.power", ...],
  "generated_at": "...", "model": "...", "prompt_version": "..."
}
```

四条硬规则：

1. **owner 唯一**：字段字典的每条字段映射到一个 owner 节点（写在 `dag.json#nodes[].owner_fields`）。审查 Agent 发现别人字段有错，只能提 `conflict`，由 owner 节点执行 patch。
2. **引用走 ID**：跨节点只出现 `char_id / fac_id / item_id / place_id / fs_id`；展示名在一个地方维护。过渡期继续用 `entities.apply_renames`，但把它收敛成「ID → display_name」的一次映射。
3. **指纹跳过**：`input_fingerprints` 全未变则节点直接返回缓存产物，不调模型。
4. **用户锁定**：前端编辑过的字段写进 `meta.locked_fields`，任何 Agent 不得自动覆盖，只能生成「建议修改」等待人工确认。

---

## 5. 数据统一性审查修正 Agent（核心新增）

不是「再让 LLM 通读一遍」，而是三层收敛：

| 层 | 做法 | 是否调 LLM |
|---|---|---|
| `rule_check` 规则层 | 引用完整性（ID 是否存在）、枚举合法、卷区间闭区间无空档、章号连续、伏笔 status 合法、必填空值、弧光缺失、payoff 空章。复用 `entities.sync_document` + `storymap.conflicts` + 字段字典的必填列 | 否 |
| `cross_check` 交叉比对层 | 每个 Agent 只提交**声明清单 claim** `{field, value, evidence_chapter, source_node}`，不交全文；比对同一实体在不同节点的声明（如「第44章战斗力36」vs「等级表上限」），输出 `{claim_a, claim_b, conflict_type, confidence}` | 是（每个 Agent 一次，输入很小） |
| `arbitrate` 仲裁层 | 按优先级裁决：`人工锁定 > 原著/章节事实 > 上游 SSOT 字段 > 下游派生摘要`；生成字段级 patch 交给 owner 回写，`recheck` 复检 | 是（仅对冲突项） |

**受控回边**：`consistency → 受影响节点 → graph → consistency`，最多 2 轮；连续两轮无新增冲突即收敛；剩余冲突落 `unresolved_conflicts.json` 交人工，绝不自动覆盖。这条规则同时解决「多 Agent 互相改」和「无限循环」。

**输出**：`data/<book>/dag/consistency.json`（冲突与裁决记录）、`patches/*.json`、`unresolved_conflicts.json`，以及 `qa.qa_score` / `completeness_check.*`。

---

## 6. 四种执行模式与「每个都能单独执行」的契约

| 模式 | 触发 | 行为 |
|---|---|---|
| `full` | 新书 / 换源 | L0 gate → 拓扑全跑 → 审查 → 冻结 |
| `node` | 一键改大纲、改某张卡 | 单 Agent 重跑 → change_set → 依赖传播 → 脏节点 patch/rebuild → 审查 → 冻结 |
| `skill` | 只改「世界观」「力量体系」等子项 | 只重跑该 Skill，其余 Skill 保持原版本，后续同 `node` |
| `review_only` | 交付前体检 | 只跑 `consistency` + `deliver`，不重生成 |

### 单独执行的四层保障

1. **输入不依赖本次上游**。任何节点 / Skill 单跑都从 `data/<book>/dag/*.json` 的**冻结快照**读输入，而不是要求上游这一轮跑过；lineage 版本不一致则拒绝合入。缺输入按 `on_missing` 明确降级：`use_last_frozen / fail / empty_ok / user_gate / blocking`。
2. **写入只替换自己那一块**。`skill` 模式只写 `dag/<agent>.json#skills.<skill_id>`，同 Agent 其余 Skill 的版本号、产物、指纹保持不动；且只写自己的 `owner_fields`，发现别人字段有错只能提交 conflict。
3. **单跑默认触发同步**。跑完自动按 `dependency_map.json` 传播，这是「关联数据同步」的实现位置；`--no-propagate` 只做本地预览，产物标记 `stale_downstream`，下次交付前强制复检。
4. **幂等与互斥**。输入指纹未变直接返回缓存（零调用）；重复执行不产生新版本；同书同节点互斥，不同节点并行读同一 lineage 快照。

### 统一入口（v1.3 修正后的实际入口）

```bash
python scripts/flowctl.py list                                 # 4 个真实可执行节点
python scripts/flowctl.py validate                             # 配置自检：节点/依赖/写权唯一/无环
python scripts/flowctl.py plan --book 迷失蔚蓝 --target storymap
python scripts/flowctl.py plan --book 迷失蔚蓝 --target decompose --changes story_bible.power_system
python scripts/flowctl.py check --book 迷失蔚蓝                 # 规则层一致性体检（只读）
python scripts/flowctl.py run --book 迷失蔚蓝 --target storymap --dry-run
python scripts/flowctl.py run --book 迷失蔚蓝 --target storymap --yes   # 真实执行，会消耗模型额度
python tests/test_flow.py                                      # 14 条回归断言
```

`plan` 输出可直接驱动执行的计划 JSON：`steps / dirty_nodes / snapshot_inputs / skipped_nodes / propagation / llm_calls_estimated / layers`。
执行器已落地：`src/flow.py#run_node` 与 `#run_plan` 通过 `build_default_cmd` 复用现有四个脚本，也可注入自定义 executor；`--dry-run` 只做准入与计划、不落盘不调模型，`--yes` 才真实执行。
桌面端已接入 `POST /api/run`（写集准入）、`POST /api/flow/plan`、`POST /api/flow/check`；`PUT /api/chapters` 可用 `flow_locks` 上报人工改动字段。

每个节点单跑都走固定 6 步：`admit（跨进程锁+额度）→ load_state（冻结快照）→ precheck（指纹命中即跳过/输入缺失按 on_missing 拒绝）→ execute → 写集与锁定字段审计（违规整组回滚）→ commit（指纹、lineage、快照）`，随后按 `propagation` 标脏下游。
v1.2 的 39 份 Skill 明细与 5 个单跑时序见 `docs/Skill细分与单独执行契约-2026-11.md`，现仅作历史参考。

### 「一键改大纲」完整时序（示例）

用户把 `world.power_system.levels` 的分级 `F–SSS` 改成 `F–SSS+`，并补上 `cost` 代价：

1. 前端提交 `change_set{path, old, new, author=user}`，写入 `meta.locked_fields` 保护该路径。
2. `dag.py` 查 `dependency_map.json` 第 2 条 → dirty = `items(patch: grade/effect)`、`characters(patch: identity/goal/weakness)`、`volumes(patch: conflict/key_events)`、`graph(rebuild: worldview[修炼体系])`。
3. 四个脏节点**并行**以 patch 模式重跑：输入 = 原产物 + change_set + 被点名字段，要求「只输出这些字段的新值」，不重述全文。
4. `consistency` 用规则层扫引用，用 claim 层比对「等级表 ↔ 道具品阶 ↔ 章节战斗描述」，发现第 44/223/315 章数值与新等级表冲突（现有 `storymap.conflicts` 已有类似案例）。
5. 仲裁：`world.power_system.levels` 是上游 SSOT 且用户锁定 → 章节数值属下游派生 → 产 patch 给 `volumes` 回写；复检一轮收敛。
6. `deliver` 冻结：写版本号 + lineage 快照，前端展示「本次改动影响了 4 个模块 / 3 处章节描述」的 diff。

全程不重跑 `geography / factions / trend_discover`，也不重拆全书。

---

## 7. 依赖传播表

`config/dependency_map.json` 现有 **17 条字段级规则**，覆盖定位、力量体系、地理、社会结构、角色名与弧光、势力、道具、卷章区间、章节引用、伏笔、节拍、卖点、篇幅、结局。每条规则给出 `owner`、`affects[{node, mode, fields, reason}]`；`mode` 为 `patch`（只改引用字段）/ `rebuild`（派生索引整体重建）/ `review`（只审查不自动改）。

字段 key 全部引用 `docs/outline_fields.json`，因此**字段字典、DAG 声明、依赖矩阵三者共用一套命名**，不会出现文档写 `power`、代码写 `power_system` 的漂移。新增字段时补一条规则即可。

---

## 8. 成本、时长与合规

- **实测基线**（`docs/墨写商业计划书-2026-11.md:53`）：15.8 万字拆解 = 16 次调用 / 28 分钟 / ¥0.9~3。若 7 Agent × 3~5 Skill 各自独立调用，会放大到 60~100 次，时长与成本不可接受。
- **三条控制线**：① 同 Agent 多 Skill 合并为一次调用；② 指纹命中直接跳过；③ `rule_check` 先过滤，只有可疑项才进 LLM 交叉比对。`node/skill` 模式是默认路径，`full` 只用于新书。
- **榜单 Agent 的合规红线**：只采公开榜单页的**排名、阅读量/在读数**以及分类判定所需的最小元数据（频道、字数、连载状态、来源 URL、快照时间），**不读原本书、不抓取/存储/解析正文**，简介与人设也不入库；对外结果表只输出 6 列。进入拆解前必须过 `rights_gate`，云端创建任务写 `compliance_ack{version, accepted_at, account}`（对应 `docs/项目缺口清单-2026-11.md` 的 P0-7），桌面端复用 `src/compliance.py` 同一条款版本号。完整白名单、口径归一与质量门槛见 `config/trend_schema.json`；跨平台阅读量数值不可比，禁止混排。
- **并发**：桌面沿用 `JOB_LOCK` + 同书互斥；云端 `worker.py:84` 取任务需补 `with_for_update(skip_locked=True)`，否则多 worker 会抢同一任务。

---

## 9. 落地分期与文件改动清单

| 期 | 内容 | 涉及文件 |
|---|---|---|
| P0 骨架（可先验证，不动生成逻辑） | DAG 声明、拓扑解析、指纹、脏标记传播、执行模式路由；把现有 `decompose / adapt / storymap / expand` 四阶段当作超节点跑通 | 新增 `src/dag.py`；`config/dag.json`、`config/dependency_map.json`；`src/webapp.py`（queue → 拓扑队列）；`server/app/worker/*`（step_key 存 node_id） |
| P1 Skill 化 | 把 `decompose.py` 的一次性大 prompt 按 `config/skills.json` 的 39 份契约拆开；registry 三级化；bindings 增加 `dag.*`；`dagctl.py plan` 接真执行器 | `src/skills.py`（新增）、`src/prompts.py`、`src/studio.py`、`config/studio.json`、`src/decompose.py`、`scripts/dagctl.py` |
| P2 一致性闭环 | 规则校验、claim 交叉比对、仲裁、patch 回写、复检；稳定 ID 与 `locked_fields` | `src/consistency.py`、`src/change_set.py`（新增）、`src/entities.py`、`src/storymap.py` |
| P3 榜单与交付 | 按 `config/trend_schema.json` 实现公开榜单采集、六标签归一、阅读量口径归一、Top20 六列输出与权利确认；大纲文档/投稿包导出 | `src/trend.py`（新增）、`scripts/dagctl.py`（接真采集器）、`src/export_book.py`、`web/src/views/*` |
| P4 云端统一 | 桌面与云端共用同一 DAG 状态机；`meta` 存指纹与 lineage；补 `skip_locked` | `server/app/models.py`、`server/app/worker/worker.py`、`server/app/services/tasks.py` |

**不改的文件**：`config/workflow.json`（旧管线保持只读，避免两套执行器混淆）；`data/迷失蔚蓝/*`（现有产物作为 P0 的回归样本，只读）。

---

## 10. 需要你拍板的 4 个点

1. **Skill 是否允许跨 Agent 复用**（例如「世界观」同时被 `outline` 与 `graph.worldview_groups` 用到）：建议共享 prompt、不共享写权，`graph` 只读派生。
2. **一致性修正是自动回写还是人工确认**：建议规则层自动、LLM 冲突项默认生成建议由人工点确认（可开关"全自动"）。
3. **榜单数据源**：自采公开榜单 / 接入第三方榜单 API / 先做人工导入 JSON 占位，三选一；合规评审未过前不接全文。
4. **P0 是否先只做桌面端**：云端 DAG 涉及 `task_steps` 语义扩展与迁移，建议桌面端先跑通再平移。

**已落实（2026-11-06，以磁盘为准）**：`config/flow.json`（4 节点 / 2 条传播规则）、`src/flow.py`（编排器）、`scripts/flowctl.py`（CLI）、`tests/test_flow.py`（14 条断言全过）、`src/webapp.py`（准入与只读 API 接入）。写权唯一、越界回滚、人工锁定字段保护、输入指纹幂等、跨书并行 + 同书串行、任意节点单跑与依赖传播均已实现并验证。v1.2 声称的 41 份 Skill 契约与榜单 Top20 契约未落盘，不再执行。

**体检发现（真实数据）**：`python scripts/flowctl.py check --book 迷失蔚蓝` 报出 395 章中 5 个 `roles` 引用无对应角色卡（吴钰、廖凯、徐江洪、徐洁、陈骏），且 `items` 卡片为空。这是既有产物的名称主键问题（见本文 §0 第 3 点），规则层只报告、不自动改数据；需要人工补卡或后续引入稳定 ID 后统一重建。

**后续可选**：榜单 Agent 若要做，先走合规评审再接 `src/trend.py`；云端 `TaskStep` 语义扩展与 `skip_locked` 修正按 §9 的 P4 单独排期。本文 §10 的 4 个拍板点中，1/2/3 随单编排器方案已失效，只剩「P4 云端是否后做」仍有效。
