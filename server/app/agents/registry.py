# -*- coding: utf-8 -*-
"""技能注册表：名称 → 技能实例，版本随技能类声明。"""

from __future__ import annotations

from .skills.adaptation import AdaptationSkill
from .skills.base import BaseSkill
from .skills.chapter_expand import ChapterExpandSkill
from .skills.chapter_summarize import ChapterSummarizeSkill
from .skills.chapter_write import ChapterWriteSkill
from .skills.character_graph import CharacterGraphSkill
from .skills.genre_research import GenreResearchSkill
from .skills.hot_preview import HotPreviewSkill
from .skills.lore_extract import LoreExtractSkill
from .skills.outline import OutlineSkill
from .skills.outline_decompose import OutlineDecomposeSkill
from .skills.review import ReviewSkill


class SkillRegistry:
    def __init__(self) -> None:
        self._skills: dict[str, BaseSkill] = {}

    def register(self, skill: BaseSkill) -> None:
        if not skill.name:
            raise ValueError("skill 必须有 name")
        self._skills[skill.name] = skill

    def get(self, name: str) -> BaseSkill:
        skill = self._skills.get(name)
        if skill is None:
            raise KeyError(f"未注册的技能：{name}")
        return skill

    def replace(self, skill: BaseSkill) -> BaseSkill | None:
        previous = self._skills.get(skill.name)
        self._skills[skill.name] = skill
        return previous

    def catalog(self) -> list[dict]:
        return [
            {
                "name": skill.name,
                "version": skill.version,
                "input": skill.input_model.__name__ if skill.input_model else None,
                "output": skill.output_model.__name__ if skill.output_model else None,
            }
            for skill in sorted(self._skills.values(), key=lambda item: item.name)
        ]


def build_registry() -> SkillRegistry:
    registry = SkillRegistry()
    for skill in (
        GenreResearchSkill(),
        OutlineDecomposeSkill(),
        AdaptationSkill(),
        OutlineSkill(),
        ChapterExpandSkill(),
        ChapterWriteSkill(),
        ChapterSummarizeSkill(),
        HotPreviewSkill(),
        CharacterGraphSkill(),
        LoreExtractSkill(),
        ReviewSkill(),
    ):
        registry.register(skill)
    return registry


registry = build_registry()
