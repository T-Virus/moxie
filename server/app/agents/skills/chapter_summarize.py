# -*- coding: utf-8 -*-
"""全量章节概括：有正文的章节批量调用模型，其余章节直接采用章纲概括。"""

from __future__ import annotations

import json
import re

from pydantic import Field

from ..contracts import SkillContext, StrictModel, call_json, list_of_dicts, text_of
from .base import BaseSkill

SYSTEM = "你是网文编辑，只输出 JSON；概括要具体，不写空话。"
PROMPT = """【技能 chapter_summarize】
书名：{title}
请概括下列章节，summary 控制在 80-200 字。
有的章节可能只有章纲信息（没有正文 content），你需要根据章纲里的
summary / conflict / hook / key_events / reversal / foreshadow 等推断
下列结构化字段，能推断的必须填全，无法推断的留空、留 0 或空数组。

必填字段：
- scene：本章主要发生场景（从 summary/key_events 提取，1-2 个短语）
- hook_type：章末钩子类型（悬念/反转/危机/揭示/伏笔/新挑战 选一个）
- emotion：本章主导情绪（紧张/悲伤/愤怒/欢乐/期待/震惊/压抑 选一个）
- tension：本章张力值 1-10（从 conflict/key_events 推断）
- roles：本章出场/提及的角色名（2-6 个）
- factions：本章涉及的势力/组织/门派（如无则空数组）
- items：本章涉及的关键道具/功法/物品（如无则空数组）
- key_events：本章关键事件，必须 5-8 条，每条 15-30 字，按发生顺序排列
- points：与 key_events 内容完全一致（旧字段，保持同步）

写作规划字段：
- chapter_function：本章功能（铺垫/冲突升级/高潮/收束/过渡 选一个）
- chapter_goal：本章目的（一句话，20 字内）
- arc：章节阶段（开局/发展/转折/高潮/收束 选一个）
- beat_type：节拍类型（开场/激励事件/冲突升级/反转/揭秘/情感推进/收束 选一个）
- pov：叙事视角（主角名或「第三人称」）
- time_span：本章时间跨度（如「当日」「三日后」）
- word_target：目标字数（整数，按篇幅推断，通常 2000-3000）
- word_actual：实际字数（有正文时给正文长度，没有则 0）
- payoff_type：爽点类型（打脸/升级/获得/揭晓/守护/复仇/情感推进 选一个）
- payoff_owner：爽点归属（角色名，通常是主角）
- payoff_intensity：爽点强度 1-10
- tear_point：泪点（没有则空字符串）
- sweet_point：甜点（没有则空字符串）
- twist：本章反转（没有则空字符串）
- new_characters：本章首次登场的角色名（没有则空数组）
- new_items：本章首次出现的关键道具（没有则空数组）
- new_settings：本章新增的设定/规则（没有则空数组）
- foreshadow_ids：本章关联或埋下的伏笔（短句，没有则空数组）
- continuity_check：与既有设定是否一致（填「通过」或「冲突：具体说明」）
- chapter_status：章节状态（有正文填「已生成」，无正文填「待生成」）

输出 JSON：
{{"chapters":[{{
"chapter_no":1,"title":"","summary":"","conflict":"","hook":"",
"chapter_id":"","scene":"","hook_type":"","emotion":"","tension":5,
"payoff":"","setup":"","key_events":[""],"points":[""],
"roles":[""],"factions":[""],"items":[""],
"chapter_function":"","chapter_goal":"","beat_type":"","pov":"","time_span":"",
"arc":"",
"word_target":2500,"word_actual":0,
"payoff_type":"","payoff_owner":"","payoff_intensity":5,
"tear_point":"","sweet_point":"","twist":"",
"new_characters":[""],"new_items":[""],"new_settings":[""],"foreshadow_ids":[""],
"continuity_check":"","chapter_status":""
}}]}}
章节：{material}
"""

FILLER = "这一章把主线矛盾向前推了一步，人物关系出现新的张力，为后续冲突埋下伏笔。"
SUMMARY_BATCH = 5


class ChapterSummarizeInput(StrictModel):
    title: str = Field(min_length=1, max_length=120)
    chapters: list[dict] = Field(default_factory=list)


class SummaryChapter(StrictModel):
    chapter_no: int
    title: str
    summary: str
    conflict: str
    hook: str
    word_count: int = 0
    # 可选结构化字段，与 chapter_write / 工作台字段同名；缺失时为空。
    chapter_id: str = ""
    scene: str = ""
    hook_type: str = ""
    emotion: str = ""
    tension: int = 0
    payoff: str = ""
    setup: str = ""
    # 关键事件（工作台「关键事件」字段，5-8 条）；points 与它同源，保留给旧客户端
    key_events: list[str] = Field(default_factory=list)
    points: list[str] = Field(default_factory=list)
    roles: list[str] = Field(default_factory=list)
    factions: list[str] = Field(default_factory=list)
    items: list[str] = Field(default_factory=list)
    # 写作规划字段：工作台「卷章概括」详情直接展示，也允许在集合编辑里修改
    arc: str = ""
    chapter_function: str = ""
    chapter_goal: str = ""
    beat_type: str = ""
    pov: str = ""
    time_span: str = ""
    word_target: int = 0
    word_actual: int = 0
    payoff_type: str = ""
    payoff_owner: str = ""
    payoff_intensity: int = 0
    tear_point: str = ""
    sweet_point: str = ""
    twist: str = ""
    new_characters: list[str] = Field(default_factory=list)
    new_items: list[str] = Field(default_factory=list)
    new_settings: list[str] = Field(default_factory=list)
    foreshadow_ids: list[str] = Field(default_factory=list)
    continuity_check: str = ""
    chapter_status: str = ""
    revision_note: str = ""


class ChapterSummarizeOutput(StrictModel):
    chapters: list[SummaryChapter] = Field(default_factory=list)


def _clip(text: str, minimum: int = 80, maximum: int = 200) -> str:
    text = " ".join(str(text or "").split())
    if len(text) > maximum:
        cut = text[:maximum]
        pos = max(cut.rfind(mark) for mark in "。！？；")
        text = cut[: pos + 1] if pos >= minimum else cut
    while len(text) < minimum:
        text = f"{text} {FILLER}".strip()
    return text[:maximum]


PROMPT_MARKERS = ("【技能", "你是网文", "输出 JSON", "书名：")


def _clean(value: str) -> str:
    value = text_of(value)
    return "" if any(marker in value for marker in PROMPT_MARKERS) else value


def _int(value, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _text_list(*values) -> list[str]:
    out: list[str] = []
    for value in values:
        if isinstance(value, list):
            out.extend(text_of(item) for item in value if text_of(item))
        elif text_of(value):
            out.append(text_of(value))
    return out


def _phrases(*values) -> list[str]:
    """把「A；B｜C」这种长文本拆成多条，用于伏笔等列表字段。"""
    out: list[str] = []
    for value in values:
        if isinstance(value, list):
            out.extend(text_of(item) for item in value if text_of(item))
        elif text_of(value):
            out.extend(
                part.strip()
                for part in re.split(r"[；;｜|\n]", text_of(value))
                if part.strip()
            )
    return out


def _fallback(chapter: dict, index: int) -> SummaryChapter:
    content = _clean(chapter.get("content"))
    summary_source = content or _clean(chapter.get("summary"))
    number = _int(chapter.get("chapter") or index, index)
    # 有正文时用正文前 1200 字算 fallback summary（让模型能看到正文），
    # 只有章纲时 summary_source 就是章纲 summary，clip 的 minimum=0 不硬凑 80 字。
    has_content = bool(content)
    events = _text_list(chapter.get("key_events"), chapter.get("points"))[:8]
    roles = _text_list(chapter.get("roles"), chapter.get("characters"))[:8]
    factions = _text_list(chapter.get("factions"))[:6]
    items = _text_list(chapter.get("items"))[:6]
    hook = _clean(chapter.get("hook")) or "新的问题被抛出，答案留到下一章。"
    tension = (
        max(0, min(10, _int(chapter.get("tension"))))
        if chapter.get("tension") is not None
        else 0
    )
    word_actual = _int(chapter.get("word_actual")) or _int(chapter.get("word_count")) or (
        len(text_of(content)) if has_content else 0
    )
    payoff = _clean(chapter.get("payoff"))
    intensity = (
        max(0, min(10, _int(chapter.get("payoff_intensity"))))
        if chapter.get("payoff_intensity") is not None
        else tension
    )
    return SummaryChapter(
        chapter_no=number,
        title=text_of(chapter.get("title")) or f"第{index}章",
        summary=_clip(summary_source or FILLER, minimum=80 if has_content else 0),
        conflict=_clean(chapter.get("conflict"))
        or _clean(chapter.get("summary"))
        or "主角的核心目标遭遇直接阻力。",
        hook=hook,
        word_count=_int(chapter.get("word_count"))
        or (len(text_of(content)) if has_content else 0),
        chapter_id=_clean(chapter.get("chapter_id")) or f"ch-{number:03d}",
        scene=_clean(chapter.get("scene")),
        hook_type=_clean(chapter.get("hook_type")),
        emotion=_clean(chapter.get("emotion")),
        tension=tension,
        payoff=payoff,
        setup=_clean(chapter.get("setup")),
        key_events=events,
        points=events,
        roles=roles,
        factions=factions,
        items=items,
        arc=_clean(chapter.get("arc")),
        chapter_function=_clean(chapter.get("chapter_function")),
        chapter_goal=_clean(chapter.get("chapter_goal")),
        beat_type=_clean(chapter.get("beat_type")),
        pov=_clean(chapter.get("pov")),
        time_span=_clean(chapter.get("time_span")),
        word_target=_int(chapter.get("word_target")),
        word_actual=word_actual,
        payoff_type=_clean(chapter.get("payoff_type")),
        payoff_owner=_clean(chapter.get("payoff_owner")) or (roles[0] if payoff else ""),
        payoff_intensity=intensity if payoff else 0,
        tear_point=_clean(chapter.get("tear_point")),
        sweet_point=_clean(chapter.get("sweet_point")),
        twist=_clean(chapter.get("twist")) or _clean(chapter.get("reversal")),
        new_characters=_text_list(chapter.get("new_characters"))[:6],
        new_items=_text_list(chapter.get("new_items"))[:6],
        new_settings=_text_list(chapter.get("new_settings"))[:6],
        foreshadow_ids=_phrases(chapter.get("foreshadow_ids"), chapter.get("foreshadow"))[:6],
        continuity_check=_clean(chapter.get("continuity_check")),
        chapter_status=_clean(chapter.get("chapter_status"))
        or ("已生成" if has_content else "待生成"),
        revision_note=_clean(chapter.get("revision_note")),
    )


class ChapterSummarizeSkill(BaseSkill):
    name = "chapter_summarize"
    version = "1.0.0"
    input_model = ChapterSummarizeInput
    output_model = ChapterSummarizeOutput

    def run(self, payload: ChapterSummarizeInput, ctx: SkillContext) -> ChapterSummarizeOutput:
        chapters = list_of_dicts(payload.chapters)
        if not chapters:
            raise ValueError("chapter_summarize 需要至少 1 章章节数据")
        indexed = list(enumerate(chapters, 1))
        result_by_no: dict[int, SummaryChapter] = {}

        # 所有章节（无论有无正文）都批量调一次模型：
        #   - 有正文 → material.content 带正文片段，模型能精准分析
        #   - 只有章纲 → material.content 空，material 里仍带 summary/conflict/key_events/hook，
        #                 让模型从章纲推断 scene / hook_type / emotion / tension / roles 等结构化字段
        # 每批 SUMMARY_BATCH 章，逐批调用，逐批 merge。
        for start in range(0, len(indexed), SUMMARY_BATCH):
            batch = indexed[start : start + SUMMARY_BATCH]
            material = [
                {
                    "chapter": chapter.get("chapter") or index,
                    "title": chapter.get("title"),
                    "summary": chapter.get("summary"),
                    # 有正文带正文片段（最多 1200 字），没有则空
                    "content": text_of(chapter.get("content"))[:1200],
                    # 章纲结构化信息：无论有无正文都附上，让模型据此推断补全字段
                    "conflict": chapter.get("conflict") or "",
                    "hook": chapter.get("hook") or "",
                    "key_events": chapter.get("key_events") or chapter.get("points") or [],
                    "reversal": chapter.get("reversal") or "",
                    "foreshadow": chapter.get("foreshadow") or "",
                    # 正文已有则透传给模型参考
                    "scene": chapter.get("scene") or "",
                    "hook_type": chapter.get("hook_type") or "",
                    "emotion": chapter.get("emotion") or "",
                    "tension": chapter.get("tension") or 0,
                    "roles": chapter.get("roles") or chapter.get("characters") or [],
                    "factions": chapter.get("factions") or [],
                    "items": chapter.get("items") or [],
                    # 规划/数据字段：人工修改过的值透传给模型，避免重算后被覆盖成空
                    "arc": chapter.get("arc") or "",
                    "chapter_function": chapter.get("chapter_function") or "",
                    "chapter_goal": chapter.get("chapter_goal") or "",
                    "beat_type": chapter.get("beat_type") or "",
                    "pov": chapter.get("pov") or "",
                    "time_span": chapter.get("time_span") or "",
                    "word_target": chapter.get("word_target") or 0,
                    "word_count": chapter.get("word_count") or 0,
                    "payoff": chapter.get("payoff") or "",
                    "setup": chapter.get("setup") or "",
                    "payoff_type": chapter.get("payoff_type") or "",
                    "payoff_owner": chapter.get("payoff_owner") or "",
                    "payoff_intensity": chapter.get("payoff_intensity") or 0,
                    "tear_point": chapter.get("tear_point") or "",
                    "sweet_point": chapter.get("sweet_point") or "",
                    "twist": chapter.get("twist") or "",
                    "new_characters": chapter.get("new_characters") or [],
                    "new_items": chapter.get("new_items") or [],
                    "new_settings": chapter.get("new_settings") or [],
                    "foreshadow_ids": chapter.get("foreshadow_ids") or [],
                    "continuity_check": chapter.get("continuity_check") or "",
                    "chapter_status": chapter.get("chapter_status") or "",
                }
                for index, chapter in batch
            ]
            try:
                data = call_json(
                    ctx,
                    system=SYSTEM,
                    user=PROMPT.format(
                        title=payload.title,
                        material=json.dumps(material, ensure_ascii=False)[:12000],
                    ),
                )
            except Exception as exc:  # noqa: BLE001 - 概括失败回退到章纲概括
                ctx.log(
                    f"第 {start + 1}–{start + len(batch)} 章概括生成失败，使用章纲概括：{type(exc).__name__}",
                    level="warning",
                )
                data = {}
            got = [] if ctx.settings.model_stub else list_of_dicts(data.get("chapters"))
            got_by_no = {
                int(item.get("chapter_no") or item.get("chapter") or i): item
                for i, item in enumerate(got, 1)
            }
            for index, chapter in batch:
                fallback = _fallback(chapter, index)
                item = got_by_no.get(fallback.chapter_no) or (got[0] if got else {})
                result_by_no[fallback.chapter_no] = _merge_item(fallback, item)

        result = [result_by_no[number] for number in sorted(result_by_no)]
        ctx.log(f"章节概括完成：{len(result)} 章（含 scene/hook_type/emotion/tension/roles 等结构化字段）")
        return ChapterSummarizeOutput(chapters=result)


def canonical_chapter(item: dict) -> dict:
    """把工作台提交的章节对象还原成服务端契约字段（不改动用户填写的值）。

    客户端用 no / words / key_events 编辑，服务端契约是 chapter_no / word_count / points；
    两边都写一份，保证读回时字段齐全且 key_events 与 points 始终同步。
    """
    raw = dict(item or {})
    number = _int(raw.get("no") or raw.get("chapter_no") or raw.get("chapter"), 0)
    events = _text_list(raw.get("key_events"), raw.get("points"))
    # 客户端「字数」编辑的是 words；同时提交旧 word_count 时以 words 为准
    words = raw.get("words")
    word_count = _int(words if words is not None and words != "" else raw.get("word_count"), 0)
    out = {
        **raw,
        "chapter_no": number,
        "no": number,
        "word_count": word_count,
        "key_events": events,
        "points": events,
    }
    for key in ("word_target", "word_actual", "payoff_intensity", "tension", "words"):
        if raw.get(key) not in (None, ""):
            out[key] = _int(raw.get(key))
    for key in (
        "roles",
        "factions",
        "items",
        "new_characters",
        "new_items",
        "new_settings",
        "foreshadow_ids",
    ):
        if key in raw:
            out[key] = _phrases(raw.get(key))
    return out


def _pick_int(model_value, base: int, low: int = 0, high: int = 10) -> int:
    """模型给整数就用模型的（夹在区间内），否则沿用兜底值。"""
    if model_value in (None, ""):
        return base
    return max(low, min(high, _int(model_value, base)))


def _merge_item(fallback: SummaryChapter, item: dict) -> SummaryChapter:
    if not text_of(item.get("summary")):
        return fallback
    return SummaryChapter(
        chapter_no=fallback.chapter_no,
        title=text_of(item.get("title")) or fallback.title,
        summary=_clip(text_of(item.get("summary"))),
        conflict=text_of(item.get("conflict")) or fallback.conflict,
        hook=text_of(item.get("hook")) or fallback.hook,
        word_count=fallback.word_count,
        chapter_id=text_of(item.get("chapter_id")) or fallback.chapter_id,
        scene=text_of(item.get("scene")) or fallback.scene,
        hook_type=text_of(item.get("hook_type")) or fallback.hook_type,
        emotion=text_of(item.get("emotion")) or fallback.emotion,
        tension=max(fallback.tension, min(10, _int(item.get("tension"))))
        if item.get("tension") is not None
        else fallback.tension,
        payoff=text_of(item.get("payoff")) or fallback.payoff,
        setup=text_of(item.get("setup")) or fallback.setup,
        key_events=_text_list(item.get("key_events"), item.get("points"))[:8]
        or fallback.key_events,
        points=_text_list(item.get("points"), item.get("key_events"))[:8]
        or fallback.points,
        roles=_text_list(item.get("roles")) or fallback.roles,
        factions=_text_list(item.get("factions")) or fallback.factions,
        items=_text_list(item.get("items")) or fallback.items,
        arc=text_of(item.get("arc")) or fallback.arc,
        chapter_function=text_of(item.get("chapter_function")) or fallback.chapter_function,
        chapter_goal=text_of(item.get("chapter_goal")) or fallback.chapter_goal,
        beat_type=text_of(item.get("beat_type")) or fallback.beat_type,
        pov=text_of(item.get("pov")) or fallback.pov,
        time_span=text_of(item.get("time_span")) or fallback.time_span,
        # 目标/实际字数以章纲与正文为准，模型只做补充
        word_target=fallback.word_target
        or _pick_int(item.get("word_target"), 0, 0, 100000),
        word_actual=fallback.word_actual
        or _pick_int(item.get("word_actual"), 0, 0, 100000),
        payoff_type=text_of(item.get("payoff_type")) or fallback.payoff_type,
        payoff_owner=text_of(item.get("payoff_owner")) or fallback.payoff_owner,
        payoff_intensity=_pick_int(
            item.get("payoff_intensity"), fallback.payoff_intensity
        ),
        tear_point=text_of(item.get("tear_point")) or fallback.tear_point,
        sweet_point=text_of(item.get("sweet_point")) or fallback.sweet_point,
        twist=text_of(item.get("twist"))
        or text_of(item.get("reversal"))
        or fallback.twist,
        new_characters=_text_list(item.get("new_characters"))[:6]
        or fallback.new_characters,
        new_items=_text_list(item.get("new_items"))[:6] or fallback.new_items,
        new_settings=_text_list(item.get("new_settings"))[:6] or fallback.new_settings,
        foreshadow_ids=_phrases(item.get("foreshadow_ids"))[:6]
        or fallback.foreshadow_ids,
        continuity_check=text_of(item.get("continuity_check")) or fallback.continuity_check,
        chapter_status=text_of(item.get("chapter_status")) or fallback.chapter_status,
        revision_note=text_of(item.get("revision_note")) or fallback.revision_note,
    )
