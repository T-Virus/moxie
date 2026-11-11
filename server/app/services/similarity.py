# -*- coding: utf-8 -*-
"""相似度与改编幅度检查（纯本地计算，不调用模型）。

指标：
  · overlap_ratio：产出文本的 n-gram 中能在原文找到的比例（越高越像照搬）；
  · sentence_overlap_ratio：产出句子中与原文句子高度重合的比例；
  · longest_common_chars：最长连续重合字符数（按 n-gram 连续命中估算）；
  · paragraphs_over_threshold：超过阈值的产出段落清单（含 preview 与比例）。

产物 `similarity.json` 写入对象存储，并汇总进任务 manifest / 体检结果。
"""

from __future__ import annotations

import re
from typing import Any

_SENTENCE_SPLIT = re.compile(r"[。！？!?\n]+")


def _clean(text: str) -> str:
    return re.sub(r"\s+", "", text or "")


def _ngrams(text: str, n: int) -> set[str]:
    cleaned = _clean(text)
    if len(cleaned) < n:
        return {cleaned} if cleaned else set()
    return {cleaned[i: i + n] for i in range(len(cleaned) - n + 1)}


def _sentences(text: str) -> list[str]:
    return [s.strip() for s in _SENTENCE_SPLIT.split(text or "") if s.strip()]


def _paragraphs(text: str) -> list[str]:
    return [p.strip() for p in re.split(r"\n{2,}|\r\n{2,}", text or "") if p.strip()]


def _overlap(ngrams_out: set[str], ngrams_src: set[str]) -> float:
    if not ngrams_out:
        return 0.0
    return len(ngrams_out & ngrams_src) / len(ngrams_out)


def _longest_run(text_out: str, text_src: str, n: int) -> int:
    """按 n-gram 连续命中估算最长连续重合字符数。"""
    cleaned_out = _clean(text_out)
    cleaned_src = _clean(text_src)
    if len(cleaned_out) < n or len(cleaned_src) < n:
        return 0
    src_grams = _ngrams(cleaned_src, n)
    best = 0
    run = 0
    for i in range(len(cleaned_out) - n + 1):
        if cleaned_out[i: i + n] in src_grams:
            run += 1
            best = max(best, run)
        else:
            run = 0
    return best + n - 1 if best else 0


def compare_texts(
    source_text: str,
    output_text: str,
    *,
    n: int = 8,
    threshold: float = 0.35,
    max_paragraphs: int = 20,
) -> dict[str, Any]:
    n = max(2, int(n))
    src_grams = _ngrams(source_text, n)
    out_grams = _ngrams(output_text, n)
    overlap_ratio = _overlap(out_grams, src_grams)

    src_sentences = _sentences(source_text)
    out_sentences = _sentences(output_text)
    high = 0
    for sentence in out_sentences:
        grams = _ngrams(sentence, n)
        if grams and _overlap(grams, src_grams) >= 0.8:
            high += 1
    sentence_ratio = high / len(out_sentences) if out_sentences else 0.0

    paragraphs = []
    for index, paragraph in enumerate(_paragraphs(output_text), 1):
        ratio = _overlap(_ngrams(paragraph, n), src_grams)
        if ratio > threshold:
            paragraphs.append(
                {
                    "paragraph": index,
                    "overlap_ratio": round(ratio, 4),
                    "preview": paragraph[:80],
                }
            )
    paragraphs.sort(key=lambda item: item["overlap_ratio"], reverse=True)
    truncated = paragraphs[:max_paragraphs]

    return {
        "ngram_size": n,
        "threshold": threshold,
        "overlap_ratio": round(overlap_ratio, 4),
        "sentence_overlap_ratio": round(sentence_ratio, 4),
        "longest_common_chars": _longest_run(output_text, source_text, n),
        "overlapping_sentences": high,
        "output_sentences": len(out_sentences),
        "paragraphs_over_threshold": len(paragraphs),
        "paragraphs": truncated,
        "flagged": overlap_ratio > threshold,
    }


def _chapter_text(chapter: Any) -> str:
    if not isinstance(chapter, dict):
        return str(chapter or "")
    for key in ("content", "text", "body", "chapter_content"):
        if chapter.get(key):
            return str(chapter[key])
    return ""


def compare_chapters(
    source_chapters: list,
    output_chapters: list,
    *,
    n: int = 8,
    threshold: float = 0.35,
    max_paragraphs: int = 20,
) -> dict[str, Any]:
    """按章节顺序配对比较；返回可直接落 similarity.json 的结果。"""
    rows = []
    total_out_chars = 0
    weighted_overlap = 0.0
    flagged_paragraphs: list[dict] = []
    longest = 0
    for index in range(min(len(source_chapters or []), len(output_chapters or []))):
        source_text = _chapter_text(source_chapters[index])
        output_text = _chapter_text(output_chapters[index])
        if not output_text:
            continue
        item = compare_texts(
            source_text, output_text, n=n, threshold=threshold, max_paragraphs=max_paragraphs
        )
        no = (output_chapters[index] or {}).get("chapter") or index + 1
        rows.append(
            {
                "chapter_no": no,
                "overlap_ratio": item["overlap_ratio"],
                "sentence_overlap_ratio": item["sentence_overlap_ratio"],
                "longest_common_chars": item["longest_common_chars"],
                "paragraphs_over_threshold": item["paragraphs_over_threshold"],
            }
        )
        total_out_chars += len(_clean(output_text))
        weighted_overlap += item["overlap_ratio"] * len(_clean(output_text))
        longest = max(longest, item["longest_common_chars"])
        for paragraph in item["paragraphs"]:
            flagged_paragraphs.append(
                {
                    "chapter_no": no,
                    **paragraph,
                }
            )
    flagged_paragraphs.sort(key=lambda p: p["overlap_ratio"], reverse=True)
    overall = weighted_overlap / total_out_chars if total_out_chars else 0.0
    return {
        "ngram_size": n,
        "threshold": threshold,
        "chapters_compared": len(rows),
        "overall_overlap_ratio": round(overall, 4),
        "chapters_over_threshold": sum(1 for r in rows if r["overlap_ratio"] > threshold),
        "longest_common_chars": longest,
        "paragraphs_over_threshold": len(flagged_paragraphs),
        "flagged_paragraphs": flagged_paragraphs[:max_paragraphs],
        "chapters": rows,
    }
