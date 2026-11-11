# -*- coding: utf-8 -*-
"""设定抽取：统一产出角色卡、势力表与道具功法。

输入可来自拆解/改编结果、章节正文与大纲；模型输出缺失时以确定性结构兜底，
保证工作台「角色 / 势力 / 道具功法」三个页签始终有数据可渲染。
"""

from __future__ import annotations

import json

from pydantic import Field

from ..contracts import SkillContext, StrictModel, call_json, list_of_dicts, text_of
from .base import BaseSkill

SYSTEM = "你是故事设定编辑，只输出 JSON。"
PROMPT = """【技能 lore_extract】
书名：{title}　题材：{genre}
请基于设定库、章节正文与大纲抽取角色卡、势力表与道具功法，字段必须齐全。
无法确定的可选字段留空，不要编造。
输出 JSON：
{{"characters":[{{"name":"","alias":"","gender":"","age":null,"role":"主角/配角/反派","affiliation":"","identity":"","personality":"","appearance":"","goal":"","arc":"","arc_detail":{{"type":"","start_state":"","turning_points":[],"end_state":"","final_fate":""}},"pov_chapters":[],"relations":[{{"target":"","type":""}}],"first_chapter":1}}],
 "factions":[{{"name":"","type":"门派/家族/组织/国家","category":"","leader":"","members":[],"territory":"","stance":"正/邪/中立","goal":"","relations":[{{"target":"","type":"","strength":0.5,"public":true}}],"first_chapter":1}}],
 "items":[{{"name":"","category":"道具/功法/武器/丹药/其他","grade":"","owner":"","holder":"","faction":"","effect":"","cost":"","origin":"","payoff":"","chapters":[],"first_chapter":1,"notes":""}}]}}
设定库：{bible}
角色：{characters}
势力：{factions}
道具：{items}
章节：{chapters}
"""

CATEGORY_MAP = {
    "武器": "武器",
    "weapon": "武器",
    "功法": "功法",
    "skill": "功法",
    "丹药": "丹药",
    "pill": "丹药",
    "道具": "道具",
    "item": "道具",
}

ARC_TYPES = {"主角": "成长型", "配角": "守护型", "反派": "堕落型"}


def _int(value, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _num(value, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _stages(text: str) -> list[str]:
    for sep in ("→", "->", "—>", "=>"):
        if sep in text:
            return [part.strip() for part in text.split(sep) if part.strip()]
    return [part.strip() for part in text.replace("，", ",").split(",") if part.strip()]


def _arc_of(item: dict, role: str, *, stub: bool) -> tuple[dict, dict]:
    """返回 (arc 对象, arc_detail 对象)。

    client 的映射层读取 `characters[].arc` 若为对象则渲染为弧光详情，
    因此这里同时把结构化弧光写入 `arc` 与 `arc_detail`，保持字段名一致。
    """
    raw = item.get("arc")
    detail = item.get("arc_detail")
    base = raw if isinstance(raw, dict) else (detail if isinstance(detail, dict) else {})
    text = "" if isinstance(raw, dict) else text_of(raw)
    if not text and isinstance(detail, dict):
        text = text_of(detail.get("summary"))
    structured = {
        "type": text_of(base.get("type")) or (ARC_TYPES.get(role, "成长型") if stub else ""),
        "start_state": text_of(base.get("start_state")) or text_of(base.get("startState")),
        "turning_points": [
            text_of(point)
            for point in (base.get("turning_points") or base.get("turningPoints") or [])
            if text_of(point)
        ],
        "end_state": text_of(base.get("end_state")) or text_of(base.get("endState")),
        "final_fate": text_of(base.get("final_fate")) or text_of(base.get("finalFate")),
    }
    stages = _stages(text) if text else []
    if stages:
        structured["start_state"] = structured["start_state"] or stages[0]
        structured["turning_points"] = structured["turning_points"] or stages[1:-1]
        if len(stages) > 1:
            structured["end_state"] = structured["end_state"] or stages[-1]
    if stub:
        structured["start_state"] = structured["start_state"] or "被动卷入"
        structured["turning_points"] = structured["turning_points"] or ["主动选择", "付出代价"]
        structured["end_state"] = structured["end_state"] or "完成阶段目标"
        structured["final_fate"] = structured["final_fate"] or "带着新目标继续前行"
    if not any(structured.values()):
        return {}, {}
    return structured, structured


def _first_chapter(item: dict, default: int = 1) -> int:
    try:
        return max(1, int(item.get("first_chapter") or default))
    except (TypeError, ValueError):
        return default


def _normalize_character(
    item: dict, index: int, *, stub: bool = False, total_chapters: int = 3
) -> dict:
    name = text_of(item.get("name")) or f"角色{index}"
    roles = ["主角", "配角", "反派"]
    role = text_of(item.get("role")) or roles[(index - 1) % len(roles)]
    relations = []
    for rel in item.get("relations") or []:
        if not isinstance(rel, dict):
            continue
        target = text_of(rel.get("target")) or text_of(rel.get("name"))
        if target:
            relations.append({"target": target, "type": text_of(rel.get("type")) or text_of(rel.get("kind")) or "关联"})
    first = _first_chapter(item)
    age = _int(item.get("age"), -1)
    if age < 0 and stub:
        age = {"主角": 24, "配角": 30, "反派": 38}.get(role, 26)
    pov = item.get("pov_chapters") or item.get("povChapters") or []
    pov_chapters = [_int(no) for no in pov if _int(no) > 0] if isinstance(pov, list) else []
    if not pov_chapters and stub and total_chapters > 0:
        if role == "主角":
            pov_chapters = list(range(first, total_chapters + 1))
        else:
            pov_chapters = [first]
    arc, arc_detail = _arc_of(item, role, stub=stub)
    return {
        "name": name,
        "alias": text_of(item.get("alias")) or text_of(item.get("aliases")),
        "gender": text_of(item.get("gender")) or "未知",
        "age": age if age >= 0 else None,
        "role": role,
        "affiliation": text_of(item.get("affiliation")) or text_of(item.get("faction")) or "无",
        "identity": text_of(item.get("identity")) or text_of(item.get("title")) or role,
        "personality": text_of(item.get("personality")) or "谨慎、目标明确",
        "appearance": text_of(item.get("appearance")) or "外形与身份相符，出场时带有明显辨识度",
        "goal": text_of(item.get("goal")) or "在核心冲突中保住自己想要的东西",
        # client 将对象形式的 arc 渲染为弧光详情，同时保留 arc_detail 供其他端读取
        "arc": arc,
        "arc_detail": arc_detail,
        "pov_chapters": pov_chapters,
        "relations": relations,
        "first_chapter": first,
    }


def _normalize_faction(
    item: dict, index: int, *, stub: bool = False, total_chapters: int = 3
) -> dict:
    name = text_of(item.get("name")) or f"势力{index}"
    members = [text_of(m) for m in (item.get("members") or []) if text_of(m)]
    faction_type = text_of(item.get("type")) or text_of(item.get("category")) or "组织"
    category = text_of(item.get("category")) or faction_type
    relations = []
    for rel in item.get("relations") or []:
        if not isinstance(rel, dict) or not text_of(rel.get("target")):
            continue
        strength = _num(rel.get("strength"), -1.0)
        public = rel.get("public")
        relations.append(
            {
                "target": text_of(rel.get("target")),
                "type": text_of(rel.get("type")) or "关联",
                "strength": max(0.0, min(1.0, strength)) if strength >= 0 else None,
                "public": public if isinstance(public, bool) else None,
            }
        )
    if stub and not relations and index <= 2:
        relations = [
            {
                "target": "与之竞争的另一方",
                "type": "敌对" if index == 1 else "对立",
                "strength": 0.7,
                "public": True,
            }
        ]
    return {
        "name": name,
        "type": faction_type,
        "category": category,
        "leader": text_of(item.get("leader")) or (members[0] if members else "未知"),
        "members": members,
        "territory": text_of(item.get("territory")) or "核心冲突发生地",
        "stance": text_of(item.get("stance")) or "中立",
        "goal": text_of(item.get("goal")) or "维持或改变现有秩序",
        "relations": relations,
        "first_chapter": _first_chapter(item),
    }


def _normalize_item(
    item: dict, index: int, *, stub: bool = False, total_chapters: int = 3
) -> dict:
    name = text_of(item.get("name")) or f"道具{index}"
    raw_category = text_of(item.get("category")) or text_of(item.get("kind")) or "道具"
    first = _first_chapter(item)
    owner = text_of(item.get("owner")) or "主角"
    chapters = item.get("chapters") or []
    chapter_list = [_int(no) for no in chapters if _int(no) > 0] if isinstance(chapters, list) else []
    if not chapter_list and total_chapters > 0:
        chapter_list = list(range(first, min(total_chapters, first + 1) + 1))
    return {
        "name": name,
        "category": CATEGORY_MAP.get(raw_category.lower(), CATEGORY_MAP.get(raw_category, raw_category)),
        "grade": text_of(item.get("grade")) or "未定阶",
        "owner": owner,
        "holder": text_of(item.get("holder")) or owner,
        "faction": text_of(item.get("faction")) or text_of(item.get("affiliation")) or ("主角阵营" if stub else ""),
        "effect": text_of(item.get("effect")) or text_of(item.get("desc")) or "推动关键线索，改变局面走向",
        "cost": text_of(item.get("cost")) or "使用一次需要付出相应代价",
        "origin": text_of(item.get("origin"))
        or ("来自一段未被公开的旧案" if stub else ""),
        "payoff": text_of(item.get("payoff"))
        or ("在后续关键节点决定局面走向" if stub else ""),
        "chapters": chapter_list,
        "first_chapter": first,
        "notes": text_of(item.get("notes")) or "首次出现即与主线冲突相关",
    }


def _fallback(
    payload: "LoreExtractInput", *, stub: bool, total_chapters: int
) -> tuple[list[dict], list[dict], list[dict]]:
    characters = [
        _normalize_character(dict(c), i, stub=stub, total_chapters=total_chapters)
        for i, c in enumerate(payload.characters, 1)
    ]
    if not characters:
        characters = [
            _normalize_character(
                {"name": "主角", "role": "主角", "personality": "谨慎、目标明确"},
                1,
                stub=stub,
                total_chapters=total_chapters,
            ),
            _normalize_character(
                {"name": "引路人", "role": "配角", "personality": "话少、掌握关键信息"},
                2,
                stub=stub,
                total_chapters=total_chapters,
            ),
            _normalize_character(
                {"name": "幕后对手", "role": "反派", "personality": "强势、善于布局"},
                3,
                stub=stub,
                total_chapters=total_chapters,
            ),
        ]
    factions = [
        _normalize_faction(dict(f), i, stub=stub, total_chapters=total_chapters)
        for i, f in enumerate(payload.factions, 1)
    ]
    if not factions:
        factions = [
            _normalize_faction(
                {"name": "主角阵营", "type": "组织", "stance": "正", "leader": "主角"},
                1,
                stub=stub,
                total_chapters=total_chapters,
            ),
            _normalize_faction(
                {"name": "既得利益方", "type": "组织", "stance": "邪"},
                2,
                stub=stub,
                total_chapters=total_chapters,
            ),
        ]
    items = [
        _normalize_item(dict(it), i, stub=stub, total_chapters=total_chapters)
        for i, it in enumerate(payload.items, 1)
    ]
    if not items:
        items = [
            _normalize_item(
                {"name": "无名信件", "category": "道具", "owner": "主角", "first_chapter": 1},
                1,
                stub=stub,
                total_chapters=total_chapters,
            ),
            _normalize_item(
                {"name": "旧钥匙", "category": "道具", "owner": "主角", "first_chapter": 2},
                2,
                stub=stub,
                total_chapters=total_chapters,
            ),
            _normalize_item(
                {"name": "残缺名单", "category": "其他", "owner": "未知", "first_chapter": 3},
                3,
                stub=stub,
                total_chapters=total_chapters,
            ),
        ]
    return characters, factions, items


class LoreExtractInput(StrictModel):
    title: str = Field(min_length=1, max_length=120)
    genre_name: str = Field(default="通用", max_length=60)
    story_bible: dict = Field(default_factory=dict)
    characters: list[dict] = Field(default_factory=list)
    factions: list[dict] = Field(default_factory=list)
    items: list[dict] = Field(default_factory=list)
    chapters: list[dict] = Field(default_factory=list)
    outline: list[dict] = Field(default_factory=list)


class LoreExtractOutput(StrictModel):
    characters: list[dict] = Field(default_factory=list)
    factions: list[dict] = Field(default_factory=list)
    items: list[dict] = Field(default_factory=list)


class LoreExtractSkill(BaseSkill):
    name = "lore_extract"
    version = "1.0.0"
    input_model = LoreExtractInput
    output_model = LoreExtractOutput

    def run(self, payload: LoreExtractInput, ctx: SkillContext) -> LoreExtractOutput:
        stub = ctx.settings.model_stub
        total_chapters = len(list_of_dicts(payload.chapters)) or len(list_of_dicts(payload.outline))
        fallback_characters, fallback_factions, fallback_items = _fallback(
            payload, stub=stub, total_chapters=total_chapters
        )
        data = call_json(
            ctx,
            system=SYSTEM,
            user=PROMPT.format(
                title=payload.title,
                genre=payload.genre_name,
                bible=json.dumps(payload.story_bible, ensure_ascii=False)[:3000],
                characters=json.dumps(payload.characters, ensure_ascii=False)[:3000],
                factions=json.dumps(payload.factions, ensure_ascii=False)[:2000],
                items=json.dumps(payload.items, ensure_ascii=False)[:2000],
                chapters=json.dumps(
                    [
                        {
                            "chapter": c.get("chapter"),
                            "title": c.get("title"),
                            "summary": text_of(c.get("summary"))[:120],
                        }
                        for c in list_of_dicts(payload.chapters, 12)
                    ],
                    ensure_ascii=False,
                )[:4000],
            ),
        )
        characters = [
            _normalize_character(dict(item), i, stub=stub, total_chapters=total_chapters)
            for i, item in enumerate([] if stub else list_of_dicts(data.get("characters")), 1)
        ] or fallback_characters
        factions = [
            _normalize_faction(dict(item), i, stub=stub, total_chapters=total_chapters)
            for i, item in enumerate([] if stub else list_of_dicts(data.get("factions")), 1)
        ] or fallback_factions
        items = [
            _normalize_item(dict(item), i, stub=stub, total_chapters=total_chapters)
            for i, item in enumerate([] if stub else list_of_dicts(data.get("items")), 1)
        ] or fallback_items
        ctx.log(f"设定抽取完成：角色 {len(characters)}，势力 {len(factions)}，道具功法 {len(items)}")
        return LoreExtractOutput(characters=characters, factions=factions, items=items)
