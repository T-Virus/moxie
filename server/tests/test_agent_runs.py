# -*- coding: utf-8 -*-
"""Agent 编排层：三模式、幂等、额度/订阅、SSE、取消、恢复、断点续跑、节点重试。"""

from __future__ import annotations

import io
import json
import threading
import time
import uuid
import zipfile

from app.agents.engine import execute_agent_run
from app.agents.skills.genre_research import GenreResearchSkill
from app.agents.skills.outline import OutlineChapter, OutlineOutput, OutlineSkill
from app.agents.skills.outline_decompose import OutlineDecomposeSkill
from app.agents.skills.compliance_review import (
    ComplianceInput,
    ComplianceOutput,
    ComplianceReviewSkill,
    ComplianceRisk,
)
from app.agents.skills.consistency_review import ConsistencyInput, ConsistencyReviewSkill
from app.config import Settings
from app.models import AgentRun, AgentRunEvent, AgentRunStep
from app.services.storage import book_slug

from sqlalchemy import func, select

from .helpers import db_session, subscribe

SOURCE_TEXT = """第一章 夜雨
雨夜，主角在旧城区接到一封没有署名的信。信里只有一句话：今夜不要回家。
他犹豫了半分钟，还是拐进了相反方向的巷子，却在拐角撞见不该出现的人。

第二章 旧账
对方开门见山，提起十年前的一笔旧账。主角第一次意识到，自己以为已经结束的事，
其实只是被人暂时按下。两人交锋三回合，主角拿到一枚旧钥匙。

第三章 钥匙
钥匙打开的不是门，而是一只封存的箱子。箱子里没有财物，只有一份名单。
名单上第一个名字，是主角最信任的人。
"""


def _stub(app):
    app.state.settings.model_stub = True
    return app


def _create(client, headers, **overrides):
    body = {
        "mode": "hot",
        "title": "测试书稿",
        "audience": "male",
        "length": "short",
        "genre": {"id": "xuanyi", "name": "悬疑"},
        "brief": "快节奏悬疑，前三章必须有反转。",
    }
    body.update(overrides)
    return client.post(
        "/v1/agent-runs",
        headers={**headers, "Idempotency-Key": f"agent-{uuid.uuid4()}"},
        json=body,
    )


def _upload(client, headers, text: str = SOURCE_TEXT) -> str:
    response = client.post(
        "/v1/uploads",
        headers=headers,
        files={"file": ("source.txt", text.encode("utf-8"), "text/plain")},
    )
    assert response.status_code == 201, response.text
    return response.json()["source_key"]


def _long_source(chapters: int = 12, chars: int = 4500) -> str:
    unit = "雨夜追逐中，主角察觉对方在故意引导他走向旧仓库，线索与十年前旧案重合。"
    body = (unit * (chars // len(unit) + 1))[:chars]
    return "\n".join(f"第{number}章 线索{number}\n{body}\n" for number in range(1, chapters + 1))


def _execute(app, run_id: str, *, overrides=None, max_steps=None):
    with db_session(app) as session:
        run = session.get(AgentRun, run_id)
        status = execute_agent_run(
            session,
            run,
            settings=app.state.settings,
            storage=app.state.storage,
            skill_overrides=overrides,
            max_steps=max_steps,
        )
        session.commit()
        return status


class _HighRiskReview(ComplianceReviewSkill):
    """合规体检桩：始终产出高危风险，验证体检结果只记录不暂停。"""

    def run(self, payload, ctx):
        return ComplianceOutput(
            risks=[
                ComplianceRisk(
                    level="high",
                    code="policy",
                    message="开篇存在高风险违规表述",
                    chapter=1,
                )
            ],
            compliance_issues=["[HIGH] 开篇存在高风险违规表述（第 1 章）"],
            high_risk=True,
        )


class _FlakyOutline(OutlineSkill):
    def __init__(self) -> None:
        self.calls = 0

    def run(self, payload, ctx):
        self.calls += 1
        if self.calls == 1:
            raise RuntimeError("upstream 抖动")
        return super().run(payload, ctx)


class _AlwaysFailOutline(OutlineSkill):
    def run(self, payload, ctx):
        raise RuntimeError("永久失败")


class _FailSegments(OutlineDecomposeSkill):
    """在第 3 段的两次尝试上失败，用于验证段级 checkpoint 与单段重试。"""

    def __init__(self, fail_calls: set[int]) -> None:
        self.calls = 0
        self.fail_calls = fail_calls

    def run(self, payload, ctx):
        self.calls += 1
        if self.calls in self.fail_calls:
            raise RuntimeError("单段拆解失败")
        return super().run(payload, ctx)


class _Counting:
    def __init__(self, inner, counter: dict):
        self.inner = inner
        self.counter = counter
        self.name = inner.name
        self.version = inner.version
        self.input_model = inner.input_model
        self.output_model = inner.output_model

    def run(self, payload, ctx):
        self.counter[self.name] = self.counter.get(self.name, 0) + 1
        return self.inner.run(payload, ctx)


def test_genres_contract(client):
    data = client.get("/v1/genres").json()
    assert data["custom_allowed"] is True
    assert data["items"]
    first = data["items"][0]
    assert set(first) == {"id", "name", "audience", "tags"}
    assert "male" in first["audience"] or "female" in first["audience"] or "all" in first["audience"]


def test_create_idempotent_and_requires_subscription(client, headers, app):
    _stub(app)
    created = client.post(
        "/v1/agent-runs",
        headers={**headers, "Idempotency-Key": "agent-idem-1"},
        json={
            "mode": "custom",
            "title": "幂等书",
            "audience": "female",
            "length": "long",
            "genre": {"id": None, "name": "古言"},
        },
    )
    assert created.status_code == 403
    assert created.json()["error"]["code"] == "subscription_required"

    subscribe(client, headers)
    first = client.post(
        "/v1/agent-runs",
        headers={**headers, "Idempotency-Key": "agent-idem-1"},
        json={
            "mode": "custom",
            "title": "幂等书",
            "audience": "female",
            "length": "long",
            "genre": {"id": None, "name": "古言"},
        },
    )
    assert first.status_code == 201, first.text
    assert first.json()["status"] == "queued"
    run_id = first.json()["run_id"]

    second = client.post(
        "/v1/agent-runs",
        headers={**headers, "Idempotency-Key": "agent-idem-1"},
        json={
            "mode": "custom",
            "title": "幂等书",
            "audience": "female",
            "length": "long",
            "genre": {"id": None, "name": "古言"},
        },
    )
    assert second.status_code == 201
    assert second.json()["run_id"] == run_id
    assert second.json()["created"] is False

    summary = client.get("/v1/entitlements", headers=headers).json()
    books = next(m for m in summary["metrics"] if m["metric"] == "books_month")
    assert books["reserved"] == 1


def test_create_and_resume_store_byok_only_in_redis(client, headers, app):
    _stub(app)
    subscribe(client, headers)
    secret = "sk-test-byok-0123456789"
    created = client.post(
        "/v1/agent-runs",
        headers={**headers, "X-BYOK-Key": secret, "Idempotency-Key": f"byok-{uuid.uuid4()}"},
        json={
            "mode": "custom",
            "title": "BYOK 书",
            "audience": "male",
            "length": "short",
            "genre": {"id": "xuanyi", "name": "悬疑"},
        },
    )
    assert created.status_code == 201, created.text
    run_id = created.json()["run_id"]
    stored = json.loads(app.state.redis.get(f"agent:byok:{run_id}"))
    assert stored["key"] == secret and stored["model"] == "" and stored["base_url"] == ""
    assert secret not in created.text

    detail = client.get(f"/v1/agent-runs/{run_id}", headers=headers)
    assert secret not in detail.text
    with db_session(app) as db:
        run = db.get(AgentRun, run_id)
        assert secret not in json.dumps(run.meta or {}, ensure_ascii=False)

    paused = client.post(f"/v1/agent-runs/{run_id}/pause", headers=headers)
    assert paused.status_code == 200, paused.text
    assert paused.json()["status"] == "paused"

    resumed_secret = "sk-test-byok-resume-9876543210"
    resumed = client.post(
        f"/v1/agent-runs/{run_id}/resume",
        headers={**headers, "X-BYOK-Key": resumed_secret},
        json={"approval": True},
    )
    assert resumed.status_code == 200, resumed.text
    stored = json.loads(app.state.redis.get(f"agent:byok:{run_id}"))
    assert stored["key"] == resumed_secret
    assert resumed_secret not in resumed.text


def test_reference_requires_source_key(client, headers, app):
    _stub(app)
    subscribe(client, headers)
    response = _create(client, headers, mode="reference")
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "source_key_required"


def test_reference_source_key_ownership(client, headers, app):
    _stub(app)
    subscribe(client, headers)
    response = _create(client, headers, mode="reference", source_key="uploads/999/other.txt")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "source_not_found"


def test_quota_exceeded(client, headers, app):
    _stub(app)
    subscribe(client, headers)
    for index in range(5):
        response = _create(client, headers, title=f"额度书{index}")
        assert response.status_code == 201, response.text
    sixth = _create(client, headers, title="额度书5")
    assert sixth.status_code == 402
    assert sixth.json()["error"]["code"] == "quota_exceeded"


class _SlowGenreResearch(GenreResearchSkill):
    def run(self, payload, ctx):
        time.sleep(3)
        return super().run(payload, ctx)


def test_running_status_visible_while_worker_busy(client, headers, app):
    """worker 执行期间必须已把 running 提交，前端不能一直看到 queued。"""
    _stub(app)
    subscribe(client, headers)
    run_id = _create(
        client,
        headers,
        mode="hot",
        title="状态可见性校验",
        options={"target_chapters": 6},
    ).json()["run_id"]
    outcome: dict = {}

    def work() -> None:
        with db_session(app) as session:
            run = session.get(AgentRun, run_id)
            try:
                outcome["status"] = execute_agent_run(
                    session,
                    run,
                    settings=app.state.settings,
                    storage=app.state.storage,
                    skill_overrides={"genre_research": _SlowGenreResearch()},
                )
                session.commit()
            except Exception:  # noqa: BLE001
                import traceback

                outcome["error"] = traceback.format_exc()

    thread = threading.Thread(target=work, daemon=True)
    thread.start()
    time.sleep(1.2)
    with db_session(app) as session:
        observed = session.get(AgentRun, run_id).status
    thread.join(timeout=20)

    assert observed == "running", (observed, outcome)
    assert outcome.get("status") == "succeeded", outcome


class _MemStorage:
    def __init__(self) -> None:
        self.json: dict[str, dict] = {}
        self.bytes: dict[str, bytes] = {}

    def put_json(self, key, value, *args, **kwargs) -> None:
        self.json[key] = value

    def put_bytes(self, key, value, *args, **kwargs) -> None:
        self.bytes[key] = value

    def exists(self, key) -> bool:
        return key in self.json or key in self.bytes


def test_hot_artifacts_keep_full_outline_and_summaries(app):
    """热门产物保留全书章纲与全量概括，只有正文限定前三章。"""
    from app.agents.artifacts import write_artifacts
    from app.agents.graph import RunView

    run = RunView(
        id="hot-full",
        mode="hot",
        title="全量章纲",
        audience="male",
        length="long",
        genre_id=None,
        genre_name="都市",
        source_key=None,
        brief=None,
    )
    storage = _MemStorage()
    state = {
        "outline": {"chapters": [{"chapter": i, "title": f"第{i}章"} for i in range(1, 13)]},
        "chapter_expand": {"chapters": [{"chapter": i, "content": "正文"} for i in range(1, 4)]},
        "chapter_summarize": {"chapters": [{"chapter_no": i} for i in range(1, 13)]},
    }
    write_artifacts(storage, run, state)

    summary_key = next(key for key in storage.json if key.endswith("chapter_summaries.json"))
    assert len(storage.json[summary_key]["chapters"]) == 12
    chapters_key = next(key for key in storage.json if key.endswith("chapters.json"))
    assert len(storage.json[chapters_key]["chapters"]) == 3
    assert len(state["outline"]["chapters"]) == 12


def test_full_outline_generation_is_batched(monkeypatch):
    """真实模型路径下 200+ 章要分批生成，不能一次请求输出整本导致截断。"""
    import re

    from app.agents.contracts import SkillContext
    from app.agents.skills import outline as outline_module

    calls: list[str] = []

    def fake_call(ctx, *, system, user):
        calls.append(user)
        if outline_module.PLAN_SUFFIX in user:
            return {
                "logline": "少年在雨夜卷入旧案。",
                "theme": "选择与代价",
                "volumes": [],
                "story_bible": {"worldview": "现代都市"},
            }
        match = re.search(r"第 (\d+)–(\d+) 章", user)
        assert match, user[:200]
        start, end = int(match.group(1)), int(match.group(2))
        return {
            "chapters": [
                {
                    "chapter": number,
                    "title": f"第{number}章 雨夜",
                    "summary": f"第{number}章推进旧案线索，主角做出选择。",
                    "key_events": ["发现线索"],
                    "hook": "新的疑点出现。",
                }
                for number in range(start, end + 1)
            ]
        }

    monkeypatch.setattr(outline_module, "call_json", fake_call)
    ctx = SkillContext(settings=Settings(model_stub=False, env="test", outline_chapter_batch=20))
    result = outline_module.OutlineSkill().run(
        outline_module.OutlineInput(
            title="分批大纲",
            audience="male",
            length="short",
            genre_name="悬疑",
            mode="hot",
            target_chapters=45,
        ),
        ctx,
    )

    assert len(result.chapters) == 45
    assert result.chapters[0].summary.startswith("第1章推进")
    assert result.chapters[-1].summary.startswith("第45章推进")
    assert len(calls) == 1 + 3  # 总纲 1 次 + 20 章一批共 3 次


def test_outline_defaults_follow_environment():
    """生产按网文标准，开发测试自动用小体量，避免本地联调跑上百次模型。"""
    from app.agents.contracts import SkillContext
    from app.agents.skills.outline import OutlineInput, OutlineSkill

    for env, expected_by_length in (
        ("production", {"short": 200, "long": 2000}),
        ("test", {"short": 10, "long": 30}),
    ):
        ctx = SkillContext(settings=Settings(model_stub=True, env=env))
        for length, expected in expected_by_length.items():
            result = OutlineSkill().run(
                OutlineInput(
                    title=f"{env}-{length}默认章数",
                    audience="male",
                    length=length,
                    genre_name="悬疑",
                    mode="hot",
                ),
                ctx,
            )
            assert len(result.chapters) == expected
            assert result.chapters[-1].chapter == expected


def test_outline_defaults_can_override_environment():
    """显式配置优先于环境自动值，方便临时联调。"""
    from app.agents.contracts import SkillContext
    from app.agents.skills.outline import OutlineInput, OutlineSkill

    ctx = SkillContext(
        settings=Settings(
            model_stub=True,
            env="test",
            outline_long_chapters=23,
            outline_short_chapters=7,
            outline_chapter_batch=7,
        )
    )
    for length, expected in (("short", 7), ("long", 23)):
        result = OutlineSkill().run(
            OutlineInput(
                title=f"{length}可配置章数",
                audience="male",
                length=length,
                genre_name="悬疑",
                mode="hot",
            ),
            ctx,
        )
        assert len(result.chapters) == expected


def test_hot_default_length_outputs_full_book(client, headers, app):
    """短篇默认 200 章：全书大纲和全部概括，但正文只有前三章。"""
    _stub(app)
    subscribe(client, headers)
    run_id = _create(client, headers, mode="hot", title="短篇全书").json()["run_id"]
    assert _execute(app, run_id) == "succeeded"

    detail = client.get(f"/v1/agent-runs/{run_id}", headers=headers).json()
    assert len(detail["outline"]["chapters"]) == 200
    assert len(detail["chapter_summaries"]) == 200
    assert len(detail["chapters"]) == 3
    assert detail["summary"]["chapters_count"] == 3
    assert len(detail["volumes"]) == 10
    assert detail["volumes"][-1]["chapter_to"] == 200


def test_reference_outputs_full_outline_with_body(client, headers, app):
    """参考创作：全文大纲 + 全卷章概览 + 黄金三章正文。"""
    _stub(app)
    subscribe(client, headers)
    source_key = _upload(client, headers, _long_source(12))
    response = _create(client, headers, mode="reference", title="参考样书", source_key=source_key)
    assert response.status_code == 201, response.text
    assert _execute(app, response.json()["run_id"]) == "succeeded"

    detail = client.get(f"/v1/agent-runs/{response.json()['run_id']}", headers=headers).json()
    assert len(detail["outline"]["chapters"]) == 12
    assert len(detail["chapter_summaries"]) == 12
    assert len(detail["chapters"]) == 3
    assert detail["summary"]["chapters_count"] == 3
    names = {item["name"] for item in detail["artifacts"]}
    assert "manuscript.md" in names
    assert "chapters.json" in names
    assert "polish_report.json" in names


def test_hot_and_custom_modes_end_to_end(client, headers, app):
    _stub(app)
    subscribe(client, headers)

    hot = _create(
        client,
        headers,
        mode="hot",
        title="热榜样书",
        options={"target_chapters": 12},
    )
    assert hot.status_code == 201, hot.text
    assert _execute(app, hot.json()["run_id"]) == "succeeded"

    detail = client.get(f"/v1/agent-runs/{hot.json()['run_id']}", headers=headers).json()
    assert detail["status"] == "succeeded"
    assert detail["progress"] == 100
    assert detail["summary"]["chapters_count"] == 3
    assert detail["summary"]["preview_chapters_count"] == 0
    assert detail["summary"]["characters_count"] >= 1
    assert detail["summary"]["items_count"] >= 1
    names = {item["name"] for item in detail["artifacts"]}
    assert {
        "outline.md",
        "chapter_summaries.json",
        "characters.json",
        "factions.json",
        "items.json",
        "story_bible.json",
        "hot_research.json",
        "positioning_card.json",
        "settings_pack.json",
        "foreshadow_ledger.json",
        "publish_pack.json",
    } <= names
    assert {"chapters.json", "chapters_full.json", "manuscript.md", "polish_report.json"} <= names
    assert "hot_preview.md" not in names
    assert len(detail["chapter_summaries"]) == 12
    assert len(detail["items"]) == detail["summary"]["items_count"]

    # 热门创作：全书章纲 + 全量章节概括 + 黄金三章正文（已润色）。
    assert len(detail["outline"]["chapters"]) == 12
    assert [item["chapter"] for item in detail["outline"]["chapters"]] == list(range(1, 13))
    assert [item["chapter_no"] for item in detail["chapter_summaries"]] == list(range(1, 13))
    # 卷章概览的规划字段：大纲阶段透传到概括结果，缺失会显示为空白
    for chapter in detail["chapter_summaries"]:
        assert chapter["key_events"] and chapter["key_events"] == chapter["points"]
        assert chapter["arc"]
        assert chapter["pov"] == "第三人称"
        assert chapter["word_target"] > 0
        # 前三章有正文，概括阶段标记为已生成；其余仍待生成
        expected_status = "已生成" if chapter["chapter_no"] <= 3 else "待生成"
        assert chapter["chapter_status"] == expected_status
    assert len(detail["chapters"]) == 3
    assert all(item.get("content") for item in detail["chapters"])
    assert len(detail["volumes"]) == 1
    assert detail["volumes"][0]["chapter_from"] == 1
    assert detail["volumes"][0]["chapter_to"] == 12

    # 六阶段结构化产出抽查
    research_doc = client.get(
        f"/v1/agent-runs/{hot.json()['run_id']}/artifacts/hot_research.json", headers=headers
    ).json()
    assert research_doc["hooks"] and research_doc["highlight_types"]
    assert research_doc["conflict_density"] and research_doc["opening_pace"]
    assert research_doc["anti_cliche"]
    positioning_doc = client.get(
        f"/v1/agent-runs/{hot.json()['run_id']}/artifacts/positioning_card.json", headers=headers
    ).json()
    assert positioning_doc["platform_direction"] and positioning_doc["genre_boundary"]
    assert positioning_doc["emotional_tone"] and positioning_doc["taboos"]
    settings_doc = client.get(
        f"/v1/agent-runs/{hot.json()['run_id']}/artifacts/settings_pack.json", headers=headers
    ).json()
    assert settings_doc["worldview"] and settings_doc["power_system"] and settings_doc["golden_finger"]
    assert settings_doc["characters"] and settings_doc["factions"] and settings_doc["items"]
    assert settings_doc["faction_relations"]
    ledger_doc = client.get(
        f"/v1/agent-runs/{hot.json()['run_id']}/artifacts/foreshadow_ledger.json", headers=headers
    ).json()
    assert ledger_doc["ledger"]
    for row in ledger_doc["ledger"]:
        assert row["planted_chapter"] >= 1 and row["payoff_chapter"] >= row["planted_chapter"]
    publish_doc = client.get(
        f"/v1/agent-runs/{hot.json()['run_id']}/artifacts/publish_pack.json", headers=headers
    ).json()
    assert publish_doc["tags"] and publish_doc["blurb"]
    assert publish_doc["cover_prompt"] and publish_doc["sequel_hint"]
    # 大纲每章带冲突/反转/伏笔/结尾钩子四要素，且爽点分布覆盖全部章
    outline_doc = detail["outline"]
    for chapter in outline_doc["chapters"]:
        assert chapter["conflict"]
        assert chapter["hook"]
    assert {row["chapter"] for row in outline_doc["highlight_distribution"]} == {
        chapter["chapter"] for chapter in outline_doc["chapters"]
    }
    custom = _create(
        client,
        headers,
        mode="custom",
        title="自定义样书",
        brief="都市异能，前三章完成第一次打脸。",
        genre={"id": "dushi", "name": "都市"},
    )
    assert _execute(app, custom.json()["run_id"]) == "succeeded"
    custom_detail = client.get(f"/v1/agent-runs/{custom.json()['run_id']}", headers=headers).json()
    # custom 同样写黄金三章正文，并按大纲目标章数产出全卷全章概括
    custom_total = len(custom_detail["outline"]["chapters"])
    assert len(custom_detail["chapters"]) == 3
    assert custom_detail["summary"]["chapters_count"] == 3
    assert custom_detail["summary"]["word_count"] > 0
    assert len(custom_detail["chapter_summaries"]) == custom_total
    assert custom_detail["volumes"][-1]["chapter_to"] == custom_total
    names = {item["name"] for item in custom_detail["artifacts"]}
    assert {
        "outline.md",
        "chapter_summaries.json",
        "characters.json",
        "factions.json",
        "items.json",
        "story_bible.json",
    } <= names
    assert {"chapters.json", "chapters_full.json", "manuscript.md", "polish_report.json"} <= names


def test_hot_full_outline_volumes_cover_planned_chapters(client, headers, app):
    """热门黄金三章正文，但分卷仍必须覆盖全书章纲，不能按正文章数压成一卷。"""
    _stub(app)
    subscribe(client, headers)
    run_id = _create(
        client,
        headers,
        mode="hot",
        title="全书分卷书",
        options={"target_chapters": 45},
    ).json()["run_id"]
    assert _execute(app, run_id) == "succeeded"

    detail = client.get(f"/v1/agent-runs/{run_id}", headers=headers).json()
    assert len(detail["chapters"]) == 3
    assert len(detail["outline"]["chapters"]) == 45
    assert len(detail["chapter_summaries"]) == 45
    assert len(detail["volumes"]) == 3
    assert detail["volumes"][-1]["chapter_to"] == 45


def test_export_bundle_contains_outline_and_aigc(client, headers, app):
    _stub(app)
    subscribe(client, headers)
    created = _create(client, headers, mode="hot", title="交付包样书")
    run_id = created.json()["run_id"]
    assert _execute(app, run_id) == "succeeded"

    response = client.get(f"/v1/agent-runs/{run_id}/export", headers=headers)
    assert response.status_code == 200, response.text
    assert response.headers["content-type"] == "application/zip"
    assert "attachment" in response.headers["content-disposition"]

    with zipfile.ZipFile(io.BytesIO(response.content)) as bundle:
        names = set(bundle.namelist())
        assert {
            "章纲/章纲.md",
            "设定/角色.json",
            "设定/势力.json",
            "设定/道具功法.json",
            "设定/设定集.json",
            "体检/体检报告.md",
            "AIGC声明.txt",
            "交付说明.md",
            "manifest.json",
        } <= names
        assert any(name.startswith("正文/") for name in names)
        manifest = json.loads(bundle.read("manifest.json"))
        assert manifest["run_id"] == run_id
        assert manifest["aigc"]["enabled"] is True
        assert manifest["title"] == "交付包样书"


def test_export_rejects_missing_run(client, headers, app):
    response = client.get("/v1/agent-runs/not-a-run/export", headers=headers)
    assert response.status_code == 404


def test_reference_mode_e2e_with_sse_and_artifacts(client, headers, app):
    _stub(app)
    subscribe(client, headers)
    source_key = _upload(client, headers)
    created = _create(
        client,
        headers,
        mode="reference",
        title="参考改编样书",
        source_key=source_key,
        genre={"id": "xuanyi", "name": "悬疑"},
    )
    assert created.status_code == 201, created.text
    run_id = created.json()["run_id"]
    assert _execute(app, run_id) == "succeeded"

    detail = client.get(f"/v1/agent-runs/{run_id}", headers=headers).json()
    stages = [item["id"] for item in detail["stages"]]
    assert stages == [
        "positioning",
        "outline_decompose",
        "settings",
        "adaptation",
        "outline",
        "chapter_expand",
        "polish",
        "chapter_summarize",
        "character_graph",
        "continuity_check",
        "consistency_review",
        "compliance_review",
        "review_merge",
        "cover_plan",
        "publish",
    ]
    assert all(item["state"] == "succeeded" for item in detail["stages"])
    names = {item["name"] for item in detail["artifacts"]}
    assert {
        "outline.md",
        "chapter_summaries.json",
        "characters.json",
        "factions.json",
        "items.json",
        "story_bible.json",
        "decomposed.json",
    } <= names
    assert "chapters.json" in names
    assert "manuscript.md" in names
    assert "polish_report.json" in names
    assert detail["summary"]["chapters_count"] == 3
    assert len(detail["chapter_summaries"]) == 3
    assert detail["summary"]["segments_count"] >= 1

    outline_url = client.get(
        f"/v1/agent-runs/{run_id}/artifacts/outline.md", headers=headers
    ).json()
    assert outline_url["url"].startswith("/v1/artifacts/download")

    events_response = client.get(f"/v1/agent-runs/{run_id}/events?since=0", headers=headers)
    assert events_response.status_code == 200
    seqs = []
    stages_in_events = set()
    for line in events_response.text.splitlines():
        if not line.startswith("data: "):
            continue
        payload = json.loads(line[6:])
        if "seq" in payload:
            seqs.append(payload["seq"])
            stages_in_events.add(payload["stage"])
    assert seqs == sorted(seqs)
    assert len(seqs) == len(set(seqs)) >= 2
    assert "outline_decompose" in stages_in_events
    assert "run" in stages_in_events


def _event_messages(client, headers, run_id: str) -> list[dict]:
    response = client.get(f"/v1/agent-runs/{run_id}/events?since=0", headers=headers)
    assert response.status_code == 200
    items = []
    for line in response.text.splitlines():
        if line.startswith("data: "):
            payload = json.loads(line[6:])
            if "seq" in payload:
                items.append(payload)
    return items


def test_segmenter_outline_single_and_sentence_boundaries(app):
    from app.agents.segmenter import plan_segments

    settings = app.state.settings
    outline = "故事主线：少年在雨夜收到密信，卷入十年旧案。" * 100
    plan = plan_segments(settings, outline)
    assert plan.single is True
    assert plan.count == 1
    assert plan.mode == "outline"

    sentence = "雨夜追逐中，主角发现线索与旧案重合。"
    long_line = sentence * 2000
    plan = plan_segments(settings, long_line)
    assert plan.count > 1
    assert plan.mode == "novel"
    assert "".join(segment.text for segment in plan.segments) == long_line
    # 切点落在句末，不切断句子
    assert all(segment.text.endswith("。") for segment in plan.segments)


def test_reference_long_source_all_chapters_and_segment_sse(client, headers, app):
    _stub(app)
    subscribe(client, headers)
    text = _long_source(chapters=12, chars=4500)
    assert len(text) >= 50000
    source_key = _upload(client, headers, text)
    created = _create(client, headers, mode="reference", title="长文参考书", source_key=source_key)
    assert created.status_code == 201, created.text
    run_id = created.json()["run_id"]
    assert _execute(app, run_id) == "succeeded"

    detail = client.get(f"/v1/agent-runs/{run_id}", headers=headers).json()
    assert detail["summary"]["chapters_count"] == 3
    assert len(detail["outline"]["chapters"]) == 12
    assert len(detail["chapter_summaries"]) == 12
    segments = detail["summary"]["segments_count"]
    assert segments >= 2

    decomposed = client.get(
        f"/v1/agent-runs/{run_id}/artifacts/decomposed.json", headers=headers
    ).json()
    assert len(decomposed["chapters"]) == 12
    assert [item["chapter"] for item in decomposed["chapters"]] == list(range(1, 13))
    names = [item["name"] for item in decomposed["characters"]]
    assert len(names) == len(set(names)), "角色跨段应按同名合并"
    assert len(decomposed["segments"]) == segments
    chapter_names = {item["name"] for item in detail["artifacts"]}
    assert "chapters.json" in chapter_names
    assert "polish_report.json" in chapter_names

    prefix = f"{book_slug('长文参考书')}/{run_id}"
    assert len(app.state.storage.list(f"{prefix}/segments")) == segments

    messages = [item["message"] for item in _event_messages(client, headers, run_id)]
    order = []
    for message in messages:
        if "段开始拆解" in message:
            order.append("start")
        elif "段完成：" in message:
            order.append("done")
    assert order == ["start", "done"] * segments


def test_segment_checkpoint_and_single_segment_retry(client, headers, app):
    from app.agents.segmenter import plan_segments
    from app.agents.registry import registry

    _stub(app)
    subscribe(client, headers)
    text = _long_source(chapters=12, chars=4500)
    total = plan_segments(app.state.settings, text).count
    source_key = _upload(client, headers, text)
    created = _create(client, headers, mode="reference", title="段级续跑书", source_key=source_key)
    run_id = created.json()["run_id"]

    failing = _FailSegments({3, 4})
    # outline_decompose 用 auto：普通错误可续跑 → paused；前端「重试」只重跑失败段
    assert _execute(app, run_id, overrides={"outline_decompose": failing}) == "paused"
    detail = client.get(f"/v1/agent-runs/{run_id}", headers=headers).json()
    assert detail["error"]["code"] == "segment_failed"

    with db_session(app) as session:
        rows = session.scalars(
            select(AgentRunStep).where(
                AgentRunStep.run_id == run_id,
                AgentRunStep.node_key.like("outline_decompose:seg:%"),
            )
        ).all()
    done = [row.node_key for row in rows if row.status == "done"]
    failed = [row.node_key for row in rows if row.status == "failed"]
    assert len(done) == 2
    assert len(failed) == 1

    resumed = client.post(
        f"/v1/agent-runs/{run_id}/resume", headers=headers, json={"retry_failed": True}
    )
    assert resumed.status_code == 200, resumed.text
    calls: dict[str, int] = {}
    counter = _Counting(registry.get("outline_decompose"), calls)
    assert _execute(app, run_id, overrides={"outline_decompose": counter}) == "succeeded"
    # 已完成的前两段直接跳过，只重跑失败段及其后续段
    assert calls["outline_decompose"] == total - 2
    final = client.get(f"/v1/agent-runs/{run_id}", headers=headers).json()
    assert final["summary"]["chapters_count"] == 3
    assert len(final["chapter_summaries"]) == 12


def test_review_only_checks_consistency_and_compliance(monkeypatch):
    """体检拆成两节点后，仍只核对设定一致性与敏感/违禁表达，不做签约评估。"""
    from app.agents.contracts import SkillContext
    from app.agents.skills import compliance_review as compliance_module
    from app.agents.skills import consistency_review as consistency_module

    monkeypatch.setattr(compliance_module, "call_json", lambda *args, **kwargs: {})
    monkeypatch.setattr(consistency_module, "call_json", lambda *args, **kwargs: {})

    compliance = ComplianceReviewSkill().run(
        ComplianceInput(
            title="合规校验书",
            genre_name="悬疑",
            chapters=[{"chapter": 1, "summary": "地下赌博和毒品交易被当场揭穿。"}],
            outline=[
                {"chapter": 1, "summary": "主角拒绝参与灰色交易。"},
                {"chapter": 2, "summary": "主角收到新的威胁。"},
            ],
            positioning={"taboos": ["赌博"]},
        ),
        SkillContext(settings=Settings(model_stub=True, env="test")),
    )
    codes = {item.code for item in compliance.risks}
    assert {"forbidden_word", "taboo"} <= codes
    assert not {"thin_chapter", "weak_hook"} & codes
    assert compliance.high_risk is True
    assert all("签约" not in item for item in compliance.compliance_issues)

    consistency = ConsistencyReviewSkill().run(
        ConsistencyInput(
            title="一致性校验书",
            genre_name="悬疑",
            chapters=[{"chapter": 1, "summary": "主角拒绝了灰色交易。"}],
            outline=[
                {"chapter": 1, "summary": "主角拒绝参与灰色交易。"},
                {"chapter": 2, "summary": "主角收到新的威胁。"},
            ],
        ),
        SkillContext(settings=Settings(model_stub=True, env="test")),
    )
    assert consistency.consistency_issues
    assert consistency.issues[0].kind == "coverage"
    assert all("签约" not in item for item in consistency.consistency_issues)


def test_content_review_model_is_admin_configurable(client, app):
    """合规体检纳管在后台模型配置里（step_key=compliance_review）。"""
    from app.models import ModelProviderConfig
    from app.services.model_config import describe_configs, resolve_step_model

    with db_session(app) as session:
        row = next(
            item for item in describe_configs(session, app.state.settings)
            if item["step_key"] == "compliance_review"
        )
        assert row["label"] == "合规体检"
        assert row["recommendation"]["primary"]

        session.add(
            ModelProviderConfig(
                step_key="compliance_review",
                label="合规体检",
                provider="deepseek",
                model="review-specific-model",
                base_url="https://api.deepseek.com",
                api_key="",
                enabled=True,
            )
        )
        session.commit()
        resolved = resolve_step_model(session, "compliance_review", app.state.settings)
    assert resolved.model == "review-specific-model"


def test_hot_never_pauses_on_high_risk(client, headers, app):
    _stub(app)
    subscribe(client, headers)
    created = _create(client, headers, mode="hot", title="自动热榜书")
    run_id = created.json()["run_id"]
    assert _execute(app, run_id, overrides={"compliance_review": _HighRiskReview()}) == "succeeded"

    detail = client.get(f"/v1/agent-runs/{run_id}", headers=headers).json()
    assert detail["status"] == "succeeded"
    assert detail["summary"]["chapters_count"] == 3
    assert detail["summary"]["preview_chapters_count"] == 0
    assert len(detail["chapters"]) == 3
    messages = [item["message"] for item in _event_messages(client, headers, run_id)]
    assert not any("已暂停" in message for message in messages)
    assert any("已记录风险" in message for message in messages)


def test_reference_high_risk_does_not_pause(client, headers, app):
    _stub(app)
    subscribe(client, headers)
    source_key = _upload(client, headers)
    created = _create(client, headers, mode="reference", title="参考高危书", source_key=source_key)
    run_id = created.json()["run_id"]
    assert _execute(app, run_id, overrides={"compliance_review": _HighRiskReview()}) == "succeeded"
    detail = client.get(f"/v1/agent-runs/{run_id}", headers=headers).json()
    assert detail["status"] == "succeeded"
    assert detail["current_stage"] == "publish"
    assert "decomposed.json" in {item["name"] for item in detail["artifacts"]}

    messages = [item["message"] for item in _event_messages(client, headers, run_id)]
    assert any("已记录风险" in message for message in messages)
    assert not any("已暂停" in message for message in messages)


def test_reference_source_too_large_explicit_error(client, headers, app):
    _stub(app)
    subscribe(client, headers)
    old = app.state.settings.agent_max_source_chars
    app.state.settings.agent_max_source_chars = 10000
    try:
        text = _long_source(chapters=4, chars=4000)
        source_key = _upload(client, headers, text)
        created = _create(client, headers, mode="reference", title="超限书", source_key=source_key)
        run_id = created.json()["run_id"]
        assert _execute(app, run_id) == "failed"
        detail = client.get(f"/v1/agent-runs/{run_id}", headers=headers).json()
        assert detail["error"]["code"] == "source_too_large"
        assert detail["summary"]["chapters_count"] == 0
        assert "decomposed.json" not in {item["name"] for item in detail["artifacts"]}
    finally:
        app.state.settings.agent_max_source_chars = old


def test_cancel_queued_releases_quota(client, headers, app):
    _stub(app)
    subscribe(client, headers)
    created = _create(client, headers, mode="hot", title="取消书")
    run_id = created.json()["run_id"]

    response = client.post(f"/v1/agent-runs/{run_id}/cancel", headers=headers)
    assert response.status_code == 200
    assert response.json()["status"] == "canceled"
    assert response.json()["changed"] is True

    again = client.post(f"/v1/agent-runs/{run_id}/cancel", headers=headers)
    assert again.json()["changed"] is False

    summary = client.get("/v1/entitlements", headers=headers).json()
    books = next(m for m in summary["metrics"] if m["metric"] == "books_month")
    assert books["reserved"] == 0


def test_resume_invalid_state_after_high_risk_success(client, headers, app):
    _stub(app)
    subscribe(client, headers)
    created = _create(client, headers, mode="custom", title="高危书")
    run_id = created.json()["run_id"]

    invalid = client.post(
        f"/v1/agent-runs/{run_id}/resume", headers=headers, json={"approval": True}
    )
    assert invalid.status_code == 409
    assert invalid.json()["error"]["code"] == "invalid_state"

    assert _execute(app, run_id, overrides={"compliance_review": _HighRiskReview()}) == "succeeded"
    detail = client.get(f"/v1/agent-runs/{run_id}", headers=headers).json()
    assert detail["status"] == "succeeded"
    assert detail["current_stage"] == "publish"
    assert "chapter_summaries.json" in {item["name"] for item in detail["artifacts"]}
    assert "chapters.json" in {item["name"] for item in detail["artifacts"]}
    assert "polish_report.json" in {item["name"] for item in detail["artifacts"]}

    again = client.post(
        f"/v1/agent-runs/{run_id}/resume", headers=headers, json={"approval": True}
    )
    assert again.status_code == 409
    assert again.json()["error"]["code"] == "invalid_state"


def test_checkpoint_resume_continues_from_next_node(client, headers, app):
    _stub(app)
    subscribe(client, headers)
    created = _create(client, headers, mode="hot", title="断点书")
    run_id = created.json()["run_id"]

    calls: dict[str, int] = {}
    from app.agents.registry import registry

    overrides = {
        name: _Counting(registry.get(name), calls)
        for name in (
            "genre_research",
            "outline",
            "chapter_summarize",
            "consistency_review",
            "compliance_review",
            "review_merge",
        )
    }
    assert _execute(app, run_id, overrides=overrides, max_steps=2) == "queued"
    steps = client.get(f"/v1/agent-runs/{run_id}", headers=headers).json()["stages"]
    assert [s["state"] for s in steps[:2]] == ["succeeded", "succeeded"]
    # 热门流程（2026-11-18）：校准→定位卡→设定→大纲→正文→润色→概括→抽取→核查→
    # 一致性+合规→合并→封面→发布，共 14 个节点
    assert len(steps) == 14
    assert all(s["state"] == "pending" for s in steps[2:])
    assert calls["genre_research"] == 1
    assert "outline" not in calls

    before = dict(calls)
    assert _execute(app, run_id, overrides=overrides) == "succeeded"
    assert calls["genre_research"] == before["genre_research"] == 1
    assert calls["outline"] == 1
    assert calls["chapter_summarize"] == 1
    assert calls["consistency_review"] == 1
    assert calls["compliance_review"] == 1
    assert calls["review_merge"] == 1


def test_node_retry_and_failed_single_node_rerun(client, headers, app):
    _stub(app)
    subscribe(client, headers)

    flaky = _create(client, headers, mode="hot", title="抖动书")
    run_id = flaky.json()["run_id"]
    skill = _FlakyOutline()
    assert _execute(app, run_id, overrides={"outline": skill}) == "succeeded"
    assert skill.calls == 2
    steps = client.get(f"/v1/agent-runs/{run_id}", headers=headers).json()["stages"]
    assert all(item["state"] == "succeeded" for item in steps)

    failing = _create(client, headers, mode="hot", title="失败书")
    failed_id = failing.json()["run_id"]
    # outline 节点 retry_policy=soft：长耗时节点失败不直接判死，转 paused 供用户续跑
    assert _execute(app, failed_id, overrides={"outline": _AlwaysFailOutline()}) == "paused"
    detail = client.get(f"/v1/agent-runs/{failed_id}", headers=headers).json()
    assert detail["status"] == "paused"
    assert detail["error"]["code"] == "stage_failed"
    states = {item["id"]: item["state"] for item in detail["stages"]}
    assert states["genre_research"] == "succeeded"
    assert states["outline"] == "failed"

    resumed = client.post(
        f"/v1/agent-runs/{failed_id}/resume", headers=headers, json={"retry_failed": True}
    )
    assert resumed.status_code == 200, resumed.text
    assert resumed.json()["status"] == "queued"
    # 只重跑失败节点，已完成节点复用 checkpoint
    assert _execute(app, failed_id) == "succeeded"
    final = client.get(f"/v1/agent-runs/{failed_id}", headers=headers).json()
    assert final["status"] == "succeeded"
    assert final["error"] is None
    calls = {item["id"]: item["state"] for item in final["stages"]}
    assert all(state == "succeeded" for state in calls.values())


def test_update_run_info_overrides_and_keeps_artifacts(client, headers, app):
    _stub(app)
    subscribe(client, headers)
    created = _create(client, headers, title="旧书名")
    run_id = created.json()["run_id"]

    active = client.patch(f"/v1/agent-runs/{run_id}", headers=headers, json={"title": "运行中改名"})
    assert active.status_code == 409

    assert _execute(app, run_id) == "succeeded"
    updated = client.patch(
        f"/v1/agent-runs/{run_id}",
        headers=headers,
        json={
            "title": "新书名",
            "author": "测试作者",
            "status_label": "已签约",
            "audience": "female",
            "length": "long",
            "genre": {"id": "dushi", "name": "都市异能"},
            "logline": "新的梗概",
            "synopsis": "新的简介",
            "themes": ["成长", "复仇"],
            "person": "第三人称",
            "style": "短句推进",
            "world": "近未来都市",
            "conflict": "主角与组织对抗",
            "mainline": "追查真相",
            "selling_points": ["强反转", "快节奏"],
            "core_hook": "开局收到自己的死亡通知",
            "tone": "热血",
            "target_platform": ["番茄", "起点"],
            "target_reader_age": "18-24",
            "update_frequency": "日更",
            "serialization_pace": "快节奏",
            "content_rating": "全年龄",
            "beats": ["开场危机", "第一次反转"],
            "ending_type": "HE 圆满",
        },
    )
    assert updated.status_code == 200, updated.text
    body = updated.json()
    assert body["title"] == "新书名"
    assert body["status_label"] == "已签约"
    assert body["audience"] == "female"
    assert body["length"] == "long"
    assert body["genre"] == {"id": "dushi", "name": "都市异能"}
    assert body["outline"]["author"] == "测试作者"
    assert body["outline"]["synopsis"] == "新的简介"
    assert body["outline"]["themes"] == ["成长", "复仇"]
    assert body["summary"]["logline"] == "新的梗概"
    assert body["outline"]["tone"] == "热血"
    assert body["outline"]["target_platform"] == ["番茄", "起点"]
    assert body["outline"]["target_reader_age"] == "18-24"
    assert body["outline"]["update_frequency"] == "日更"
    assert body["outline"]["serialization_pace"] == "快节奏"
    assert body["outline"]["content_rating"] == "全年龄"
    assert body["outline"]["beats"] == ["开场危机", "第一次反转"]
    assert body["outline"]["ending_type"] == "HE 圆满"
    # 重复字段只保留一个：题材取 run.genre，书名/状态/简介/篇幅/频道不再从大纲重复返回
    for key in (
        "genre_tone",
        "genre",
        "book_title",
        "status",
        "book_summary",
        "length_class",
        "audience",
        "target_reader_gender",
        "n_chapters",
        "theme",
    ):
        assert key not in body["outline"]
        assert key not in (body.get("story_bible") or {})

    detail = client.get(f"/v1/agent-runs/{run_id}", headers=headers).json()
    assert detail["title"] == "新书名"
    assert detail["status_label"] == "已签约"
    # 改名后产物仍从旧书名目录读取
    artifact = client.get(f"/v1/agent-runs/{run_id}/artifacts/outline.md", headers=headers)
    assert artifact.status_code == 200

    required = client.patch(f"/v1/agent-runs/{run_id}", headers=headers, json={"title": "  "})
    assert required.status_code == 422


def test_custom_target_chapters_option(client, headers, app):
    _stub(app)
    subscribe(client, headers)
    created = client.post(
        "/v1/agent-runs",
        headers={**headers, "Idempotency-Key": f"target-{uuid.uuid4()}"},
        json={
            "mode": "custom",
            "title": "目标章数样书",
            "audience": "male",
            "length": "long",
            "genre": {"id": "xuanyi", "name": "悬疑"},
            "options": {"target_chapters": 5},
        },
    )
    assert created.status_code == 201, created.text
    run_id = created.json()["run_id"]
    assert _execute(app, run_id) == "succeeded"
    detail = client.get(f"/v1/agent-runs/{run_id}", headers=headers).json()
    assert len(detail["chapters"]) == 3
    assert len(detail["outline"]["chapters"]) == 5
    assert len(detail["chapter_summaries"]) == 5
    assert detail["volumes"][-1]["chapter_to"] == 5
    assert detail["options"]["target_chapters"] == 5
    assert detail["summary"]["chapters_count"] == 3


def test_options_validation_rejects_invalid_chapters(client, headers):
    response = client.post(
        "/v1/agent-runs",
        headers={**headers, "Idempotency-Key": f"bad-option-{uuid.uuid4()}"},
        json={
            "mode": "custom",
            "title": "非法选项",
            "audience": "male",
            "length": "long",
            "genre": {"id": "xuanyi", "name": "悬疑"},
            "options": {"target_chapters": 0},
        },
    )
    assert response.status_code == 422


def test_body_window_options_are_persisted(client, headers):
    """云端分段调度：起始章与窗口章数必须被 schema 接受并原样落到 run.meta.options。"""
    subscribe(client, headers)
    created = _create(
        client,
        headers,
        length="long",
        options={"body_start": 4, "body_chapters": 2},
    )
    assert created.status_code == 201, created.text
    run_id = created.json()["run_id"]
    detail = client.get(f"/v1/agent-runs/{run_id}", headers=headers).json()
    assert detail["options"]["body_start"] == 4
    assert detail["options"]["body_chapters"] == 2


def test_body_window_options_reject_conflicting_and_invalid(client, headers):
    subscribe(client, headers)
    conflicting = _create(
        client,
        headers,
        length="long",
        options={"body_start": 2, "body_segment": 1},
    )
    assert conflicting.status_code == 422

    invalid_size = _create(
        client,
        headers,
        length="long",
        options={"body_chapters": 0},
    )
    assert invalid_size.status_code == 422


def test_adaptation_options_reach_skill_payload():
    from types import SimpleNamespace

    from app.agents.graph import _adaptation

    payload = _adaptation(
        SimpleNamespace(title="选项样书"),
        {"outline_decompose": {}},
        {"options": {"adaptation_style": "冷峻短句", "adaptation_extra": "主角改为女性"}},
    )
    assert payload["style"] == "冷峻短句"
    assert payload["requirements"] == "主角改为女性"


def test_positioning_payload_derives_from_research():
    """阶段2 定位卡：入参只带榜单校准结论，不做任何用户确认项透传。"""
    from types import SimpleNamespace

    from app.agents.graph import _hot_positioning

    payload = _hot_positioning(
        SimpleNamespace(title="定位书", genre_name="玄幻", audience="male", length="long"),
        {"genre_research": {"hooks": ["第一章抛危机"], "highlight_types": ["打脸反转"]}},
        {"options": {"platform": "起点"}},  # 选项应被忽略，定位卡不再消费用户输入
    )
    assert payload["research"]["hooks"] == ["第一章抛危机"]
    assert payload["research"]["highlight_types"] == ["打脸反转"]
    assert "platform" not in payload
    assert "highlight_preferences" not in payload
    assert "taboos" not in payload


def test_hot_positioning_derived_from_research_flows_to_publish(client, headers, app):
    """热门六阶段：定位卡由榜单分析自动推导，发布包随交付稿导出。"""
    _stub(app)
    subscribe(client, headers)
    created = _create(client, headers, mode="hot", title="定位样书")
    assert created.status_code == 201, created.text
    run_id = created.json()["run_id"]
    assert _execute(app, run_id) == "succeeded"

    detail = client.get(f"/v1/agent-runs/{run_id}", headers=headers).json()
    assert not detail.get("options")
    card = client.get(
        f"/v1/agent-runs/{run_id}/artifacts/positioning_card.json", headers=headers
    ).json()
    # 平台/方向/边界/基调均由校准结论推导，字段必须非空
    assert card["platform"]
    assert card["platform_direction"] and card["genre_boundary"]
    assert card["emotional_tone"] and card["summary"]
    assert card["highlight_preferences"], card
    assert card["taboos"], card

    bundle_resp = client.get(f"/v1/agent-runs/{run_id}/export", headers=headers)
    assert bundle_resp.status_code == 200, bundle_resp.text
    with zipfile.ZipFile(io.BytesIO(bundle_resp.content)) as bundle:
        names = set(bundle.namelist())
        assert "发布包/发布包.md" in names
        publish_md = bundle.read("发布包/发布包.md").decode("utf-8")
        assert "封面提示词" in publish_md
        assert "续写入口" in publish_md


def test_outline_includes_work_info_fields(client, headers, app):
    """真实模型产出的信息页字段要进入 outline，避免工作台大片空白。"""
    _stub(app)
    subscribe(client, headers)
    created = _create(client, headers, title="信息字段样书")
    run_id = created.json()["run_id"]
    assert _execute(app, run_id) == "succeeded"

    outline = client.get(f"/v1/agent-runs/{run_id}", headers=headers).json()["outline"]
    for key in (
        "type_primary",
        "core_hook",
        "selling_points",
        "target_platform",
        "target_reader_age",
        "total_chapters_planned",
        "chapter_words_target",
        "estimated_words",
        "tone",
        "person",
        "style",
        "conflict",
        "suspense",
        "subplots",
        "supporting",
        "antagonist",
        "foreshadow_text",
        "places",
        "items_text",
        "terms",
        "timeline",
        "map_text",
        "theme_core",
        "theme_statement",
        "ending_type",
        "ending_state",
        "protagonist_final_fate",
        "taboos",
        "update_frequency",
        "serialization_pace",
        "content_rating",
        "series_plan",
        "keywords",
        "beats",
    ):
        assert outline.get(key), f"outline.{key} 为空"


def test_update_run_allows_empty_author(client, headers, app):
    """AI 生成的作品可能没有作者署名，编辑信息时不能因此被 422 拦住。"""
    _stub(app)
    subscribe(client, headers)
    created = _create(client, headers, title="未署名作品")
    run_id = created.json()["run_id"]
    assert _execute(app, run_id) == "succeeded"

    updated = client.patch(
        f"/v1/agent-runs/{run_id}",
        headers=headers,
        json={"author": "", "tone": "冷峻"},
    )
    assert updated.status_code == 200, updated.text
    body = updated.json()
    assert body["outline"].get("author", "") == ""
    assert body["outline"]["tone"] == "冷峻"


def test_update_run_collections_crud(client, headers, app):
    _stub(app)
    subscribe(client, headers)
    created = _create(client, headers, title="集合编辑")
    run_id = created.json()["run_id"]
    assert _execute(app, run_id) == "succeeded"

    characters = [
        {"name": "新角色", "gender": "女", "identity": "测试身份", "tags": ["测试"]}
    ]
    factions = [{"name": "新势力", "stance": "中立", "members": []}]
    items = [{"name": "新道具", "category": "法宝", "effect": "测试效果"}]
    volumes = [
        {
            "no": 1,
            "title": "第一卷 测试",
            "chapter_from": 1,
            "chapter_to": 2,
            "summary": "测试卷概括",
        }
    ]
    chapter_summaries = [
        {
            "no": 1,
            "title": "测试第一章",
            "summary": "测试章节概括",
            "words": 1800,
            "key_events": ["事件一", "事件二"],
            "scene": "码头",
            "hook_type": "反转",
            "emotion": "紧张",
            "tension": 7,
            "arc": "开局",
            "chapter_function": "冲突升级",
            "chapter_goal": "逼主角做出第一次选择",
            "beat_type": "激励事件",
            "pov": "主角",
            "time_span": "当日",
            "word_target": 2500,
            "word_actual": 1800,
            "payoff_type": "打脸",
            "payoff_owner": "主角",
            "payoff_intensity": 8,
            "twist": "对手其实是旧识",
            "new_characters": ["新角色"],
            "new_items": ["新道具"],
            "new_settings": ["新规则"],
            "foreshadow_ids": ["钥匙的来历", "老管家的身份"],
            "continuity_check": "通过",
            "chapter_status": "待修订",
            "revision_note": "补写环境描写",
        },
        {"no": 99, "title": "新增章节", "summary": "新增章节概括"},
    ]

    updated = client.patch(
        f"/v1/agent-runs/{run_id}/collections",
        headers=headers,
        json={
            "characters": characters,
            "factions": factions,
            "items": items,
            "volumes": volumes,
            "chapter_summaries": chapter_summaries,
            "chapter_hidden": [1],
        },
    )
    assert updated.status_code == 200, updated.text
    body = updated.json()
    assert [item["name"] for item in body["characters"]] == ["新角色"]
    assert [item["name"] for item in body["factions"]] == ["新势力"]
    assert [item["name"] for item in body["items"]] == ["新道具"]
    assert [volume["title"] for volume in body["volumes"]] == ["第一卷 测试"]
    assert [chapter["title"] for chapter in body["chapter_summaries"]] == [
        "测试第一章",
        "新增章节",
    ]
    assert body["chapter_hidden"] == [1]
    # 章节集合的新增规划字段：读回时字段齐全，字数与关键事件双向同步
    first = body["chapter_summaries"][0]
    assert first["words"] == first["word_count"] == 1800
    assert first["key_events"] == first["points"] == ["事件一", "事件二"]
    assert first["scene"] == "码头" and first["hook_type"] == "反转"
    assert first["emotion"] == "紧张" and first["tension"] == 7
    assert first["chapter_function"] == "冲突升级" and first["beat_type"] == "激励事件"
    assert first["chapter_goal"] == "逼主角做出第一次选择" and first["arc"] == "开局"
    assert first["pov"] == "主角" and first["time_span"] == "当日"
    assert first["word_target"] == 2500 and first["word_actual"] == 1800
    assert first["payoff_type"] == "打脸" and first["payoff_intensity"] == 8
    assert first["foreshadow_ids"] == ["钥匙的来历", "老管家的身份"]
    assert first["continuity_check"] == "通过" and first["chapter_status"] == "待修订"

    detail = client.get(f"/v1/agent-runs/{run_id}", headers=headers).json()
    assert [item["name"] for item in detail["characters"]] == ["新角色"]
    assert detail["summary"]["characters_count"] == 1
    assert detail["summary"]["items_count"] == 1

    empty = client.patch(
        f"/v1/agent-runs/{run_id}/collections",
        headers=headers,
        json={"items": []},
    )
    assert empty.status_code == 200, empty.text
    assert empty.json()["items"] == []
    assert empty.json()["summary"]["items_count"] == 0


def test_update_run_collections_rejects_active_and_blank_name(client, headers, app):
    _stub(app)
    subscribe(client, headers)
    created = _create(client, headers, title="集合校验")
    run_id = created.json()["run_id"]

    active = client.patch(
        f"/v1/agent-runs/{run_id}/collections",
        headers=headers,
        json={"characters": [{"name": "运行中"}]},
    )
    assert active.status_code == 409

    assert _execute(app, run_id) == "succeeded"
    blank = client.patch(
        f"/v1/agent-runs/{run_id}/collections",
        headers=headers,
        json={"characters": [{"name": "  "}]},
    )
    assert blank.status_code == 422
    bad_volume = client.patch(
        f"/v1/agent-runs/{run_id}/collections",
        headers=headers,
        json={"volumes": [{"no": 0}]},
    )
    assert bad_volume.status_code == 422
    noop = client.patch(f"/v1/agent-runs/{run_id}/collections", headers=headers, json={})
    assert noop.status_code == 422


def test_other_account_gets_404(client, headers, app):
    _stub(app)
    subscribe(client, headers)
    created = _create(client, headers, mode="hot", title="越权书")
    run_id = created.json()["run_id"]

    other = client.post(
        "/v1/auth/register",
        json={"email": "other@example.com", "password": "password123"},
    )
    assert other.status_code == 201
    other_headers = {"Authorization": f"Bearer {other.json()['access_token']}"}

    assert client.get(f"/v1/agent-runs/{run_id}", headers=other_headers).status_code == 404
    assert (
        client.post(f"/v1/agent-runs/{run_id}/cancel", headers=other_headers).status_code == 404
    )
    assert (
        client.post(
            f"/v1/agent-runs/{run_id}/resume", headers=other_headers, json={"approval": True}
        ).status_code
        == 404
    )
    assert (
        client.get(
            f"/v1/agent-runs/{run_id}/artifacts/outline.md", headers=other_headers
        ).status_code
        == 404
    )


def test_list_pagination(client, headers, app):
    _stub(app)
    subscribe(client, headers)
    for index in range(2):
        assert _create(client, headers, title=f"列表书{index}").status_code == 201
    page = client.get("/v1/agent-runs?limit=1&offset=0", headers=headers).json()
    assert page["total"] == 2
    assert len(page["items"]) == 1
    assert page["next_offset"] == 1


def test_list_filters_single_combined_and_total(client, headers, app):
    _stub(app)
    subscribe(client, headers)
    hot = _create(client, headers, title="热榜悬疑")
    source_key = _upload(client, headers)
    reference = _create(
        client,
        headers,
        mode="reference",
        audience="female",
        length="long",
        genre={"id": "yanqing", "name": "言情"},
        source_key=source_key,
        title="参考言情",
    )
    custom_a = _create(
        client,
        headers,
        mode="custom",
        audience="male",
        length="long",
        genre={"id": "kehuan", "name": "科幻"},
        title="自定义科幻A",
    )
    custom_b = _create(
        client,
        headers,
        mode="custom",
        audience="male",
        length="long",
        genre={"id": "kehuan", "name": "科幻"},
        title="自定义科幻B",
    )
    for response in (hot, reference, custom_a, custom_b):
        assert response.status_code == 201, response.text

    def _ids(query: str) -> list[str]:
        body = client.get(f"/v1/agent-runs?{query}", headers=headers).json()
        return [item["run_id"] for item in body["items"]]

    # 单一过滤：mode / audience / length
    assert _ids("mode=hot") == [hot.json()["run_id"]]
    assert _ids("audience=female") == [reference.json()["run_id"]]
    assert len(_ids("length=long")) == 3

    # genre 支持中文名与 id，且两种写法等价
    by_name = client.get("/v1/agent-runs?genre=悬疑", headers=headers).json()
    by_id = client.get("/v1/agent-runs?genre=xuanyi", headers=headers).json()
    assert by_name["total"] == by_id["total"] == 1
    assert [item["run_id"] for item in by_name["items"]] == [hot.json()["run_id"]]
    assert [item["run_id"] for item in by_id["items"]] == [hot.json()["run_id"]]

    # 组合过滤为 AND
    combined = client.get(
        "/v1/agent-runs?mode=custom&audience=male&length=long&genre=科幻", headers=headers
    ).json()
    assert combined["total"] == 2
    assert [item["title"] for item in combined["items"]] == ["自定义科幻B", "自定义科幻A"]

    # 空结果不报错
    empty = client.get("/v1/agent-runs?genre=不存在题材", headers=headers).json()
    assert empty["total"] == 0 and empty["items"] == []
    empty_combo = client.get(
        "/v1/agent-runs?mode=reference&audience=male", headers=headers
    ).json()
    assert empty_combo["total"] == 0 and empty_combo["items"] == []

    # 分页与过滤并用，total 反映过滤后的总数
    page = client.get(
        "/v1/agent-runs?mode=custom&length=long&limit=1&offset=0", headers=headers
    ).json()
    assert page["total"] == 2 and len(page["items"]) == 1
    assert page["next_offset"] == 1
    assert page["items"][0]["title"] == "自定义科幻B"
    second = client.get(
        "/v1/agent-runs?mode=custom&length=long&limit=1&offset=1", headers=headers
    ).json()
    assert [item["title"] for item in second["items"]] == ["自定义科幻A"]
    assert second["next_offset"] is None

    # 非法枚举 422
    assert client.get("/v1/agent-runs?mode=all", headers=headers).status_code == 422
    assert client.get("/v1/agent-runs?audience=all", headers=headers).status_code == 422
    assert client.get("/v1/agent-runs?length=medium", headers=headers).status_code == 422


def test_optional_workbench_fields_and_volume_consistency(client, headers, app):
    _stub(app)
    subscribe(client, headers)
    created = _create(
        client, headers, mode="hot", title="可选字段样书", options={"target_chapters": 3}
    )
    run_id = created.json()["run_id"]
    assert _execute(app, run_id) == "succeeded"
    detail = client.get(f"/v1/agent-runs/{run_id}", headers=headers).json()

    assert len(detail["chapters"]) == 3
    total = len(detail["chapter_summaries"])
    assert total == 3
    for summary in detail["chapter_summaries"]:
        for key in (
            "chapter_id",
            "scene",
            "hook_type",
            "emotion",
            "tension",
            "payoff",
            "setup",
            "points",
            "roles",
            "factions",
            "items",
        ):
            assert key in summary
        assert summary["chapter_id"].startswith("ch-")
        assert 0 <= summary["tension"] <= 10
        assert summary["points"]

    volumes = detail["volumes"]
    assert volumes
    assert volumes[0]["chapter_from"] == 1
    assert volumes[-1]["chapter_to"] == total
    for left, right in zip(volumes, volumes[1:]):
        assert left["chapter_to"] + 1 == right["chapter_from"]
    for volume in volumes:
        for key in (
            "no",
            "title",
            "summary",
            "conflict",
            "chapter_from",
            "chapter_to",
            "theme",
            "core_event",
            "conflict_axis",
            "end_hook",
            "arc",
            "tension_profile",
        ):
            assert key in volume
        assert volume["title"] and volume["theme"] and volume["end_hook"]
        assert volume["tension_profile"]
    assert len(volumes) == (total + 19) // 20

    for row in detail["characters"]:
        assert row["gender"]
        assert isinstance(row["age"], int) and row["age"] > 0
        detail_arc = row["arc_detail"]
        assert detail_arc["type"] and detail_arc["start_state"]
        assert detail_arc["turning_points"] and detail_arc["end_state"]
        assert detail_arc["final_fate"]
        assert row["pov_chapters"]
    for row in detail["factions"]:
        assert row["category"] and row["goal"]
        assert row["relations"]
        assert {"target", "type", "strength", "public"} <= set(row["relations"][0])
    for row in detail["items"]:
        assert row["payoff"] and row["origin"]
        assert row["holder"] and row["faction"]
        assert row["chapters"]

    outline = detail["outline"]
    opening = outline["opening"]
    assert opening["strategy"] and opening["first_image"]
    assert isinstance(opening["golden_finger_demo"], int)
    assert outline["worldview"] and outline["worldview"][0]["points"]
    assert outline["map_levels"] == ["世界层", "区域层", "场景层"]
    assert outline["map_regions"] and outline["map_scenes"]
    assert set(outline["signing_check"]) >= {"score", "risk", "suggestions", "issues"}
    assert isinstance(outline["signing_check"]["score"], int)
    assert set(outline["completeness_check"]) >= {
        "missing_fields",
        "unfilled_payoff",
        "unrecovered",
        "arc_missing",
        "no_hook",
    }

    names = {item["name"] for item in detail["artifacts"]}
    assert "volumes.json" in names
    volumes_file = client.get(
        f"/v1/agent-runs/{run_id}/artifacts/volumes.json", headers=headers
    ).json()
    assert len(volumes_file["volumes"]) == len(volumes)

    # 单卷退化：显式指定 3 章时，仍输出合法分卷结构
    hot = _create(
        client,
        headers,
        mode="hot",
        title="单卷校验书",
        options={"target_chapters": 3},
    )
    hot_id = hot.json()["run_id"]
    assert _execute(app, hot_id) == "succeeded"
    hot_detail = client.get(f"/v1/agent-runs/{hot_id}", headers=headers).json()
    hot_volumes = hot_detail["volumes"]
    assert len(hot_volumes) == 1
    assert hot_volumes[0]["chapter_from"] == 1
    assert hot_volumes[0]["chapter_to"] == len(hot_detail["chapter_summaries"]) == 3
    assert hot_volumes[0]["title"] and hot_volumes[0]["arc"]


class _MinimalOutline(OutlineSkill):
    """只返回最小合法大纲，模拟模型未给出任何可选字段。"""

    def run(self, payload, ctx):
        return OutlineOutput(
            logline="最小大纲",
            chapters=[
                OutlineChapter(
                    chapter=1,
                    title="第一章 起点",
                    summary="主角被卷入核心冲突。",
                    key_events=["主角发现异常"],
                    hook="新的问题被抛出。",
                    arc="开局",
                )
            ],
        )


def test_missing_optional_fields_do_not_break_run(client, headers, app):
    _stub(app)
    subscribe(client, headers)
    created = _create(client, headers, mode="custom", title="缺失字段样书")
    run_id = created.json()["run_id"]
    assert _execute(app, run_id, overrides={"outline": _MinimalOutline()}) == "succeeded"
    detail = client.get(f"/v1/agent-runs/{run_id}", headers=headers).json()
    assert len(detail["chapters"]) == 1
    # 大纲未给分卷时，服务端按章节概括补出合法结构，避免客户端空白
    assert len(detail["volumes"]) == 1
    assert detail["volumes"][0]["chapter_from"] == 1
    assert detail["volumes"][0]["chapter_to"] == 1
    assert detail["outline"]["signing_check"] == {}
    assert detail["outline"]["completeness_check"] == {}
    # 概括的可选字段仍按确定性值兜底，与章纲不断链
    assert len(detail["chapter_summaries"]) == 1
    assert detail["chapter_summaries"][0]["chapter_id"] == "ch-001"


def test_run_events_include_skill_execution_logs(client, headers, app):
    """执行过程要能看到技能内部日志（模型、分批进度、兜底），而不是只有阶段开始/结束。"""
    _stub(app)
    subscribe(client, headers)
    created = _create(
        client,
        headers,
        mode="hot",
        title="任务日志书",
        options={"target_chapters": 6},
    )
    run_id = created.json()["run_id"]
    assert _execute(app, run_id) == "succeeded"

    events = _event_messages(client, headers, run_id)
    messages = [item["message"] for item in events]
    assert any("调用模型" in message for message in messages)
    assert any("章节概括完成" in message for message in messages)
    assert any("发布包完成" in message for message in messages)
    assert [item["seq"] for item in events] == sorted(item["seq"] for item in events)


def test_skill_logs_are_visible_while_node_still_running(client, headers, app):
    """实时刷新前提：串行节点执行中日志已提交，另一个数据库会话能立刻读到。"""
    _stub(app)
    subscribe(client, headers)
    created = _create(
        client,
        headers,
        mode="hot",
        title="实时日志书",
        options={"target_chapters": 4},
    )
    run_id = created.json()["run_id"]
    seen: dict[str, int] = {}

    class _LiveLogOutline(OutlineSkill):
        def run(self, payload, ctx):  # noqa: ANN001
            ctx.log("第一批章纲开始生成")
            # 引擎给串行节点注入了 on_log 钩子，日志应已即时 commit；
            # 这里另开一个会话读取，模拟后台任务详情在任务未结束时轮询。
            with app.state.db.session() as session:
                seen["live"] = int(
                    session.scalar(
                        select(func.count())
                        .select_from(AgentRunEvent)
                        .where(
                            AgentRunEvent.run_id == run_id,
                            AgentRunEvent.message == "第一批章纲开始生成",
                        )
                    )
                    or 0
                )
            return super().run(payload, ctx)

    assert _execute(app, run_id, overrides={"outline": _LiveLogOutline()}) == "succeeded"
    assert seen["live"] == 1


def test_three_modes_auto_generate_cover_after_flow(client, headers, app, monkeypatch):
    """热门/参考/自定义三种流程都基于 cover_plan 自动出图，前端无需再手动点生成。"""
    import app.agents.engine as engine

    _stub(app)
    subscribe(client, headers)
    monkeypatch.setattr(app.state.settings, "agent_cover_auto_generate", True, raising=False)

    calls: list[dict] = []

    def fake_generate_cover(**kwargs):
        run = kwargs["run"]
        calls.append(
            {
                "mode": run.mode,
                "prompt": kwargs.get("prompt", ""),
                "style": kwargs.get("style", ""),
                "layout": kwargs.get("layout", ""),
            }
        )
        key = f"covers/{run.account_id}/{run.id}.jpg"
        run.meta = {
            **(run.meta or {}),
            "cover": {
                "key": key,
                "fmt": "jpg",
                "source": "ai",
                "model": "stub-image",
                "width": kwargs.get("width") or 600,
                "height": kwargs.get("height") or 800,
                "updated_at": "2026-11-19T00:00:00+00:00",
            },
        }
        return {"url": f"/agent-runs/{run.id}/cover?v=stub", "source": "ai"}

    monkeypatch.setattr(engine, "generate_run_cover", fake_generate_cover)

    source_key = _upload(client, headers, SOURCE_TEXT)
    cases = [
        ("hot", {}),
        ("reference", {"source_key": source_key}),
        ("custom", {}),
    ]
    for mode, extra in cases:
        created = _create(
            client,
            headers,
            mode=mode,
            title=f"自动封面-{mode}",
            options={"target_chapters": 3},
            **extra,
        )
        assert created.status_code == 201, created.text
        run_id = created.json()["run_id"]
        assert _execute(app, run_id) == "succeeded"
        detail = client.get(f"/v1/agent-runs/{run_id}", headers=headers).json()
        assert detail["cover_url"], f"{mode} 模式未返回封面"
        assert detail["cover"]["source"] == "ai"
        messages = [item["message"] for item in _event_messages(client, headers, run_id)]
        assert any("封面已自动生成" in message for message in messages)

    assert [item["mode"] for item in calls] == ["hot", "reference", "custom"]
    assert all(item["prompt"] for item in calls)
    assert all(item["style"] and item["layout"] for item in calls)
