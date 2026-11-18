# -*- coding: utf-8 -*-
"""P1–P5 云端技能闭环单测：正文链 / humanizer / cover / memory / continuity。

只依赖标准库与仓库内模块，不启动 app；放在 server/tests 并入既有 pytest 基线。
"""

from __future__ import annotations

from app.agents.graph import CLOUD_BODY_CHAPTERS, GRAPHS, _expand
from app.agents.memory import build_context, search
from app.agents.skills.cover_plan import CoverInput, CoverSkill
from app.agents.skills.humanizer import HumanizerInput, HumanizerSkill
from app.agents.skills.continuity_check import ContinuityCheckSkill, ContinuityInput
from app.config import Settings
from app.agents.contracts import SkillContext


def _stub_ctx() -> SkillContext:
    return SkillContext(settings=Settings(model_stub=True, env="test", llm_base_url="http://upstream.test"))


# ---------- P1 正文链 ----------

def test_all_graphs_have_body_chain_after_outline():
    for mode, graph in GRAPHS.items():
        ids = graph.node_ids()
        assert "chapter_expand" in ids and "polish" in ids, mode
        assert ids.index("outline") < ids.index("chapter_expand") < ids.index("polish"), mode
        assert "chapter_expand" in graph.node("chapter_summarize").depends_on, mode
        assert graph.node("chapter_expand").chaptered is True, mode
        assert graph.node("chapter_expand").skill == "chapter_write", mode


def test_expand_caps_chapters_and_injects_memory():
    state = {
        "outline": {
            "chapters": [
                {"chapter": i, "title": f"第{i}章", "summary": f"第{i}章发生的关键事件与冲突。" * 3}
                for i in range(1, 8)
            ],
            "story_bible": {"world": "都市异能"},
        }
    }
    view = type("V", (), {"title": "测试", "genre_name": "都市", "mode": "hot"})()
    payload = _expand(view, state, {})
    assert len(payload["chapters"]) == CLOUD_BODY_CHAPTERS
    assert payload["story_bible"]["world"] == "都市异能"
    assert payload["chapters"][0]["memory_context"] == ""  # 第一章无前文
    assert "最近章节脉络" in payload["chapters"][1]["memory_context"]


# ---------- P4 记忆检索 ----------

def test_memory_search_and_build_context():
    chapters = [
        {"chapter": i, "title": f"第{i}章", "summary": f"林越在第{i}章找到关键道具青铜钥匙，引出旧案真相。"}
        for i in range(1, 6)
    ]
    hits = search(chapters, "青铜钥匙 旧案", top_k=2)
    assert hits and all("no" in hit for hit in hits)
    context = build_context(chapters, chapters[4])
    assert "【前文记忆】" in context
    assert "最近章节脉络" in context
    assert build_context(chapters[:1], chapters[0]) == ""


# ---------- P2 humanizer ----------

def test_humanizer_detects_and_cleans_traces():
    payload = HumanizerInput(
        title="测试",
        genre_name="都市",
        chapters=[{"chapter": 1, "title": "第一章", "content": "首先，他仿佛明白了什么。总之，一切尘埃落定。"}],
    )
    out = HumanizerSkill().run(payload, _stub_ctx())
    assert len(out.chapters) == 1
    assert out.total_traces >= 2
    assert "首先" not in out.chapters[0].content
    assert out.chapters[0].source in {"fallback", "model", "passthrough"}


# ---------- P3 cover ----------

def test_cover_plan_reuses_prompt_builder_and_checks_crop():
    payload = CoverInput(
        title="非常非常长的书名超过十二个字会告警",
        genre_name="都市异能",
        author="某位笔名很长的作者名字",
        outline={"story_bible": {"world": "现代都市", "core_hook": "隐藏规则"}, "themes": ["成长"]},
    )
    out = CoverSkill().run(payload, _stub_ctx())
    assert out.plan.prompt and "都市异能" in out.plan.prompt
    assert out.plan.style == "gold" and out.plan.layout == "top"
    assert any(not check.ok for check in out.plan.checks)
    assert out.plan.source == "services.cover#build_prompt"


# ---------- P5 continuity ----------

def test_continuity_checks_four_dimensions_and_cross_compare():
    payload = ContinuityInput(
        title="测试",
        chapters=[{"chapter_no": 1, "roles": ["林越"], "foreshadow_ids": ["F1"]}],
        outline=[{"chapter": 1}],
        foreshadow_ledger=[{"id": "F1", "desc": "钥匙", "planted_chapter": 5, "payoff_chapter": 2}],
        desktop_ledger=[{"text": "另一条桌面伏笔", "status": "待确认"}],
        settings={"characters": [{"name": "林越", "stance": "主角"}]},
        characters=[{"name": "林越", "stance": "反派"}],
    )
    out = ContinuityCheckSkill().run(payload, _stub_ctx())
    assert set(out.dimension_summary) == {"character", "foreshadow", "timeline", "setting"}
    assert any(row.status == "conflict" and row.dimension == "foreshadow" for row in out.checks)
    assert any(claim.conflict and claim.subject == "林越" for claim in out.claims)
    assert out.conflict_count >= 2


# ---------- 第十六批：全本正文分段调度 ----------

def test_expand_body_start_and_chapters_window():
    state = {
        "outline": {
            "chapters": [
                {"chapter": i, "title": f"第{i}章", "summary": f"林越在第{i}章推进主线冲突，拿到新的线索。" * 2}
                for i in range(1, 11)
            ],
            "story_bible": {},
        }
    }
    view = type("V", (), {"title": "分段", "genre_name": "都市", "mode": "hot"})()
    # 第 4 章起写 3 章：章号稳定为 4/5/6，不重编号为 1/2/3
    payload = _expand(view, state, {"options": {"body_start": 4, "body_chapters": 3}})
    assert [c["chapter"] for c in payload["chapters"]] == [4, 5, 6]
    # 第二段第一章节能读到前文（来自章纲索引，不含未来章）
    assert "前文记忆" in payload["chapters"][0]["memory_context"]
    assert "第6章" not in payload["chapters"][0]["memory_context"]


def test_expand_body_segment_slicing():
    state = {
        "outline": {
            "chapters": [
                {"chapter": i, "title": f"第{i}章", "summary": f"第{i}章事件，主角做出关键选择并承担后果。" * 2}
                for i in range(1, 9)
            ],
            "story_bible": {},
        }
    }
    view = type("V", (), {"title": "分段", "genre_name": "都市", "mode": "hot"})()
    # 每段 2 章，第 2 段 → 第 3/4 章
    extra = {"options": {"body_segment": 2, "body_chapters": 2}}
    payload = _expand(view, state, extra)
    assert [c["chapter"] for c in payload["chapters"]] == [3, 4]


def test_expand_respects_max_cap():
    state = {
        "outline": {
            "chapters": [{"chapter": i, "title": f"第{i}章", "summary": "事件"} for i in range(1, 50)],
            "story_bible": {},
        }
    }
    view = type("V", (), {"title": "上限", "genre_name": "都市", "mode": "hot"})()
    # 请求 100 章，但 extra 注入上限 5 → 只写 5 章
    payload = _expand(view, state, {"options": {"body_chapters": 100}, "body_max_chapters": 5})
    assert len(payload["chapters"]) == 5


def test_expand_includes_prior_written_chapters_in_memory():
    state = {
        "outline": {
            "chapters": [
                {"chapter": i, "title": f"第{i}章", "summary": f"第{i}章主线推进。" * 2}
                for i in range(1, 8)
            ],
            "story_bible": {},
        },
        # 第一段已写正文：含独特的专名"青锋"，应作为跨段前情被检索到
        "chapter_expand": {
            "chapters": [
                {
                    "no": 1, "chapter": 1, "title": "第1章",
                    "summary": "林越在旧货铺获得青锋剑，签下契约。",
                    "content": "林越握住青锋剑，剑鞘上刻着古老的纹路。" * 10,
                }
            ]
        },
    }
    view = type("V", (), {"title": "跨段", "genre_name": "都市", "mode": "hot"})()
    payload = _expand(view, state, {"options": {"body_start": 2, "body_chapters": 1}})
    ctx = payload["chapters"][0]["memory_context"]
    assert "青锋" in ctx  # 已写正文的专名进入第 2 章前情
