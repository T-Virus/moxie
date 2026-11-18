# -*- coding: utf-8 -*-
"""内置技能集合。每个技能都是纯函数式、强类型、可单测的。"""

from .adaptation import AdaptationSkill
from .base import BaseSkill
from .chapter_summarize import ChapterSummarizeSkill
from .chapter_write import ChapterWriteSkill
from .character_graph import CharacterGraphSkill
from .compliance_review import ComplianceReviewSkill
from .consistency_review import ConsistencyReviewSkill
from .continuity_check import ContinuityCheckSkill
from .cover_plan import CoverSkill
from .genre_research import GenreResearchSkill
from .humanizer import HumanizerSkill
from .lore_extract import LoreExtractSkill
from .outline import OutlineSkill
from .outline_decompose import OutlineDecomposeSkill
from .positioning import PositioningSkill
from .publish_pack import PublishPackSkill
from .review_merge import ReviewMergeSkill
from .settings_pack import SettingsPackSkill

__all__ = [
    "AdaptationSkill",
    "BaseSkill",
    "ChapterSummarizeSkill",
    "ChapterWriteSkill",
    "CharacterGraphSkill",
    "ComplianceReviewSkill",
    "ConsistencyReviewSkill",
    "ContinuityCheckSkill",
    "CoverSkill",
    "GenreResearchSkill",
    "HumanizerSkill",
    "LoreExtractSkill",
    "OutlineSkill",
    "OutlineDecomposeSkill",
    "PositioningSkill",
    "PublishPackSkill",
    "ReviewMergeSkill",
    "SettingsPackSkill",
]
