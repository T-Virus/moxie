# -*- coding: utf-8 -*-
"""角色/势力/关系图谱：输出可直接渲染的节点与关系边。"""

from __future__ import annotations

import json

from pydantic import Field

from ..contracts import SkillContext, StrictModel, call_json, list_of_dicts, text_of
from .base import BaseSkill


class CharacterGraphInput(StrictModel):
    title: str = Field(min_length=1, max_length=120)
    story_bible: dict = Field(default_factory=dict)
    characters: list[dict] = Field(default_factory=list)
    factions: list[dict] = Field(default_factory=list)
    chapters: list[dict] = Field(default_factory=list)


class Relation(StrictModel):
    source: str
    target: str
    kind: str
    note: str = ""


class CharacterGraphOutput(StrictModel):
    story_bible: dict = Field(default_factory=dict)
    characters: list[dict] = Field(default_factory=list)
    factions: list[dict] = Field(default_factory=list)
    relations: list[Relation] = Field(default_factory=list)


SYSTEM = "你是故事设定编辑，只输出 JSON。"

PROMPT = """【技能 character_graph】
书名：{title}
请基于设定库与章节出场整理角色、势力与关系网。
输出 JSON：
{{"story_bible":{{}},
 "characters":[{{"name":"","role":"","stance":"","personality":"","faction":""}}],
 "factions":[{{"name":"","category":"","stance":""}}],
 "relations":[{{"source":"","target":"","kind":"盟友/对手/亲属/上下级","note":""}}]}}

设定库：{bible}
角色：{characters}
势力：{factions}
章节：{chapters}
"""


def _fallback(payload: CharacterGraphInput) -> CharacterGraphOutput:
    characters = [dict(c) for c in payload.characters if isinstance(c, dict)]
    factions = [dict(f) for f in payload.factions if isinstance(f, dict)]
    if not characters:
        characters = [
            {"name": "主角", "role": "主角", "stance": "正面", "personality": "谨慎、目标明确"},
            {"name": "引路人", "role": "导师", "stance": "中立", "personality": "话少、信息关键"},
            {"name": "对手", "role": "反派", "stance": "敌方", "personality": "强势、善于布局"},
        ]
    if not factions:
        factions = [
            {"name": "主角阵营", "category": "组织", "stance": "正面"},
            {"name": "既得利益方", "category": "组织", "stance": "敌方"},
        ]
    # 以章节出场共现构建关系边，保证图谱有可渲染的确定性结构
    relations: list[Relation] = []
    seen: set[tuple[str, str]] = set()
    for chapter in payload.chapters:
        roles = [text_of(r) for r in (chapter.get("roles") or []) if text_of(r)]
        for i in range(len(roles)):
            for j in range(i + 1, len(roles)):
                pair = (roles[i], roles[j])
                if pair in seen:
                    continue
                seen.add(pair)
                relations.append(
                    Relation(source=pair[0], target=pair[1], kind="同章出场", note=f"第{chapter.get('chapter', '?')}章")
                )
    if len(characters) >= 2:
        relations.insert(
            0,
            Relation(source=characters[0].get("name", "主角"), target=characters[-1].get("name", "对手"), kind="对手"),
        )
    return CharacterGraphOutput(
        story_bible=dict(payload.story_bible or {}),
        characters=characters,
        factions=factions,
        relations=relations[:40],
    )


class CharacterGraphSkill(BaseSkill):
    name = "character_graph"
    version = "1.0.0"
    input_model = CharacterGraphInput
    output_model = CharacterGraphOutput

    def run(self, payload: CharacterGraphInput, ctx: SkillContext) -> CharacterGraphOutput:
        fallback = _fallback(payload)
        data = call_json(
            ctx,
            system=SYSTEM,
            user=PROMPT.format(
                title=payload.title,
                bible=json.dumps(payload.story_bible, ensure_ascii=False)[:4000],
                characters=json.dumps(payload.characters, ensure_ascii=False)[:4000],
                factions=json.dumps(payload.factions, ensure_ascii=False)[:2000],
                chapters=json.dumps(
                    [{"chapter": c.get("chapter"), "roles": c.get("roles") or []} for c in payload.chapters],
                    ensure_ascii=False,
                )[:4000],
            ),
        )
        characters = list_of_dicts(data.get("characters")) or fallback.characters
        factions = list_of_dicts(data.get("factions")) or fallback.factions
        relations = []
        for item in list_of_dicts(data.get("relations")):
            source = text_of(item.get("source"))
            target = text_of(item.get("target"))
            if source and target:
                relations.append(
                    Relation(source=source, target=target, kind=text_of(item.get("kind")) or "关联", note=text_of(item.get("note")))
                )
        if not relations:
            relations = fallback.relations
        ctx.log(f"图谱完成：角色 {len(characters)}，势力 {len(factions)}，关系 {len(relations)}")
        return CharacterGraphOutput(
            story_bible=data.get("story_bible") if isinstance(data.get("story_bible"), dict) else fallback.story_bible,
            characters=characters,
            factions=factions,
            relations=relations[:60],
        )
