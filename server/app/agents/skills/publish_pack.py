# -*- coding: utf-8 -*-
"""发布包：质检之后产出平台标签、简介、封面提示词与续写入口建议。

只做「可发布的包装材料」，不改正文；产出进入 publish_pack.json 并随稿包导出。
"""

from __future__ import annotations

import json

from pydantic import Field

from ..contracts import SkillContext, StrictModel, call_json, list_of_dicts, text_of
from .base import BaseSkill


class PublishInput(StrictModel):
    title: str = Field(min_length=1, max_length=120)
    genre_name: str = Field(min_length=1, max_length=60)
    chapters: list[dict] = Field(default_factory=list)
    outline: list[dict] = Field(default_factory=list)
    positioning: dict = Field(default_factory=dict)
    settings: dict = Field(default_factory=dict)
    review: dict = Field(default_factory=dict)


class PublishOutput(StrictModel):
    tags: list[str] = Field(default_factory=list)
    blurb: str = ""
    cover_prompt: str = ""
    first_chapter_hook: str = ""
    sequel_hint: str = ""
    notes: list[str] = Field(default_factory=list)


SYSTEM = "你是网文运营编辑，只输出 JSON；文案要可直接复制发布，不写空话。"

PROMPT = """【技能 publish_pack】
书名：{title}　题材：{genre}　目标平台：{platform}

定位卡：{positioning}
第一章大纲与钩子：{first_chapter}
体检结论：score={score}，高危={high_risk}

请产出发布材料：
1. tags：6-8 个平台搜索标签（题材词+人设词+爽点词，各不超过 8 字）；
2. blurb：100-200 字书籍简介，第一句必须是钩子，禁止剧透第三章之后的内容；
3. cover_prompt：AI 封面提示词（中文，含主体、场景、情绪、风格，60-120 字）；
4. first_chapter_hook：把第一章开场钩子压缩成 30 字以内的平台展示语；
5. sequel_hint：续写入口建议（下一卷第一个钩子从哪接）。
输出 JSON：
{{"tags":[""],"blurb":"","cover_prompt":"","first_chapter_hook":"","sequel_hint":"","notes":["发布注意事项"]}}
"""


def _fallback(payload: PublishInput) -> PublishOutput:
    positioning = payload.positioning or {}
    platform = text_of(positioning.get("platform")) or "通用平台"
    highlights = [
        text_of(item) for item in (positioning.get("highlight_preferences") or []) if text_of(item)
    ] or ["强钩子开局", "阶段性兑现"]
    first = next(iter(list_of_dicts(payload.chapters, 1)), {})
    first_outline = next(iter(list_of_dicts(payload.outline, 1)), {})
    hook = (
        text_of(first.get("hook"))
        or text_of(first_outline.get("hook"))
        or "第一章抛出的危机，答案藏在下一章。"
    )
    golden = text_of((payload.settings or {}).get("golden_finger"))
    blurb = (
        f"开局即是死局。{text_of(first_outline.get('summary'))[:60]} "
        f"主角唯一的筹码是{golden[:30] or '一个别人看不见的规则'}，"
        "用它换一条活路，代价是把自己推到所有人的对面。"
    )[:200]
    return PublishOutput(
        tags=[payload.genre_name, "强钩子", *highlights][:8],
        blurb=blurb,
        cover_prompt=(
            f"{payload.genre_name}题材小说封面：主角背影立于冲突现场，画面主色对比强烈，"
            "人物剪影与规则/力量符号交织，电影感构图，竖版 3:4。"
        ),
        first_chapter_hook=hook[:30],
        sequel_hint="下一卷从「新浮出的对手」接第一个钩子，延续本章末尾的未答问题。",
        notes=[f"发布到{platform}前请人工复核简介与标签是否触发敏感词。"],
    )


class PublishPackSkill(BaseSkill):
    name = "publish_pack"
    version = "1.0.0"
    input_model = PublishInput
    output_model = PublishOutput

    def run(self, payload: PublishInput, ctx: SkillContext) -> PublishOutput:
        fallback = _fallback(payload)
        positioning = payload.positioning or {}
        positioning_view = {
            key: positioning.get(key)
            for key in ("platform", "emotional_tone", "highlight_preferences", "summary")
            if text_of(positioning.get(key)) or positioning.get(key)
        }
        first_outline = next(iter(list_of_dicts(payload.outline, 1)), {})
        data = call_json(
            ctx,
            system=SYSTEM,
            user=PROMPT.format(
                title=payload.title,
                genre=payload.genre_name,
                platform=text_of(positioning.get("platform")) or "未指定",
                positioning=json.dumps(positioning_view, ensure_ascii=False)[:1500] or "未提供",
                first_chapter=json.dumps(
                    {
                        key: first_outline.get(key)
                        for key in ("title", "summary", "conflict", "hook")
                        if text_of(first_outline.get(key))
                    },
                    ensure_ascii=False,
                ),
                score=int((payload.review or {}).get("score") or 0),
                high_risk=bool((payload.review or {}).get("high_risk")),
            ),
        )
        result = PublishOutput(
            tags=(
                [text_of(item)[:12] for item in (data.get("tags") or []) if text_of(item)][:8]
                or fallback.tags
            ),
            blurb=text_of(data.get("blurb"))[:400] or fallback.blurb,
            cover_prompt=text_of(data.get("cover_prompt"))[:300] or fallback.cover_prompt,
            first_chapter_hook=text_of(data.get("first_chapter_hook"))[:60]
            or fallback.first_chapter_hook,
            sequel_hint=text_of(data.get("sequel_hint"))[:200] or fallback.sequel_hint,
            notes=(
                [text_of(item)[:120] for item in (data.get("notes") or []) if text_of(item)][:6]
                or fallback.notes
            ),
        )
        ctx.log(f"发布包完成：{len(result.tags)} 个标签，简介 {len(result.blurb)} 字")
        return result
