# -*- coding: utf-8 -*-
"""内置技能集合。每个技能都是纯函数式、强类型、可单测的。"""

from .adaptation import AdaptationSkill
from .base import BaseSkill
from .chapter_expand import ChapterExpandSkill
from .chapter_summarize import ChapterSummarizeSkill
from .chapter_write import ChapterWriteSkill
from .character_graph import CharacterGraphSkill
from .genre_research import GenreResearchSkill
from .hot_preview import HotPreviewSkill
from .lore_extract import LoreExtractSkill
from .outline import OutlineSkill
from .outline_decompose import OutlineDecomposeSkill
from .review import ReviewSkill

__all__ = [
    "AdaptationSkill",
    "BaseSkill",
    "ChapterExpandSkill",
    "ChapterSummarizeSkill",
    "ChapterWriteSkill",
    "CharacterGraphSkill",
    "GenreResearchSkill",
    "HotPreviewSkill",
    "LoreExtractSkill",
    "OutlineSkill",
    "OutlineDecomposeSkill",
    "ReviewSkill",
]
