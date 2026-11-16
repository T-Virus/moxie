# -*- coding: utf-8 -*-
"""设定生成：基于定位卡先生成世界观 / 力量体系 / 势力 / 金手指，
再从设定派生角色卡与功法道具表、势力关系网。设定先行，大纲与正文只引用不另造。
"""

from __future__ import annotations

import json

from pydantic import Field

from ..contracts import SkillContext, StrictModel, call_json, list_of_dicts, text_of
from .base import BaseSkill


class SettingsInput(StrictModel):
    title: str = Field(min_length=1, max_length=120)
    genre_name: str = Field(min_length=1, max_length=60)
    positioning: dict = Field(default_factory=dict)
    research: dict = Field(default_factory=dict)


class FactionPack(StrictModel):
    name: str
    category: str = ""
    stance: str = ""
    desc: str = ""


class FactionRelation(StrictModel):
    source: str
    target: str
    kind: str = ""
    note: str = ""


class CharacterPack(StrictModel):
    name: str
    role: str = ""
    stance: str = ""
    personality: str = ""
    goal: str = ""
    arc: str = ""


class ItemPack(StrictModel):
    name: str
    kind: str = ""
    desc: str = ""
    owner: str = ""


class SettingsOutput(StrictModel):
    worldview: str = ""
    power_system: str = ""
    golden_finger: str = ""
    factions: list[FactionPack] = Field(default_factory=list)
    faction_relations: list[FactionRelation] = Field(default_factory=list)
    characters: list[CharacterPack] = Field(default_factory=list)
    items: list[ItemPack] = Field(default_factory=list)


SYSTEM = "你是网文世界观架构师，只输出 JSON；设定必须能直接支撑剧情冲突，不写百科式空话。"

PROMPT = """【技能 settings_pack】
书名：{title}　题材：{genre}

定位卡（用户已确认，必须遵守）：
{positioning}

题材校准结论：
{research}

请先生成世界观 / 力量体系 / 势力 / 金手指，再从这些设定派生角色与道具；
雷区必须规避，反套路空间要体现到金手指设计里。
输出 JSON：
{{"worldview":"世界观，2-4 句，含核心规则与主要矛盾",
 "power_system":"力量体系：等级/进阶路径/代价与限制",
 "golden_finger":"金手指：能力、来源、使用代价、成长空间与反套路点",
 "factions":[{{"name":"","category":"官方/宗门/财阀/民间等","stance":"对主角的态度","desc":""}}],
 "faction_relations":[{{"source":"","target":"","kind":"敌对/盟友/依附/制衡","note":""}}],
 "characters":[{{"name":"","role":"主角/重要配角/对手","stance":"","personality":"","goal":"","arc":"人物弧光"}}],
 "items":[{{"name":"","kind":"功法/道具/信物","desc":"","owner":""}}]}}
角色 4-6 个、势力 3-5 个、道具 3-5 个；名字必须原创，禁止与任何真实作品同名。
"""


def _fallback(payload: SettingsInput) -> SettingsOutput:
    positioning = payload.positioning or {}
    genre = payload.genre_name
    golden = text_of(positioning.get("summary")) or f"《{payload.title}》的核心能力"
    return SettingsOutput(
        worldview=(
            f"{genre}世界由一套显性规则维持秩序，规则背后藏着维持者与破坏者的长期博弈；"
            "主角所处的位置恰好是两种力量的交界处。"
        ),
        power_system="五级进阶，每级有明确代价：越强越接近规则本身，也越容易被规则反噬",
        golden_finger=f"{golden}：可验证、可成长、有代价；首次展示放在第一章",
        factions=[
            FactionPack(name="秩序维持方", category="官方", stance="表面拉拢、实际提防", desc="规则的执行者，也是主要压力来源"),
            FactionPack(name="规则破坏方", category="地下", stance="敌对", desc="用打破规则获利，与主角目标部分重合"),
            FactionPack(name="主角所属小团体", category="民间", stance="盟友", desc="弱者联盟，情绪爽点来源"),
        ],
        faction_relations=[
            FactionRelation(source="秩序维持方", target="规则破坏方", kind="制衡", note="长期明面博弈"),
            FactionRelation(source="主角所属小团体", target="秩序维持方", kind="依附", note="被迫挂靠，随时反水"),
            FactionRelation(source="主角所属小团体", target="规则破坏方", kind="敌对", note="目标重合但手段冲突"),
        ],
        characters=[
            CharacterPack(name="主角", role="主角", stance="被低估的强者", personality="先算后动，主动做决定", goal="在规则夹缝中拿到话语权", arc="从被动卷入到主动改写规则"),
            CharacterPack(name="引路人", role="重要配角", stance="盟友", personality="惜字如金，给关键线索不给答案", goal="找到能继承自己理念的人", arc="从旁观到托付"),
            CharacterPack(name="正面对手", role="对手", stance="敌对", personality="有明确目标与合理动机", goal="维持自己对规则的解释权", arc="从压制主角到被主角逼出真面目"),
            CharacterPack(name="同伴", role="重要配角", stance="盟友", personality="冲动但忠诚，负责情绪落点", goal="证明自己不是累赘", arc="从拖后腿到独当一面"),
        ],
        items=[
            ItemPack(name="关键信物", kind="信物", desc="贯穿主线的身份凭证，第一章出现", owner="主角"),
            ItemPack(name="代价道具", kind="道具", desc="每次使用都要付出明确代价", owner="主角"),
            ItemPack(name="对手的底牌", kind="道具", desc="反派压箱口的筹码，后期反转用", owner="正面对手"),
        ],
    )


class SettingsPackSkill(BaseSkill):
    name = "settings_pack"
    version = "1.0.0"
    input_model = SettingsInput
    output_model = SettingsOutput

    def run(self, payload: SettingsInput, ctx: SkillContext) -> SettingsOutput:
        fallback = _fallback(payload)
        positioning_view = {
            key: payload.positioning.get(key)
            for key in ("platform", "platform_direction", "genre_boundary", "emotional_tone", "summary")
            if text_of(payload.positioning.get(key))
        }
        research_view = {
            key: payload.research.get(key)
            for key in ("hooks", "highlight_types", "anti_cliche", "opening_pace")
            if payload.research.get(key)
        }
        data = call_json(
            ctx,
            system=SYSTEM,
            user=PROMPT.format(
                title=payload.title,
                genre=payload.genre_name,
                positioning=json.dumps(positioning_view, ensure_ascii=False)[:2500]
                or "未生成，按题材通用定位处理",
                research=json.dumps(research_view, ensure_ascii=False)[:2500] or "未生成",
            ),
        )

        def _packs(key: str, model, limit: int):
            rows = []
            fields = set(model.model_fields)
            for item in list_of_dicts(data.get(key), limit):
                name = text_of(item.get("name"))
                if not name:
                    continue
                clean = {k: v for k, v in item.items() if k in fields}
                clean["name"] = name[:40]
                rows.append(model(**clean))
            return rows

        result = SettingsOutput(
            worldview=text_of(data.get("worldview")) or fallback.worldview,
            power_system=text_of(data.get("power_system")) or fallback.power_system,
            golden_finger=text_of(data.get("golden_finger")) or fallback.golden_finger,
            factions=_packs("factions", FactionPack, 6) or fallback.factions,
            faction_relations=(
                [
                    FactionRelation(
                        source=text_of(pair.get("source")),
                        target=text_of(pair.get("target")),
                        kind=text_of(pair.get("kind")),
                        note=text_of(pair.get("note"))[:120],
                    )
                    for pair in list_of_dicts(data.get("faction_relations"), 10)
                    if text_of(pair.get("source")) and text_of(pair.get("target"))
                ]
                or fallback.faction_relations
            ),
            characters=_packs("characters", CharacterPack, 8) or fallback.characters,
            items=_packs("items", ItemPack, 8) or fallback.items,
        )
        ctx.log(
            f"设定生成完成：角色 {len(result.characters)} / 势力 {len(result.factions)} / 道具 {len(result.items)}"
        )
        return result
