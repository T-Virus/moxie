# -*- coding: utf-8 -*-
"""同题材热门作品调研 + 前三章概括。

没有可靠检索源时只用模型知识，并在 sources 中明确标注「模型推断」，
绝不伪造榜单/链接。后续接入搜索适配器时只需填充 items 与 sources。
"""

from __future__ import annotations

from pydantic import Field

from ...services.rankings import SOURCE_LABELS, fetch_rankings_sync
from ..contracts import SkillContext, StrictModel, call_json, list_of_dicts, text_of
from .base import BaseSkill


class GenreResearchInput(StrictModel):
    title: str = Field(min_length=1, max_length=120)
    genre_id: str | None = None
    genre_name: str = Field(min_length=1, max_length=60)
    audience: str = Field(pattern="^(male|female)$")
    length: str = Field(pattern="^(long|short)$")


class ResearchWork(StrictModel):
    title: str
    hook: str
    three_chapter_summary: str
    tags: list[str] = Field(default_factory=list)


class ResearchSource(StrictModel):
    type: str
    note: str


class GenreResearchOutput(StrictModel):
    genre: str
    works: list[ResearchWork] = Field(default_factory=list)
    takeaways: list[str] = Field(default_factory=list)
    sources: list[ResearchSource] = Field(default_factory=list)


SYSTEM = "你是网文市场研究员，只输出 JSON，不编造真实榜单或链接。"

PROMPT = """【技能 genre_research】
题材：{genre}
目标读者：{audience}
篇幅：{length}
拟写书名：{title}

给出同题材 4 个「典型热门作品特征」，可以是虚构样本名，但必须明确是模型推断。
输出 JSON：
{{"works":[{{"title":"样本名","hook":"一句话卖点","three_chapter_summary":"前三章剧情梗概","tags":["标签"]}}],
 "takeaways":["可复用的开篇策略"],
 "sources":[{{"type":"model_inference","note":"无外部检索源，内容为模型知识推断"}}]}}
"""


def _fallback(payload: GenreResearchInput) -> GenreResearchOutput:
    genre = payload.genre_name
    works = [
        ResearchWork(
            title=f"{genre}·开局即高能（样本）",
            hook="第一章抛出最大冲突，三章内完成第一次反转与金手指落地。",
            three_chapter_summary="第一章主角遭遇剧变并暴露异常能力；第二章被势力盯上，建立第一条对抗线；第三章小胜一场，拿到阶段性筹码。",
            tags=["强开局", "快节奏", "升级流"],
        ),
        ResearchWork(
            title=f"{genre}·身份错位（样本）",
            hook="错认身份带来持续误会与利益冲突，读者追着看主角何时拆穿。",
            three_chapter_summary="第一章错认现场；第二章被迫入局；第三章借势反打，埋下身世伏笔。",
            tags=["身份梗", "悬念", "情感线"],
        ),
        ResearchWork(
            title=f"{genre}·群像逆袭（样本）",
            hook="弱者联盟对抗既定秩序，情绪爽点来自集体翻身。",
            three_chapter_summary="第一章结盟契机；第二章第一次协同作战；第三章赢得喘息并立下新目标。",
            tags=["群像", "逆袭", "热血"],
        ),
        ResearchWork(
            title=f"{genre}·长线悬念（样本）",
            hook="用一章一个大问题牵引追更，答案逐步兑现。",
            three_chapter_summary="第一章异常事件；第二章追查受阻；第三章拿到关键物证。",
            tags=["悬疑", "追更", "长线"],
        ),
    ]
    return GenreResearchOutput(
        genre=genre,
        works=works,
        takeaways=[
            "前三章必须完成「冲突—选择—阶段兑现」闭环",
            "每章结尾保留一个可执行的问题，而不是纯悬念",
            "主角主动做决定，避免被动推进",
        ],
        sources=[ResearchSource(type="model_inference", note="无外部检索源，以上为模型知识推断，非真实榜单数据")],
    )


class GenreResearchSkill(BaseSkill):
    name = "genre_research"
    version = "1.0.0"
    input_model = GenreResearchInput
    output_model = GenreResearchOutput

    def run(self, payload: GenreResearchInput, ctx: SkillContext) -> GenreResearchOutput:
        ranking_items: list[dict] = []
        ranking_reports: list[dict] = []
        if ctx.settings.ranking_enabled and not ctx.settings.model_stub:
            try:
                ranking_items, ranking_reports = fetch_rankings_sync(
                    ctx.settings,
                    limit=10,
                    genre=payload.genre_name,
                    audience=payload.audience,
                )
                if ranking_items:
                    ctx.log(f"榜单抓取完成：{len(ranking_items)} 条元数据")
            except Exception as exc:  # noqa: BLE001 - 榜单失败不影响主流程
                ctx.log(f"榜单抓取失败，回退模型推断：{type(exc).__name__}", level="warning")

        data = call_json(
            ctx,
            system=SYSTEM,
            user=PROMPT.format(
                genre=payload.genre_name,
                audience="男频" if payload.audience == "male" else "女频",
                length="长篇" if payload.length == "long" else "短篇",
                title=payload.title,
            ),
        )
        works = []
        for item in list_of_dicts(data.get("works"), 5):
            title = text_of(item.get("title"))
            if not title:
                continue
            works.append(
                ResearchWork(
                    title=title,
                    hook=text_of(item.get("hook")) or "以强冲突开局，三章内兑现第一次小胜。",
                    three_chapter_summary=text_of(item.get("three_chapter_summary")) or "前三章完成冲突建立、主角选择与阶段兑现。",
                    tags=[text_of(t) for t in (item.get("tags") or []) if text_of(t)][:6],
                )
            )
        real_works = [
            ResearchWork(
                title=f"{SOURCE_LABELS.get(item.get('site'), item.get('site'))} · 第{item.get('rank')}名《{item.get('title')}》",
                hook=f"作者：{item.get('author') or '未知'}；榜单仅取元数据，不抓正文。",
                three_chapter_summary=text_of(item.get("summary"))[:200]
                or "仅取得榜单排名与书名，正文需原创改编，禁止同名与连续撞句。",
                tags=[tag for tag in ("榜单", SOURCE_LABELS.get(item.get("site"), ""), item.get("genre")) if tag],
            )
            for item in ranking_items[:5]
        ]
        if not works and not real_works:
            out = _fallback(payload)
            ctx.log("未取得可用调研结果，使用模型推断样本")
            return out

        sources = [
            ResearchSource(type=text_of(s.get("type")) or "model_inference", note=text_of(s.get("note")))
            for s in list_of_dicts(data.get("sources"))
            if text_of(s.get("note"))
        ]
        for report in ranking_reports:
            label = report.get("label") or report.get("site")
            if report.get("ok"):
                sources.append(
                    ResearchSource(
                        type="web_ranking",
                        note=f"{label}：{report.get('count', 0)} 条（仅书名/作者/排名元数据）",
                    )
                )
            else:
                sources.append(
                    ResearchSource(type="web_ranking", note=f"{label}：抓取失败（{report.get('error') or 'unknown'}）")
                )
        if real_works:
            sources = [source for source in sources if source.type != "model_inference"]
            sources.append(
                ResearchSource(
                    type="model_inference",
                    note="模型推断：基于榜单书名/题材补充开篇策略，不包含任何榜单正文",
                )
            )
        if not sources:
            sources = [ResearchSource(type="model_inference", note="无外部检索源，以上为模型知识推断")]
        takeaways = [text_of(t) for t in (data.get("takeaways") or []) if text_of(t)][:6]
        takeaways.append("榜单只用于提炼题材与开篇策略；人物、地名、组织名与书名必须全部重命名，禁止同名与连续撞句。")
        return GenreResearchOutput(
            genre=payload.genre_name,
            works=(real_works + works)[:8],
            takeaways=takeaways[:7],
            sources=sources,
        )
