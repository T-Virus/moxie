# -*- coding: utf-8 -*-
"""相似度检查：n-gram/句级重合、最长连续片段、超阈值段落。"""

from __future__ import annotations

from app.services.similarity import compare_chapters, compare_texts


SOURCE = (
    "第一章 雨夜\n\n"
    "陆沉站在屋檐下，雨水顺着瓦片滴落。他握紧了手里的铜钥匙，"
    "那是父亲留给他的唯一遗物。远处传来马蹄声，越来越近。\n\n"
    "门被推开了，一个披着蓑衣的男人走了进来。"
)
OUTPUT_COPY = (
    "第一章 雨夜\n\n"
    "陆沉站在屋檐下，雨水顺着瓦片滴落。他握紧了手里的铜钥匙，"
    "那是父亲留给他的唯一遗物。远处传来马蹄声，越来越近。\n\n"
    "门被推开了，一个披着蓑衣的男人走了进来。"
)
OUTPUT_REWRITE = (
    "第一章 雨夜\n\n"
    "夜雨敲打着青瓦，陆沉靠着门框，掌心的铜钥匙被捏得发烫。"
    "这是父亲留下的最后一件东西。街口忽然响起急促的马蹄。\n\n"
    "木门吱呀一声，一个满身泥水的陌生人侧身闪了进来。"
)


def test_copy_detected_as_high_overlap():
    result = compare_texts(SOURCE, OUTPUT_COPY, n=8, threshold=0.35)
    assert result["overlap_ratio"] > 0.9
    assert result["sentence_overlap_ratio"] >= 0.8
    assert result["longest_common_chars"] >= 40
    assert result["flagged"] is True
    assert result["paragraphs_over_threshold"] >= 2
    assert result["paragraphs"][0]["overlap_ratio"] > 0.9


def test_rewrite_is_below_threshold():
    result = compare_texts(SOURCE, OUTPUT_REWRITE, n=8, threshold=0.35)
    assert result["overlap_ratio"] < 0.35
    assert result["flagged"] is False
    assert result["paragraphs_over_threshold"] == 0


def test_compare_chapters_aggregates_and_flags():
    source = [{"chapter": 1, "content": SOURCE}, {"chapter": 2, "content": SOURCE}]
    output = [{"chapter": 1, "text": OUTPUT_COPY}, {"chapter": 2, "text": OUTPUT_REWRITE}]
    result = compare_chapters(source, output, n=8, threshold=0.35)
    assert result["chapters_compared"] == 2
    assert result["chapters_over_threshold"] == 1
    assert 0.35 < result["overall_overlap_ratio"] < 0.9
    assert result["flagged_paragraphs"]
    assert result["flagged_paragraphs"][0]["chapter_no"] == 1
