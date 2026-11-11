# 相似度与改编幅度检查（本地计算）

纯本地 n-gram 计算，不调用模型、不依赖外部服务；用于提示「产出与参考作品是否过于接近」。

## 1. 算法

| 指标 | 说明 |
|---|---|
| `overlap_ratio` | 产出文本的 n-gram 中，能在原文找到的比例（0–1，越高越像照搬） |
| `sentence_overlap_ratio` | 产出句子中，与原文 n-gram 重合率 ≥ 0.8 的句子占比 |
| `longest_common_chars` | 最长连续重合字符数（按 n-gram 连续命中估算） |
| `paragraphs_over_threshold` | 超过阈值的段落数 |
| `flagged` | `overlap_ratio > threshold`（单文本） |

- 默认 `n=8`（`SIMILARITY_NGRAM`）、阈值 `0.35`（`SIMILARITY_THRESHOLD`）；
- 段落按空行切分，超阈值段落按重合率倒序，最多输出 `SIMILARITY_MAX_PARAGRAPHS` 条（默认 20）；
- 去空白后比较，避免排版差异影响结果。

章节聚合（`compare_chapters`）：按章节顺序配对，输出

```json
{
  "ngram_size": 8,
  "threshold": 0.35,
  "chapters_compared": 2,
  "overall_overlap_ratio": 0.46,
  "chapters_over_threshold": 1,
  "longest_common_chars": 120,
  "paragraphs_over_threshold": 3,
  "flagged_paragraphs": [{"chapter_no": 1, "paragraph": 1, "overlap_ratio": 0.93, "preview": "…"}],
  "chapters": [{"chapter_no": 1, "overlap_ratio": 0.93, ...}]
}
```

## 2. 产物与入口

| 任务 | 产物 key | manifest 摘要 |
|---|---|---|
| 改编 `adapt` | `<book>/<task_id>/similarity.json` | `manifest.similarity = {artifact, overall_overlap_ratio, chapters_over_threshold, paragraphs_over_threshold, flagged}` |
| 审查 `review` | `<book>/<task_id>/review/similarity.json` | 同上 |

- 改编：有原章节时比对原书 vs 改编产出；`local=true` 同样执行；
- 审查：优先取 `decomposed_doc`，否则按 `source_key` 文本切段；无源文本时跳过并记录。
- 相似度仅是**提示性体检指标**，不阻断任务、不自动退款、不替代人工判断。

## 3. 配置

```dotenv
SIMILARITY_NGRAM=8
SIMILARITY_THRESHOLD=0.35
SIMILARITY_MAX_PARAGRAPHS=20
```

## 4. 测试

`tests/test_similarity.py`（3 条）：原文复制 → 高重合且 `flagged`；改写 → 低于阈值；
跨章节聚合与 `flagged_paragraphs` 归属；另有 runner 集成断言（`test_runners_ext.py`）。
