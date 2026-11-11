# -*- coding: utf-8 -*-
"""大纲规划：把调研/拆解/改编素材收敛成可执行的分章大纲。"""

from __future__ import annotations

import json

from pydantic import Field

from ..contracts import SkillContext, StrictModel, call_json, list_of_dicts, text_of
from .base import BaseSkill

CHAPTER_TOTAL = {"long": 12, "short": 6}

ARC_TEMPLATES = [
    ("开局", "主角被卷入核心冲突，第一次异常暴露"),
    ("入局", "主角作出主动选择，建立第一条对抗线"),
    ("试炼", "小规模交锋，拿到阶段性筹码"),
    ("误解", "关键关系出现错位，信息差扩大"),
    ("反转", "旧线索被推翻，真正的对手浮出水面"),
    ("低谷", "一次失败让主角失去依靠"),
    ("结盟", "被迫与曾经的对手合作"),
    ("真相", "身世/规则的关键部分被揭开"),
    ("代价", "胜利伴随不可逆的损失"),
    ("决战", "正面对抗既定秩序"),
    ("余波", "新秩序建立，旧问题留下尾巴"),
    ("新局", "主角带着新目标出发，钩子留给下一部"),
]


class OutlineInput(StrictModel):
    title: str = Field(min_length=1, max_length=120)
    audience: str = Field(pattern="^(male|female)$")
    length: str = Field(pattern="^(long|short)$")
    genre_name: str = Field(min_length=1, max_length=60)
    brief: str | None = None
    research: dict = Field(default_factory=dict)
    decomposition: dict = Field(default_factory=dict)
    adaptation: dict = Field(default_factory=dict)
    # 创作高级选项：0 = 沿用篇幅默认；续写章数追加在目标章数之后
    target_chapters: int = Field(default=0, ge=0, le=500)
    sequel_chapters: int = Field(default=0, ge=0, le=200)


class OutlineChapter(StrictModel):
    chapter: int
    title: str
    summary: str
    key_events: list[str] = Field(default_factory=list)
    hook: str = ""
    arc: str = ""


class OutlineOutput(StrictModel):
    logline: str
    theme: str = ""
    story_bible: dict = Field(default_factory=dict)
    chapters: list[OutlineChapter] = Field(default_factory=list)
    # 以下为工作台需要的可选结构化字段；缺失时为空，不影响既有契约。
    volumes: list[dict] = Field(default_factory=list)
    opening: dict = Field(default_factory=dict)
    worldview: list[dict] = Field(default_factory=list)
    map_levels: list[str] = Field(default_factory=list)
    map_regions: list[dict] = Field(default_factory=list)
    map_scenes: list[dict] = Field(default_factory=list)
    signing_check: dict = Field(default_factory=dict)
    completeness_check: dict = Field(default_factory=dict)
    # 作品信息页需要的定位/叙事/连载字段（真实模型产出，缺失时由规范化兜底）
    type_primary: str = ""
    type_secondary: list[str] = Field(default_factory=list)
    core_hook: str = ""
    selling_points: list[str] = Field(default_factory=list)
    target_platform: list[str] = Field(default_factory=list)
    target_reader_age: str = ""
    total_chapters_planned: int = 0
    chapter_words_target: int = 0
    estimated_words: int = 0
    tone: str = ""
    person: str = ""
    style: str = ""
    conflict: str = ""
    suspense: str = ""
    subplots: list[str] = Field(default_factory=list)
    supporting: str = ""
    antagonist: str = ""
    foreshadow_text: str = ""
    places: str = ""
    items_text: str = ""
    terms: str = ""
    timeline: str = ""
    map_text: str = ""
    theme_core: str = ""
    theme_statement: str = ""
    innovation_points: list[str] = Field(default_factory=list)
    comparative_titles: list[str] = Field(default_factory=list)
    ending_type: str = ""
    ending_state: str = ""
    protagonist_final_fate: str = ""
    taboos: str = ""
    update_frequency: str = ""
    serialization_pace: str = ""
    content_rating: str = ""
    series_plan: str = ""
    keywords: list[str] = Field(default_factory=list)
    aigc_disclosure: str = ""
    status: str = ""
    genre_tone: str = ""
    audience: str = ""
    book_summary: str = ""
    beats: list[str] = Field(default_factory=list)


SYSTEM = "你是网文主编，输出可逐章执行的大纲 JSON，不写正文。"

PROMPT = """【技能 outline】
书名：{title}
题材：{genre}　读者：{audience}　篇幅：{length}
创作 brief：{brief}

调研要点：{research}
改编素材摘要：{material}

输出 JSON：
{{"logline":"一句话故事线","theme":"主题","story_bible":{{"synopsis":"","world":"","power":"","protagonist":"","mainline":""}},
 "chapters":[{{"chapter":1,"title":"","summary":"","key_events":[""],"hook":"","arc":"开局"}}],
 "volumes":[{{"no":1,"title":"第一卷","summary":"","conflict":"","chapter_from":1,"chapter_to":3,
 "theme":"","core_event":"","conflict_axis":"","end_hook":"","arc":"","tension_profile":"3→5→7"}}],
 "opening":{{"strategy":"","first_image":"","golden_finger_demo":1}},
 "worldview":[{{"group":"","points":[{{"text":"","chapters":[1]}}]}}],
 "map_levels":[""],
 "map_regions":[{{"name":"","parent":"","kind":"","desc":"","chapters":[1]}}],
 "map_scenes":[{{"chapter":1,"region":"","characters":[""],"factions":[""],"items":[""],"event":""}}],
 "signing_check":{{"score":80,"risk":"low/medium/high","suggestions":[""],"issues":[""]}},
 "completeness_check":{{"missing_fields":[""],"unfilled_payoff":[""],"unrecovered":[""],"arc_missing":[""],"no_hook":[""]}},
 "type_primary":"主类型","type_secondary":["子类型"],"core_hook":"核心钩子","selling_points":["卖点1","卖点2"],
 "target_platform":["目标平台"],"target_reader_age":"18-30","total_chapters_planned":12,"chapter_words_target":2500,
 "tone":"整体基调","person":"第三人称","style":"文风与语言","conflict":"核心冲突","suspense":"核心悬念",
 "subplots":["支线1"],"supporting":"主要配角","antagonist":"主要反派","foreshadow_text":"伏笔设计",
 "places":"主要地点","items_text":"关键道具","terms":"核心术语","timeline":"时间线","map_text":"地图概览",
 "theme_core":"核心主题","theme_statement":"主题命题","innovation_points":["创新点"],"comparative_titles":["对标作品"],
 "ending_type":"结局类型","ending_state":"结局后的世界","protagonist_final_fate":"主角最终命运","taboos":"写作禁忌",
 "update_frequency":"更新频率","serialization_pace":"连载节奏","content_rating":"内容分级",
 "series_plan":"系列化规划","keywords":["关键词"],"aigc_disclosure":"AI 辅助创作说明",
 "beats":["第1章具体事件","第3章具体事件","第6章阶段兑现"]}}
章节数要求：{total} 章，章号连续，前三章必须完成「冲突—选择—阶段兑现」。
卷划分：按每 3 章一卷切分（不足 3 章的尾卷独立成卷）；只有一卷时同样输出完整字段。
作品信息字段要求：除无法从题材/书名/brief 推断的信息外，上面的定位、叙事、连载字段都要填写；
列表字段每条不超过 60 字，不要输出空字符串占位。
beats 必须写本书的具体剧情节点并按章号递增，禁止照抄示例文字。
无法确定的字段留空，不要编造。
"""


def volumes_for_chapters(chapters: list[dict], genre_name: str) -> list[dict]:
    """按最终章节重算分卷，保证卷区间与写作章数一致（reference 改编后章数可能变化）。"""
    rows: list[OutlineChapter] = []
    for index, chapter in enumerate(chapters, 1):
        rows.append(
            OutlineChapter(
                chapter=index,
                title=text_of(chapter.get("title")) or f"第{index}章",
                summary=text_of(chapter.get("summary"))
                or text_of(chapter.get("content"))[:200]
                or "剧情推进。",
                hook=text_of(chapter.get("hook")),
                arc=text_of(chapter.get("arc"))
                or ARC_TEMPLATES[(index - 1) % len(ARC_TEMPLATES)][0],
            )
        )
    payload = OutlineInput(
        title="章节分卷", audience="male", length="short", genre_name=genre_name or "通用"
    )
    return _build_volumes(rows, payload)


def _material(payload: OutlineInput) -> dict:
    for source in (payload.adaptation, payload.decomposition):
        if source and source.get("chapters"):
            return source
    return {}


CN_NUM = ("一", "二", "三", "四", "五", "六", "七", "八", "九", "十")
VOLUME_CHAPTERS = 3
POWER_GENRES = ("玄幻", "仙侠", "奇幻", "都市", "科幻", "武侠")


def _cn_no(value: int) -> str:
    return CN_NUM[value - 1] if 1 <= value <= len(CN_NUM) else str(value)


def _build_volumes(chapters: list[OutlineChapter], payload: OutlineInput) -> list[dict]:
    """按每 3 章一卷切分；单卷（含不足 3 章）也输出完整字段。"""
    total = len(chapters)
    if total <= 0:
        return []
    count = (total + VOLUME_CHAPTERS - 1) // VOLUME_CHAPTERS
    volumes: list[dict] = []
    for number in range(1, count + 1):
        start = (number - 1) * VOLUME_CHAPTERS + 1
        end = min(total, number * VOLUME_CHAPTERS)
        rows = chapters[start - 1:end]
        arc_names = [row.arc for row in rows if row.arc]
        titles = "、".join(row.title[:12] for row in rows if row.title)
        first_arc = arc_names[0] if arc_names else ""
        last_arc = arc_names[-1] if arc_names else first_arc
        tension = "→".join(str(min(10, 2 + 2 * i + number)) for i in range(1, len(rows) + 1))
        volumes.append(
            {
                "no": number,
                "title": f"第{_cn_no(number)}卷" + (f"·{first_arc}" if first_arc else ""),
                "summary": f"本卷覆盖第 {start}–{end} 章，围绕{payload.genre_name}题材的核心矛盾推进。",
                "conflict": rows[0].summary if rows else "",
                "chapter_from": start,
                "chapter_to": end,
                "theme": f"{payload.genre_name}·{first_arc or '推进'}",
                "core_event": titles or (rows[0].summary if rows else ""),
                "conflict_axis": f"{first_arc or '开局'} 对 对立势力阻挠" if first_arc else "",
                "end_hook": rows[-1].hook if rows else "",
                "arc": f"{first_arc} → {last_arc}" if arc_names else "",
                "tension_profile": tension,
            }
        )
    return volumes


def _build_opening(payload: OutlineInput, chapters: list[OutlineChapter]) -> dict:
    genre = payload.genre_name
    if any(key in genre for key in ("悬疑", "推理")):
        strategy = "以异常事件开场，先给结果再给原因"
    elif any(key in genre for key in ("言情", "甜宠", "婚恋")):
        strategy = "以关系错位开场，用第一场误会建立张力"
    elif any(key in genre for key in POWER_GENRES):
        strategy = "以金手指首次触发开场，快速建立代入感"
    else:
        strategy = f"以主角处境的核心异常开场，点明{genre}题材的主要看点"
    first = chapters[0] if chapters else None
    return {
        "strategy": strategy,
        "first_image": (first.summary[:160] if first else ""),
        "golden_finger_demo": 1 if (chapters and any(key in genre for key in POWER_GENRES)) else 0,
    }


def _build_worldview(bible: dict, payload: OutlineInput) -> list[dict]:
    return [
        {
            "group": "世界规则",
            "points": [
                {
                    "text": text_of(bible.get("world")) or f"{payload.genre_name}架空世界",
                    "chapters": [1],
                }
            ],
        },
        {
            "group": "力量体系",
            "points": [
                {"text": text_of(bible.get("power")) or "成长体系", "chapters": [1]}
            ],
        },
        {
            "group": "主线格局",
            "points": [
                {
                    "text": text_of(bible.get("mainline")) or "被卷入 → 主动入局 → 反转 → 决战 → 新局",
                    "chapters": [1, 2, 3],
                }
            ],
        },
    ]


def _build_map(
    payload: OutlineInput,
    chapters: list[OutlineChapter],
    bible: dict,
    *,
    stub: bool,
) -> tuple[list[str], list[dict], list[dict]]:
    world = text_of(bible.get("world")) or f"{payload.genre_name}架空世界"
    primary = f"{payload.genre_name}核心区域"
    regions = [
        {
            "name": primary,
            "parent": "",
            "kind": "主舞台",
            "desc": world[:120],
            "chapters": [1],
        },
        {
            "name": "边缘地带",
            "parent": primary,
            "kind": "次级区域",
            "desc": "主角被迫离开主舞台后进入的区域，信息更少、风险更高。",
            "chapters": [max(1, len(chapters) - 1)],
        },
        {
            "name": "核心秘密所在地",
            "parent": primary,
            "kind": "关键场景",
            "desc": "主线真相所在，通常在大纲后段才向读者开放。",
            "chapters": [max(1, len(chapters))],
        },
    ]
    scenes = [
        {
            "chapter": chapter.chapter,
            "region": primary,
            "characters": ["主角"] if stub else [],
            "factions": ["主角阵营"] if stub else [],
            "items": [],
            "event": chapter.summary[:160],
        }
        for chapter in chapters
    ]
    return ["世界层", "区域层", "场景层"], regions, scenes


def _signing_check(
    chapters: list[OutlineChapter], logline: str, theme: str
) -> dict:
    """基于大纲结构做确定性签约体检，不使用虚构评分。"""
    issues: list[str] = []
    suggestions: list[str] = []
    score = 50
    if logline:
        score += 10
    else:
        issues.append("缺少一句话故事线（logline）")
    if theme:
        score += 5
    else:
        issues.append("缺少主题表达")
    if len(chapters) >= 3:
        score += 10
    else:
        issues.append("章节数不足 3 章，开篇冲突难以完整展开")
        suggestions.append("至少补足 3 章，完成「冲突—选择—阶段兑现」")
    hooked = sum(1 for chapter in chapters if chapter.hook)
    if chapters and hooked == len(chapters):
        score += 10
    elif chapters:
        issues.append(f"有 {len(chapters) - hooked} 章缺少章末钩子")
        suggestions.append("为缺少钩子的章节补一个明确的下一步问题")
    arcs = sum(1 for chapter in chapters if chapter.arc)
    if chapters and arcs == len(chapters):
        score += 10
    elif chapters:
        issues.append(f"有 {len(chapters) - arcs} 章未标注叙事阶段")
    if score > 95:
        score = 95
    risk = "low" if score >= 85 else "medium" if score >= 70 else "high"
    return {
        "score": score,
        "risk": risk,
        "issues": issues,
        "suggestions": suggestions,
    }


def _completeness_check(
    chapters: list[OutlineChapter], logline: str, theme: str
) -> dict:
    missing: list[str] = []
    if not logline:
        missing.append("logline")
    if not theme:
        missing.append("theme")
    if not chapters:
        missing.append("chapters")
    return {
        "missing_fields": missing,
        "unfilled_payoff": [],
        "unrecovered": [],
        "arc_missing": [f"第{chapter.chapter}章" for chapter in chapters if not chapter.arc],
        "no_hook": [f"第{chapter.chapter}章" for chapter in chapters if not chapter.hook],
    }


def _total_of(payload: OutlineInput) -> int:
    base = payload.target_chapters or CHAPTER_TOTAL.get(payload.length, 12)
    return max(1, min(500, base + max(0, payload.sequel_chapters)))


def _fallback(payload: OutlineInput, *, stub: bool = True) -> OutlineOutput:
    material = _material(payload)
    total = _total_of(payload)
    source_chapters = list_of_dicts(material.get("chapters"))
    chapters: list[OutlineChapter] = []
    for index in range(1, total + 1):
        arc, note = ARC_TEMPLATES[(index - 1) % len(ARC_TEMPLATES)]
        src = source_chapters[index - 1] if index - 1 < len(source_chapters) else {}
        title = text_of(src.get("title")) or f"{payload.genre_name}·{arc}"
        summary = text_of(src.get("summary")) or (
            f"《{payload.title}》第 {index} 章：{note}。主角主动作出选择，并把局面推向下一阶段。"
        )
        chapters.append(
            OutlineChapter(
                chapter=index,
                title=title[:40],
                summary=summary[:300],
                key_events=[text_of(e) for e in (src.get("key_events") or []) if text_of(e)][:4]
                or [note],
                hook=text_of(src.get("hook")) or "新的问题被抛出，答案要等到下一章。",
                arc=arc,
            )
        )
    bible = {
        "synopsis": f"《{payload.title}》讲述主角在{payload.genre_name}世界中从被动卷入到主动改写规则的过程。",
        "world": text_of((material.get("story_bible") or {}).get("world")) or f"{payload.genre_name}架空世界",
        "power": text_of((material.get("story_bible") or {}).get("power")) or "成长体系",
        "protagonist": text_of((material.get("story_bible") or {}).get("protagonist")) or "主角",
        "mainline": "被卷入 → 主动入局 → 反转 → 决战 → 新局",
    }
    logline = f"一个普通人被卷入{payload.genre_name}世界的核心冲突，在一次次代价中学会主动改写规则。"
    theme = payload.genre_name + "题材下的成长与选择"
    volumes = _build_volumes(chapters, payload)
    map_levels, map_regions, map_scenes = _build_map(
        payload, chapters, bible, stub=stub
    )
    per_chapter = 2500 if payload.length == "long" else 1800
    audience_text = "男频" if payload.audience == "male" else "女频"
    return OutlineOutput(
        logline=logline,
        theme=theme,
        story_bible=bible,
        chapters=chapters,
        volumes=volumes,
        opening=_build_opening(payload, chapters),
        worldview=_build_worldview(bible, payload),
        map_levels=map_levels,
        map_regions=map_regions,
        map_scenes=map_scenes,
        signing_check=_signing_check(chapters, logline, theme),
        completeness_check=_completeness_check(chapters, logline, theme),
        type_primary=payload.genre_name,
        type_secondary=[],
        core_hook=logline,
        selling_points=["强钩子开局", "核心冲突可视化", "阶段兑现清晰"],
        target_platform=["通用平台"],
        target_reader_age="18-30",
        total_chapters_planned=total,
        chapter_words_target=per_chapter,
        estimated_words=total * per_chapter,
        tone="快节奏、强冲突",
        person="第三人称",
        style="短句推进，画面感优先",
        conflict=bible["mainline"],
        suspense="主角能否在代价失控前完成目标",
        subplots=["主角与旧关系的修复", "对手阵营内部的权力更替"],
        supporting="引路人",
        antagonist="幕后对手",
        foreshadow_text="前 3 章埋下的异常细节在后文回收",
        places="主舞台与边缘地带",
        items_text="关键道具沿主线节点流转",
        terms="核心术语与规则在首章交代",
        timeline="按章推进，关键节点落在章末钩子",
        map_text="世界层 / 区域层 / 场景层",
        theme_core=theme,
        theme_statement=theme,
        innovation_points=["把核心能力做成可验证的规则"],
        comparative_titles=[],
        ending_type="阶段胜利 + 新局开启",
        ending_state="新秩序建立，旧问题留下尾巴",
        protagonist_final_fate="带着新目标继续前行",
        taboos="不降智，不强行误会",
        update_frequency="日更",
        serialization_pace="每 3 章一个小高潮",
        content_rating="全年龄",
        series_plan="主线可收束，保留续作空间",
        keywords=["成长", "逆袭", "强钩子"],
        aigc_disclosure="AI 辅助创作，发布前请人工复核",
        status="连载中",
        genre_tone=payload.genre_name,
        audience=audience_text,
        book_summary=bible["synopsis"],
        beats=[chapter.summary[:60] for chapter in chapters[:6]],
    )


def _int(value, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _volumes_of(
    data: dict, fallback: OutlineOutput, chapters: list[OutlineChapter], payload: OutlineInput
) -> list[dict]:
    """优先采用模型分卷，但必须覆盖全部章节且区间连续，否则退回确定性分卷。"""
    raw = list_of_dicts(data.get("volumes"))
    computed = _build_volumes(chapters, payload)
    if not raw:
        return computed
    ordered = sorted(
        raw, key=lambda item: _int(item.get("no"), 0) or _int(item.get("chapter_from"), 0)
    )
    spans: list[tuple[int, int]] = []
    for item in ordered:
        start = _int(item.get("chapter_from"), -1)
        end = _int(item.get("chapter_to"), -1)
        if start < 1 or end < start or end > len(chapters):
            return computed
        spans.append((start, end))
    expect = 1
    for start, end in spans:
        if start != expect:
            return computed
        expect = end + 1
    if expect - 1 != len(chapters):
        return computed
    merged: list[dict] = []
    for index, item in enumerate(ordered):
        base = computed[index] if index < len(computed) else {}
        volume = dict(base)
        for key in (
            "title", "summary", "conflict", "theme", "core_event",
            "conflict_axis", "end_hook", "arc", "tension_profile",
        ):
            if text_of(item.get(key)):
                volume[key] = text_of(item.get(key))
        volume["no"] = index + 1
        volume["chapter_from"], volume["chapter_to"] = spans[index]
        merged.append(volume)
    return merged


def _texts(data: dict, key: str, limit: int = 12) -> list[str]:
    raw = data.get(key) or []
    if isinstance(raw, str):
        raw = [
            part.strip()
            for part in raw.replace("；", ";").replace("、", ",").replace("\n", ",").split(",")
        ]
    if not isinstance(raw, list):
        return []
    return [text_of(item) for item in raw if text_of(item)][:limit]


def _normalize(
    data: dict, fallback: OutlineOutput, total: int, payload: OutlineInput, *, stub: bool = False
) -> OutlineOutput:
    chapters = []
    for index, item in enumerate(list_of_dicts(data.get("chapters")), 1):
        chapters.append(
            OutlineChapter(
                chapter=index,
                title=text_of(item.get("title")) or f"第{index}章",
                summary=text_of(item.get("summary")) or "剧情推进。",
                key_events=[text_of(e) for e in (item.get("key_events") or []) if text_of(e)][:6],
                hook=text_of(item.get("hook")),
                # 叙事阶段用于分卷结构与节奏检查；模型缺失时按章序回退到模板
                arc=text_of(item.get("arc"))
                or ARC_TEMPLATES[(index - 1) % len(ARC_TEMPLATES)][0],
            )
        )
    if not chapters:
        return fallback
    chapters = chapters[:total]
    # 模型返回章数不足目标章数时，用确定性大纲补齐，避免用户设置的目标章数失效
    if len(chapters) < total:
        for index in range(len(chapters) + 1, total + 1):
            source = fallback.chapters[index - 1] if index - 1 < len(fallback.chapters) else None
            if source is None:
                arc, note = ARC_TEMPLATES[(index - 1) % len(ARC_TEMPLATES)]
                chapters.append(
                    OutlineChapter(
                        chapter=index,
                        title=f"第{index}章",
                        summary="剧情继续推进。",
                        key_events=[note],
                        hook="新的问题被抛出。",
                        arc=arc,
                    )
                )
            else:
                chapters.append(source.model_copy(update={"chapter": index}))
    logline_value = text_of(data.get("logline")) or fallback.logline
    theme_value = text_of(data.get("theme")) or fallback.theme
    base_signing = _signing_check(chapters, logline_value, theme_value)
    base_completeness = _completeness_check(chapters, logline_value, theme_value)
    opening = data.get("opening") if isinstance(data.get("opening"), dict) else {}
    opening = {
        "strategy": text_of(opening.get("strategy")) or fallback.opening.get("strategy", ""),
        "first_image": text_of(opening.get("first_image")) or fallback.opening.get("first_image", ""),
        "golden_finger_demo": _int(
            opening.get("golden_finger_demo"),
            _int(fallback.opening.get("golden_finger_demo")),
        ),
    }
    signing = data.get("signing_check") if isinstance(data.get("signing_check"), dict) else {}
    signing = {
        "score": _int(signing.get("score"), _int(base_signing.get("score", 0))),
        "risk": text_of(signing.get("risk")) or base_signing.get("risk", ""),
        "suggestions": [
            text_of(item) for item in (signing.get("suggestions") or []) if text_of(item)
        ] or base_signing.get("suggestions", []),
        "issues": [
            text_of(item) for item in (signing.get("issues") or []) if text_of(item)
        ] or base_signing.get("issues", []),
    }
    completeness = (
        data.get("completeness_check")
        if isinstance(data.get("completeness_check"), dict)
        else {}
    )
    completeness = {
        key: [text_of(item) for item in (completeness.get(key) or []) if text_of(item)]
        or base_completeness.get(key, [])
        for key in ("missing_fields", "unfilled_payoff", "unrecovered", "arc_missing", "no_hook")
    }
    per_chapter = _int(data.get("chapter_words_target"), fallback.chapter_words_target)
    total_planned = _int(data.get("total_chapters_planned"), fallback.total_chapters_planned) or total
    estimated = _int(data.get("estimated_words"), total_planned * per_chapter)
    bible = data.get("story_bible") if isinstance(data.get("story_bible"), dict) else fallback.story_bible
    book_summary = (
        text_of(data.get("book_summary"))
        or text_of(bible.get("synopsis"))
        or fallback.book_summary
    )

    def text_field(key: str) -> str:
        return text_of(data.get(key)) or (getattr(fallback, key) if stub else "")

    def list_field(key: str, limit: int = 12) -> list[str]:
        return _texts(data, key, limit) or (getattr(fallback, key) if stub else [])

    return OutlineOutput(
        logline=logline_value,
        theme=theme_value,
        story_bible=bible,
        chapters=chapters,
        volumes=_volumes_of(data, fallback, chapters, payload),
        opening=opening,
        worldview=list_of_dicts(data.get("worldview")) or fallback.worldview,
        map_levels=[text_of(item) for item in (data.get("map_levels") or []) if text_of(item)]
        or fallback.map_levels,
        map_regions=list_of_dicts(data.get("map_regions")) or fallback.map_regions,
        map_scenes=list_of_dicts(data.get("map_scenes")) or fallback.map_scenes,
        signing_check=signing,
        completeness_check=completeness,
        type_primary=text_of(data.get("type_primary")) or fallback.type_primary,
        type_secondary=list_field("type_secondary", 6),
        core_hook=text_of(data.get("core_hook")) or logline_value,
        selling_points=list_field("selling_points", 6),
        target_platform=list_field("target_platform", 4),
        target_reader_age=text_of(data.get("target_reader_age")) or fallback.target_reader_age,
        total_chapters_planned=total_planned,
        chapter_words_target=per_chapter,
        estimated_words=estimated,
        tone=text_field("tone"),
        person=text_of(data.get("person")) or fallback.person,
        style=text_field("style"),
        conflict=text_of(data.get("conflict")) or text_of(bible.get("mainline")),
        suspense=text_field("suspense"),
        subplots=list_field("subplots", 8),
        supporting=text_field("supporting"),
        antagonist=text_field("antagonist"),
        foreshadow_text=text_field("foreshadow_text"),
        places=text_field("places"),
        items_text=text_field("items_text"),
        terms=text_field("terms"),
        timeline=text_field("timeline"),
        map_text=text_field("map_text"),
        theme_core=text_of(data.get("theme_core")) or theme_value,
        theme_statement=text_of(data.get("theme_statement")) or theme_value,
        innovation_points=list_field("innovation_points", 6),
        comparative_titles=list_field("comparative_titles", 6),
        ending_type=text_field("ending_type"),
        ending_state=text_field("ending_state"),
        protagonist_final_fate=text_field("protagonist_final_fate"),
        taboos=text_field("taboos"),
        update_frequency=text_field("update_frequency"),
        serialization_pace=text_field("serialization_pace"),
        content_rating=text_field("content_rating"),
        series_plan=text_field("series_plan"),
        keywords=list_field("keywords", 12),
        aigc_disclosure=text_of(data.get("aigc_disclosure"))
        or "AI 辅助创作，发布前请人工复核",
        status=text_of(data.get("status")) or fallback.status,
        genre_tone=fallback.genre_tone,
        audience=fallback.audience,
        book_summary=book_summary,
        beats=_texts(data, "beats", 20)
        or [chapter.summary[:60] for chapter in chapters[:6]],
    )


class OutlineSkill(BaseSkill):
    name = "outline"
    version = "1.0.0"
    input_model = OutlineInput
    output_model = OutlineOutput

    def run(self, payload: OutlineInput, ctx: SkillContext) -> OutlineOutput:
        fallback = _fallback(payload, stub=ctx.settings.model_stub)
        total = _total_of(payload)
        material = _material(payload)
        material_view = {
            "book_summary": text_of(material.get("book_summary"))[:300],
            "story_bible": material.get("story_bible") or {},
            "chapters": [
                {"title": c.get("title"), "summary": c.get("summary")} for c in list_of_dicts(material.get("chapters"), 12)
            ],
        }
        research_view = {
            "works": [w.get("title") for w in list_of_dicts(payload.research.get("works"), 4)],
            "takeaways": payload.research.get("takeaways") or [],
        }
        data = call_json(
            ctx,
            system=SYSTEM,
            user=PROMPT.format(
                title=payload.title,
                genre=payload.genre_name,
                audience="男频" if payload.audience == "male" else "女频",
                length="长篇" if payload.length == "long" else "短篇",
                brief=payload.brief or "无",
                research=json.dumps(research_view, ensure_ascii=False),
                material=json.dumps(material_view, ensure_ascii=False)[:8000],
                total=total,
            ),
        )
        result = _normalize(
            data,
            fallback,
            total,
            payload,
            stub=ctx.settings.model_stub,
        )
        ctx.log(
            f"大纲完成：{len(result.chapters)} 章 / {len(result.volumes)} 卷"
        )
        return result
