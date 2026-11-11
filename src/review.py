# -*- coding: utf-8 -*-
"""
AI 审查
========
对单章正文做「只诊断、不改写」的审查，产出 Markdown / HTML / JSON 三种报告。

输入：
  · book_id      当前所选书（data/<书名>/）
  · chapter_no   所选章节号（第 N 章 / N / 章节数据里的顺序号）
  · chapter_text 粘贴或上传的单章正文

后端自动加载比对基准（缺哪项就跳过并标注，绝不硬凑）：
  · 本书简介 / 大纲   chapters.json → story_bible.synopsis（退回 decomposed.json.book_summary）
  · 本章概览          chapters.json → chapters[i].summary / points / scene / roles
  · 角色卡 / 势力卡   story_bible 里解析出的人物卡片 / 势力卡片
  · 名词 / 道具 / 地点 / 禁忌  story_bible 的 terms / items / places / taboos 等字段

处理流水线：
  1) 分段分句 → 稳定句子 ID（P01-S01，纯由文本顺序决定，可复现）+ 真实行号
  2) AI 味诊断（只出问题清单，不改写）
  3) 主题偏离检测：以「本书简介 + 本章概览」为基准 → 无 / 轻 / 中 / 重 + 依据 quote
  4) 错别字检测：规则初筛 + 模型复核 → 疑似错字 / 位置 / 建议写法
  5) 设定 / 剧情一致性检测：有基准才做，无基准标注「未配置设定库，跳过」
  5b) 违规风险检测（过审相关）：规则初筛 + 模型复核 → 风险类 / 处置方向（删除细节·改成暗示·整段删）
  5c) 逻辑与连贯性检测：前后矛盾 / 时序因果 / 视角跳变 / 重复叙述 / 称谓混乱
  5d) 行文统计体检（纯程序、0 调用）：句长段长 / 对话占比 / 缓饰词·抽象词密度 /
      破折号括号 / 模板句式 / 开篇章末钩子 / 高频重复词
  6) 对 Top 问题生成正向 / 反向建议（默认仅 AI 味；--advice-scope all 覆盖全部问题类型）
  7) 引用校验：所有问题必须带 quote，程序逐条验证其确实出现在原文里
  8) 统一排序（严重度 → 类型 → 文中位置）+ 过审风险总览 + 手动修改清单
  9) 输出 Markdown / HTML / JSON

方便人工修正的设计：
  · 每条问题都带「句子 ID + 真实行号 + 原文 + 上一句/下一句」，能直接跳到编辑器对应位置
  · 每条问题都带一句「怎么改」的可执行动作（只说方向，不给成稿）
  · 报告末尾给出按文中位置排序的可勾选修改清单，从上往下改完勾一条
  · 体检项全部是程序算的，改完再跑一次能直接看数值有没有变好

明确不做（报告里也会写明）：
  · 不自动改写正文
  · 不生成替换段落 / 替换句
  · 不承诺绕过任何检测器或平台审核

用法（一般由控制台「⑥ AI 审查」页调用，这里保留命令行入口便于排查）：
  python review.py --book 我的书 --chapter-no 12 --text-file input/ch12.txt
  python review.py --book 我的书 --chapter-no 12 --text-file ch12.txt --checks ai_taste,typo
  python review.py --book 我的书 --chapter-no 12 --text-file ch12.txt --dry-run
"""

import argparse
import html
import json
import os
import re
import sys
from datetime import datetime

from deepseek_common import (DEFAULT_BASE_URL, DEFAULT_MODEL, JsonParseError,
                            OutputTruncated, chat_json, resolve_base_url)
from story_bible import parse as parse_story_bible
from paths import ROOT, book_chapters, book_decomposed, book_dir, resolve

# ---------------------------------------------------------------- 常量
SYSTEM_PROMPT = "你是中文网文资深责编，只做诊断、不做改写。只输出 JSON，不要任何额外解释，不要 Markdown 代码块。"

DISCLAIMER = ("本报告只做诊断：不改写正文、不生成替换段落或替换句，只指出「哪里有问题 + 该往哪个方向改」。"
              "「AI 味」是对行文风格的判断，「过审风险」是对平台常见拒稿原因的经验性提示；"
              "两者都不等同、也不承诺通过或绕过任何检测器或平台审核。")

# 检查项：key → 展示名
CHECK_LABEL = {
    "ai_taste": "AI 味诊断",
    "theme": "主题偏离检测",
    "typo": "错别字检测",
    "consistency": "设定 / 剧情一致性检测",
    "risk": "违规风险检测（过审相关）",
    "logic": "逻辑与连贯性检测",
    "foreshadow": "伏笔 / 支线回收检测",
    "stats": "行文统计体检",
    "advice": "Top 问题建议生成",
}
ALL_CHECKS = ["ai_taste", "theme", "typo", "consistency", "risk", "logic",
              "foreshadow", "stats", "advice"]
# 纯程序、不调模型的检查项（用于估算调用次数；结果稳定可复现）
NO_CALL_CHECKS = {"stats"}

# 问题类型：key → 展示名（同时决定统一排序里的类型优先级）
TYPE_LABEL = {
    "risk": "违规风险",
    "logic": "逻辑连贯",
    "consistency": "设定 / 剧情一致性",
    "foreshadow": "伏笔 / 支线",
    "typo": "错别字",
    "theme": "主题偏离",
    "repeat": "重复用词",
    "ai_taste": "AI 味",
}
# 排序优先级：越靠前越影响过审与阅读体验
TYPE_PRIORITY = {"risk": 0, "logic": 1, "consistency": 2, "foreshadow": 3,
                 "typo": 4, "theme": 5, "repeat": 6, "ai_taste": 7}
# 问题 ID 前缀（报告里给每条问题一个稳定编号）
TYPE_CODE = {"risk": "R", "logic": "L", "consistency": "C", "foreshadow": "F",
             "typo": "T", "theme": "H", "repeat": "P", "ai_taste": "A"}
SEV_RANK = {"高": 3, "中": 2, "低": 1}
SEV_LABEL = ["高", "中", "低"]

# 建议范围：ai = 仅 AI 味（默认，与流水线第 6 步一致）；all = 覆盖全部问题类型
#（错别字 / 重复用词 / 设定一致性 / 伏笔这些也要能给正反建议，否则正文里最显眼的那几条永远没有建议）
ADVICE_SCOPES = {"ai": ["ai_taste"], "all": list(TYPE_LABEL)}
DEFAULT_ADVICE_SCOPE = "ai"
DEFAULT_TOP_N = 5
# 一次建议调用最多问几条问题：问太多会被模型输出上限截断，宁可分几批问
ADVICE_BATCH = 8
# 单章正文的可审查上限（超长章节先提示，避免把提示词撑爆）
MAX_TEXT_CHARS = 60_000
# 上下文记忆：审查时向前追溯的章节数（前情提要 / 伏笔回收比对）
PREV_CONTEXT = 5
# 向后看的章节数：只靠前文只能查「矛盾」，查不出「承上启下」——
# 本章有没有接住上一章的收尾、有没有为下一章留下过渡，必须同时看后文。
NEXT_CONTEXT = 2

SENT_END = "。！？!?…"
CLOSERS = "」』”’）)】》〉"
QUOTE_PAIRS = [("“", "”"), ("「", "」"), ("『", "』"), ("‘", "’")]

# 规则初筛：高置信度常见错别字（错 → 正）。命中后仍交给模型复核。
CONFUSIONS = {
    "做为": "作为", "按排": "安排", "报怨": "抱怨", "辩别": "辨别", "松驰": "松弛",
    "精萃": "精粹", "重迭": "重叠", "渡假": "度假", "幅射": "辐射", "凑和": "凑合",
    "既使": "即使", "迫不急待": "迫不及待", "一愁莫展": "一筹莫展", "谈笑风声": "谈笑风生",
    "走头无路": "走投无路", "再接再励": "再接再厉", "直接了当": "直截了当", "甘败下风": "甘拜下风",
    "自抱自弃": "自暴自弃", "一如继往": "一如既往", "默守成规": "墨守成规", "穿流不息": "川流不息",
    "一股作气": "一鼓作气", "悬梁刺骨": "悬梁刺股", "食不裹腹": "食不果腹", "一诺千斤": "一诺千金",
    "不径而走": "不胫而走", "烩炙人口": "脍炙人口", "床第之私": "床笫之私", "萎糜不振": "萎靡不振",
    "有持无恐": "有恃无恐", "额首称庆": "额手称庆", "不落巢臼": "不落窠臼", "鼎立相助": "鼎力相助",
    "黄梁美梦": "黄粱美梦", "美仑美奂": "美轮美奂", "蛛丝蚂迹": "蛛丝马迹", "姿意妄为": "恣意妄为",
    "灸手可热": "炙手可热", "滥芋充数": "滥竽充数", "世外桃园": "世外桃源", "名列前矛": "名列前茅",
    "脏款": "赃款", "渲泄": "宣泄", "寒喧": "寒暄", "弦律": "旋律", "膺品": "赝品",
    "蜇伏": "蛰伏", "装祯": "装帧", "坐阵": "坐镇", "编篡": "编纂", "沉缅": "沉湎",
    "嘻戏": "嬉戏", "陷井": "陷阱", "渲嚣": "喧嚣", "水笼头": "水龙头", "峻工": "竣工",
    "亲睐": "青睐", "趋之若骛": "趋之若鹜", "好高鹜远": "好高骛远", "洁白无暇": "洁白无瑕",
    "娇揉造作": "矫揉造作", "竭泽而鱼": "竭泽而渔", "禁若寒蝉": "噤若寒蝉", "开门缉盗": "开门揖盗",
}
# 叠字：只有这几个虚词叠用几乎必错（"爸爸/看看"这类是正常构词，不在表里）
DUP_WORDS = ["的的", "了了", "是是", "在在", "和和", "也也", "就就", "都都", "又又"]
# 连续重复标点（"！！""？！"属常见强调：！？等只报三连以上；全角句号两连即报）
RE_DUP_PUNC = re.compile(r"(。)\1{1,}|([，、；：！？])\2{2,}")
RE_HALF_PUNC = re.compile(r"(?<=[\u4e00-\u9fff])[,;:!?](?=[\u4e00-\u9fff])")

# ---- 过审相关：高风险信号初筛（只做候选，定性一律交给模型复核；误报会被复核掉）
RISK_RULES = [
    ("低俗擦边", re.compile(r"呻吟|娇喘|情欲|挑逗|缠绵|床笫|赤裸|裸露|色情|淫秽|亵渎")),
    ("血腥暴力", re.compile(r"血肉模糊|脑浆|内脏|断肢|残肢|开膛|肢解|虐杀|剥皮|挖眼|肠子|碎尸")),
    ("违法违禁", re.compile(r"冰毒|海洛因|摇头丸|大麻|毒品|贩毒|制毒|走私|枪支|炸药|雷管|管制刀具")),
    ("自残自杀", re.compile(r"割腕|自杀|跳楼|上吊|服毒|轻生|自残")),
    ("涉赌涉黄", re.compile(r"赌场|赌博|博彩|嫖娼|卖淫|赌注")),
    ("辱骂歧视", re.compile(r"傻[逼叉]|妈的|尼玛|脑残|婊子|贱种")),
]

# ---- 行文体检用的词表（程序统计密度，人工一眼能改）
ABSTRACT_WORDS = ["氛围感", "张力", "宿命感", "质感", "褶皱", "某种", "莫名", "微妙",
                  "不可名状", "缥缈", "虚无", "深邃", "悸动", "涟漪", "漩涡", "洪流", "荒诞"]
HEDGE_WORDS = ["微微", "轻轻", "缓缓", "淡淡", "似乎", "仿佛", "莫名", "不由得", "不禁",
               "隐隐", "略微", "些许", "几分", "一丝", "仿佛是", "好像"]
# 情绪张力：身体反应 / 冲突强度词（程序统计密度，作为质检代理指标）
EMOTION_WORDS = ["愤怒", "怒火", "恐惧", "惊恐", "慌张", "焦急", "紧张", "颤", "发抖", "冷汗",
                 "咬牙", "低吼", "嘶吼", "咆哮", "心跳", "窒息", "刺骨", "灼", "狠", "猛地",
                 "骤然", "陡然", "死死", "攥", "掐", "吼"]
RE_TEMPLATE = [
    ("「不是…而是…」句式", re.compile(r"不是[^。！？]{1,24}[，、][^。！？]{1,24}而是")),
    ("「这一刻他终于明白」", re.compile(r"这(一刻|一瞬间|一刹那|一瞬)[^。！？]{0,14}(终于|忽然|似乎)?明(白|悟)")),
    ("「一股…涌上心头」", re.compile(r"一股[^。！？]{0,12}(涌上心头|升起|蔓延|窜起)")),
    ("「三分…七分…」", re.compile(r"[三五七九]分[^。！？]{0,10}[三五七九]分")),
    ("「仿佛/似乎」连用", re.compile(r"(仿佛|似乎|好像)[^。！？]{0,12}(仿佛|似乎|好像)")),
]
RE_DASH = re.compile(r"——[^。！？\n]{1,40}")
RE_PAREN = re.compile(r"（[^）]{1,24}）|\([^)]{1,24}\)")
# 重复词统计里要剔除的虚词字符（避免 "的了""他的" 这类噪声）
REPEAT_STOP = set("的了是我在有和就不也都很又而那你我他她它们着过吗呢吧啊呀哦嗯上下里外中前后大小多少")


class StepError(Exception):
    """某一个检查环节失败（模型返回非法 JSON / 调用异常），不影响其它环节。"""


class Stopped(Exception):
    """用户点了「停止」：不是故障，只是提前中止（调用方应给中性提示，不要当错误弹红）。"""


# ---------------------------------------------------------------- 通用小工具
def _norm(v):
    return str(v or "").strip()


def _sev(v):
    """把模型给的各种严重度说法收敛成 高 / 中 / 低。"""
    s = _norm(v)
    if s in SEV_RANK:
        return s
    if "高" in s or "严重" in s or "strong" in s.lower():
        return "高"
    if "低" in s or "轻微" in s or "weak" in s.lower():
        return "低"
    return "中"


def _list(v):
    """模型偶尔返回字符串而不是数组，兜一下。"""
    if isinstance(v, list):
        return v
    if isinstance(v, dict):
        return [v]
    return []


def _sids(v, valid):
    out = []
    for s in _list(v):
        s = _norm(s)
        if s in valid:
            out.append(s)
    if not out and _norm(v):
        # 只给了一个字符串、里面可能写了多个 ID
        for s in re.findall(r"P\d+-S\d+", _norm(v)):
            if s in valid:
                out.append(s)
    return out


def read_text_file(path):
    """与拆解同源的多编码兜底读取。"""
    raw = open(path, "rb").read()
    for enc in ("utf-8-sig", "utf-8", "gb18030"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


# ---------------------------------------------------------------- 1. 分段分句
def _split_para(ptext, base):
    """把一段切成句子，返回 [(start, end, text)]（偏移为全文绝对偏移）。"""
    out = []
    i, n, start = 0, len(ptext), 0
    while i < n:
        if ptext[i] in SENT_END:
            j = i + 1
            while j < n and ptext[j] in CLOSERS:
                j += 1
            while j < n and ptext[j] in SENT_END:      # …… ！！ 这类连发标点算一句
                j += 1
                while j < n and ptext[j] in CLOSERS:
                    j += 1
            seg = ptext[start:j]
            if seg.strip():
                out.append((base + start, base + j, seg))
            i = start = j
        else:
            i += 1
    if start < n:
        seg = ptext[start:]
        if seg.strip():
            out.append((base + start, base + n, seg))
    return out


def split_segments(text):
    """分段 + 分句，生成稳定句子 ID。

    ID 形如 P01-S01（第 1 段第 1 句），完全由文本顺序决定：
    同一份正文无论跑多少次，ID 都一样，便于报告之间互相引用。
    """
    text = text or ""
    paragraphs, sentences = [], []
    off = 0
    pno = 0
    # 逐行走（而不是按 \n+ 切）：这样能给出真实行号，方便回编辑器里跳
    for lineno, raw_line in enumerate(text.split("\n"), 1):
        line = raw_line.strip()
        if not line:
            off += len(raw_line) + 1
            continue
        # 行内可能有前导空格，按实际出现位置定位
        delta = len(raw_line) - len(raw_line.lstrip())
        base = off + delta
        pno += 1
        pid = "P%02d" % pno
        paragraphs.append({"id": pid, "no": pno, "line": lineno, "start": base,
                           "end": base + len(line), "text": line})
        for sno, (s, e, seg) in enumerate(_split_para(line, base), 1):
            sentences.append({"id": "%s-S%02d" % (pid, sno), "para": pno, "no": sno, "line": lineno,
                              "start": s, "end": e, "text": seg})
        off += len(raw_line) + 1
    return paragraphs, sentences


def line_of(sentences, sids, offset=-1):
    """问题所在的行号：优先用句子 ID，其次用原文偏移回查。"""
    if sids:
        for s in sentences:
            if s["id"] == sids[0]:
                return s.get("line")
    if offset and offset >= 0:
        for s in sentences:
            if s["start"] <= offset < s["end"]:
                return s.get("line")
    return None


def _sid_contains(sentences, sid, quote):
    """模型回传的 sid 是否真的包含这段 quote（防止它给错位置）。"""
    for s in sentences:
        if s["id"] == sid:
            return quote in s["text"]
    return False


def context_of(sentences, sids):
    """取问题所在句的前后句，方便人工定位后通读上下文再改。"""
    if not sids:
        return {}
    idx = next((i for i, s in enumerate(sentences) if s["id"] == sids[0]), None)
    if idx is None:
        return {}
    return {
        "prev": sentences[idx - 1]["text"] if idx > 0 else "",
        "next": sentences[idx + 1]["text"] if idx + 1 < len(sentences) else "",
    }


def annotated_text(paragraphs, sentences):
    """给模型看的正文：带上句子 ID，便于它回传 sids。"""
    by_para = {}
    for s in sentences:
        by_para.setdefault(s["para"], []).append(s)
    return "\n\n".join(
        "\n".join("%s：%s" % (s["id"], s["text"]) for s in by_para.get(p["no"], []))
        for p in paragraphs)


# ---------------------------------------------------------------- 引用校验
_HARD_DROP = re.compile(r"[\s，。！？、；：\"'「」『』（）()《》〈〉…—\-·,.;:!?]")


def _hard(s):
    """去掉空白与全部标点后的极简形式，用于兜底比对。"""
    return _HARD_DROP.sub("", s or "")


def locate_span(text, quote, sentences=None, sids=None):
    """把 quote 定位到原文的真实起止下标 [start, end)，给前端做原文高亮。

    模型回传的 quote 常和原文有空白 / 全半角 / 标点差异，直接 str.find 会落空，
    所以逐级放宽：句内精确 → 全文精确 → 忽略空白 → 忽略空白与标点（字符映射回原位置）
    → 最后退回「整句」范围。只要 quote 能过引用校验，这里基本都能给出可高亮的区间。"""
    q = _norm(quote)
    if not text or not q:
        return None

    def _in_sentences():
        if not sentences or not sids:
            return None
        for s in sentences:
            if s["id"] in sids:
                k = text[s["start"]:s["end"]].find(q)
                if k >= 0:
                    return (s["start"] + k, s["start"] + k + len(q))
        return None

    # 1) 模型给了句子 ID：先在该句内找，同一句话里同一片段出现多次时更准
    hit = _in_sentences()
    if hit:
        return hit
    # 2) 全文精确
    i = text.find(q)
    if i >= 0:
        return (i, i + len(q))
    # 3) 忽略空白 / 标点：构造「原文字符下标映射」，把扁平化命中的位置还原成真实下标
    for drop_punct in (False, True):
        pos_map, buf = [], []
        for pos, ch in enumerate(text):
            if ch.isspace() or (drop_punct and _HARD_DROP.match(ch)):
                continue
            pos_map.append(pos)
            buf.append(ch)
        tgt = "".join(c for c in q
                      if not c.isspace() and not (drop_punct and _HARD_DROP.match(c)))
        flat = "".join(buf)
        if tgt:
            k = flat.find(tgt)
            if k >= 0:
                return (pos_map[k], pos_map[k + len(tgt) - 1] + 1)
    # 4) 兜底：整句标注，至少能跳到那一句
    if sentences and sids:
        for s in sentences:
            if s["id"] in sids:
                return (s["start"], s["end"])
    return None


def find_quote(text, quote):
    """验证 quote 确实出现在原文里；命中返回下标，否则 -1。"""
    q = _norm(quote)
    if not q:
        return -1
    i = text.find(q)
    if i >= 0:
        return i
    # 模型常带空白/全角半角差异：去掉空白再比
    flat_t = re.sub(r"\s+", "", text)
    flat_q = re.sub(r"\s+", "", q)
    if flat_q and flat_q in flat_t:
        return 0
    # 再放宽：忽略标点差异
    if _hard(q) and _hard(q) in _hard(text):
        return 0
    return -1


def quote_ok(text, quote):
    return find_quote(text, quote) >= 0


# ---------------------------------------------------------------- 基准加载
def _chapter_no_int(chapter_no):
    m = re.search(r"\d+", str(chapter_no or ""))
    return int(m.group(0)) if m else None


def find_chapter(chapters, chapter_no):
    """按章号在章节数据里定位本章：先认 chapter_id，再认顺序号。"""
    chapters = chapters or []
    n = _chapter_no_int(chapter_no)
    if n is None:
        return None
    want = {"第%d章" % n, "第 %d 章" % n, str(n)}
    for i, c in enumerate(chapters, 1):
        if _norm(c.get("chapter_id")) in want or str(c.get("no") or "") == str(n):
            return c
    if 1 <= n <= len(chapters):
        return chapters[n - 1]
    return None


def load_baseline(book, chapter_no):
    """从 data/<书名>/ 加载比对基准；缺什么就在 notes 里标注。"""
    data = {}
    try:
        with open(book_chapters(book), encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        data = {}
    # decomposed.json：书简介 + 结构化设定库 / 角色卡兜底（改编产物不一定重新生成设定库原文）
    dec = {}
    try:
        with open(book_decomposed(book), encoding="utf-8") as f:
            dec = json.load(f) or {}
    except (OSError, ValueError):
        dec = {}
    raw_sb = data.get("story_bible")
    if not (isinstance(raw_sb, str) and raw_sb.strip()) and not isinstance(raw_sb, dict):
        raw_sb = dec.get("story_bible") or ""
    fields, cards, factions = parse_story_bible(raw_sb or "")
    if not fields and isinstance(dec.get("story_bible"), dict):
        fields = dec.get("story_bible") or {}
    cards = cards or [c for c in (dec.get("characters") or []) if isinstance(c, dict)]
    factions = factions or [f for f in (dec.get("factions") or []) if isinstance(f, dict)]
    chapters = data.get("chapters") or []
    chapter = find_chapter(chapters, chapter_no)

    book_summary = _norm(dec.get("book_summary"))

    synopsis = _norm(fields.get("synopsis")) or book_summary
    ch_summary = _norm((chapter or {}).get("summary"))
    ch_points = [_norm(p) for p in ((chapter or {}).get("points") or []) if _norm(p)]
    ch_hook = _norm((chapter or {}).get("hook"))
    ch_conflict = _norm((chapter or {}).get("conflict"))
    # 情绪流基准：拆解时标好的「这一章该兑现什么、该埋在哪儿、该用什么钩子收尾」
    ch_emotion = _norm((chapter or {}).get("emotion"))
    ch_payoff = _norm((chapter or {}).get("payoff"))
    ch_setup = _norm((chapter or {}).get("setup"))
    ch_hook_type = _norm((chapter or {}).get("hook_type"))
    try:
        ch_tension = int((chapter or {}).get("tension") or 0)
    except (TypeError, ValueError):
        ch_tension = 0

    # 上下文记忆：最近已发生章节的摘要与章末悬念（供逻辑 / 伏笔检测比对）
    prev_chapters = []
    cur_no = _chapter_no_int(chapter_no)
    if cur_no is not None:
        for c in chapters:
            try:
                cn = int(c.get("no"))
            except (TypeError, ValueError):
                continue
            if cn >= cur_no:
                continue
            prev_chapters.append({
                "no": cn,
                "title": _norm(c.get("title")),
                "summary": _norm(c.get("summary")) or "；".join(
                    _norm(p) for p in (c.get("points") or []) if _norm(p)),
                "hook": _norm(c.get("hook")),
            })
        prev_chapters.sort(key=lambda x: x["no"])
        prev_chapters = prev_chapters[-PREV_CONTEXT:]

    # 后文概览：判断本章是否接得住下一章、有没有为后续留过渡（承上启下的「启下」半边）
    next_chapters = []
    if cur_no is not None:
        for c in chapters:
            try:
                cn = int(c.get("no"))
            except (TypeError, ValueError):
                continue
            if cn <= cur_no:
                continue
            next_chapters.append({
                "no": cn,
                "title": _norm(c.get("title")),
                "summary": _norm(c.get("summary")) or "；".join(
                    _norm(p) for p in (c.get("points") or []) if _norm(p)),
                "conflict": _norm(c.get("conflict")),
            })
        next_chapters.sort(key=lambda x: x["no"])
        next_chapters = next_chapters[:NEXT_CONTEXT]

    # 设定库：角色卡 / 势力卡 + 名词 / 道具 / 地点 / 禁忌等世界设定字段
    setting_fields = {k: _norm(fields.get(k)) for k in
                      ("terms", "items", "places", "taboos", "power", "world",
                       "protagonist", "supporting", "antagonist", "genre", "style", "person",
                       "timeline", "foreshadow", "mainline", "subplots", "suspense")}
    setting_fields = {k: v for k, v in setting_fields.items() if v}
    has_setting = bool(cards or factions or setting_fields)

    notes = []
    if not synopsis:
        notes.append("未配置本书简介 / 大纲（story_bible.synopsis），主题偏离检测的「全书基准」缺失")
    if not ch_summary and not ch_points:
        notes.append("未配置本章概览（chapter_summaries），主题偏离检测的「本章基准」缺失")
    if not cards:
        notes.append("未配置角色卡，一致性检测不做人物设定比对")
    if not factions:
        notes.append("未配置势力卡，一致性检测不做势力设定比对")
    if not setting_fields:
        notes.append("未配置名词 / 道具 / 地点 / 禁忌等世界设定字段")
    if cur_no and cur_no > 1 and not prev_chapters:
        notes.append("未加载到第 %s 章之前的章节摘要，逻辑 / 伏笔检测缺少前文记忆" % cur_no)
    if cur_no is not None and not next_chapters:
        notes.append("本章之后没有章节可对比：「启下 / 承接下一章」一项只按本章章末钩子判断")
    if not setting_fields.get("timeline"):
        notes.append("未配置时间线（story_bible.timeline），时间线错误检测缺少基准")
    if not (setting_fields.get("foreshadow") or any(c.get("hook") for c in prev_chapters) or ch_hook):
        notes.append("未配置伏笔清单（story_bible.foreshadow）且无章末悬念，伏笔回收检测缺少基准")

    return {
        "book": book,
        "chapter_no": chapter_no,
        "chapter": chapter,
        "title": _norm((chapter or {}).get("title")),
        "chapter_id": _norm((chapter or {}).get("chapter_id")),
        "fields": fields,
        "cards": cards,
        "factions": factions,
        "synopsis": synopsis,
        "book_summary": book_summary,
        "chapter_summary": ch_summary,
        "chapter_points": ch_points,
        "chapter_scene": _norm((chapter or {}).get("scene")),
        "chapter_roles": [_norm(x) for x in ((chapter or {}).get("roles") or []) if _norm(x)],
        "chapter_factions": [_norm(x) for x in ((chapter or {}).get("factions") or []) if _norm(x)],
        "setting_fields": setting_fields,
        "chapter_hook": ch_hook,
        "chapter_conflict": ch_conflict,
        "chapter_emotion": ch_emotion,
        "chapter_tension": ch_tension,
        "chapter_payoff": ch_payoff,
        "chapter_setup": ch_setup,
        "chapter_hook_type": ch_hook_type,
        "prev_chapters": prev_chapters,
        "has_prev_context": bool(prev_chapters),
        "next_chapters": next_chapters,
        "has_next_context": bool(next_chapters),
        "n_chapters": len(chapters),
        "has_synopsis": bool(synopsis),
        "has_chapter_summary": bool(ch_summary or ch_points),
        "has_setting": has_setting,
        "n_cards": len(cards),
        "n_factions": len(factions),
        "notes": notes,
    }


def setting_digest(base):
    """把设定库压成给模型看的短文本（角色卡只留与本章相关的，控制体积）。"""
    lines = []
    roles = base.get("chapter_roles") or []
    cards = base.get("cards") or []
    if cards:
        picked = cards
        if roles:
            picked = [c for c in cards
                      if any(_norm(r) and (_norm(r) in _norm(c.get("name")) or _norm(c.get("name")) in _norm(r))
                             for r in roles)] or cards
        for c in picked:
            seg = "；".join("%s：%s" % (k, _norm(c.get(k))) for k in
                            ("name", "gender", "role", "alignment", "stance", "identity",
                             "personality", "speech", "goal", "catchwords") if _norm(c.get(k)))
            if seg:
                lines.append("- " + seg)
    for f in (base.get("factions") or []):
        seg = "；".join("%s：%s" % (k, _norm(f.get(k))) for k in
                        ("name", "category", "stance", "relType", "desc") if _norm(f.get(k)))
        if seg:
            lines.append("- [势力] " + seg)
    label = {"terms": "专有名词表", "items": "关键道具", "places": "重要地点", "taboos": "写作禁忌与铁律",
             "power": "力量体系与金手指", "world": "世界观与时代背景", "protagonist": "主角设定",
             "supporting": "主要配角", "antagonist": "主要反派", "genre": "题材与基调",
             "style": "文风与语言", "person": "叙事人称",
             "timeline": "时间线", "foreshadow": "伏笔清单", "mainline": "主线",
             "subplots": "支线", "suspense": "悬念"}
    for k, v in (base.get("setting_fields") or {}).items():
        lines.append("- [%s] %s" % (label.get(k, k), v))
    # 情绪流基准：没有这几行，模型只会挑字词毛病，判断不了「该爽的地方爽了没有」
    if base.get("chapter_emotion") or base.get("chapter_tension"):
        seg = base.get("chapter_emotion") or ""
        if base.get("chapter_tension"):
            seg += ("，" if seg else "") + "峰值 %s/10" % base["chapter_tension"]
        lines.append("- [本章情绪走向] %s" % seg)
    if base.get("chapter_payoff"):
        lines.append("- [本章应兑现的爽点] %s（正文里必须真发生，不能只用一句带过）" % base["chapter_payoff"])
    if base.get("chapter_setup"):
        lines.append("- [本章应埋下的铺垫] %s" % base["chapter_setup"])
    if base.get("chapter_hook_type"):
        lines.append("- [章末钩子类型应为] %s" % base["chapter_hook_type"])
    if base.get("chapter_conflict"):
        lines.append("- [本章核心冲突] %s" % base["chapter_conflict"])
    return "\n".join(lines)


def memory_digest(base):
    """把「前情提要 + 设定/人物/道具/时间线」压成给模型看的上下文记忆块。"""
    lines = []
    prev = base.get("prev_chapters") or []
    if prev:
        lines.append("【前情提要】（最近 %d 章）" % len(prev))
        for c in prev:
            seg = "第 %s 章 %s" % (c.get("no"), c.get("title") or "")
            if c.get("summary"):
                seg += "：" + c["summary"]
            if c.get("hook"):
                seg += "（章末悬念：%s）" % c["hook"]
            lines.append("- " + seg.strip())
    else:
        lines.append("【前情提要】（无前文章节记载）")
    nxt = base.get("next_chapters") or []
    if nxt:
        lines.append("【后文概览】（接下来 %d 章，用来判断本章的收尾能否接得上、该留的过渡有没有留）"
                     % len(nxt))
        for c in nxt:
            seg = "第 %s 章 %s" % (c.get("no"), c.get("title") or "")
            if c.get("summary"):
                seg += "：" + c["summary"]
            if c.get("conflict"):
                seg += "（该章核心冲突：%s）" % c["conflict"]
            lines.append("- " + seg.strip())
    sd = setting_digest(base)
    if sd:
        lines.append("【设定 / 人物 / 道具 / 时间线】")
        lines.append(sd)
    return "\n".join(lines)


def foreshadow_digest(base):
    """汇总伏笔 / 支线清单：设定库显式字段 + 前文章末悬念 + 本章章末悬念。"""
    lines = []
    sf = base.get("setting_fields") or {}
    for k, label in (("foreshadow", "伏笔清单"), ("mainline", "主线"),
                     ("subplots", "支线"), ("suspense", "悬念")):
        v = sf.get(k)
        if v:
            lines.append("[%s] %s" % (label, v))
    for c in (base.get("prev_chapters") or []):
        if c.get("hook"):
            lines.append("- 第 %s 章章末悬念：%s" % (c.get("no"), c["hook"]))
    if base.get("chapter_conflict"):
        lines.append("- 本章核心冲突（正文要对上）：%s" % base["chapter_conflict"])
    if base.get("chapter_hook"):
        lines.append("- 本章章末悬念（待后续回收）：%s" % base["chapter_hook"])
    return "\n".join(lines)


# ---------------------------------------------------------------- 4a. 错别字规则初筛
def rule_typos(text, sentences):
    """规则初筛：只报高置信度候选，之后交给模型复核。"""
    out = []
    seen = set()

    def add(word, suggest, kind, why):
        key = (word, suggest)
        if key in seen:
            return
        seen.add(key)
        i = text.find(word)
        out.append({"quote": word, "suggest": suggest, "kind": kind,
                    "severity": "中", "reason": why, "sids": _sid_at(sentences, i)})

    for wrong, right in CONFUSIONS.items():
        if wrong in text:
            add(wrong, right, "别字形近 / 音近", "常见错别字：「%s」应为「%s」" % (wrong, right))
    for w in DUP_WORDS:
        for m in re.finditer(re.escape(w), text):
            add(w, w[0], "叠字重复", "疑似多写了一个「%s」" % w[0])
            break
    for m in RE_DUP_PUNC.finditer(text):
        p = m.group(1) or m.group(2)
        add(m.group(0), p, "标点重复", "标点重复：「%s」连用 %d 次" % (p, len(m.group(0))))
    for m in RE_HALF_PUNC.finditer(text):
        add(m.group(0), {",": "，", ";": "；", ":": "：", "!": "！", "?": "？"}[m.group(0)],
            "半角标点", "中文之间夹了半角标点「%s」" % m.group(0))
    for lq, rq in QUOTE_PAIRS:
        if text.count(lq) != text.count(rq):
            add(lq, lq + rq, "引号不成对", "「%s」与「%s」数量不一致（%d vs %d）"
                % (lq, rq, text.count(lq), text.count(rq)))
    return out


def _sid_at(sentences, offset):
    if offset is None or offset < 0:
        return []
    for s in sentences:
        if s["start"] <= offset < s["end"]:
            return [s["id"]]
    return []


# ---------------------------------------------------------------- 规则初筛：违规风险 / 重复用词
def sensitive_scan(text, sentences):
    """过审相关的高风险信号初筛。

    只出候选（含 ±12 字上下文），定性一律交给模型复核；模型判定没问题就丢掉，
    避免"风雨无阻""自杀式袭击"这类正常表达被误报成问题。"""
    out = []
    for kind, rx in RISK_RULES:
        for m in rx.finditer(text):
            a = max(0, m.start() - 12)
            b = min(len(text), m.end() + 12)
            out.append({
                "quote": text[a:b],        # 直接从原文切片，必然通过引用校验
                "kind": kind, "hit": m.group(0), "severity": "中",
                "sids": _sid_at(sentences, m.start()),
                "reason": "规则初筛命中「%s」类信号：%s（待模型复核）" % (kind, m.group(0)),
            })
    return out


def repeat_scan(text, sentences, names=()):
    """重复用词统计：纯程序、可复现，也是人工最容易改的一类问题。"""
    counts = {}
    for n in (2, 3):
        for m in re.finditer(r"(?=([\u4e00-\u9fff]{%d}))" % n, text):
            w = m.group(1)
            if any(c in REPEAT_STOP for c in w):
                continue
            counts[w] = counts.get(w, 0) + 1
    picked = []
    for w, c in sorted(counts.items(), key=lambda kv: (-kv[1], -len(kv[0]))):
        if c < 3:
            continue
        if any(w in p[0] for p in picked):          # 已被更长的词覆盖
            continue
        if any(_norm(x) and _norm(x) in w for x in names):
            continue                                # 人名 / 势力名高频属正常叙事
        picked.append((w, c))
    return picked[:8]


# ---------------------------------------------------------------- 行文统计体检（不调模型）
def build_stats(text, paragraphs, sentences, names=()):
    """纯程序体检：段落 / 句长 / 对话占比 / 词频密度 / 开篇章末钩子。

    返回 (rows, issues)：rows 直接进报告表格，issues 是需要人工动手的高频重复词。"""
    rows = []

    def row(name, value, level, tip):
        rows.append({"name": name, "value": value, "level": level, "tip": tip})

    n = len(text)
    if not sentences or not n:
        return rows, []
    per_k = lambda v: round(v / n * 1000, 1)         # noqa: E731
    sent_lens = [len(s["text"]) for s in sentences]
    para_lens = [len(p["text"]) for p in paragraphs]
    avg_sent = sum(sent_lens) / len(sent_lens)
    max_sent = max(sent_lens)
    long_para = sum(1 for x in para_lens if x > 300)
    quoted = sum(len(m.group(0))
                 for m in re.finditer(r"[“「『][^”」』]{1,300}[”」』]", text))
    dialog = quoted / n * 100
    hedge = sum(text.count(w) for w in HEDGE_WORDS)
    abstract = sum(text.count(w) for w in ABSTRACT_WORDS)
    punct_extra = len(RE_DASH.findall(text)) + len(RE_PAREN.findall(text))

    bad_sent = max_sent > 100 or avg_sent > 45
    row("句子长度", "平均 %.0f 字 / 最长 %d 字 / 超 80 字 %d 句"
        % (avg_sent, max_sent, sum(1 for x in sent_lens if x > 80)),
        "偏高" if bad_sent else "正常",
        "从句中逗号处断开，单句尽量压到 60 字内" if bad_sent else "句长分布健康")
    row("段落长度", "平均 %.0f 字 / 超 300 字 %d 段"
        % (sum(para_lens) / len(para_lens), long_para),
        "偏高" if long_para else "正常",
        "按场景或动作把超长段切开，手机端更友好" if long_para else "段落切分合理")
    row("对话占比", "%.0f%%" % dialog,
        "注意" if (dialog < 15 or dialog > 70) else "正常",
        "偏少=叙述堆砌，把陈述改成对白；偏多=缺场景，补动作与心理"
        if (dialog < 15 or dialog > 70) else "对话与叙述比例正常")

    # 叙事节奏：段落长短波动 + 长短句交替（程序代理指标）
    para_avg = sum(para_lens) / len(para_lens)
    para_std = (sum((x - para_avg) ** 2 for x in para_lens) / len(para_lens)) ** 0.5
    short_ratio = sum(1 for x in sent_lens if x <= 20) / len(sent_lens) * 100
    long_ratio = sum(1 for x in sent_lens if x >= 60) / len(sent_lens) * 100
    flat = para_std < 20 and short_ratio < 10
    row("叙事节奏", "段长波动 ±%.0f 字 / 短句 %.0f%% / 长句 %.0f%%" % (para_std, short_ratio, long_ratio),
        "偏平" if flat else "正常",
        "长短段与长短句交替制造起伏，别每段一样长" if flat else "节奏有起伏")

    # 情绪张力：情绪/冲突强度词密度 + 感叹问句密度（程序代理指标）
    emo = sum(text.count(w) for w in EMOTION_WORDS)
    bang = len(re.findall(r"[！？!?]", text))
    tension = per_k(emo)
    row("情绪张力", "%.1f 处/千字强度词 / 感叹问句 %d 处" % (tension, bang),
        "偏弱" if (tension < 2 and bang < 3) else ("偏强" if tension > 15 else "正常"),
        "补冲突与身体反应，避免平铺直叙" if (tension < 2 and bang < 3)
        else ("注意别靠感叹号硬撑情绪" if tension > 15 else "情绪张弛有度"))

    row("缓饰词密度", "%.1f 处/千字（微微 / 轻轻 / 似乎 / 仿佛…）" % per_k(hedge),
        "偏高" if per_k(hedge) > 8 else ("注意" if per_k(hedge) > 4 else "正常"),
        "删掉一半「微微 / 轻轻 / 缓缓 / 似乎 / 仿佛」，动作直接写"
        if per_k(hedge) > 4 else "缓饰词用量正常")
    row("抽象词密度", "%.1f 处/千字（氛围感 / 张力 / 宿命感 / 某种…）" % per_k(abstract),
        "偏高" if per_k(abstract) > 4 else ("注意" if per_k(abstract) > 1.5 else "正常"),
        "把「氛围感 / 张力 / 宿命感」换成看得见听得见的具体细节"
        if per_k(abstract) > 1.5 else "抽象词用量正常")
    row("破折号 / 括号", "%.1f 处/千字" % per_k(punct_extra),
        "注意" if per_k(punct_extra) > 6 else "正常",
        "多用于二次解释，能删就删，把信息并进句子本身"
        if per_k(punct_extra) > 6 else "使用克制")

    tmpl = []
    for name, rx in RE_TEMPLATE:
        c = len(rx.findall(text))
        if c:
            tmpl.append("%s ×%d" % (name, c))
    row("模板句式命中", "、".join(tmpl) if tmpl else "无",
        "偏高" if len(tmpl) >= 3 else ("注意" if tmpl else "正常"),
        "同一句式反复出现会显得套路化，全章保留 1~2 处即可" if tmpl else "未命中常见模板句式")

    first = paragraphs[0]["text"] if paragraphs else ""
    last = paragraphs[-1]["text"] if paragraphs else ""
    hook = bool(re.search(r"[“「『！？]|，他|，她|猛地|突然|忽然|竟", first))
    row("开篇钩子", "前段 %d 字，%s" % (len(first), "有抓手的迹象" if hook else "偏平"),
        "正常" if hook else "注意",
        "前 3 句内放一个悬念、冲突或反常细节" if not hook else "开篇已有冲突或对话")
    end_hook = bool(re.search(r"[！？…]|转身|离开|沉默|欲言又止|却|然而|只是", last))
    row("章末钩子", "%s" % ("有收束 / 悬念" if end_hook else "偏弱"),
        "正常" if end_hook else "注意",
        "章末留一个未解答的问题或反转，提高追读" if not end_hook else "章末已留口子")

    issues = []
    reps = repeat_scan(text, sentences, names)
    for w, c in reps:
        sids = [s["id"] for s in sentences if w in s["text"]][:6]
        issues.append({
            "quote": w, "count": c,
            "severity": "中" if c >= 8 else "低",
            "sids": sids,
            "reason": "「%s」在全章出现 %d 次%s" % (w, c, "，短距离内反复出现" if c >= 8 else ""),
        })
    row("重复用词 TOP", "、".join("%s×%d" % (w, c) for w, c in reps) or "无",
        "注意" if reps else "正常",
        "不必全删，把挨得近的几次换掉或换个说法即可" if reps else "用词重复度正常")
    return rows, issues


# ---------------------------------------------------------------- 人工可执行动作 / 过审风险
def fix_action(it):
    """把一条问题翻译成「人手能直接执行的一个动作」——只给动作，不给成稿。"""
    q, t = it.get("quote", ""), it.get("type")
    if t == "typo":
        return ("把「%s」改为「%s」" % (q, it["suggest"])) if it.get("suggest") \
            else ("核对并改正「%s」" % q)
    if t == "risk":
        return "按「%s」处置（删除细节 / 改成暗示 / 整段删，三选一）" % (it.get("action") or "弱化处理")
    if t == "logic":
        return "核对前后文说法，补一句过渡或统一口径，使因果 / 时序自洽"
    if t == "consistency":
        return "对照设定「%s」修正该处" % (it.get("ref") or "设定库")
    if t == "theme":
        return "删减或改写该处，使其回到本章概览主线"
    if t == "repeat":
        return "「%s」出现 %s 次，把挨得近的几次换掉或换个说法" % (q, it.get("count", "数"))
    if t == "ai_taste":
        return "按正向 / 反向建议重写该处（自行成稿，报告不给替换文本）"
    return "人工复核该处"


def risk_summary(issues, theme_level, risk_checked=True, risk_rule_only=False):
    """过审风险总览：只做经验性提示，不承诺任何结果。

    risk_checked=False 表示本次根本没勾选违规风险检测；
    risk_rule_only=True 表示只跑完了规则初筛、模型复核没跑成（结论仅供参考）。
    """
    n_high = sum(1 for i in issues if i["severity"] == "高")
    n_risk = sum(1 for i in issues if i["type"] == "risk")
    n_risk_high = sum(1 for i in issues if i["type"] == "risk" and i["severity"] == "高")
    reasons = []
    if n_risk_high:
        reasons.append("%d 条高风险违规项" % n_risk_high)
    if n_risk:
        reasons.append("共 %d 条违规风险项" % n_risk)
    if theme_level == "重":
        reasons.append("主题偏离判定为「重」")
    elif theme_level == "中":
        reasons.append("主题偏离判定为「中」")
    if n_high:
        reasons.append("%d 条高严重度问题" % n_high)
    if not risk_checked:
        reasons.append("本次未勾选违规风险检测，结论不含该项")
    elif risk_rule_only:
        reasons.append("违规风险仅完成规则初筛，模型复核未跑成，请自行判断")
    level = "高" if (n_risk_high or n_risk >= 3 or (theme_level == "重" and n_high >= 3)) \
        else ("中" if (n_risk or n_high >= 3 or theme_level in ("中", "重")) else "低")
    return {"level": level, "reasons": reasons or ["未发现明显风险项"],
            "n_risk": n_risk, "n_high": n_high,
            "risk_checked": risk_checked, "risk_rule_only": risk_rule_only}


# ---------------------------------------------------------------- 提示词
AI_TASTE_PROMPT = """你是中文网文资深责编，负责诊断一章正文里的「AI 味」。

【任务】只找出问题，列成清单。禁止改写、禁止给出替换句或替换段落、禁止给范文。

【检查维度】（不必逐条套，命中才算问题）
1. 段落结尾强行升华 / 点题 / 抒情拔高（"这一刻他终于明白……"）
2. 三段式排比堆砌、"不是 A，而是 B，更是 C" 句式泛滥
3. 抽象名词堆砌：氛围感、张力、宿命感、质感、褶皱、某种……
4. 破折号解释癖、括号补注癖（用标点给读者二次解释已经写清楚的东西）
5. 模糊修饰词泛滥：微微、轻轻、缓缓、淡淡、似乎、仿佛、莫名、不由得
6. 机械对仗 / 对称句式，相邻句子结构高度雷同
7. 无信息量的过渡与情绪标签（他心中一凛、不禁感到、一股……涌上心头）
8. 模板化感官与数字描写（"三分……七分……""空气中弥漫着……"）
9. 同一形容词 / 同一意象在短距离内反复出现，或三个以上形容词堆着修饰同一名词
10. 每段都用同一种节奏收尾；连续多句都以同一主语（他 / 她）开头
11. 情绪直说而不演：直接给结论（"他很愤怒"）而不是给动作与反应
12. 环境描写与情节无关，纯粹在凑字数

【输出】只输出一个 JSON 对象：
{"issues":[{"sids":["P01-S02"],"category":"上面某一维度","severity":"高|中|低","quote":"从下面原文里逐字复制的一段，8~40 字，不得改写、不得加省略号","reason":"一句话说明为什么算 AI 味"}]}

【铁律】
1. quote 必须是原文里真实存在的连续片段，逐字照抄，一个字都不能改；找不到原文就不要报这条。
2. 没有问题时输出 {"issues":[]}，不要为了凑数硬报。
3. sids 只能填下面列出的句子 ID。
4. severity：高 = 明显模板化、读者一眼能看出；中 = 有痕迹但不严重；低 = 轻微可保留。
__CRAFT_NOTE__

【本章正文（带句子 ID）】
__TEXT__"""

RISK_PROMPT = """你是中文网文合规审读，负责标出一章正文里可能被平台拒稿 / 限流的高风险描写。

【规则初筛候选】（可能含误报，请复核；正常表达一律丢掉）
__CANDIDATES__

【判定维度】（只对真正可能被判违规的才报，正常剧情需要不算）
1. 低俗擦边：露骨或暗示性的情欲描写、挑逗细节
2. 血腥暴力：过度细致的伤残、虐杀、器官描写
3. 违法违禁：毒品、走私、制毒、枪支弹药等具体流程或细节
4. 自残自杀：自杀 / 自残的具体方法与诱导性细节（一笔带过的情节需要不算）
5. 涉赌涉黄：赌博、嫖娼等的具体描写与美化
6. 辱骂歧视：侮辱性称呼、对群体的贬损
7. 现实影射：明显指向现实中真实机构、企业、在世人物的负面描写

【输出】只输出一个 JSON 对象：
{"issues":[{"sids":["P01-S02"],"kind":"上面某一维度","severity":"高|中|低","action":"删除细节|改成暗示|整段删除|弱化用词","quote":"正文原文片段，8~40 字","reason":"为什么可能被判违规、触发哪类审核"}]}

【铁律】
1. quote 必须逐字照抄原文；找不到原文就不要报。
2. 只在真的可能触发审核时报；正常剧情需要（如"反派吸毒""战场受伤"）要判成「低」或干脆不报，并说明可保留。
3. action 只给处置方向，绝对不要写替换文本、不要写"可以改成……"的成稿。
4. severity：高=很可能被拒稿；中=建议弱化；低=可保留但需留意。

【本章正文（带句子 ID）】
__TEXT__"""

LOGIC_PROMPT = """你是中文网文资深责编，负责检查一章正文的逻辑与连贯性，并核对与前文是否一致。

【前文记忆】（已发生章节 / 人物当前状态 / 道具与时间线）
__MEMORY__

【本章概览】（若有）
__OVERVIEW__

【判定维度】
1. 人物前后矛盾：与【前文记忆】里已确立的人设、身份、关系、能力不符（性格突变、能力忽强忽弱、关系错乱）
2. 时间线错误：与已建立的时序 / 季节 / 年龄 / 事件先后冲突
3. 道具状态跳变：物品 / 伤势 / 线索在前文与本章之间无交代地出现或消失
4. 设定冲突：与【前文记忆】里的世界观、势力、专有名词冲突
5. 章内前后矛盾：同一件事在文中说法不一致（人数、时间、方位、物品状态）
6. 时序 / 因果断裂：先发生后发生颠倒，或缺了必要的原因就出了结果
7. 视角跳变：第一 / 第三人称混用，或突然切进另一个角色的心理
8. 重复叙述：同一信息在短距离内说了两遍
9. 人物凭空出现或消失：上场 / 离场没有交代
10. 称谓混乱：同一角色文中用了多个互不统一的叫法
11. 能力与物品状态跳变：刚用完的东西下一段又出现了，伤势忽好忽坏
12. 承接断裂（承上）：本章开头没有接住上一章的收尾——场景、人物状态、未解悬念与
    【前情提要】里上一章的章末悬念对不上，读起来像中间跳了一段
13. 启下断裂（启下）：本章结尾与【后文概览】里下一章的开局接不上，
    或下一章要用的关键线索 / 人物 / 地点在本章毫无交代，导致后文凭空冒出来
    （只判「接不上」，不得要求改写后文，也不得因为后文写得好坏给本章扣分）

【输出】只输出一个 JSON 对象：
{"issues":[{"sids":["P01-S02"],"kind":"上面某一维度","severity":"高|中|低","quote":"正文原文片段，8~40 字","reason":"哪里矛盾、与前文哪一处对不上"}]}

【铁律】
1. quote 必须逐字照抄原文；两条相互矛盾的地方都要能指到原文，找不到就不报。
2. 只有【前文记忆】或设定库里明确写过的事实才算「与前文矛盾」；没写过的不要臆测。
   第 13 条请严格按【后文概览】的记载判断，概览里没写的衔接问题不要臆测。
3. 不要改写正文、不要给替换文本。

【本章正文（带句子 ID）】
__TEXT__"""

THEME_PROMPT = """你是中文网文资深责编，判断一章正文是否偏离了它应有的主题 / 剧情走向。

【基准·本书简介 / 大纲】
__SYNOPSIS__

【基准·本章概览】
__OVERVIEW__

【任务】
1. 判断本章正文相对上述基准的主题偏离程度：无 / 轻 / 中 / 重。
   - 无：完全贴合基准
   - 轻：整体贴合，个别句子游离
   - 中：有明显跑题段落或情节与概览不符
   - 重：主题跑偏、情节与概览冲突
2. 给出依据：每条依据必须是从正文里逐字复制的 quote。
3. 把偏离处也列成 issues（可以是 0 条）。

【输出】只输出一个 JSON 对象：
{"level":"无|轻|中|重","summary":"两三句判断说明","evidence":[{"quote":"正文原文片段","why":"为什么算偏离/贴合"}],"issues":[{"sids":["P01-S02"],"severity":"高|中|低","quote":"正文原文片段，8~40 字","reason":"为什么算偏离"}]}

【铁律】quote 必须逐字照抄原文，找不到就不报；不要改写正文、不要给替换文本。
__CRAFT_NOTE__

【本章正文（带句子 ID）】
__TEXT__"""

TYPO_PROMPT = """你是中文网文资深校对，负责找出正文里的错别字。

【规则初筛候选】（可能含误报，请你复核；确认没错就丢掉）
__CANDIDATES__

【任务】
1. 复核上面的候选，错的留下、对的丢掉。
2. 另外再通读正文，补出规则没抓到的错字（别字形近、音近字、多字漏字、叠字、标点误用）。
3. 只报你有把握的，不确定就不报。

【输出】只输出一个 JSON 对象：
{"issues":[{"sids":["P01-S02"],"quote":"原文里的疑似错字或错词，1~20 字，逐字照抄","suggest":"建议的正确写法","kind":"别字形近|音近|多字漏字|叠字|标点","severity":"高|中|低","reason":"为什么这里错了"}]}

【铁律】quote 必须是原文里真实存在的连续片段；suggest 只给正确写法这一个词 / 短语，不要造句、不要给替换段落。

【本章正文（带句子 ID）】
__TEXT__"""

CONSISTENCY_PROMPT = """你是中文网文资深责编，负责检查正文是否违反了本书已设定的世界观与剧情设定。

【设定库】（角色卡 / 势力卡 / 名词 / 道具 / 地点 / 禁忌……）
__SETTING__

【本章概览】
__OVERVIEW__

【任务】逐条比对正文与设定库，只报确实冲突的地方：
· 人名 / 势力名 / 地名 / 功法 / 道具名写错或张冠李戴
· 角色做了设定里不允许的事（性格、能力、身份、说话风格不符）
· 势力立场、人物关系与设定冲突
· 违反了写作禁忌与铁律
· 与本章概览的情节走向冲突
· 设定里给了[本章应兑现的爽点]，正文却没真发生、只用一句「他赢了」带过（这是「只铺垫不给」的头号毛病）
· 设定里给了[章末钩子类型应为]，正文结尾却收在该类型之外（例：要求「反转」，结尾只是抒情）

【输出】只输出一个 JSON 对象：
{"issues":[{"sids":["P01-S02"],"ref":"命中的设定条目（如「角色卡·沈砚」「专有名词表·玄铁令」）","severity":"高|中|低","quote":"正文原文片段，8~40 字","reason":"与哪条设定冲突、怎么冲突"}]}

【铁律】
1. quote 必须逐字照抄原文，找不到就不报。
2. 设定库里没写的东西不算冲突（例如设定没写某角色不能游泳，就不能报）。
3. 没有冲突就输出 {"issues":[]}。
4. 不要改写正文、不要给替换文本。
__CRAFT_NOTE__

【本章正文（带句子 ID）】
__TEXT__"""

FORESHADOW_PROMPT = """你是中文网文资深责编，负责管理伏笔与支线的回收状态。

【伏笔 / 支线清单】（来自设定库与已发生章节）
__FORESHADOW__

【前文记忆】（最近章节进展）
__MEMORY__

【本章概览】
__OVERVIEW__

【任务】
1. 对照清单，判断每条伏笔 / 支线在本章之后的状态：已回收 / 部分回收 / 未回收 / 超期未回收 / 支线进行中 / 支线已闭环。
2. 找出本章新埋下的伏笔（status 记「新埋」），便于后续追踪。
3. 对「应回收却悬空」「支线长期不闭环」「回收得突兀」的，列成 issues（quote 从正文逐字复制）。

【输出】只输出一个 JSON 对象：
{"items":[{"title":"伏笔/支线名","status":"已回收|部分回收|未回收|超期未回收|支线进行中|支线已闭环|新埋","evidence":"正文原文片段（可空，8~40 字）","note":"一句话说明"}],
 "issues":[{"sids":["P01-S02"],"kind":"伏笔未回收|支线未闭环|伏笔突兀回收","severity":"高|中|低","quote":"正文原文片段，8~40 字","reason":"哪条伏笔/支线、为什么有问题"}]}

【铁律】
1. quote 必须逐字照抄原文；找不到原文就不报。
2. 清单外的伏笔只在本章有明确铺垫时才记「新埋」，不要臆造。
3. 没有问题时 items 照常给出状态，issues 输出 []。
4. 不要改写正文、不要给替换文本。
__CRAFT_NOTE__

【本章正文（带句子 ID）】
__TEXT__"""

ADVICE_PROMPT = """你是中文网文资深责编。下面是一章正文里被判定的 Top 问题（本轮范围：__SCOPE__）。

【任务】针对每条问题给出**方向性**建议，分正向与反向两条：
· positive（正向）：这一段应该往哪个方向改——写什么、抓哪个具体细节、视角落在谁身上。只说方向，不写成稿。
· negative（反向）：明确不要怎么写——点名要避开的句式、词、写法。

【铁律】
1. 禁止输出可以直接粘贴进正文的替换句 / 替换段落；只给方向、要点、反例。
2. 每条建议不超过 60 字。
3. 按下面给的问题顺序逐条对应，一条都不要漏、不要新增。

【输出】只输出一个 JSON 对象：
{"advices":[{"idx":0,"positive":"……","negative":"……"}]}
__CRAFT_NOTE__

【Top 问题】
__ISSUES__"""


# ---------------------------------------------------------------- 模型调用

def _craft_note(kind):
    """审查各检查项的追加评估维度（craft.py，源自用户写作设定；可在提示词模板库覆盖 craft.*）。
    craft 模块缺失时静默降级为空——审查主流程不受影响。"""
    try:
        import craft
        t = craft.review_note(kind)
        return "\n\n" + t if t else ""
    except Exception:  # noqa
        return ""

def _call(prompt, api_key, base_url, model):
    prompt = prompt.replace("__CRAFT_NOTE__", "")  # 兜底：占位符不得泄漏进 prompt
    try:
        return chat_json(api_key, base_url, model, SYSTEM_PROMPT, prompt, retries=1)
    except OutputTruncated:
        # 截断是「这次要模型说的东西太多」，重试同样会被截断，提示说清出路
        raise StepError("模型输出超过长度上限被截断：本次要审查的内容太多（章节过长或勾选的检查项过多），"
                        "请减少检查项或缩短章节后重试")
    except JsonParseError as e:
        raise StepError("模型输出不是合法 JSON（已重试一次）")
    except Exception as e:                      # 网络 / 鉴权 / 超时
        raise StepError("%s" % e)


def _resolve_key(cli=None):
    """取 API Key：返回空串时由调用方降级为纯程序体检。"""
    k = _norm(cli or os.environ.get("DEEPSEEK_API_KEY", ""))
    if not k:
        return ""
    return k


# ---------------------------------------------------------------- 问题归一化
def _mk_issue(kind, d, text, sentences, valid_ids, extra=None):
    """把模型/规则给的一条问题归一化；quote 校验不过的丢弃。"""
    quote = _norm(d.get("quote"))
    if not quote:
        return None
    idx = find_quote(text, quote)
    if idx < 0:
        return None
    sids = _sids(d.get("sids"), valid_ids)
    # quote 是唯一的真实依据：模型若给了对不上的句子 ID，以 quote 所在句为准，避免行号指错
    exact = text.find(quote)
    truth = _sid_at(sentences, exact) if exact >= 0 else []
    if truth and (not sids or not _sid_contains(sentences, sids[0], quote)):
        sids = (truth + [x for x in sids if x not in truth])[:6]
    if not sids:
        sids = _sid_at(sentences, idx if idx > 0 else None)
    # 前端「点击问题 → 定位原文并高亮」用的真实区间（相对正文，含首尾）
    span = locate_span(text, quote, sentences, sids)
    it = {
        "type": kind,
        "type_label": TYPE_LABEL.get(kind, kind),
        "severity": _sev(d.get("severity")),
        "title": _norm(d.get("title")) or _norm(d.get("category")) or _norm(d.get("kind")) or TYPE_LABEL.get(kind, kind),
        "quote": quote,
        "reason": _norm(d.get("reason")) or _norm(d.get("why")),
        "sids": sids,
        "line": line_of(sentences, sids, idx),
        "context": context_of(sentences, sids),
        "offset": span[0] if span else idx,
        "span": list(span) if span else None,
        "quote_ok": True,
    }
    if kind == "typo":
        it["suggest"] = _norm(d.get("suggest"))
    if kind == "consistency":
        it["ref"] = _norm(d.get("ref"))
    if kind == "risk":
        it["action"] = _norm(d.get("action"))
    if kind == "repeat":
        it["count"] = d.get("count")
    if extra:
        it.update(extra)
    it["fix"] = fix_action(it)
    return it


def sort_issues(issues):
    """统一排序：严重度 → 类型 → 文中位置。"""
    return sorted(issues, key=lambda x: (-SEV_RANK.get(x["severity"], 0),
                                         TYPE_PRIORITY.get(x["type"], 9),
                                         x.get("offset") if x.get("offset", -1) >= 0 else 1 << 30))


# ---------------------------------------------------------------- 主流程
def run_review(book, chapter_no, chapter_text, checks=None, model=DEFAULT_MODEL,
               base_url=None, api_key=None, top_n=DEFAULT_TOP_N,
               advice_scope=DEFAULT_ADVICE_SCOPE, on_log=None, should_stop=None):
    """跑完整条流水线，返回结果 dict（不落盘）。"""
    def log(msg):
        if on_log:
            on_log(msg)

    def stopped():
        return bool(should_stop and should_stop())

    text = (chapter_text or "").strip()
    if not text:
        raise ValueError("章节正文为空")
    if len(text) > MAX_TEXT_CHARS:
        raise ValueError(f"章节正文 {len(text)} 字，超过 {MAX_TEXT_CHARS} 字上限（请按章分段审查）")

    checks = [c for c in (checks or ALL_CHECKS) if c in CHECK_LABEL]
    if not checks:
        raise ValueError("没有勾选任何检查项")

    base = load_baseline(book, chapter_no)
    paragraphs, sentences = split_segments(text)
    valid_ids = {s["id"] for s in sentences}
    annotated = annotated_text(paragraphs, sentences)
    log(f"[基准] 书《{book}》第 {chapter_no} 章："
        f"简介/大纲 {'✔' if base['has_synopsis'] else '✘'}｜"
        f"本章概览 {'✔' if base['has_chapter_summary'] else '✘'}｜"
        f"角色卡 {base['n_cards']}｜势力卡 {base['n_factions']}｜"
        f"设定库 {'✔' if base['has_setting'] else '✘'}")
    for n in base["notes"]:
        log(f"       · {n}")
    log(f"[分句] {len(paragraphs)} 段 / {len(sentences)} 句，正文 {len(text)} 字")

    url = resolve_base_url(base_url)
    key = _resolve_key(api_key)
    model = model or DEFAULT_MODEL
    no_key_dropped = []
    if not key:
        # 无 Key 时不要逐个环节去撞鉴权错误：只保留程序能独立完成的项（行文统计 + 错别字规则初筛）
        keep = {"stats", "typo"}
        no_key_dropped = [CHECK_LABEL.get(c, c) for c in checks if c not in keep]
        checks = [c for c in checks if c in keep] or ["stats"]
        if no_key_dropped:
            log("未配置 API Key：跳过 " + "、".join(no_key_dropped) + "，本次只跑程序体检")

    issues, skipped, theme = [], [], {"level": "未检测", "summary": "", "evidence": []}
    foreshadow_items = []
    if no_key_dropped:
        skipped.append({"check": "api_key", "label": "AI 检查项",
                        "reason": "未配置 API Key，已跳过：" + "、".join(no_key_dropped)})
    stats_rows, repeat_issues = [], []
    # 需要跑模型的环节数（stats 是纯程序体检，不占调用；advice 视范围内有无问题而定）
    n_calls = sum(1 for c in checks if c != "advice" and c not in NO_CALL_CHECKS)
    advice_types = ADVICE_SCOPES.get(advice_scope) or ADVICE_SCOPES[DEFAULT_ADVICE_SCOPE]
    if "advice" in checks and any(t in checks for t in advice_types):
        n_calls += 1
    # 人名 / 势力名：重复用词统计要排除它们（主角名字高频是正常叙事）
    known_names = ([_norm(c.get("name")) for c in (base.get("cards") or [])]
                   + [_norm(f.get("name")) for f in (base.get("factions") or [])]
                   + (base.get("chapter_roles") or []))
    step = 0

    # ---------- 2. AI 味诊断
    ai_issues = []
    if "ai_taste" in checks:
        step += 1
        if stopped():
            raise Stopped()
        log(f"[{step}/{n_calls}] AI 味诊断（{len(sentences)} 句）...")
        try:
            res = _call(AI_TASTE_PROMPT.replace("__CRAFT_NOTE__", _craft_note("ai_taste"))
                                  .replace("__TEXT__", annotated), key, url, model)
            for d in _list(res.get("issues")):
                it = _mk_issue("ai_taste", d, text, sentences, valid_ids)
                if it:
                    ai_issues.append(it)
            log(f"        AI 味问题 {len(ai_issues)} 条")
        except StepError as e:
            skipped.append({"check": "ai_taste", "label": CHECK_LABEL["ai_taste"], "reason": str(e)})
            log(f"        [!] 跳过：{e}")
        issues += ai_issues

    # ---------- 3. 主题偏离检测
    if "theme" in checks:
        step += 1
        if stopped():
            raise Stopped()
        if not (base["has_synopsis"] or base["has_chapter_summary"]):
            skipped.append({"check": "theme", "label": CHECK_LABEL["theme"],
                            "reason": "未配置本书简介与本章概览，跳过"})
            log(f"[{step}/{n_calls}] 主题偏离检测：未配置基准，跳过")
        else:
            log(f"[{step}/{n_calls}] 主题偏离检测（本书简介 + 本章概览）...")
            overview = "\n".join(x for x in (
                "标题：%s" % base["title"], "场景：%s" % base["chapter_scene"],
                "角色：%s" % "、".join(base["chapter_roles"]),
                "概览：%s" % base["chapter_summary"],
                "情节要点：" + "；".join(base["chapter_points"]) if base["chapter_points"] else "",
            ) if x.strip())
            prompt = (THEME_PROMPT
                      .replace("__CRAFT_NOTE__", _craft_note("theme"))
                      .replace("__SYNOPSIS__", base["synopsis"] or "（本书未配置简介/大纲）")
                      .replace("__OVERVIEW__", overview or "（本章未配置概览）")
                      .replace("__TEXT__", annotated))
            try:
                res = _call(prompt, key, url, model)
                level = _norm(res.get("level")) or "无"
                if level not in ("无", "轻", "中", "重"):
                    level = "中"
                ev = []
                for d in _list(res.get("evidence")):
                    q = _norm(d.get("quote"))
                    if q and quote_ok(text, q):
                        ev.append({"quote": q, "why": _norm(d.get("why"))})
                got = 0
                for d in _list(res.get("issues")):
                    it = _mk_issue("theme", d, text, sentences, valid_ids)
                    if it:
                        issues.append(it)
                        got += 1
                theme = {"level": level, "summary": _norm(res.get("summary")), "evidence": ev}
                log(f"        偏离等级：{level}（问题 {got} 条 / 依据 {len(ev)} 条）")
            except StepError as e:
                skipped.append({"check": "theme", "label": CHECK_LABEL["theme"], "reason": str(e)})
                log(f"        [!] 跳过：{e}")

    # ---------- 4. 错别字检测
    if "typo" in checks:
        step += 1
        if stopped():
            raise Stopped()
        cands = rule_typos(text, sentences)
        log(f"[{step}/{n_calls}] 错别字检测（规则初筛 {len(cands)} 条 → 模型复核）...")
        cand_txt = "\n".join("%s → 建议 %s（%s）" % (c["quote"], c["suggest"], c["reason"])
                             for c in cands) or "（规则未命中）"
        prompt = (TYPO_PROMPT.replace("__CANDIDATES__", cand_txt).replace("__TEXT__", annotated))
        got = 0
        try:
            if not key:
                raise StepError("未配置 API Key")
            res = _call(prompt, key, url, model)
            for d in _list(res.get("issues")):
                it = _mk_issue("typo", d, text, sentences, valid_ids)
                if it:
                    issues.append(it)
                    got += 1
            log(f"        确认/补充错别字 {got} 条")
        except StepError as e:
            for c in cands:                      # 模型不可用：退回规则结果并标注
                it = _mk_issue("typo", c, text, sentences, valid_ids,
                               extra={"reason": c["reason"] + "（规则初筛，未经模型复核）"})
                if it:
                    issues.append(it)
            skipped.append({"check": "typo", "label": CHECK_LABEL["typo"] + "（模型复核）", "reason": str(e)})
            log(f"        [!] 模型复核失败（{e}），改用规则初筛结果")

    # ---------- 5. 设定 / 剧情一致性检测
    if "consistency" in checks:
        step += 1
        if stopped():
            raise Stopped()
        if not base["has_setting"]:
            skipped.append({"check": "consistency", "label": CHECK_LABEL["consistency"],
                            "reason": "未配置设定库，跳过"})
            log(f"[{step}/{n_calls}] 设定 / 剧情一致性检测：未配置设定库，跳过")
        else:
            log(f"[{step}/{n_calls}] 设定 / 剧情一致性检测（{base['n_cards']} 角色卡 / "
                f"{base['n_factions']} 势力卡 / {len(base['setting_fields'])} 项世界设定）...")
            overview = "标题：%s\n概览：%s" % (base["title"], base["chapter_summary"])
            prompt = (CONSISTENCY_PROMPT
                      .replace("__CRAFT_NOTE__", _craft_note("consistency"))
                      .replace("__SETTING__", setting_digest(base))
                      .replace("__OVERVIEW__", overview)
                      .replace("__TEXT__", annotated))
            try:
                res = _call(prompt, key, url, model)
                got = 0
                for d in _list(res.get("issues")):
                    it = _mk_issue("consistency", d, text, sentences, valid_ids)
                    if it:
                        issues.append(it)
                        got += 1
                log(f"        一致性问题 {got} 条")
            except StepError as e:
                skipped.append({"check": "consistency", "label": CHECK_LABEL["consistency"], "reason": str(e)})
                log(f"        [!] 跳过：{e}")

    # ---------- 5b. 违规风险检测（过审相关）
    risk_checked = False
    risk_rule_only = False
    if "risk" in checks:
        step += 1
        if stopped():
            raise Stopped()
        cands = sensitive_scan(text, sentences)
        log(f"[{step}/{n_calls}] 违规风险检测（规则初筛 {len(cands)} 条 → 模型复核）...")
        cand_txt = "\n".join("- [%s] 命中「%s」：…%s…" % (c["kind"], c["hit"], c["quote"])
                             for c in cands) or "（规则未命中，请通读判断）"
        prompt = RISK_PROMPT.replace("__CANDIDATES__", cand_txt).replace("__TEXT__", annotated)
        try:
            res = _call(prompt, key, url, model)
            got = 0
            for d in _list(res.get("issues")):
                it = _mk_issue("risk", d, text, sentences, valid_ids)
                if it:
                    issues.append(it)
                    got += 1
            risk_checked = True
            hi = sum(1 for i in issues if i["type"] == "risk" and i["severity"] == "高")
            log(f"        违规风险 {got} 条（高 {hi}）")
        except StepError as e:
            # 模型不可用：退回规则初筛，但一律压成「低」并标注需自行判断，避免误吓
            for c in cands:
                it = _mk_issue("risk", c, text, sentences, valid_ids,
                               extra={"severity": "低", "action": "弱化处理",
                                      "reason": c["reason"] + "（规则初筛，未经模型复核，请自行判断）"})
                if it:
                    issues.append(it)
            risk_checked = True
            risk_rule_only = True
            skipped.append({"check": "risk", "label": CHECK_LABEL["risk"] + "（模型复核）", "reason": str(e)})
            log(f"        [!] 模型复核失败（{e}），改用规则初筛结果（已压为「低」，需自行判断）")

    # ---------- 5c. 逻辑与连贯性检测（含前文记忆比对）
    if "logic" in checks:
        step += 1
        if stopped():
            raise Stopped()
        log(f"[{step}/{n_calls}] 逻辑与连贯性检测（{len(sentences)} 句，前文 "
            f"{len(base.get('prev_chapters') or [])} 章 / 后文 "
            f"{len(base.get('next_chapters') or [])} 章记忆）...")
        overview = "标题：%s\n概览：%s\n情节要点：%s" % (
            base["title"], base["chapter_summary"], "；".join(base["chapter_points"]))
        prompt = (LOGIC_PROMPT
                  .replace("__MEMORY__", memory_digest(base))
                  .replace("__OVERVIEW__", overview.strip())
                  .replace("__TEXT__", annotated))
        try:
            res = _call(prompt, key, url, model)
            got = 0
            for d in _list(res.get("issues")):
                it = _mk_issue("logic", d, text, sentences, valid_ids)
                if it:
                    issues.append(it)
                    got += 1
            log(f"        逻辑 / 连贯问题 {got} 条")
        except StepError as e:
            skipped.append({"check": "logic", "label": CHECK_LABEL["logic"], "reason": str(e)})
            log(f"        [!] 跳过：{e}")

    # ---------- 5c-2. 伏笔 / 支线回收检测（需伏笔清单，否则跳过）
    if "foreshadow" in checks:
        step += 1
        if stopped():
            raise Stopped()
        fl = foreshadow_digest(base)
        if not fl.strip():
            skipped.append({"check": "foreshadow", "label": CHECK_LABEL["foreshadow"],
                            "reason": "未配置伏笔 / 支线清单，也无章末悬念，跳过"})
            log(f"[{step}/{n_calls}] 伏笔 / 支线回收检测：无清单，跳过")
        else:
            log(f"[{step}/{n_calls}] 伏笔 / 支线回收检测...")
            ov = "标题：%s\n概览：%s" % (base["title"], base["chapter_summary"])
            prompt = (FORESHADOW_PROMPT
                      .replace("__CRAFT_NOTE__", _craft_note("foreshadow"))
                      .replace("__FORESHADOW__", fl)
                      .replace("__MEMORY__", memory_digest(base))
                      .replace("__OVERVIEW__", ov)
                      .replace("__TEXT__", annotated))
            try:
                res = _call(prompt, key, url, model)
                got = 0
                for d in _list(res.get("items")):
                    t = _norm(d.get("title"))
                    if t:
                        foreshadow_items.append({
                            "title": t,
                            "status": _norm(d.get("status")) or "未回收",
                            "evidence": _norm(d.get("evidence")),
                            "note": _norm(d.get("note")),
                        })
                for d in _list(res.get("issues")):
                    it = _mk_issue("foreshadow", d, text, sentences, valid_ids)
                    if it:
                        issues.append(it)
                        got += 1
                log(f"        伏笔 {len(foreshadow_items)} 条 / 回收问题 {got} 条")
            except StepError as e:
                skipped.append({"check": "foreshadow", "label": CHECK_LABEL["foreshadow"], "reason": str(e)})
                log(f"        [!] 跳过：{e}")

    # ---------- 5d. 行文统计体检（纯程序，不调模型）
    if "stats" in checks:
        log("[体检] 行文统计：段落 / 句长 / 对话占比 / 词频密度 / 开篇章末钩子（不调模型）")
        stats_rows, repeat_issues = build_stats(text, paragraphs, sentences, known_names)
        for w in repeat_issues:
            it = _mk_issue("repeat", w, text, sentences, valid_ids)
            if it:
                issues.append(it)
        warn = sum(1 for r in stats_rows if r["level"] in ("偏高", "注意"))
        log(f"        体检 {len(stats_rows)} 项，{warn} 项需要注意；高频重复词 {len(repeat_issues)} 个")

    # ---------- 6. Top 问题的正向 / 反向建议
    advice_n = 0
    if "advice" in checks:
        pool = sort_issues([i for i in issues if i["type"] in advice_types])
        if not pool:
            skipped.append({"check": "advice", "label": CHECK_LABEL["advice"],
                            "reason": "建议范围内没有问题（或未勾选对应检查项），跳过"})
        else:
            step += 1
            if stopped():
                raise Stopped()
            top = pool[:max(1, int(top_n or DEFAULT_TOP_N))]
            scope_txt = "、".join(TYPE_LABEL[t] for t in advice_types)
            log(f"[{step}/{n_calls}] 为 Top {len(top)} 条问题（{scope_txt}）生成正向 / 反向建议...")
            # 分批问：一条问题要两条 60 字建议，一次问太多会被输出上限截断（整批建议全丢）
            for b0 in range(0, len(top), ADVICE_BATCH):
                if stopped():
                    raise Stopped()
                batch = top[b0:b0 + ADVICE_BATCH]
                lines = []
                for i, it in enumerate(batch):
                    lines.append("[%d] %s（%s·%s）\n原文：%s\n判断：%s" %
                                 (i, it["title"], it["type_label"], it["severity"], it["quote"], it["reason"]))
                try:
                    res = _call(ADVICE_PROMPT.replace("__SCOPE__", scope_txt)
                                .replace("__CRAFT_NOTE__", _craft_note("advice"))
                                .replace("__ISSUES__", "\n\n".join(lines)), key, url, model)
                    by_idx = {}
                    for a in _list(res.get("advices")):
                        try:
                            by_idx[int(a.get("idx"))] = a
                        except (TypeError, ValueError):
                            continue
                    for i, it in enumerate(batch):
                        a = by_idx.get(i)
                        if not a:
                            continue
                        it["advice"] = {"positive": _norm(a.get("positive")), "negative": _norm(a.get("negative"))}
                        advice_n += 1
                    log("        已生成 %d/%d 组建议" % (advice_n, len(top)))
                except StepError as e:
                    skipped.append({"check": "advice", "label": CHECK_LABEL["advice"],
                                    "reason": "第 %d~%d 条：%s" % (b0 + 1, b0 + len(batch), e)})
                    log(f"        [!] 跳过第 {b0 + 1}~{b0 + len(batch)} 条：{e}")

    # ---------- 7. 引用校验（_mk_issue 已逐条验证；这里统一编号并汇总）
    issues = sort_issues(issues)
    for i, it in enumerate(issues, 1):
        it["id"] = "%s-%03d" % (TYPE_CODE.get(it["type"], "X"), i)

    stats = {"total": len(issues), "by_severity": {s: 0 for s in SEV_LABEL}, "by_type": {}}
    for it in issues:
        stats["by_severity"][it["severity"]] = stats["by_severity"].get(it["severity"], 0) + 1
        stats["by_type"][it["type_label"]] = stats["by_type"].get(it["type_label"], 0) + 1

    # 过审风险总览
    risk = risk_summary(issues, theme["level"], risk_checked, risk_rule_only)
    # 人工修改清单：按文中位置从上往下排，改完一条勾一条
    checklist = ["- [ ] [%s · %s · 第 %s 行] %s\n      原文：%s" %
                 (it["id"], it["type_label"], it.get("line") or "-", it["fix"], it["quote"][:30])
                 for it in sorted(issues, key=lambda x: (x.get("line") or 0, x.get("offset") or 0))]

    log(f"[完成] 共 {len(issues)} 条问题（高 {stats['by_severity']['高']} / "
        f"中 {stats['by_severity']['中']} / 低 {stats['by_severity']['低']}）；"
        f"过审风险 {risk['level']}；跳过 {len(skipped)} 项")

    return {
        "meta": {
            "book": book,
            "chapter_no": str(chapter_no),
            "chapter_id": base["chapter_id"],
            "title": base["title"],
            "model": model,
            "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "checks": checks,
            "check_labels": [CHECK_LABEL[c] for c in checks],
            "chars": len(text),
            "n_paragraphs": len(paragraphs),
            "n_sentences": len(sentences),
            "top_n": top_n,
            "advice_scope": advice_scope,
            "advice_types": advice_types,
        },
        "baseline": {
            "synopsis": base["synopsis"],
            "synopsis_chars": len(base["synopsis"]),
            "chapter_summary": base["chapter_summary"],
            "chapter_points": base["chapter_points"],
            "chapter_scene": base["chapter_scene"],
            "chapter_roles": base["chapter_roles"],
            "chapter_hook": base.get("chapter_hook", ""),
            "chapter_conflict": base.get("chapter_conflict", ""),
            "chapter_emotion": base.get("chapter_emotion", ""),
            "chapter_tension": base.get("chapter_tension", 0),
            "chapter_payoff": base.get("chapter_payoff", ""),
            "chapter_setup": base.get("chapter_setup", ""),
            "chapter_hook_type": base.get("chapter_hook_type", ""),
            "n_prev": len(base.get("prev_chapters") or []),
            "n_next": len(base.get("next_chapters") or []),
            "n_cards": base["n_cards"],
            "n_factions": base["n_factions"],
            "setting_keys": list((base.get("setting_fields") or {}).keys()),
            "has_synopsis": base["has_synopsis"],
            "has_chapter_summary": base["has_chapter_summary"],
            "has_setting": base["has_setting"],
            "has_timeline": bool((base.get("setting_fields") or {}).get("timeline")),
            "has_foreshadow": bool((base.get("setting_fields") or {}).get("foreshadow")),
            "notes": base["notes"],
        },
        "theme": theme,
        "stats": stats,
        "stats_report": stats_rows,
        "risk": risk,
        "checklist": checklist,
        "foreshadow": foreshadow_items,
        "issues": issues,
        "skipped": skipped,
        "sentences": [{"id": s["id"], "para": s["para"], "no": s["no"],
                       "line": s.get("line"), "text": s["text"]} for s in sentences],
        # 本次审查的正文（已 strip）：issues[].span 的下标基准就是它，
        # 前端据此渲染原文并高亮问题点；没人改正文也不会错位
        "text": text,
        "disclaimer": DISCLAIMER,
    }


# ---------------------------------------------------------------- 8. 报告渲染
def _md_esc(s):
    return _norm(s).replace("|", "\\|").replace("\n", " ")


def render_markdown(r):
    m = r["meta"]
    L = []
    L.append("# AI 审查报告 · 《%s》%s" % (m["book"], m["chapter_id"] or ("第 %s 章" % m["chapter_no"])))
    if m["title"]:
        L[-1] += "《%s》" % m["title"]
    L.append("")
    L.append("> 生成时间：%s　模型：%s　正文 %d 字 / %d 段 / %d 句"
             % (m["generated_at"], m["model"], m["chars"], m["n_paragraphs"], m["n_sentences"]))
    L.append(">")
    L.append("> %s" % r["disclaimer"])
    L.append("")
    L.append("## 一、比对基准加载情况")
    L.append("")
    b = r["baseline"]
    L.append("| 基准 | 状态 | 说明 |")
    L.append("| --- | --- | --- |")
    L.append("| 本书简介 / 大纲 | %s | %s |" % ("✔ 已加载" if b["has_synopsis"] else "✘ 未配置",
                                                ("%d 字" % b["synopsis_chars"]) if b["has_synopsis"] else "主题偏离检测缺全书基准"))
    L.append("| 本章概览 | %s | %s |" % ("✔ 已加载" if b["has_chapter_summary"] else "✘ 未配置",
                                         ("%d 字 + %d 条情节要点" % (len(b["chapter_summary"]), len(b["chapter_points"])))
                                         if b["has_chapter_summary"] else "主题偏离检测缺本章基准"))
    L.append("| 角色卡 | %s | %s |" % ("✔ %d 张" % b["n_cards"] if b["n_cards"] else "✘ 未配置",
                                       "一致性检测会比对人物设定" if b["n_cards"] else "不做人物设定比对"))
    L.append("| 势力卡 | %s | %s |" % ("✔ %d 张" % b["n_factions"] if b["n_factions"] else "✘ 未配置",
                                       "一致性检测会比对势力设定" if b["n_factions"] else "不做势力设定比对"))
    L.append("| 名词 / 道具 / 地点等 | %s | %s |" % ("✔ %d 项" % len(b["setting_keys"]) if b["setting_keys"] else "✘ 未配置",
                                                     "、".join(b["setting_keys"]) if b["setting_keys"] else "不做世界设定比对"))
    L.append("")
    for n in b["notes"]:
        L.append("- 标注：%s" % n)
    if b["notes"]:
        L.append("")
    L.append("## 二、总览")
    L.append("")
    st = r["stats"]
    L.append("- 问题总数：**%d**（高 %d / 中 %d / 低 %d）"
             % (st["total"], st["by_severity"].get("高", 0), st["by_severity"].get("中", 0),
                st["by_severity"].get("低", 0)))
    if st["by_type"]:
        L.append("- 按类型：" + "、".join("%s %d" % (k, v) for k, v in st["by_type"].items()))
    else:
        L.append("- 按类型：无")
    t = r["theme"]
    L.append("- 主题偏离：**%s**%s" % (t["level"], ("——" + t["summary"]) if t.get("summary") else ""))
    for e in t.get("evidence") or []:
        L.append("  - 依据：> %s　（%s）" % (_md_esc(e["quote"]), _md_esc(e["why"])))
    L.append("- 引用校验：所有问题均已程序验证，其 quote 确实出现在原文中。")
    rk = r.get("risk") or {}
    L.append("- 过审风险：**%s**%s" % (rk.get("level", "未评估"),
                                      ("（" + "；".join(rk.get("reasons") or []) + "）")
                                      if rk.get("reasons") else ""))
    L.append("")
    L.append("## 三、行文统计体检（纯程序计算，不调模型，结果可复现）")
    L.append("")
    if r.get("stats_report"):
        L.append("| 体检项 | 实测 | 判定 | 怎么改 |")
        L.append("| --- | --- | --- | --- |")
        for row in r["stats_report"]:
            L.append("| %s | %s | %s | %s |" % (_md_esc(row["name"]), _md_esc(row["value"]),
                                                row["level"], _md_esc(row["tip"])))
    else:
        L.append("（本次未勾选「行文统计体检」）")
    L.append("")
    L.append("## 四、问题清单（统一排序：严重度 → 类型 → 文中位置）")
    L.append("")
    if not r["issues"]:
        L.append("（未发现问题）")
        L.append("")
    for i, it in enumerate(r["issues"], 1):
        loc = "、".join(it["sids"]) if it["sids"] else "—"
        L.append("### %d. [%s·%s·%s] %s" % (i, it["id"], it["type_label"], it["severity"], it["title"]))
        L.append("")
        L.append("- 位置：%s（第 %s 行）" % (loc, it.get("line") or "-"))
        L.append("- 原文：> %s" % _md_esc(it["quote"]))
        ctx = it.get("context") or {}
        if ctx.get("prev"):
            L.append("- 上一句：%s" % _md_esc(ctx["prev"]))
        if ctx.get("next"):
            L.append("- 下一句：%s" % _md_esc(ctx["next"]))
        if it.get("fix"):
            L.append("- **怎么改**：%s" % _md_esc(it["fix"]))
        if it.get("suggest"):
            L.append("- 建议写法：**%s**" % _md_esc(it["suggest"]))
        if it.get("ref"):
            L.append("- 命中设定：%s" % _md_esc(it["ref"]))
        if it.get("reason"):
            L.append("- 依据：%s" % _md_esc(it["reason"]))
        ad = it.get("advice")
        if ad:
            L.append("- 正向建议：%s" % _md_esc(ad.get("positive")))
            L.append("- 反向建议：%s" % _md_esc(ad.get("negative")))
        L.append("")
    L.append("## 五、手动修改清单（按文中位置从上往下，改完勾一条）")
    L.append("")
    if r.get("checklist"):
        for c in r["checklist"]:
            L.append(c)
    else:
        L.append("- 无。")
    L.append("")
    L.append("## 六、跳过项与说明")
    L.append("")
    if r["skipped"]:
        for s in r["skipped"]:
            L.append("- **%s**：%s" % (s["label"], s["reason"]))
    else:
        L.append("- 无，勾选项全部完成。")
    L.append("")
    L.append("---")
    L.append("")
    L.append("本报告由 flowwork「AI 审查」自动生成。%s" % r["disclaimer"])
    L.append("")
    return "\n".join(L)


def render_html(r):
    m = r["meta"]
    e = html.escape
    st = r["stats"]
    t = r["theme"]
    b = r["baseline"]

    def badge(ok, txt):
        c = "#059669" if ok else "#B45309"
        bg = "rgba(5,150,105,.10)" if ok else "rgba(180,83,9,.10)"
        return ('<span style="display:inline-block;padding:1px 8px;border-radius:999px;'
                'font-size:12px;color:%s;background:%s">%s</span>' % (c, bg, e(txt)))

    sev_color = {"高": "#DC2626", "中": "#B45309", "低": "#2563EB"}
    rows = []
    for i, it in enumerate(r["issues"], 1):
        parts = ['<div style="border:1px solid rgba(15,23,42,.12);border-radius:10px;'
                 'padding:12px 14px;margin-bottom:10px;background:#fff">']
        parts.append('<div style="font-weight:600;font-size:14px">%d. '
                     '<span style="color:%s">[%s]</span> %s <span style="color:rgba(30,41,59,.45);'
                     'font-weight:400">· %s · %s</span></div>'
                     % (i, sev_color.get(it["severity"], "#1E293B"), e(it["id"]),
                        e(it["title"]), e(it["type_label"]), e(it["severity"])))
        parts.append('<div style="margin-top:6px;color:rgba(30,41,59,.66);font-size:13px">'
                     '位置：%s（第 %s 行）</div>'
                     % (e("、".join(it["sids"]) if it["sids"] else "—"), it.get("line") or "-"))
        parts.append('<blockquote style="margin:8px 0;padding:6px 10px;border-left:3px solid #0D9488;'
                     'background:rgba(13,148,136,.06);color:#1E293B">%s</blockquote>' % e(it["quote"]))
        ctx = it.get("context") or {}
        if ctx.get("prev") or ctx.get("next"):
            parts.append('<div style="font-size:12px;color:rgba(30,41,59,.5)">'
                         '上一句：%s　｜　下一句：%s</div>'
                         % (e(ctx.get("prev") or "—"), e(ctx.get("next") or "—")))
        if it.get("fix"):
            parts.append('<div style="margin-top:4px;font-size:13px">怎么改：<b>%s</b></div>' % e(it["fix"]))
        if it.get("suggest"):
            parts.append('<div style="font-size:13px">建议写法：<b>%s</b></div>' % e(it["suggest"]))
        if it.get("ref"):
            parts.append('<div style="font-size:13px;color:rgba(30,41,59,.66)">命中设定：%s</div>' % e(it["ref"]))
        if it.get("reason"):
            parts.append('<div style="font-size:13px;color:rgba(30,41,59,.66)">依据：%s</div>' % e(it["reason"]))
        ad = it.get("advice")
        if ad:
            parts.append('<div style="margin-top:6px;font-size:13px">'
                         '<div>正向建议：%s</div><div>反向建议：%s</div></div>'
                         % (e(ad.get("positive", "")), e(ad.get("negative", ""))))
        parts.append("</div>")
        rows.append("".join(parts))

    skipped = "".join("<li><b>%s</b>：%s</li>" % (e(s["label"]), e(s["reason"])) for s in r["skipped"]) \
        or "<li>无，勾选项全部完成。</li>"
    notes = "".join("<li>%s</li>" % e(n) for n in b["notes"]) or "<li>无</li>"
    ev = "".join('<li><i style="color:rgba(30,41,59,.7)">%s</i> —— %s</li>'
                 % (e(x["quote"]), e(x["why"])) for x in (t.get("evidence") or []))
    by_type = "、".join("%s %d" % (e(k), v) for k, v in st["by_type"].items()) or "无"

    # 行文统计体检表
    srows = "".join("<tr><td>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>"
                    % (e(x["name"]), e(x["value"]), e(x["level"]), e(x["tip"]))
                    for x in (r.get("stats_report") or []))
    stats_tbl = ('<table><tr><th>体检项</th><th>实测</th><th>判定</th><th>怎么改</th></tr>%s</table>'
                 % srows) if srows else '<div class="note">（本次未勾选「行文统计体检」）</div>'
    # 过审风险
    rk = r.get("risk") or {}
    risk_txt = "<b>%s</b>%s" % (e(rk.get("level", "未评估")),
                                ("（" + e("；".join(rk.get("reasons") or [])) + "）")
                                if rk.get("reasons") else "")
    # 手动修改清单（按文中位置从上往下）
    chk_items = sorted(r["issues"], key=lambda x: (x.get("line") or 0, x.get("offset") or 0))
    chk = "".join('<li>[%s · %s · 第 %s 行] %s<br><i style="color:rgba(30,41,59,.55)">原文：%s</i></li>'
                  % (e(it["id"]), e(it["type_label"]), it.get("line") or "-",
                     e(it.get("fix") or ""), e(it["quote"][:30]))
                  for it in chk_items) or "<li>无。</li>"

    return """<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8">
<title>AI 审查报告 · %(book)s %(cid)s</title>
<style>
body{margin:0;padding:28px;background:#F4F6FA;color:#1E293B;
font:14px/1.7 "Segoe UI","Microsoft YaHei",system-ui,sans-serif}
.wrap{max-width:900px;margin:0 auto;background:#fff;border-radius:16px;padding:26px 30px;
box-shadow:0 1px 2px rgba(15,23,42,.05),0 8px 24px rgba(15,23,42,.08)}
h1{font-size:22px;margin:0 0 6px}
h2{font-size:16px;margin:26px 0 10px;padding-left:9px;border-left:3px solid #0D9488}
table{border-collapse:collapse;width:100%%;font-size:13px}
th,td{border:1px solid rgba(15,23,42,.12);padding:6px 9px;text-align:left}
th{background:#F7F9FC}
.note{color:rgba(30,41,59,.66);font-size:13px}
.disc{margin:10px 0;padding:9px 12px;border-radius:8px;background:rgba(13,148,136,.08);
color:#0D9488;font-size:13px}
.foot{margin-top:24px;color:rgba(30,41,59,.45);font-size:12px}
</style></head><body><div class="wrap">
<h1>AI 审查报告 · 《%(book)s》%(cid)s%(title)s</h1>
<div class="note">生成时间：%(time)s　模型：%(model)s　正文 %(chars)d 字 / %(np)d 段 / %(ns)d 句</div>
<div class="disc">%(disc)s</div>
<h2>一、比对基准加载情况</h2>
<table><tr><th>基准</th><th>状态</th><th>说明</th></tr>
<tr><td>本书简介 / 大纲</td><td>%(b1)s</td><td>%(b1d)s</td></tr>
<tr><td>本章概览</td><td>%(b2)s</td><td>%(b2d)s</td></tr>
<tr><td>角色卡</td><td>%(b3)s</td><td>%(b3d)s</td></tr>
<tr><td>势力卡</td><td>%(b4)s</td><td>%(b4d)s</td></tr>
<tr><td>名词 / 道具 / 地点等</td><td>%(b5)s</td><td>%(b5d)s</td></tr></table>
<ul class="note">%(notes)s</ul>
<h2>二、总览</h2>
<div>问题总数：<b>%(total)d</b>（高 %(h)d / 中 %(mid)d / 低 %(l)d）</div>
<div class="note">按类型：%(bytype)s</div>
<div>主题偏离：<b>%(level)s</b>%(tsum)s</div>
<ul class="note">%(ev)s</ul>
<div class="note">引用校验：所有问题均已程序验证，其 quote 确实出现在原文中。</div>
<div>过审风险：%(risk)s</div>
<h2>三、行文统计体检（纯程序计算，不调模型，结果可复现）</h2>
%(statstbl)s
<h2>四、问题清单（统一排序：严重度 → 类型 → 文中位置）</h2>
%(rows)s
<h2>五、手动修改清单（按文中位置从上往下，改完勾一条）</h2>
<ul class="note">%(chk)s</ul>
<h2>六、跳过项与说明</h2>
<ul class="note">%(skipped)s</ul>
<div class="foot">本报告由 flowwork「AI 审查」自动生成。%(disc)s</div>
</div></body></html>""" % {
        "book": e(m["book"]), "cid": e(m["chapter_id"] or ("第 %s 章" % m["chapter_no"])),
        "title": ("《%s》" % e(m["title"])) if m["title"] else "",
        "time": e(m["generated_at"]), "model": e(m["model"]), "chars": m["chars"],
        "np": m["n_paragraphs"], "ns": m["n_sentences"], "disc": e(r["disclaimer"]),
        "b1": badge(b["has_synopsis"], "✔ 已加载" if b["has_synopsis"] else "✘ 未配置"),
        "b1d": ("%d 字" % b["synopsis_chars"]) if b["has_synopsis"] else "主题偏离检测缺全书基准",
        "b2": badge(b["has_chapter_summary"], "✔ 已加载" if b["has_chapter_summary"] else "✘ 未配置"),
        "b2d": ("%d 字 + %d 条情节要点" % (len(b["chapter_summary"]), len(b["chapter_points"])))
               if b["has_chapter_summary"] else "主题偏离检测缺本章基准",
        "b3": badge(bool(b["n_cards"]), "✔ %d 张" % b["n_cards"] if b["n_cards"] else "✘ 未配置"),
        "b3d": "一致性检测会比对人物设定" if b["n_cards"] else "不做人物设定比对",
        "b4": badge(bool(b["n_factions"]), "✔ %d 张" % b["n_factions"] if b["n_factions"] else "✘ 未配置"),
        "b4d": "一致性检测会比对势力设定" if b["n_factions"] else "不做势力设定比对",
        "b5": badge(bool(b["setting_keys"]), "✔ %d 项" % len(b["setting_keys"]) if b["setting_keys"] else "✘ 未配置"),
        "b5d": e("、".join(b["setting_keys"])) if b["setting_keys"] else "不做世界设定比对",
        "notes": notes,
        "total": st["total"], "h": st["by_severity"].get("高", 0),
        "mid": st["by_severity"].get("中", 0), "l": st["by_severity"].get("低", 0),
        "bytype": by_type, "level": e(t["level"]),
        "tsum": ("——" + e(t["summary"])) if t.get("summary") else "",
        "ev": ev, "rows": "".join(rows) or '<div class="note">（未发现问题）</div>',
        "statstbl": stats_tbl, "risk": risk_txt, "chk": chk,
        "skipped": skipped,
    }


# ---------------------------------------------------------------- 落盘
def _slug(chapter_no):
    m = re.search(r"\d+", str(chapter_no or ""))
    return ("ch" + m.group(0).zfill(3)) if m else "ch"


def save_reports(book, chapter_no, result, out_dir=None):
    """报告写入 data/<书名>/review/，返回 {json, md, html} 相对于项目根的路径。"""
    d = out_dir or os.path.join(book_dir(book), "review")
    os.makedirs(d, exist_ok=True)
    stem = "%s_%s" % (_slug(chapter_no), datetime.now().strftime("%Y%m%d-%H%M%S"))
    paths = {}
    for ext, content in (("json", json.dumps(result, ensure_ascii=False, indent=2)),
                         ("md", render_markdown(result)),
                         ("html", render_html(result))):
        p = os.path.join(d, "%s.%s" % (stem, ext))
        with open(p, "w", encoding="utf-8") as f:
            f.write(content)
        paths[ext] = os.path.relpath(p, ROOT).replace("\\", "/")
    return paths


# ---------------------------------------------------------------- 签约预审（跨章：扫前 2 万字）
# 平台签约审核只看前 2 万字（≈前 10 章），单章审查看不出「开篇不抓人 / 主角太被动 / 爽点连用」
# 这类跨章问题，所以预审独立成一条流水线：程序初筛 5 项 + 一次模型复核（有 Key 才跑）。
PRECHECK_WINDOW = 10
PRECHECK_CHARS = 20_000
# 无 Key 降级稿的首行标记（与 expand.local_prose 的写法一致），预审据此跳过写作清单
SKELETON_MARK = "【本地骨架 · 未调用 AI】"

# 前 1000 字的冲突信号（程序初筛）：命中越多，开头越可能「有戏」
OPEN_CONFLICT_WORDS = ("杀", "死", "逼", "跪", "废物", "退婚", "背叛", "威胁", "冷笑",
                       "打", "骂", "滚", "危机", "血", "逃", "债", "辱", "怒", "刀")
# 章尾：强钩子信号 / 弱收尾信号
HOOK_STRONG_WORDS = ("突然", "竟然", "却", "但", "原来", "猛地", "骤然", "陡然", "一道",
                     "杀", "死", "危机", "居然", "谁知", "不料")
HOOK_WEAK_WORDS = ("睡去", "一夜无话", "结束", "散去", "回房", "晚安", "入睡", "第二天")
# 金手指词面扫描时要剔除的泛词（它们几乎必在正文里出现，命中没有诊断价值）
POWER_STOP_WORDS = {"系统", "能力", "可以", "获得", "主角", "金手指", "力量", "体系", "修炼",
                    "提升", "通过", "但是", "因为", "所以", "如果", "没有", "一个", "什么",
                    "这个", "那个", "自己", "别人", "已经", "就是"}

SIGNING_PROMPT = """你是中文网文平台的签约编辑，只看开篇前 2 万字决定签不签。下面是某书的简介、金手指设定与开篇正文节选。只输出 JSON：

{
  "opening_hook": {"level": "强", "why": "前 1000 字有没有把人按在椅子上的冲突或悬念，一句话"},
  "golden_finger": {"demonstrated": true, "chapter": 2, "evidence": "金手指第一次真正被使用、读者看到效果的原文句子（没有就空字符串）"},
  "protagonist_active": {"score": 7, "why": "主角是主动行动还是被动挨打，一句话", "evidence": "最能说明问题的原文句子"}
}

判定标准：
1. opening_hook.level 只填 强 / 中 / 弱：开头即有冲突或悬念为强；有悬念但慢热为中；铺垫世界观、日常流水为弱。
2. golden_finger.demonstrated：金手指真的被使用并产生效果才为 true；只被提到 / 介绍来历 / 觉醒成功都算 false；chapter 填实演发生的章号。
3. protagonist_active.score 0~10：主角被动挨打、被人推着走给 0~4；有反抗但多为应激给 5~6；主动布局、主动出击给 7~10。
4. evidence 必须照抄原文，一个字都不能改，改了就视为无效证据。
5. 只输出 JSON，不要解释，不要代码块围栏。

本书简介：__SYNOPSIS__
金手指设定：__POWER__
开篇正文（按章分隔）：
__TEXT__"""


def load_manuscript_window(book, window=PRECHECK_WINDOW, max_chars=PRECHECK_CHARS):
    """读 data/<书>/manuscript/ 前 window 章正文（按文件名章号排序），总量截到 max_chars。

    返回 [{"no": 章号, "text": 正文}]；找不到正文目录时返回空列表（调用方负责报错）。
    无 Key 生成的「本地骨架」只是写作清单，不是小说正文：跳过；全窗口都是骨架时直接报错，
    否则这种稿子也会被判「可投」，而平台一书一命，误投即废书。
    """
    mdir = os.path.join(book_dir(book), "manuscript")
    out, total, skeleton = [], 0, []
    if not os.path.isdir(mdir):
        return out
    files = []
    for fn in os.listdir(mdir):
        m = re.fullmatch(r"(\d{1,4})\.txt", fn)
        if m:
            files.append((int(m.group(1)), fn))
    for no, fn in sorted(files)[:window]:
        if total >= max_chars:
            break
        text = read_text_file(os.path.join(mdir, fn)).strip()
        if not text:
            continue
        if text.startswith(SKELETON_MARK):
            skeleton.append(no)
            continue
        if total + len(text) > max_chars:
            # 装不下的整章直接跳过：截半章会让「章尾钩子」检查把半截正文当成真结尾误判
            if out:
                break
            text = text[:max_chars]             # 第一章本身就超限：只能截断，聊胜于无
        out.append({"no": no, "text": text})
        total += len(text)
    if not out and skeleton:
        raise ValueError(
            f"manuscript/ 下的第 {'、'.join(map(str, skeleton))} 章都是「本地骨架」"
            "（未调用 AI 的写作清单，不是小说正文）：请先配置 API Key 重新生成正文，再做签约预审")
    return out


def _power_terms(power_text):
    """从「力量体系与金手指」设定里抠候选词（2~8 字、去泛词），用于正文词面命中初筛。"""
    terms = []
    for t in re.split(r"[^一-龥A-Za-z0-9]+", power_text or ""):
        if 2 <= len(t) <= 8 and t not in POWER_STOP_WORDS and t not in terms:
            terms.append(t)
    return terms[:12]


def _opening_hook_check(text):
    """前 1000 字冲突 / 悬念初筛：问号感叹号、对话、冲突词三类信号计分。"""
    head = (text or "")[:1000]
    q = sum(head.count(x) for x in "？！?!")
    dialog = len(re.findall(r"[“「\"]", head))
    conf = sum(1 for w in OPEN_CONFLICT_WORDS if w in head)
    hits = [w for w in OPEN_CONFLICT_WORDS if w in head][:6]
    score = (1 if q else 0) + (1 if dialog else 0) + min(2, conf)
    level = "通过" if score >= 3 else ("警告" if score >= 2 else "高危")
    detail = (f"前 1000 字：？！×{q}｜对话引号×{dialog}｜冲突词×{conf}"
              + (f"（{'、'.join(hits)}）" if hits else ""))
    if level == "高危":
        detail += "——开头几乎没有任何冲突 / 悬念信号，签约编辑翻不过这一页"
    return {"key": "first_1000", "label": "前 1000 字冲突 / 悬念",
            "level": level, "detail": detail}


def _golden_finger_check(power_text, chapters_text, model_judge=None,
                         demo_no=0, has_skeleton=False):
    """金手指实演：模型复核 > 骨架实演章号 > 设定词词面命中，依次兜底。"""
    label = "金手指实演（前 3 章）"
    # 模型读过正文，结论最硬：说实演了就是实演了（证据已校验），说没有就是没有
    if model_judge:
        if model_judge.get("demonstrated"):
            ch = model_judge.get("chapter")
            ev = _norm(model_judge.get("evidence"))
            return {"key": "golden_finger", "label": label, "level": "通过",
                    "detail": f"模型复核：第 {ch or '?'} 章已实演" + (f"——「{ev[:40]}…」" if ev else "")}
        return {"key": "golden_finger", "label": label, "level": "高危",
                "detail": "模型复核：开篇窗口内金手指只被提到 / 介绍，没有真正使用——"
                          "只口述不实演是签约被毙的典型原因"}
    if has_skeleton:
        if not demo_no:
            return {"key": "golden_finger", "label": label, "level": "高危",
                    "detail": "骨架诊断：全书没有标出金手指的实演章号，疑似只口述不实演"}
        if demo_no > 3:
            return {"key": "golden_finger", "label": label, "level": "高危",
                    "detail": f"骨架诊断：金手指第 {demo_no} 章才第一次实演，"
                              f"签约窗口（前 3 章）内必须看到效果"}
        detail = f"骨架标注第 {demo_no} 章实演"
        if power_text and not [t for t in _power_terms(power_text)
                               if t in "\n".join(c["text"] for c in chapters_text[:3])]:
            detail += "（词面未命中设定词，建议人工确认）"
        return {"key": "golden_finger", "label": label, "level": "通过", "detail": detail}
    if not power_text:
        # 没配金手指设定，模型也无从判断「实演」与否，宁可标未检也不给假结论
        return {"key": "golden_finger", "label": label, "level": "未检",
                "detail": "未配置力量体系与金手指（story_bible.power），跳过"}
    terms = _power_terms(power_text)
    head3 = "\n".join(c["text"] for c in chapters_text[:3])
    hits = [t for t in terms if t in head3]
    if hits:
        return {"key": "golden_finger", "label": label, "level": "通过",
                "detail": f"词面初筛：设定词「{'、'.join(hits[:4])}」在前 3 章出场（未配 Key，未做实演复核）"}
    return {"key": "golden_finger", "label": label, "level": "高危" if terms else "警告",
            "detail": (f"词面初筛：设定词（{'、'.join(terms[:6]) or '无'}）在前 3 章正文无一出场，"
                       f"金手指疑似只存在于设定里")}


def _three_piece_check(protagonist, chapters_text, ch1_conflict, has_skeleton):
    """首章三件套的前两件：①主角名字早早出场 ②核心冲突写明（金手指由单独一项判定）。

    ② 依赖骨架数据：chapters.json 缺失时无从判断，只做①的正文检查，避免把「没骨架」误报成「没冲突」。
    """
    head = chapters_text[0]["text"][:800] if chapters_text else ""
    miss = []
    if protagonist and protagonist not in head:
        miss.append(f"主角「{protagonist}」前 800 字未出场")
    if not protagonist:
        miss.append("未识别主角姓名（角色卡 / story_bible.protagonist 均缺）")
    if has_skeleton and not ch1_conflict:
        miss.append("第 1 章核心冲突为空")
    level = "通过" if not miss else ("高危" if len(miss) >= 2 else "警告")
    if not miss:
        detail = "主角早出场、冲突写明" if has_skeleton \
            else "主角前 800 字已出场（未配置章节骨架，冲突一项未判）"
    else:
        detail = "；".join(miss)
    return {"key": "three_piece", "label": "首章主角 / 核心冲突",
            "level": level, "detail": detail}


def _chapter_hooks_check(chapters_text, skeleton):
    """章末钩子强度（前 10 章）：正文尾 200 字找强 / 弱信号；骨架 hook 为空时也要记一笔。

    只有骨架里确有这一章时才用骨架 hook 判定——否则「没配骨架」会被误报成「每章都没钩子」。
    """
    rows, weak_nos = [], []
    skel = {c.get("no"): c for c in (skeleton or []) if isinstance(c, dict)}
    for c in chapters_text:
        tail = c["text"][-200:]
        strong = sum(1 for w in HOOK_STRONG_WORDS if w in tail) + \
            sum(1 for x in "？！" if x in tail)
        weak = any(w in tail for w in HOOK_WEAK_WORDS)
        skel_hook = _norm((skel.get(c["no"]) or {}).get("hook"))
        bad = (weak and not strong) or (c["no"] in skel and not skel_hook)
        if bad:
            weak_nos.append(c["no"])
        rows.append(f"第{c['no']}章{'✘' if bad else '✔'}")
    first3_bad = [n for n in weak_nos if n <= 3]
    level = "高危" if first3_bad else ("警告" if len(weak_nos) >= 3 else "通过")
    detail = " ".join(rows)
    if weak_nos:
        detail += f"——第 {'、'.join(map(str, weak_nos))} 章章尾偏弱或无钩子"
    return {"key": "chapter_hooks", "label": "章末钩子强度（前 10 章）",
            "level": level, "detail": detail}


def _repeat_payoff_check(skeleton_issues, has_skeleton):
    """爽点节奏：直接复用拆解模块的骨架校验结果（重复拍 / 爽点空缺 / 过渡拍）。"""
    if not has_skeleton:
        return {"key": "repeat_payoff", "label": "爽点节奏（重复拍 / 兑现表）", "level": "未检",
                "detail": "chapters.json 缺失或为空，跳过"}
    payoff_issues = [x for x in (skeleton_issues or [])
                     if "爽点" in x.get("msg", "") or "过渡拍" in x.get("msg", "")]
    hi = [x for x in payoff_issues if x.get("sev") == "高"]
    level = "高危" if len(hi) >= 3 else ("警告" if payoff_issues else "通过")
    detail = (f"骨架体检 {len(payoff_issues)} 条节奏类问题"
              + (f"，最典型：{payoff_issues[0]['msg']}" if payoff_issues else "，节奏达标"))
    return {"key": "repeat_payoff", "label": "爽点节奏（重复拍 / 兑现表）",
            "level": level, "detail": detail}


def run_signing_precheck(book, model=DEFAULT_MODEL, base_url=None, api_key=None,
                         on_log=None, should_stop=None):
    """签约预审：扫前 2 万字（≈前 10 章），5 项程序检查 + 一次模型复核，返回结果 dict（不落盘）。

    结果形状与单章审查不同（kind=signing_precheck）：checks 每项给 通过/警告/高危/未检，
    verdict 给「可投 / 需修改后再投 / 建议重写开篇」——对应编辑的三档处理。
    """
    def log(msg):
        if on_log:
            on_log(msg)

    def stopped():
        return bool(should_stop and should_stop())

    mds = load_manuscript_window(book)
    if not mds:
        raise ValueError(f"《{book}》manuscript/ 下没有正文（%03d.txt），请先生成正文再做签约预审")
    total = sum(len(c["text"]) for c in mds)
    log(f"[签约预审] 《{book}》窗口：前 {len(mds)} 章 / {total} 字（上限 {PRECHECK_CHARS}）")

    base = load_baseline(book, "1")
    fields = base.get("fields") or {}
    power_text = _norm(base.get("setting_fields", {}).get("power"))
    # 主角名：优先角色卡里 role=主角的，其次 protagonist 设定字段的第一个词
    protagonist = next((_norm(c.get("name")) for c in (base.get("cards") or [])
                        if "主角" in _norm(c.get("role"))), "")
    if not protagonist:
        protagonist = re.split(r"[，,、（(\s]", _norm(fields.get("protagonist")))[0] \
            if _norm(fields.get("protagonist")) else ""
    # 骨架（chapters.json）：章级 payoff / hook / 冲突 + 拆解时的签约体检结果
    skeleton, opening, skeleton_issues = [], {}, []
    try:
        with open(book_chapters(book), encoding="utf-8") as f:
            skel_data = json.load(f) or {}
        if not isinstance(skel_data, dict):
            skel_data = {}
        skeleton = [c for c in (skel_data.get("chapters") or []) if isinstance(c, dict)]
        opening = skel_data.get("opening") if isinstance(skel_data.get("opening"), dict) else {}
        skeleton_issues = skel_data.get("signing_check")
        if not isinstance(skeleton_issues, list):
            from decompose import signing_check as _sc
            skeleton_issues = _sc(skeleton, opening)
        skeleton_issues = [x for x in skeleton_issues if isinstance(x, dict)]
    except (OSError, ValueError):
        log("[!] chapters.json 缺失或损坏：爽点节奏 / 首章冲突两项只能依据正文粗判")
    has_skeleton = bool(skeleton)
    ch1 = next((c for c in skeleton if isinstance(c, dict) and c.get("no") == 1),
               (skeleton[0] if skeleton and isinstance(skeleton[0], dict) else {}))
    demo_no = _chapter_no_int((opening or {}).get("golden_finger_demo")) or 0

    checks, issues = [], []

    def emit(check):
        checks.append(check)
        if check["level"] == "高危":
            issues.append({"sev": "高", "chapter": 0, "msg": f"{check['label']}：{check['detail']}"})
        elif check["level"] == "警告":
            issues.append({"sev": "中", "chapter": 0, "msg": f"{check['label']}：{check['detail']}"})

    # ---------- 程序初筛（0 调用）
    emit(_opening_hook_check(mds[0]["text"]))
    emit(_three_piece_check(protagonist, mds, _norm(ch1.get("conflict")), has_skeleton))
    emit(_chapter_hooks_check(mds, skeleton))
    emit(_repeat_payoff_check(skeleton_issues, has_skeleton))
    log("[程序初筛] 前1000字信号 / 首章三件套 / 章末钩子 / 爽点节奏 完成")

    # ---------- 模型复核（一次调用：开头吸引力 + 金手指实演 + 主角主动性）
    key = _resolve_key(api_key)
    model_judge = None
    if stopped():
        raise Stopped()
    if key:
        log("[1/1] 模型复核：开头吸引力 + 金手指实演 + 主角主动性 ...")
        seg = "\n\n".join(f"【第{c['no']}章】\n{c['text'][:3000]}" for c in mds[:3])
        prompt = (SIGNING_PROMPT
                  .replace("__SYNOPSIS__", base.get("synopsis") or "（未配置）")
                  .replace("__POWER__", power_text or "（未配置）")
                  .replace("__TEXT__", seg))
        url = resolve_base_url(base_url)
        try:
            res = _call(prompt, key, url, model or DEFAULT_MODEL)
            full_text = "\n".join(c["text"] for c in mds)
            oh = res.get("opening_hook") or {}
            gf = res.get("golden_finger") or {}
            pa = res.get("protagonist_active") or {}
            # 证据必须能在原文里找到，找不到就降级处理（模型编的不能信）
            gf_ev = _norm(gf.get("evidence"))
            pa_ev = _norm(pa.get("evidence"))
            model_judge = {
                "opening_level": next((x for x in ("强", "中", "弱") if x in _norm(oh.get("level"))), "中"),
                "opening_why": _norm(oh.get("why")),
                "demonstrated": bool(gf.get("demonstrated")) and (not gf_ev or quote_ok(full_text, gf_ev)),
                "chapter": gf.get("chapter"),
                "evidence": gf_ev,
                "score": pa.get("score"),
                "pa_why": _norm(pa.get("why")),
                "pa_evidence": pa_ev if pa_ev and quote_ok(full_text, pa_ev) else "",
            }
            log(f"        开头吸引力 {model_judge['opening_level']}｜"
                f"金手指实演 {'✔' if model_judge['demonstrated'] else '✘'}｜"
                f"主动性 {model_judge['score']}")
        except StepError as e:
            log(f"        [!] 模型复核失败，只保留程序初筛：{e}")
            checks.append({"key": "model", "label": "模型复核", "level": "未检", "detail": str(e)})
    else:
        log("[i] 未配置 API Key：跳过模型复核（开头吸引力 / 实演判定 / 主动性只有程序初筛）")
        checks.append({"key": "model", "label": "模型复核", "level": "未检",
                       "detail": "未配置 API Key"})

    if model_judge:
        lv = {"强": "通过", "中": "警告", "弱": "高危"}[model_judge["opening_level"]]
        # 用模型结论替换程序初筛的「前 1000 字」项（同一检查，模型更准）
        checks[:] = [c for c in checks if c["key"] != "first_1000"]
        issues[:] = [x for x in issues if not x["msg"].startswith("前 1000 字")]
        emit({"key": "first_1000", "label": "前 1000 字冲突 / 悬念", "level": lv,
              "detail": "模型复核：" + (model_judge["opening_why"] or model_judge["opening_level"])})
        try:
            score = int(model_judge.get("score"))
        except (TypeError, ValueError):
            score = -1
        pa_level = "通过" if score >= 7 else ("警告" if score >= 5 else "高危" if score >= 0 else "未检")
        pa_detail = f"模型复核：主动性 {score}/10——{model_judge['pa_why'] or '（无说明）'}"
        if model_judge["pa_evidence"]:
            pa_detail += f"（如「{model_judge['pa_evidence'][:36]}…」）"
        if score <= 4 and score >= 0:
            pa_detail += "——主角全程被动挨打是「剧情平淡」的第一来源"
        emit({"key": "passive", "label": "主角主动性", "level": pa_level, "detail": pa_detail})
    elif "passive" not in [c["key"] for c in checks]:
        emit({"key": "passive", "label": "主角主动性", "level": "未检",
              "detail": "需模型判定（未配 Key 或复核失败）"})
    emit(_golden_finger_check(power_text, mds, model_judge, demo_no, has_skeleton))

    # 骨架体检的问题并入，但去掉已被上面检查项覆盖的三类（金手指 / 第 1 章冲突 / 章末钩子），
    # 只保留更细的章级信息（爽点空缺、重复拍、过渡拍），否则同一问题会在清单里报两遍。
    for x in (skeleton_issues or []):
        msg = x.get("msg", "")
        if any(k in msg for k in ("金手指", "核心冲突为空", "章末钩子为空")):
            continue
        issues.append({"sev": x.get("sev", "中"), "chapter": x.get("chapter", 0),
                       "msg": "[骨架] " + msg})

    hi = sum(1 for c in checks if c["level"] == "高危")
    warn = sum(1 for c in checks if c["level"] == "警告")
    verdict = "建议重写开篇" if hi >= 2 else ("需修改后再投" if (hi or warn >= 2) else "可投")
    verdict_why = "；".join(c["label"] for c in checks if c["level"] == "高危") or \
        "；".join(c["label"] for c in checks if c["level"] == "警告") or "各项均通过"
    log(f"[签约预审] 结论：{verdict}（高危 {hi} / 警告 {warn}）——{verdict_why}")
    return {"kind": "signing_precheck", "book": book,
            "window_chapters": len(mds), "chars": total,
            "protagonist": protagonist, "opening": opening,
            "checks": checks, "issues": issues,
            "verdict": verdict, "verdict_why": verdict_why,
            "created": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}


def render_precheck_md(r):
    """签约预审的 Markdown 报告：结论先行，检查项按 高危→警告→通过→未检 排。"""
    rank = {"高危": 0, "警告": 1, "通过": 2, "未检": 3}
    lines = [f"# 签约预审报告 —— 《{r['book']}》", "",
             f"- 窗口：前 {r['window_chapters']} 章 / {r['chars']} 字（签约审核只看前 2 万字）",
             f"- 结论：**{r['verdict']}**（{r['verdict_why']}）",
             f"- 生成时间：{r['created']}", "", "## 检查项", ""]
    for c in sorted(r["checks"], key=lambda x: rank.get(x["level"], 9)):
        mark = {"高危": "🔴", "警告": "🟡", "通过": "🟢", "未检": "⚪"}.get(c["level"], "⚪")
        lines.append(f"- {mark} **{c['label']}**（{c['level']}）：{c['detail']}")
    if r.get("issues"):
        lines += ["", "## 问题清单（含骨架体检）", ""]
        for i, x in enumerate(r["issues"], 1):
            ch = f"第{x['chapter']}章 " if x.get("chapter") else ""
            lines.append(f"{i}. [{x['sev']}] {ch}{x['msg']}")
    lines += ["", "---", DISCLAIMER]
    return "\n".join(lines)


def unique_report_stem(d, stem, exts=("json", "md")):
    """同秒重跑会撞文件名：补 -2/-3 后缀，保证每次执行都单独留一份历史报告。"""
    cand, i = stem, 1
    while any(os.path.exists(os.path.join(d, "%s.%s" % (cand, e))) for e in exts):
        i += 1
        cand = "%s-%d" % (stem, i)
    return cand


def save_precheck_reports(book, result, out_dir=None):
    """预审报告写入 data/<书名>/review/，文件名前缀 signing_ 与单章报告区分。"""
    d = out_dir or os.path.join(book_dir(book), "review")
    os.makedirs(d, exist_ok=True)
    stem = unique_report_stem(d, "signing_%s" % datetime.now().strftime("%Y%m%d-%H%M%S"))
    paths = {}
    for ext, content in (("json", json.dumps(result, ensure_ascii=False, indent=2)),
                         ("md", render_precheck_md(result))):
        p = os.path.join(d, "%s.%s" % (stem, ext))
        with open(p, "w", encoding="utf-8") as f:
            f.write(content)
        paths[ext] = os.path.relpath(p, ROOT).replace("\\", "/")
    return paths


# ---------------------------------------------------------------- 命令行
def main():
    ap = argparse.ArgumentParser(description="AI 审查：对单章正文做只诊断不改写的问题审查；--signing 做跨章签约预审")
    ap.add_argument("--book", required=True, help="书名（data/<书名>/）")
    ap.add_argument("--signing", action="store_true",
                    help="签约预审：扫前 2 万字（≈前 10 章），不需 --chapter-no / 正文文件")
    ap.add_argument("--chapter-no", default="", help="章节号，如 12 / 第12章")
    ap.add_argument("--text-file", help="单章正文文件（自动识别 UTF-8/GBK）")
    ap.add_argument("--text", help="单章正文（也可直接传字符串）")
    ap.add_argument("--checks", default=",".join(ALL_CHECKS),
                    help="要跑的检查项，逗号分隔（默认全跑）：" + " / ".join(ALL_CHECKS))
    ap.add_argument("--top-n", type=int, default=DEFAULT_TOP_N, help="生成建议的 Top 问题条数")
    ap.add_argument("--advice-scope", default=DEFAULT_ADVICE_SCOPE, choices=sorted(ADVICE_SCOPES),
                    help="建议范围：ai=仅 AI 味（默认）；all=全部问题类型")
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--base-url", default=None, help=f"默认 {DEFAULT_BASE_URL}（或环境变量 DEEPSEEK_BASE_URL）")
    ap.add_argument("--api-key", default=None, help="默认读环境变量 DEEPSEEK_API_KEY")
    ap.add_argument("--no-save", action="store_true", help="只打印报告，不落盘")
    ap.add_argument("--dry-run", action="store_true", help="只加载基准并统计调用规模，不调 API")
    args = ap.parse_args()

    if args.signing:
        # 签约预审：跨章扫前 2 万字，程序初筛 + 一次模型复核，报告前缀 signing_
        result = run_signing_precheck(args.book, model=args.model, base_url=args.base_url,
                                      api_key=args.api_key, on_log=lambda m: print(m))
        print()
        print(render_precheck_md(result))
        if not args.no_save:
            paths = save_precheck_reports(args.book, result)
            print("[完成] 报告已写出：" + "、".join(paths.values()))
        return
    if not args.chapter_no:
        sys.exit("[x] 单章审查需 --chapter-no；跨章签约预审请用 --signing")

    text = args.text
    if not text and args.text_file:
        text = read_text_file(resolve(args.text_file))
    if not text:
        sys.exit("[x] 请提供章节正文：--text-file <文件> 或 --text <正文>")

    base = load_baseline(args.book, args.chapter_no)
    paragraphs, sentences = split_segments(text.strip())
    print(f"[i] 书《{args.book}》第 {args.chapter_no} 章"
          + (f"《{base['title']}》" if base["title"] else ""))
    print(f"[i] 正文 {len(text.strip())} 字 → {len(paragraphs)} 段 / {len(sentences)} 句")
    print(f"[i] 基准：简介/大纲 {'✔' if base['has_synopsis'] else '✘'}｜"
          f"本章概览 {'✔' if base['has_chapter_summary'] else '✘'}｜"
          f"角色卡 {base['n_cards']}｜势力卡 {base['n_factions']}｜"
          f"设定库 {'✔' if base['has_setting'] else '✘'}")
    for n in base["notes"]:
        print(f"    · {n}")

    checks = [c.strip() for c in (args.checks or "").split(",") if c.strip() in CHECK_LABEL]
    if not checks:
        sys.exit(f"[x] --checks 没有有效项，可选：{' / '.join(ALL_CHECKS)}")

    if args.dry_run:
        n = sum(1 for c in checks if c != "advice" and c not in NO_CALL_CHECKS)
        print(f"[dry-run] 将执行：{'、'.join(CHECK_LABEL[c] for c in checks)}（约 {n} 次模型调用）")
        print(f"[dry-run] model={args.model} base_url={resolve_base_url(args.base_url)}")
        return

    result = run_review(args.book, args.chapter_no, text, checks=checks, model=args.model,
                        base_url=args.base_url, api_key=args.api_key, top_n=args.top_n,
                        advice_scope=args.advice_scope, on_log=lambda m: print(m))
    print()
    print(render_markdown(result))
    if not args.no_save:
        paths = save_reports(args.book, args.chapter_no, result)
        print("[完成] 报告已写出：")
        for k, p in paths.items():
            print(f"       {p}")


if __name__ == "__main__":
    main()
