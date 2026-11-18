# -*- coding: utf-8 -*-
"""统一记忆索引 + 稳定实体 ID + 跨端 claim 台账 回归。

- 桌面 src/entity_ids.py 与云端 app/agents/entity_ids.py 是同一算法的镜像，
  本测试交叉加载两端模块，锁定 ID 与台账归一化结果一致。
- 云端 memory.from_desktop_index 能把桌面 memory_index.json 折算成检索源。
- continuity_check 以稳定 ID 命中跨端台账，且能识别回收章语义冲突。
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

from app.agents import entity_ids as cloud_ids
from app.agents.memory import build_context, from_desktop_index, search
from app.agents.skills.continuity_check import ContinuityCheckSkill, ContinuityInput

ROOT = Path(__file__).resolve().parents[2]


def _load_desktop_ids():
    path = ROOT / "src" / "entity_ids.py"
    spec = importlib.util.spec_from_file_location("desktop_entity_ids", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_desktop_cloud_id_mirrors_agree():
    desk = _load_desktop_ids()
    cases = [
        ("char", "林辰"),
        ("char", "林 辰"),          # 空白归一化
        ("faction", "天剑宗"),
        ("item", "玄铁剑"),
        ("fs", "玉佩里的秘密"),
    ]
    for kind, name in cases:
        assert desk.stable_id(kind, name) == cloud_ids.stable_id(kind, name), (kind, name)
        assert desk.entity_id(kind, name) == cloud_ids.entity_id(kind, name), (kind, name)

    # 折叠重复字：'萧炎炎炎' 与 '萧炎' 归一化到同一 ID（别名归并基础）
    assert cloud_ids.entity_id("char", "萧炎炎炎") == cloud_ids.entity_id("char", "萧炎")

    # 同名不同类必须不同 ID
    assert cloud_ids.entity_id("char", "青锋") != cloud_ids.entity_id("item", "青锋")


def test_normalize_ledger_disambiguates_chapter_semantics():
    desk = _load_desktop_ids()
    desktop_row = {"text": "玉佩里藏着旧案线索，第七章揭晓", "seed": "玉佩里的秘密", "chapter": 7, "status": "已回收"}
    cloud_row = {"id": "F1", "desc": "玉佩里的秘密", "planted_chapter": 2, "payoff_chapter": 9}

    d = cloud_ids.normalize_ledger_row(desktop_row, source="desktop")
    c = cloud_ids.normalize_ledger_row(cloud_row, source="cloud")

    # 桌面 chapter=回收章 → payoff_chapter；不误当埋设章
    assert d["planted_chapter"] == 0
    assert d["payoff_chapter"] == 7
    # 云端拆列直接采用
    assert c["planted_chapter"] == 2
    assert c["payoff_chapter"] == 9
    # 同 seed 跨端稳定 ID 一致；F1 顺序号降级为 legacy_id
    assert d["id"] == c["id"]
    assert c["legacy_id"] == "F1"
    # 两端归一化逻辑一致（同一份镜像实现）
    assert desk.normalize_ledger_row(desktop_row, source="desktop") == d


def test_from_desktop_index_feeds_cloud_search():
    index = {
        "version": 2,
        "nouns": ["林辰", "天剑宗"],
        "chapters": {
            "1": {
                "version": 2, "no": 1, "title": "开局", "summary": "林辰在山门被逐，得到一枚玉佩",
                "roles": ["林辰"], "factions": ["天剑宗"], "items": ["玉佩"],
                "role_ids": [cloud_ids.entity_id("char", "林辰")],
                "head": "林辰被逐", "tail": "玉佩发烫", "chars": 120,
                "tf": [["林辰", 3], ["玉佩", 2]], "tf_total": 5,
            },
            "2": {
                "version": 2, "no": 2, "title": "追杀", "summary": "林辰遭天剑宗追杀，逃入荒野",
                "roles": ["林辰"], "factions": ["天剑宗"],
                "head": "追兵将至", "tail": "跳下悬崖", "chars": 90,
                "tf": [["追杀", 2]], "tf_total": 2,
            },
        },
    }
    rows = from_desktop_index(index)
    assert [row["no"] for row in rows] == [1, 2]
    assert rows[0]["role_ids"] == [cloud_ids.entity_id("char", "林辰")]

    hits = search(rows, "林辰 玉佩", top_k=2)
    assert hits and hits[0]["no"] in (1, 2)

    ctx = build_context(rows, {"chapter": 2, "title": "追杀", "summary": "林辰逃亡", "roles": ["林辰"]})
    assert "前文记忆" in ctx


def _run_local(payload: ContinuityInput):
    from app.agents.contracts import SkillContext
    from app.config import Settings

    settings = Settings(model_stub=True, env="test", llm_base_url="http://upstream.test")
    ctx = SkillContext(settings=settings)
    return ContinuityCheckSkill().run(payload, ctx)


def test_continuity_matches_cross_end_ledger_by_stable_id():
    seed = "玉佩里的秘密"
    sid = cloud_ids.foreshadow_id(seed)
    payload = ContinuityInput(
        title="统一索引测试",
        chapters=[],
        outline=[],
        foreshadow_ledger=[{"id": sid, "desc": seed, "planted_chapter": 2, "payoff_chapter": 9}],
        desktop_ledger=[{"id": sid, "text": seed, "chapter": 9, "status": "已回收"}],
        settings={},
        characters=[],
    )
    out = _run_local(payload)
    cross = [row for row in out.checks if row.dimension == "foreshadow" and row.source == "both"]
    assert cross, out.checks
    # 回收章语义一致（桌面 chapter=9 == 云端 payoff_chapter=9）→ pass
    assert all(row.status != "conflict" for row in cross)
    assert all("稳定ID" in row.evidence for row in cross)

    # 桌面回收章改成 5，与云端 9 冲突 → 应报 conflict
    payload.desktop_ledger = [{"id": sid, "text": seed, "chapter": 5, "status": "已回收"}]
    out2 = _run_local(payload)
    cross2 = [row for row in out2.checks if row.dimension == "foreshadow" and row.source == "both"]
    assert any(row.status == "conflict" for row in cross2)


def test_claims_use_stable_entity_id():
    payload = ContinuityInput(
        title="实体 ID 测试",
        settings={"characters": [{"name": "林辰", "stance": "正面"}]},
        characters=[{"name": "林辰", "stance": "反面"}],
    )
    out = _run_local(payload)
    claims = [c for c in out.claims if c.subject == "林辰"]
    assert claims
    assert claims[0].subject_id == cloud_ids.entity_id("char", "林辰")
    assert claims[0].conflict is True  # 立场不一致


def test_lore_extract_emits_stable_ids():
    # 归一化函数位于模块级，直接校验输出字段
    from app.agents.skills import lore_extract

    row = lore_extract._normalize_character({"name": "林辰"}, 1, stub=True)
    assert row["id"] == cloud_ids.entity_id("char", "林辰")
    assert lore_extract._normalize_faction({"name": "天剑宗"}, 1)["id"] == cloud_ids.entity_id("faction", "天剑宗")
    assert lore_extract._normalize_item({"name": "玄铁剑"}, 1)["id"] == cloud_ids.entity_id("item", "玄铁剑")
