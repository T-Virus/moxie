# -*- coding: utf-8 -*-
"""写入一条「全字段」演示运行，用于界面样式核对。

用法（在 server 目录）：
    python scripts/seed_demo.py
    python scripts/seed_demo.py --database-url postgresql+psycopg://...

脚本是幂等的：固定 run_id / 账号，重复执行会覆盖旧演示数据。
演示账号：demo@moxie.app / demo1234
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

SERVER_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVER_DIR))

from sqlalchemy import delete, select  # noqa: E402
from sqlalchemy.engine import Engine  # noqa: E402
from sqlalchemy import create_engine, inspect  # noqa: E402

from app.config import Settings  # noqa: E402
from app.models import (  # noqa: E402
    Account,
    AgentRun,
    AgentRunEvent,
    AgentRunStep,
    Plan,
    Subscription,
)
from app.security import hash_password  # noqa: E402
from app.seed import ensure_credit_packs, ensure_plans  # noqa: E402

DEMO_EMAIL = "demo@moxie.app"
DEMO_PASSWORD = "demo1234"
RUN_ID = "d3a0f1e1-0000-4000-8000-000000000001"
TITLE = "全字段演示 · 山海照夜"


def _iso(dt: datetime) -> str:
    return dt.isoformat()


def build_outline(now: datetime) -> dict:
    story_bible = {
        "genre": "东方玄幻",
        "genre_tone": "东方玄幻 · 冷峻热血",
        "synopsis": "被逐出宗门的少年在雨夜捡到一枚会呼吸的青铜兽核，从此每夜都要与山海异兽谈一笔交易，而每一笔交易都要拿走他的一段记忆。",
        "audience": "男频 · 18-30 岁",
        "era": "架空 · 东岭",
        "world": "东岭群山压着归墟入口，山海异兽以契约为食。",
        "power": "照夜司以灯为器、兽核为契；契约越深，记忆越薄。",
        "protagonist": "林照，被逐外门弟子，谨慎记仇，心软。",
        "mainline": "林照从逐徒成长为照夜司执灯人，逐步揭开归墟真相。",
        "conflict": "青云宗要封山，照夜司要开门，归墟会要放兽。",
        "person": "第三人称限知",
        "style": "短句、冷色调、动作驱动",
        "book_summary": "少年林照被逐出青云宗，在雨夜捡到一枚会呼吸的青铜兽核。兽核替他挡下致命一击，也替他定下规矩：每夜一次交易，每次拿走一段记忆。为了查清父亲十年前失踪的真相，他进入照夜司，成为最年轻的执灯人。",
        "book_title": "山海照夜",
        "title_alternatives": ["夜行山海", "兽核契约"],
        "n_chapters": 5,
        "total_chapters_planned": 360,
        "chapter_words_target": 3300,
        "estimated_words": 1200000,
        "keywords": ["山海异兽", "契约", "宗门", "记忆代价"],
        "target_platform": ["起点中文网", "番茄小说"],
        "type_primary": "东方玄幻",
        "type_secondary": ["宗门", "异兽", "权谋"],
        "core_hook": "每夜与山海异兽做一笔交易，代价是失去一段记忆",
        "opening": {
            "strategy": "雨夜逐出宗门 + 兽核开口",
            "first_image": "雨幕里，少年把青铜兽核攥出血",
            "golden_finger_demo": 1,
        },
    }
    volumes = [
        {
            "no": 1,
            "title": "第一卷 夜雨入山海",
            "chapter_from": 1,
            "chapter_to": 2,
            "summary": "林照被逐出青云宗，在雨夜与青铜兽核定下第一笔交易，第一次听见山海的声音。",
            "conflict": "失去宗门身份与获得兽核力量之间的拉扯",
            "theme": "失去与获得",
            "core_event": "雨夜认主",
            "conflict_axis": "林照 vs 青云宗",
            "end_hook": "兽核说：今夜不要回家",
            "arc": "从被动逐出到主动选择",
            "tension_profile": "低开高走，第 2 章抬到第一个峰值",
        },
        {
            "no": 2,
            "title": "第二卷 照夜司",
            "chapter_from": 3,
            "chapter_to": 4,
            "summary": "林照进入照夜司，与苏晚搭档处理第一桩异兽交易案，沈无咎的影子开始出现。",
            "conflict": "照夜司的规矩与林照的私心",
            "theme": "规则与例外",
            "core_event": "第一场交易",
            "conflict_axis": "照夜司 vs 归墟会",
            "end_hook": "交易名单上出现父亲的名字",
            "arc": "从独行到结盟",
            "tension_profile": "双线并进，第 4 章收束到悬念",
        },
        {
            "no": 3,
            "title": "第三卷 归墟之门",
            "chapter_from": 5,
            "chapter_to": 5,
            "summary": "归墟渡口，林照必须在记忆与真相之间做出选择。",
            "conflict": "记住父亲还是守住照夜司",
            "theme": "记忆即身份",
            "core_event": "归墟开门",
            "conflict_axis": "林照 vs 自己",
            "end_hook": "门后传来父亲的声音",
            "arc": "从追问真相到承担代价",
            "tension_profile": "单章冲刺，结尾留白",
        },
    ]
    return {
        "logline": "被逐出宗门的少年在雨夜捡到一枚会呼吸的青铜兽核，从此每夜都要与山海异兽谈判。",
        "theme": "山海共生",
        "themes": ["成长", "共生", "代价"],
        "beats": [
            "第 1 章：雨夜被逐，兽核认主",
            "第 2 章：第一笔交易，记忆被拿走",
            "第 3 章：进入照夜司，遇到苏晚",
            "第 4 章：交易名单出现父亲的名字",
            "第 5 章：归墟渡口，真相与代价",
        ],
        "book_title": "山海照夜",
        "title_alternatives": ["夜行山海", "兽核契约"],
        "book_summary": story_bible["book_summary"],
        "author": "墨写演示",
        "status": "连载中",
        "era": "架空 · 东岭",
        "ai": True,
        "n_chapters": 5,
        "generated_at": _iso(now - timedelta(minutes=95)),
        "source_type": "原创",
        "language": "简体中文",
        "schema_version": "outline-2026-11",
        "rights_status": "原创",
        "opening": story_bible["opening"],
        "genre_tone": story_bible["genre_tone"],
        "synopsis": story_bible["synopsis"],
        "audience": story_bible["audience"],
        "type_primary": story_bible["type_primary"],
        "type_secondary": story_bible["type_secondary"],
        "core_hook": story_bible["core_hook"],
        "target_platform": story_bible["target_platform"],
        "platform_style": {
            "起点": "长线升级、章末钩子",
            "番茄": "快节奏、前三章反转",
        },
        "target_reader_age": "18-30",
        "target_reader_gender": "男性向",
        "estimated_words": 1200000,
        "length_class": "长篇",
        "total_chapters_planned": 360,
        "chapter_words_target": 3300,
        "serialization_pace": "日更 2 章",
        "update_frequency": "每日 20:00",
        "content_rating": "全年龄",
        "ending_type": "开放式",
        "series_plan": "三部曲",
        "keywords": ["山海异兽", "契约", "宗门", "记忆代价"],
        "aigc_disclosure": "AI 辅助生成大纲与初稿，人工精修",
        "person": "第三人称限知",
        "style": "短句、冷色调、动作驱动",
        "world": story_bible["world"],
        "power": story_bible["power"],
        "conflict": story_bible["conflict"],
        "suspense": "林照父亲十年前为何失踪，兽核为何认他为主。",
        "mainline": story_bible["mainline"],
        "taboos": "不写虐杀幼兽、不写无代价金手指",
        "subplots": "苏晚寻找失踪的师父；沈无咎借封山掩盖旧案。",
        "protagonist": story_bible["protagonist"],
        "supporting": "苏晚，照夜司巡夜人，嘴硬心软。",
        "antagonist": "沈无咎，青云宗执法长老，封山派首领。",
        "foreshadow": "青铜兽核的呼吸声与父亲留下的灯油气味一致。",
        "places": "青云宗、照夜司、归墟渡、雨夜旧城",
        "items": "青铜兽核、照夜刀、山海图残卷、无名信",
        "terms": "照夜司、执灯人、契兽、归墟、记忆税",
        "timeline": "开元十三年雨夜 → 三日后照夜司 → 第七夜归墟渡",
        "map": "东岭—皇城—归墟渡三点一线",
        "plot": {
            "timeline": ["开元十三年·雨夜逐出", "三日后·照夜司入职", "第七夜·归墟渡"],
            "mainline": ["被逐", "认主", "入司", "查案", "开门"],
            "subplots": ["苏晚寻师", "沈无咎封山", "老铜的记忆"],
            "conflict": ["林照与宗门", "照夜司与归墟会", "林照与自己的记忆"],
            "suspense": ["父亲下落", "兽核来历", "门后声音"],
            "foreshadow": ["父亲旧灯", "青铜兽核的呼吸", "名单上的名字"],
        },
        "worldview": [
            {
                "group": "力量体系",
                "points": [
                    {"text": "契兽以记忆为食，契约越深，记忆越薄", "chapters": [1, 2]},
                    {"text": "照夜灯可照出异兽真名", "chapters": [3, 4]},
                ],
            },
            {
                "group": "势力格局",
                "points": [
                    {"text": "青云宗封山，照夜司开门，归墟会放兽", "chapters": [3, 5]},
                ],
            },
            {
                "group": "地理",
                "points": [
                    {"text": "东岭压着归墟入口，皇城在中间", "chapters": [1, 5]},
                ],
            },
        ],
        "map_levels": ["东岭", "皇城", "归墟"],
        "map_regions": [
            {"name": "东岭", "kind": "山脉", "desc": "青云宗所在，终年雨雾", "chapters": [1, 2]},
            {"name": "皇城", "kind": "都城", "desc": "照夜司总部", "chapters": [3, 4]},
            {"name": "归墟渡", "kind": "渡口", "desc": "山海交界", "chapters": [5]},
            {"name": "雨夜旧城", "kind": "城区", "desc": "林照父亲失踪地", "chapters": [1, 5]},
        ],
        "map_scenes": [
            {
                "chapter": 1,
                "region": "东岭",
                "characters": ["林照", "沈无咎"],
                "factions": ["青云宗"],
                "items": ["青铜兽核"],
                "event": "林照被逐，雨夜捡到兽核",
            },
            {
                "chapter": 3,
                "region": "皇城",
                "characters": ["林照", "苏晚"],
                "factions": ["照夜司"],
                "items": ["照夜刀"],
                "event": "入职照夜司，接到第一桩交易案",
            },
            {
                "chapter": 5,
                "region": "归墟渡",
                "characters": ["林照", "苏晚", "老铜"],
                "factions": ["照夜司", "归墟会"],
                "items": ["青铜兽核", "山海图残卷"],
                "event": "归墟开门，林照做出选择",
            },
        ],
        "theme_core": "力量来自交换，成长来自承担",
        "theme_statement": "每一次索取都要付出记忆，真正的强大是记得自己为什么出发。",
        "selling_points": ["每夜交易", "记忆代价", "宗门权谋"],
        "innovation_points": ["异兽契约以记忆计价", "照夜司灯器体系"],
        "ending_type": "开放式",
        "comparative_titles": ["《夜航船》", "《山海秘闻》"],
        "ending_state": "归墟门半开，林照选择留下守灯",
        "protagonist_final_fate": "成为照夜司新一任守门人，忘记父亲的名字却记得那盏灯",
        "signing_check": {
            "score": 86,
            "risk": "低",
            "issues": ["第三章节奏略慢"],
            "suggestions": ["强化第三章交易冲突", "提前埋入沈无咎旧案"],
        },
        "completeness_check": {
            "missing_fields": ["第 6 卷大纲"],
            "unfilled_payoff": ["父亲旧案"],
            "unrecovered": ["青铜兽核来历"],
            "arc_missing": ["老铜"],
            "no_hook": ["第 4 章"],
        },
        "qa_score": 91,
        "volumes": volumes,
        "hooks": [
            {"chapter": 1, "text": "兽核在他掌心呼吸", "type": "悬念"},
            {"chapter": 3, "text": "名单上出现父亲的名字", "type": "反转"},
            {"chapter": 5, "text": "门后传来父亲的声音", "type": "钩子"},
        ],
        "setups": [
            {"chapter": 1, "text": "父亲留下的灯油", "type": "伏笔"},
            {"chapter": 2, "text": "老铜不愿提归墟", "type": "伏笔"},
        ],
        "payoffs": [
            {"chapter": 3, "text": "灯油气味与兽核一致", "type": "兑现"},
            {"chapter": 5, "text": "老铜身份揭晓", "type": "兑现"},
        ],
        "conflicts": [
            {"chapter": 2, "text": "林照第一次拒绝交易", "type": "冲突"},
            {"chapter": 4, "text": "沈无咎封锁照夜司", "type": "冲突"},
        ],
        "foreshadows": [
            {
                "text": "父亲留下的灯油",
                "seed": "第 1 章",
                "payoff": "第 7 章",
                "chapter": 1,
                "status": "未回收",
            },
            {
                "text": "青铜兽核的来历",
                "seed": "第 2 章",
                "payoff": "第 5 章",
                "chapter": 2,
                "status": "部分回收",
            },
        ],
        "timeEvents": [
            {"chapter": 1, "text": "开元十三年 · 雨夜"},
            {"chapter": 3, "text": "三日后 · 照夜司"},
            {"chapter": 5, "text": "第七夜 · 归墟渡", "is_volume": True},
        ],
        "emotionCurve": [
            {"chapter": 1, "tension": 4, "emotion": "压抑", "hook": "兽核呼吸"},
            {"chapter": 2, "tension": 7, "emotion": "惊惧", "hook": "第一笔交易"},
            {"chapter": 3, "tension": 6, "emotion": "戒备", "hook": "名单上的名字"},
            {"chapter": 4, "tension": 8, "emotion": "愤怒", "hook": "沈无咎出手"},
            {"chapter": 5, "tension": 9, "emotion": "决绝", "hook": "门后声音"},
        ],
        "itemLinks": [
            {"item": "青铜兽核", "from": "归墟", "to": "林照", "note": "认主", "chapter": 1},
            {"item": "照夜刀", "from": "照夜司", "to": "苏晚", "note": "配发", "chapter": 3},
            {"item": "山海图残卷", "from": "青云宗", "to": "沈无咎", "note": "私藏", "chapter": 4},
        ],
        "chapters": [
            {"chapter": 1, "title": "夜雨出宗", "summary": "林照被逐，捡到兽核", "key_events": ["逐出宗门", "兽核认主"], "hook": "兽核开口", "arc": "起"},
            {"chapter": 2, "title": "会呼吸的兽核", "summary": "第一笔交易", "key_events": ["记忆被拿走", "老铜出现"], "hook": "今夜不要回家", "arc": "承"},
            {"chapter": 3, "title": "第一场交易", "summary": "进入照夜司", "key_events": ["入职", "苏晚搭档"], "hook": "名单上的名字", "arc": "转"},
            {"chapter": 4, "title": "山海来客", "summary": "沈无咎封锁照夜司", "key_events": ["封司", "旧案浮现"], "hook": "父亲的名字", "arc": "转"},
            {"chapter": 5, "title": "照夜司", "summary": "归墟开门", "key_events": ["开门", "选择", "守灯"], "hook": "门后声音", "arc": "合"},
        ],
        "story_bible": story_bible,
    }


def _chapter_rows() -> tuple[list[dict], list[dict]]:
    chapters = [
        {
            "chapter": 1,
            "chapter_id": "ch-001",
            "title": "夜雨出宗",
            "scene": "青云宗山门 · 雨夜",
            "summary": "林照被逐出青云宗，在雨夜山门前捡到一枚会呼吸的青铜兽核。",
            "content": "雨下得像有人在倒扣整座山。\n林照跪在山门前，听执法长老念完最后一句逐令。青铜令牌落地，碎成两半。\n“从今夜起，你不再是青云宗弟子。”\n他没有争辩，只把散落的行李一件件塞回包袱。起身时，脚边多了一枚青铜兽核，正随着雨声一呼一吸。\n林照把它攥进掌心，指缝立刻渗出血。\n兽核里传来一个很老的声音：“今夜，不要回家。”",
            "word_count": 186,
            "conflict": "林照被逐，失去宗门身份",
            "hook": "兽核开口，今夜不要回家",
            "hook_type": "悬念",
            "emotion": "压抑",
            "tension": 4,
            "payoff": "林照第一次做出选择",
            "setup": "父亲留下的旧灯",
            "arc": "起",
            "key_events": ["沈无咎宣读逐令", "林照捡到青铜兽核", "兽核开口"],
            "points": ["雨夜", "逐出宗门", "兽核认主"],
            "roles": ["林照", "沈无咎"],
            "factions": ["青云宗"],
            "items": ["青铜兽核"],
            "chapter_function": "建立主角困境",
            "chapter_goal": "让林照失去宗门身份",
            "beat_type": "开篇",
            "pov": "林照",
            "time_span": "一夜",
            "word_target": 3500,
            "word_actual": 186,
            "payoff_type": "情绪释放",
            "payoff_owner": "林照",
            "payoff_intensity": 7,
            "tear_point": "令牌碎裂",
            "sweet_point": "兽核认主",
            "twist": "兽核主动开口",
            "new_characters": ["林照", "沈无咎"],
            "new_items": ["青铜兽核"],
            "new_settings": ["青云宗", "照夜司"],
            "foreshadow_ids": ["f-101"],
            "continuity_check": "与后文雨夜时间线一致",
            "chapter_status": "定稿",
            "revision_note": "加强雨夜氛围与逐令细节",
        },
        {
            "chapter": 2,
            "chapter_id": "ch-002",
            "title": "会呼吸的兽核",
            "scene": "雨夜旧城 · 破庙",
            "summary": "林照与兽核完成第一笔交易，以一段记忆换取活下去的机会。",
            "content": "破庙漏雨，香案上供着半截没有脸的神像。\n兽核在掌心发烫，声音贴着骨头响：“借你一段记忆，换你一条命。”\n林照问：“哪一段？”\n“最不重要的那一段。”\n他想起母亲的脸，想起父亲离家那天的灯油味，最后说：“拿走吧。”\n雨停时，他已经想不起母亲姓什么。庙门口多了一个佝偻的老人，自称老铜，正笑眯眯地看着他手里的兽核。",
            "word_count": 164,
            "conflict": "林照必须在记忆与生存之间交易",
            "hook": "老铜出现，知道兽核的来历",
            "hook_type": "人物钩子",
            "emotion": "惊惧",
            "tension": 7,
            "payoff": "林照活下来",
            "setup": "母亲的脸被拿走",
            "arc": "承",
            "key_events": ["第一笔交易", "记忆被拿走", "老铜出现"],
            "points": ["记忆交易", "代价", "老铜登场"],
            "roles": ["林照", "老铜"],
            "factions": [],
            "items": ["青铜兽核"],
            "chapter_function": "展示金手指代价",
            "chapter_goal": "让读者理解记忆税规则",
            "beat_type": "激励事件",
            "pov": "林照",
            "time_span": "一夜",
            "word_target": 3500,
            "word_actual": 164,
            "payoff_type": "规则展示",
            "payoff_owner": "林照",
            "payoff_intensity": 6,
            "tear_point": "忘记母亲姓氏",
            "sweet_point": "绝境翻盘",
            "twist": "老铜认识兽核",
            "new_characters": ["老铜"],
            "new_items": [],
            "new_settings": ["记忆税"],
            "foreshadow_ids": ["f-102"],
            "continuity_check": "记忆缺失与第 5 章呼应",
            "chapter_status": "定稿",
            "revision_note": "交易台词再压缩",
        },
        {
            "chapter": 3,
            "chapter_id": "ch-003",
            "title": "第一场交易",
            "scene": "皇城 · 照夜司",
            "summary": "林照进入照夜司，与苏晚搭档处理第一桩异兽交易案。",
            "content": "照夜司的门比青云宗矮，却更冷。\n苏晚把一盏青灯推到他面前：“执灯人第一课，先学会看影子。”\n灯亮起，墙上浮出一头没有角的兽影。林照掌心的兽核突然安静下来，像在听。\n“它想要什么？”苏晚问。\n“它想回家。”林照说。\n苏晚看了他很久，才在案卷上写下两个字：可谈。",
            "word_count": 142,
            "conflict": "照夜司的规矩与林照的私心",
            "hook": "交易名单上出现父亲的名字",
            "hook_type": "反转",
            "emotion": "戒备",
            "tension": 6,
            "payoff": "林照获得照夜司身份",
            "setup": "青灯与影子",
            "arc": "转",
            "key_events": ["入职照夜司", "第一次看影子", "名单出现父亲名字"],
            "points": ["入职", "苏晚搭档", "名单伏笔"],
            "roles": ["林照", "苏晚"],
            "factions": ["照夜司"],
            "items": ["照夜刀", "青铜兽核"],
            "chapter_function": "引入新阵营",
            "chapter_goal": "让林照进入照夜司",
            "beat_type": "第一转折点",
            "pov": "林照",
            "time_span": "三日后",
            "word_target": 3300,
            "word_actual": 142,
            "payoff_type": "身份升级",
            "payoff_owner": "林照",
            "payoff_intensity": 5,
            "tear_point": "",
            "sweet_point": "看影子",
            "twist": "名单上的名字",
            "new_characters": ["苏晚"],
            "new_items": ["照夜刀"],
            "new_settings": ["照夜司", "执灯人"],
            "foreshadow_ids": ["f-103"],
            "continuity_check": "与第 1 章雨夜相隔三日",
            "chapter_status": "定稿",
            "revision_note": "名单出场再提前半页",
        },
        {
            "chapter": 4,
            "chapter_id": "ch-004",
            "title": "山海来客",
            "scene": "皇城 · 照夜司地牢",
            "summary": "沈无咎封锁照夜司，林照在旧案卷宗里发现父亲的名字。",
            "content": "沈无咎带来的是封条，不是刀。\n“归墟异动，照夜司暂停一切交易。”他站在地牢门口，目光落在林照掌心的兽核上，“尤其是你。”\n封条贴上时，苏晚把一卷旧案塞进林照怀里。夜里，他借着兽核的微光翻开，第一页只有一行字：\n开元三年，执灯人林渡，失踪于归墟渡。\n林渡，是他父亲的名字。",
            "word_count": 137,
            "conflict": "沈无咎封锁照夜司，林照被迫转入暗线",
            "hook": "父亲的名字出现在旧案里",
            "hook_type": "身份钩子",
            "emotion": "愤怒",
            "tension": 8,
            "payoff": "旧案线索浮出",
            "setup": "林渡失踪",
            "arc": "转",
            "key_events": ["封司", "旧案卷宗", "父亲名字"],
            "points": ["封司", "旧案", "父子线"],
            "roles": ["林照", "苏晚", "沈无咎"],
            "factions": ["照夜司", "青云宗"],
            "items": ["山海图残卷"],
            "chapter_function": "抬升对抗",
            "chapter_goal": "把宗门与照夜司的冲突推到台面",
            "beat_type": "中点",
            "pov": "林照",
            "time_span": "当夜",
            "word_target": 3300,
            "word_actual": 137,
            "payoff_type": "信息兑现",
            "payoff_owner": "林照",
            "payoff_intensity": 8,
            "tear_point": "父亲名字",
            "sweet_point": "",
            "twist": "沈无咎早就知道",
            "new_characters": [],
            "new_items": ["山海图残卷"],
            "new_settings": ["照夜司地牢"],
            "foreshadow_ids": ["f-104"],
            "continuity_check": "旧案年份与第 1 章灯油呼应",
            "chapter_status": "待精修",
            "revision_note": "地牢对峙增加一个动作细节",
        },
        {
            "chapter": 5,
            "chapter_id": "ch-005",
            "title": "照夜司",
            "scene": "归墟渡 · 夜",
            "summary": "归墟开门，林照在记忆与真相之间做出选择，成为新的守灯人。",
            "content": "归墟渡没有水，只有一层向下的雾。\n门开的时候，林照听见父亲的声音从雾里传来：“别进来。”\n兽核在他掌心剧烈跳动，老铜站在身后，第一次没有笑。\n“进去，你能拿回所有记忆；留下，你只能守住这盏灯。”\n林照把灯举高。灯光照过雾面，照出一张和自己很像的脸。\n他说：“我记得他为什么不回家。”\n门缓缓合上。照夜司的灯，从此换了一个人守。",
            "word_count": 164,
            "conflict": "记住父亲还是守住照夜司",
            "hook": "门后传来父亲的声音",
            "hook_type": "情感钩子",
            "emotion": "决绝",
            "tension": 9,
            "payoff": "林照完成选择",
            "setup": "守灯人身份",
            "arc": "合",
            "key_events": ["归墟开门", "父亲声音", "林照守灯"],
            "points": ["开门", "选择", "守灯"],
            "roles": ["林照", "老铜", "苏晚"],
            "factions": ["照夜司", "归墟会"],
            "items": ["青铜兽核", "照夜刀"],
            "chapter_function": "收束本卷",
            "chapter_goal": "完成林照的身份转变",
            "beat_type": "高潮",
            "pov": "林照",
            "time_span": "第七夜",
            "word_target": 3600,
            "word_actual": 164,
            "payoff_type": "情感兑现",
            "payoff_owner": "林照",
            "payoff_intensity": 9,
            "tear_point": "父亲的声音",
            "sweet_point": "",
            "twist": "守灯人换人",
            "new_characters": [],
            "new_items": [],
            "new_settings": ["归墟门", "守灯人"],
            "foreshadow_ids": ["f-105"],
            "continuity_check": "与第 2 章记忆缺失一致",
            "chapter_status": "定稿",
            "revision_note": "结尾留白再收半句",
        },
    ]
    summaries = [
        {
            "chapter": row["chapter"],
            "title": row["title"],
            "summary": row["summary"],
            "conflict": row["conflict"],
            "hook": row["hook"],
            "word_count": row["word_count"],
            **{
                key: row[key]
                for key in (
                    "chapter_id",
                    "scene",
                    "key_events",
                    "points",
                    "roles",
                    "factions",
                    "items",
                    "hook_type",
                    "emotion",
                    "tension",
                    "payoff",
                    "setup",
                    "arc",
                    "chapter_function",
                    "chapter_goal",
                    "beat_type",
                    "pov",
                    "time_span",
                    "word_target",
                    "word_actual",
                    "payoff_type",
                    "payoff_owner",
                    "payoff_intensity",
                    "tear_point",
                    "sweet_point",
                    "twist",
                    "new_characters",
                    "new_items",
                    "new_settings",
                    "foreshadow_ids",
                    "continuity_check",
                    "chapter_status",
                    "revision_note",
                )
            },
        }
        for row in chapters
    ]
    return chapters, summaries


CHARACTERS = [
    {
        "name": "林照",
        "alias": "阿照",
        "role": "主角",
        "identity": "青云宗外门弟子（已逐出）",
        "type": "主角",
        "gender": "male",
        "age": 18,
        "camp": "照夜司",
        "stance": "正",
        "faction": "照夜司",
        "factionName": "照夜司",
        "factionCategory": "官方机构",
        "subFaction": "执灯人",
        "personality": "谨慎、记仇、心软",
        "goal": "查清父亲十年前失踪的真相",
        "core_desire": "被记得",
        "core_fear": "忘记重要的人",
        "first_chapter": 1,
        "join_chapter": 1,
        "leave_chapter": None,
        "loyalty": 0.72,
        "relations": [
            {"target": "苏晚", "type": "搭档"},
            {"target": "沈无咎", "type": "宿敌"},
            {"target": "林渡", "type": "父子"},
        ],
        "description": "被逐出青云宗的少年，掌心有一枚会呼吸的青铜兽核。",
        "race": "人族",
        "alignment": "中立善良",
        "relation_to": "苏晚",
        "relation_type": "搭档",
        "relation_direction": "双向",
        "relation_strength": 0.6,
        "relation_public": True,
        "relation_chapter": 3,
        "speech": "短句，先问代价",
        "catchwords": "先说代价。",
        "weakness": "对亲近的人狠不下心",
        "appearance": "清瘦，左手掌心有兽核留下的青铜纹",
        "quirks": ["数雨滴", "把灯芯剪得很短"],
        "strengths": ["观察力强", "能忍"],
        "flaws": ["记仇", "不肯求助"],
        "backstory": "父亲林渡是照夜司执灯人，十年前失踪于归墟渡。",
        "secret": "他已经忘记母亲的名字",
        "arc": {
            "type": "正向成长",
            "start_state": "被逐出宗门的弃徒",
            "turning_points": ["兽核认主", "进入照夜司", "归墟开门"],
            "end_state": "照夜司守灯人",
            "final_fate": "留在归墟守灯",
        },
        "obstacle_methods": ["谈判", "借势", "以记忆为筹码"],
        "exit_reason": "",
        "voice_sample": ["先说代价。", "我记得他为什么不回家。"],
        "pov_chapters": [1, 2, 3, 4, 5],
        "tags": ["主角", "执灯人", "兽核"],
    },
    {
        "name": "苏晚",
        "alias": "晚姐",
        "role": "配角",
        "identity": "照夜司巡夜人",
        "type": "关键配角",
        "gender": "female",
        "age": 21,
        "camp": "照夜司",
        "stance": "正",
        "faction": "照夜司",
        "factionName": "照夜司",
        "factionCategory": "官方机构",
        "subFaction": "巡夜组",
        "personality": "嘴硬心软，规矩优先",
        "goal": "找回失踪的师父",
        "core_desire": "守住照夜司",
        "core_fear": "再次失去同伴",
        "first_chapter": 3,
        "join_chapter": 3,
        "loyalty": 0.9,
        "relations": [
            {"target": "林照", "type": "搭档"},
            {"target": "苏无涯", "type": "师徒"},
        ],
        "description": "照夜司最年轻的巡夜人，青灯不离手。",
        "race": "人族",
        "alignment": "守序中立",
        "relation_to": "林照",
        "relation_type": "搭档",
        "relation_direction": "双向",
        "relation_strength": 0.6,
        "relation_public": True,
        "relation_chapter": 3,
        "speech": "干脆，带命令句",
        "catchwords": "先看影子。",
        "weakness": "不肯承认害怕",
        "appearance": "高马尾，右眉有一道旧疤",
        "quirks": ["擦灯罩", "记人名"],
        "strengths": ["执行力", "刀法"],
        "flaws": ["固执"],
        "backstory": "师父在归墟渡失踪，她因此加入巡夜组。",
        "secret": "她见过林渡最后一面",
        "arc": {
            "type": "解开心结",
            "start_state": "只信规矩",
            "turning_points": ["与林照搭档", "发现师父旧案"],
            "end_state": "学会变通",
            "final_fate": "接任巡夜长",
        },
        "obstacle_methods": ["查案", "动刀", "守灯"],
        "voice_sample": ["先看影子。", "规矩不是用来害人的。"],
        "pov_chapters": [3],
        "tags": ["女主", "照夜司", "巡夜人"],
    },
    {
        "name": "沈无咎",
        "alias": "沈执法",
        "role": "反派",
        "identity": "青云宗执法长老",
        "type": "主要反派",
        "gender": "male",
        "age": 46,
        "camp": "青云宗",
        "stance": "邪",
        "faction": "青云宗",
        "factionName": "青云宗",
        "factionCategory": "宗门",
        "subFaction": "执法堂",
        "personality": "克制、算计、极重秩序",
        "goal": "封死归墟，掩盖旧案",
        "core_desire": "维持秩序",
        "core_fear": "旧案翻案",
        "first_chapter": 1,
        "join_chapter": 1,
        "loyalty": 0.95,
        "relations": [
            {"target": "林照", "type": "宿敌"},
            {"target": "林渡", "type": "旧友"},
        ],
        "description": "青云宗执法长老，封山派首领，知道归墟的真相。",
        "race": "人族",
        "alignment": "守序邪恶",
        "relation_to": "林照",
        "relation_type": "宿敌",
        "relation_direction": "单向",
        "relation_strength": 0.8,
        "relation_public": False,
        "relation_chapter": 1,
        "speech": "慢，少用形容词",
        "catchwords": "山门不可开。",
        "weakness": "不愿承认自己错了",
        "appearance": "灰袍，左手缺一指",
        "quirks": ["摩挲断指", "看人不看眼"],
        "strengths": ["布局", "剑法"],
        "flaws": ["多疑"],
        "backstory": "十年前与林渡一同进入归墟，只有他活着回来。",
        "secret": "林渡是他亲手关在门后的",
        "arc": {
            "type": "反向堕落",
            "start_state": "秩序的守护者",
            "turning_points": ["封山", "旧案暴露"],
            "end_state": "被秩序反噬",
            "final_fate": "失踪于归墟",
        },
        "obstacle_methods": ["封司", "借刀", "封锁消息"],
        "voice_sample": ["山门不可开。", "你父亲当年也这么说。"],
        "pov_chapters": [4],
        "tags": ["反派", "执法长老", "封山派"],
    },
    {
        "name": "老铜",
        "alias": "铜爷",
        "role": "配角",
        "identity": "兽核器灵",
        "type": "神秘配角",
        "gender": "unknown",
        "age": 0,
        "camp": "中立",
        "stance": "中立",
        "faction": "",
        "factionName": "",
        "factionCategory": "",
        "subFaction": "",
        "personality": "玩世不恭，半真半假",
        "goal": "找回自己的身体",
        "core_desire": "回到归墟",
        "core_fear": "被遗忘",
        "first_chapter": 2,
        "join_chapter": 2,
        "loyalty": 0.3,
        "relations": [
            {"target": "林照", "type": "契约"},
            {"target": "林渡", "type": "故人"},
        ],
        "description": "住在青铜兽核里的老器灵，知道归墟的规矩。",
        "race": "器灵",
        "alignment": "绝对中立",
        "relation_to": "林照",
        "relation_type": "契约",
        "relation_direction": "单向",
        "relation_strength": 0.5,
        "relation_public": False,
        "relation_chapter": 2,
        "speech": "拖长音，爱打岔",
        "catchwords": "急什么。",
        "weakness": "不能离开兽核太久",
        "appearance": "半透明的小老头，铜绿色",
        "quirks": ["数记忆", "闻灯油"],
        "strengths": ["懂归墟", "会谈判"],
        "flaws": ["不说全话"],
        "backstory": "曾是归墟守门人，被剥去身体封入兽核。",
        "secret": "他认识林渡，也知道门后有什么",
        "arc": {
            "type": "真相揭示",
            "start_state": "装傻的器灵",
            "turning_points": ["第一次交易", "归墟开门"],
            "end_state": "恢复守门人身份",
            "final_fate": "回到归墟",
        },
        "obstacle_methods": ["交易", "隐瞒", "指路"],
        "voice_sample": ["急什么。", "记忆最不值钱，也最值钱。"],
        "pov_chapters": [],
        "tags": ["器灵", "归墟", "神秘"],
    },
]

FACTIONS = [
    {
        "name": "青云宗",
        "type": "门派",
        "category": "宗门",
        "leader": "掌门玄诚",
        "stance": "正",
        "territory": "东岭",
        "goal": "维持山海封印，封死归墟",
        "members_count": 3,
        "first_chapter": 1,
        "description": "东岭第一大宗，主张封山，内部由执法堂实际掌权。",
        "members": [
            {"name": "沈无咎", "role": "执法长老", "relation": "实际掌权"},
            {"name": "玄诚", "role": "掌门", "relation": "名义领袖"},
            {"name": "林照", "role": "前任外门弟子", "relation": "已逐出"},
        ],
        "rel_to": "照夜司",
        "rel_type": "合作",
        "rel_strength": 0.4,
        "rel_public": True,
        "relations": ["照夜司：合作", "归墟会：敌对"],
    },
    {
        "name": "照夜司",
        "type": "官方机构",
        "category": "官方机构",
        "leader": "司主苏无涯",
        "stance": "中立",
        "territory": "皇城",
        "goal": "收容异兽，维持人兽契约",
        "members_count": 3,
        "first_chapter": 3,
        "description": "皇城直属的异兽管理机构，执灯人以灯照出异兽真名。",
        "members": [
            {"name": "苏晚", "role": "巡夜人", "relation": "骨干"},
            {"name": "苏无涯", "role": "司主", "relation": "领袖"},
            {"name": "林照", "role": "执灯人", "relation": "新人"},
        ],
        "rel_to": "归墟会",
        "rel_type": "敌对",
        "rel_strength": 0.9,
        "rel_public": True,
        "relations": ["青云宗：合作", "归墟会：敌对"],
    },
    {
        "name": "归墟会",
        "type": "隐秘组织",
        "category": "隐秘组织",
        "leader": "无名氏",
        "stance": "邪",
        "territory": "归墟渡",
        "goal": "打开归墟，放异兽入世",
        "members_count": 2,
        "first_chapter": 4,
        "description": "藏在归墟渡口的隐秘组织，认为契约是对异兽的奴役。",
        "members": [
            {"name": "无名氏", "role": "会长", "relation": "首领"},
            {"name": "老铜", "role": "前任守门人", "relation": "叛逃"},
        ],
        "rel_to": "照夜司",
        "rel_type": "敌对",
        "rel_strength": 0.9,
        "rel_public": False,
        "relations": ["照夜司：敌对", "青云宗：敌对"],
    },
]

ITEMS = [
    {
        "name": "青铜兽核",
        "category": "道具",
        "grade": "天品",
        "owner": "归墟",
        "holder": "林照",
        "faction": "照夜司",
        "effect": "每夜可与山海异兽交易一次，交易内容由兽核判定。",
        "cost": "每次交易随机拿走持有者一段记忆。",
        "origin": "归墟门后，第一代守门人的心脏。",
        "note": "不可离身超过三日，否则器灵消散。",
        "first_chapter": 1,
        "chapters": [1, 2, 3, 4, 5],
        "description": "一枚会呼吸的青铜兽核，表面刻着看不懂的山海纹。",
        "payoff": "归墟开门的钥匙，也是林照父亲留下的最后线索。",
    },
    {
        "name": "照夜刀",
        "category": "兵器",
        "grade": "玄品",
        "owner": "照夜司",
        "holder": "苏晚",
        "faction": "照夜司",
        "effect": "刀身可映出异兽真名，斩断低级契约。",
        "cost": "每次出刀消耗灯油。",
        "origin": "照夜司工坊。",
        "note": "配发制式，刀柄刻有持有人编号。",
        "first_chapter": 3,
        "chapters": [3, 4, 5],
        "description": "窄刃短刀，刀背嵌着一枚青灯碎片。",
        "payoff": "第 5 章斩断归墟门的第一道锁。",
    },
    {
        "name": "山海图残卷",
        "category": "功法",
        "grade": "灵品",
        "owner": "青云宗",
        "holder": "沈无咎",
        "faction": "青云宗",
        "effect": "记录归墟水道与异兽真名，可推演契约路径。",
        "cost": "阅读者会被图中异兽注视。",
        "origin": "青云宗禁地。",
        "note": "残缺三页，缺的正是归墟门那一页。",
        "first_chapter": 4,
        "chapters": [4, 5],
        "description": "一卷兽皮图，边角被火烧过。",
        "payoff": "第 5 章林照用它找到归墟门的正确入口。",
    },
    {
        "name": "无名信",
        "category": "道具",
        "grade": "凡品",
        "owner": "",
        "holder": "林照",
        "faction": "",
        "effect": "信纸遇雨显字，只有一句话。",
        "cost": "",
        "origin": "雨夜旧城。",
        "note": "信末没有署名，只有一个灯油印。",
        "first_chapter": 1,
        "chapters": [1],
        "description": "一封没有署名的信，纸上有父亲常用的灯油味。",
        "payoff": "第 4 章确认是林渡留下的。",
    },
]


def seed(database_url: str | None) -> None:
    settings = Settings()
    url = database_url or settings.database_url
    engine: Engine = create_engine(url, future=True)
    if not inspect(engine).has_table("agent_runs"):
        raise SystemExit(
            f"数据库 {url} 缺少 agent_runs 表，请先在 server 目录执行：alembic upgrade head"
        )

    from sqlalchemy.orm import Session

    now = datetime.now(timezone.utc)
    chapters, summaries = _chapter_rows()
    outline = build_outline(now)

    with Session(engine, autoflush=False, expire_on_commit=False) as session:
        ensure_plans(session)
        ensure_credit_packs(session, settings.credit_pack_validity_days)
        session.flush()

        account = session.scalar(select(Account).where(Account.email == DEMO_EMAIL))
        if account is None:
            account = Account(email=DEMO_EMAIL, status="active", role="user")
            session.add(account)
            session.flush()
        account.password_hash = hash_password(DEMO_PASSWORD)
        account.status = "active"

        plan = session.scalar(select(Plan).where(Plan.code == "creator")) or session.scalar(
            select(Plan).order_by(Plan.id)
        )
        if plan is None:
            raise SystemExit("没有可用套餐，请先启动一次服务端以写入 plans 种子")
        sub = session.scalar(
            select(Subscription)
            .where(Subscription.account_id == account.id)
            .order_by(Subscription.id.desc())
        )
        if sub is None:
            sub = Subscription(
                account_id=account.id,
                plan_id=plan.id,
                status="active",
                seats=1,
                current_start_at=now - timedelta(days=7),
                current_end_at=now + timedelta(days=90),
                cancel_at_period_end=False,
                provider="mock",
            )
            session.add(sub)
        else:
            sub.plan_id = plan.id
            sub.status = "active"
            sub.current_start_at = now - timedelta(days=7)
            sub.current_end_at = now + timedelta(days=90)
            sub.cancel_at_period_end = False

        # 清理旧演示数据
        session.execute(delete(AgentRunStep).where(AgentRunStep.run_id == RUN_ID))
        session.execute(delete(AgentRunEvent).where(AgentRunEvent.run_id == RUN_ID))
        session.execute(delete(AgentRun).where(AgentRun.id == RUN_ID))

        started = now - timedelta(hours=3)
        run = AgentRun(
            id=RUN_ID,
            account_id=account.id,
            mode="custom",
            title=TITLE,
            audience="male",
            length="long",
            genre_id="xuanhuan",
            genre_name="东方玄幻",
            brief="被逐少年与山海异兽做交易，以记忆为代价查清父亲失踪真相。",
            status="succeeded",
            progress=100,
            current_stage="review",
            idempotency_key="seed-full-fields-v1",
            reserved_metric="books_month",
            reserved_quantity=1,
            tokens_total=128600,
            cost_cents=1280,
            meta={"demo": True, "source": "seed_demo.py"},
            created_at=started,
            started_at=started,
            finished_at=started + timedelta(minutes=95),
            updated_at=started + timedelta(minutes=95),
        )
        session.add(run)

        outputs = {
            "outline": outline,
            "chapter_expand": {"chapters": chapters},
            "chapter_summarize": {"chapters": summaries},
            "character_graph": {
                "characters": CHARACTERS,
                "factions": FACTIONS,
                "items": ITEMS,
                "relations": [
                    {"source": "林照", "target": "苏晚", "type": "搭档"},
                    {"source": "林照", "target": "沈无咎", "type": "宿敌"},
                ],
            },
            "review": {
                "score": 92,
                "risk": "低",
                "issues": ["第 4 章信息密度偏高"],
                "suggestions": ["把旧案拆成两段揭示"],
            },
        }
        for index, (node_key, output) in enumerate(outputs.items()):
            node_start = started + timedelta(minutes=index * 18)
            node_end = node_start + timedelta(minutes=15)
            session.add(
                AgentRunStep(
                    run_id=RUN_ID,
                    node_key=node_key,
                    status="done",
                    attempts=1,
                    output=output,
                    meta={"demo": True},
                    started_at=node_start,
                    finished_at=node_end,
                    updated_at=node_end,
                )
            )

        session.commit()

    engine.dispose()
    print(f"[ok] 演示运行已写入：{RUN_ID}")
    print(f"     标题：{TITLE}")
    print(f"     账号：{DEMO_EMAIL} / {DEMO_PASSWORD}")
    print(f"     数据库：{url}")


def main() -> None:
    parser = argparse.ArgumentParser(description="写入全字段演示运行")
    parser.add_argument("--database-url", default="", help="覆盖 DATABASE_URL")
    args = parser.parse_args()
    seed(args.database_url or None)


if __name__ == "__main__":
    main()
