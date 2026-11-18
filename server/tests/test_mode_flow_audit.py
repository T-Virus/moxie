# -*- coding: utf-8 -*-
"""三模式流程 × 10 环节技能方案核对：把实测的覆盖与产出固化为契约。

背景（2026-11-17 核对）：hot/reference/custom 三图都属"规划型"流程——产出大纲、
概括、设定、实体、体检与发布包，不写正文。
更新（2026-11-18 P1–P5）：三图恢复正文链（chapter_expand → polish），并加入
continuity_check 四维核查表与 cover_plan 封面方案；10 环节在云端全部有产出。
本测试防止两种漂移：① 图节点悄悄增删导致覆盖声明失真；② SSOT 写入未实现的产出字段。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.agents.graph import GRAPHS

from .helpers import subscribe
from .test_agent_runs import _create, _execute, _stub, _upload

CATALOG = Path(__file__).resolve().parents[2] / "config" / "skills_catalog.json"

# 端到端实测的节点链（不含段级 checkpoint outline_decompose:seg:*）
EXPECTED_NODES = {
    "hot": {
        "genre_research", "positioning", "settings", "outline", "chapter_expand", "polish",
        "chapter_summarize", "character_graph", "continuity_check",
        "consistency_review", "compliance_review", "review_merge", "cover_plan", "publish",
    },
    "reference": {
        "positioning", "outline_decompose", "settings", "adaptation", "outline",
        "chapter_expand", "polish", "chapter_summarize", "character_graph", "continuity_check",
        "consistency_review", "compliance_review", "review_merge", "cover_plan", "publish",
    },
    "custom": {
        "positioning", "settings", "outline", "chapter_expand", "polish",
        "chapter_summarize", "character_graph", "continuity_check",
        "consistency_review", "compliance_review", "review_merge", "cover_plan", "publish",
    },
}

CORE_ARTIFACTS = {
    "outline.md", "chapter_summaries.json", "characters.json", "factions.json", "items.json",
    "story_bible.json", "positioning_card.json", "settings_pack.json", "foreshadow_ledger.json",
    "publish_pack.json", "volumes.json",
}
BODY_ARTIFACTS = {"chapters.json", "chapters_full.json", "manuscript.md", "polish_report.json"}
EXTENDED_ARTIFACTS = {"continuity_check.json", "cover_plan.json"}
BODY_NODES = {"chapter_expand", "polish"}


def test_mode_node_chains_are_locked():
    """节点链是 10 环节覆盖声明的落点；增删节点必须显式改测试与 SSOT。"""
    assert set(GRAPHS) == set(EXPECTED_NODES)
    for mode, expected in EXPECTED_NODES.items():
        assert set(GRAPHS[mode].node_ids()) == expected, mode


def test_all_modes_write_body():
    """三模式均有正文节点（SSOT write=full）：黄金三章 + 润色。"""
    for mode, graph in GRAPHS.items():
        assert BODY_NODES <= set(graph.node_ids()), mode
        assert graph.node("chapter_expand").skill == "chapter_write", mode
        assert graph.node("polish").skill == "humanizer", mode


def test_catalog_writes_have_no_unimplemented_claims():
    """历史上 writes 曾声明 compliance_ack / meta#claims，代码里并不存在。"""
    doc = json.loads(CATALOG.read_text(encoding="utf-8"))
    writes = [w for item in doc["items"] for w in (item.get("writes") or [])]
    assert not any("compliance_ack" in w for w in writes)
    assert not any("meta#claims" in w for w in writes)
    by_id = {item["id"]: item for item in doc["items"]}
    assert "foreshadow_ledger.json" in by_id["consistency"]["writes"]
    assert "continuity_check.json" in by_id["consistency"]["writes"]
    assert by_id["write"]["coverage"] == "full"
    assert by_id["polish"]["coverage"] == "full"
    assert by_id["cover"]["coverage"] == "full"


@pytest.mark.parametrize("mode", ["hot", "reference", "custom"])
def test_mode_runtime_artifacts_and_fields(client, headers, app, mode):
    """实测三模式：run 成功、核心/正文/扩展产物齐全、发布与体检字段完整。"""
    _stub(app)
    subscribe(client, headers)
    kwargs: dict = {"options": {"target_chapters": 6}}
    if mode == "reference":
        kwargs["source_key"] = _upload(client, headers)
    created = _create(client, headers, mode=mode, title=f"流程审计-{mode}", **kwargs)
    assert created.status_code == 201, created.text
    run_id = created.json()["run_id"]
    assert _execute(app, run_id) == "succeeded"

    detail = client.get(f"/v1/agent-runs/{run_id}", headers=headers).json()
    names = {item["name"] for item in detail["artifacts"]}
    assert CORE_ARTIFACTS <= names, mode
    assert BODY_ARTIFACTS <= names, mode
    assert EXTENDED_ARTIFACTS <= names, mode
    assert detail["summary"]["chapters_count"] == 3, mode
    assert len(detail["chapters"]) == 3, mode
    assert len(detail["outline"]["chapters"]) == 6, mode
    assert len(detail["chapter_summaries"]) == 6, mode
    for chapter in detail["outline"]["chapters"]:
        assert chapter.get("conflict") and chapter.get("hook"), mode

    publish = client.get(
        f"/v1/agent-runs/{run_id}/artifacts/publish_pack.json", headers=headers
    ).json()
    assert publish.get("tags") and publish.get("blurb"), mode
    review = detail["review"] or {}
    assert review.get("score") is not None and review.get("suggestions"), mode

    continuity = client.get(
        f"/v1/agent-runs/{run_id}/artifacts/continuity_check.json", headers=headers
    ).json()
    assert set(continuity["dimension_summary"]) == {"character", "foreshadow", "timeline", "setting"}, mode
    cover = client.get(
        f"/v1/agent-runs/{run_id}/artifacts/cover_plan.json", headers=headers
    ).json()
    assert cover["plan"]["prompt"] and cover["plan"]["checks"], mode
