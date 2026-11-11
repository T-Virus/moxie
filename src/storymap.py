#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
设定图谱：基于拆解产出（chapters.json / decomposed.json）生成 data/<书名>/storymap.json
——人物关系图谱 / 世界观设定 / 关键道具 / 一致性信息。

迭代设计：只读拆解与改编的既有产物，不改动它们的任何输出结构。
程序统计（出场章数、首现章、词条来源章、伏笔跟踪）保底，
至多一次 AI 调用补齐（卷分组 / 关系边 / 道具卡 / 一致性冲突）；AI 不可用自动降级。
"""

import argparse
import json
import os
import re
import sys
import datetime

SRC_DIR = os.path.dirname(os.path.abspath(__file__))
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

from paths import book_dir, book_chapters, book_decomposed  # noqa: E402
from deepseek_common import DEFAULT_MODEL, chat_json, resolve_base_url         # noqa: E402
from story_bible import RELATION_KINDS, all_relations, all_faction_relations  # noqa: E402


def _read_json(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def _no_of(ch, i):
    """章节号：chapter_id / chapter / no 里的第一个数字，都没有就按顺序号。"""
    for k in ("chapter_id", "chapter", "no"):
        m = re.search(r"(\d+)", str(ch.get(k) or ""))
        if m:
            return int(m.group(1))
    return i + 1


def _as_list(v):
    return v if isinstance(v, list) else []


def _as_dict(v):
    return v if isinstance(v, dict) else {}


def _s(v):
    return str(v or "").strip()


def _int(v, default=0):
    """AI 偶尔把章号写成「第3章」「3-5」，取第一个整数，失败回退 default。"""
    if isinstance(v, bool):
        return default
    if isinstance(v, (int, float)):
        return int(v)
    m = re.search(r"\d+", _s(v))
    return int(m.group(0)) if m else default


def _clean_name(s):
    """人名/术语归一：去括注（主角）、去书名号与引号空白，用于宽松匹配。"""
    s = _s(s)
    s = re.sub(r"[（(][^）)]*[）)]", "", s)
    return re.sub(r"[《》〈〉「」『』“”\"'·\s]", "", s)


def _match_name(name, names):
    """把 AI 写出的人名对齐到节点里的标准名：全等 → 去括注全等 → 互相包含。"""
    raw = _s(name)
    if not raw:
        return ""
    if raw in names:
        return raw
    clean = _clean_name(raw)
    if not clean:
        return ""
    if clean in names:
        return clean
    for n in names:
        if len(n) >= 2 and (n in clean or clean in n):
            return n
    return ""


# ---------------------------------------------------------------- 程序统计
def build_nodes(cards, chapters):
    """人物节点：出场章数 / 首现章来自逐章 roles 统计；desc 用角色卡身份+目标。

    逐章 roles 偶有「陈实（主角）」这类带括注写法，先按角色卡标准名对齐再计数，
    避免同名同人被拆成两个节点（一个 count=0、一个 count=N）。
    """
    std = []
    for c in cards:
        name = _s(c.get("name"))
        if name and name not in std:
            std.append(name)
    appears, first = {}, {}
    for i, ch in enumerate(chapters):
        no = _no_of(ch, i)
        for r in ch.get("roles") or []:
            raw = _s(r)
            if not raw:
                continue
            name = _match_name(raw, std) or raw
            appears[name] = appears.get(name, 0) + 1
            first.setdefault(name, no)
    nodes, seen = [], set()
    for c in cards:
        name = _s(c.get("name"))
        if not name or name in seen:
            continue
        seen.add(name)
        nodes.append({
            "name": name, "role": _s(c.get("role")), "gender": _s(c.get("gender")),
            # 人设倾向 / 对主角态度 / 势力两层 / 关键关系：节点详情直接回显角色卡
            "alignment": _s(c.get("alignment")), "stance": _s(c.get("stance")),
            "factionCategory": _s(c.get("factionCategory")),
            "factionName": _s(c.get("factionName")) or _s(c.get("faction")),
            "subFaction": _s(c.get("subFaction")), "loyalty": _s(c.get("loyalty")),
            "relationTo": _s(c.get("relationTo")), "relationType": _s(c.get("relationType")),
            "relationStrength": _s(c.get("relationStrength")),
            "identity": _s(c.get("identity")), "goal": _s(c.get("goal")),
            "count": appears.get(name, 0), "first": first.get(name, 0),
        })
    for r, cnt in sorted(appears.items(), key=lambda kv: -kv[1]):
        if r not in seen:
            seen.add(r)
            nodes.append({"name": r, "role": "", "gender": "", "alignment": "",
                          "stance": "", "factionCategory": "", "factionName": "",
                          "subFaction": "", "loyalty": "", "relationTo": "", "relationType": "",
                          "relationStrength": "", "identity": "", "goal": "",
                          "count": cnt, "first": first.get(r, 0)})
    nodes.sort(key=lambda n: (-n["count"], n["first"] or 99999))
    return nodes


def structured_edges(nodes, cards):
    """人物卡里的结构化关系 → 图谱边（主关系 + 「其他关系」）。

    每条边带 type/strength/direction/secret，前端据此上色、加粗、画虚线、加箭头：
    关系类型描述「两人之间是什么关系」，人设倾向与对主角态度都不参与连边。
    """
    names = {n["name"] for n in nodes}
    out, seen_pairs = [], set()
    for c in cards or []:
        nm = _match_name(_s(c.get("name")), names)
        if not nm:
            continue
        for r in all_relations(c):
            to = _match_name(_s(r.get("target")), names)
            if not to or to == nm:
                continue
            pair = tuple(sorted((nm, to)))
            if pair in seen_pairs:      # 一对人物只留一条（主关系在前，优先保留）
                continue
            seen_pairs.add(pair)
            out.append({"a": nm, "b": to, "label": r.get("type") or "",
                        "strength": r.get("strength") or "",
                        "direction": r.get("direction") or "双向",
                        "secret": r.get("isPublic") == "否",
                        "from": "card"})
    return out


def fallback_edges(nodes, chapters, cards=None):
    """程序统计版关系：优先用人物卡的结构化关系（关系对象 + 18 类关系类型），
    其次按逐章同场共现补全；无 AI 也能画出有意义的关系网。
    对主角态度（己方 / 敌对）不是关系类型，不参与连边。"""
    names = {n["name"] for n in nodes}
    cnt = {n["name"]: n["count"] for n in nodes}

    # 1) 结构化边：关系对象 + 关系类型（含其他关系）
    sem = structured_edges(nodes, cards)
    seen_pairs = {tuple(sorted((e["a"], e["b"]))) for e in sem}

    # 2) 同场共现边（补充分支）
    ch_sets = []
    for ch in chapters:
        s = set()
        for r in (ch.get("roles") or []):
            raw = _s(r)
            if not raw:
                continue
            nm = _match_name(raw, names) or raw
            if nm in names:
                s.add(nm)
        if len(s) > 1:
            ch_sets.append(s)
    co = {}
    for s in ch_sets:
        lst = sorted(s)
        for i in range(len(lst)):
            for j in range(i + 1, len(lst)):
                p = (lst[i], lst[j])
                co[p] = co.get(p, 0) + 1
    co_edges = []
    co_seen = set()
    for (a, b), c in sorted(co.items(), key=lambda kv: -kv[1]):
        if c < 2 or cnt.get(a, 0) < 2 or cnt.get(b, 0) < 2:
            continue
        key = tuple(sorted((a, b)))
        if key in co_seen:
            continue
        co_seen.add(key)
        co_edges.append({"a": a, "b": b, "label": "共%d章" % c})

    # 合并：语义边优先，共现边补全，总上限 30
    edges, seen = [], set()
    for e in sem + co_edges:
        key = tuple(sorted((e["a"], e["b"])))
        if key in seen:
            continue
        seen.add(key)
        edges.append(e)
        if len(edges) >= 30:
            break
    return edges



def build_faction_graph(factions):
    """势力节点 + 势力间关系边（明面 / 暗中）。
    边来自每个势力的「主关系」与「其他关系」（all_faction_relations 已归一类型 / 公开性）。"""
    fac_names = {_s(f.get("name")) for f in (factions or []) if _s(f.get("name"))}
    nodes = []
    for f in factions or []:
        nm = _s(f.get("name"))
        if not nm:
            continue
        nodes.append({"name": nm, "category": _s(f.get("category")),
                      "stance": _s(f.get("stance")), "relTo": _s(f.get("relTo")),
                      "relType": _s(f.get("relType")), "desc": _s(f.get("desc"))})
    edges, seen = [], set()
    for f in factions or []:
        nm = _s(f.get("name"))
        if not nm:
            continue
        for r in all_faction_relations(f):
            to = _match_name(_s(r.get("target")), fac_names)
            if not to or to == nm:
                continue
            pair = tuple(sorted((nm, to)))
            if pair in seen:
                continue
            seen.add(pair)
            secret = _s(r.get("isPublic")) == "否"
            edges.append({"a": nm, "b": to, "label": _s(r.get("type")) or "关联",
                          "strength": _s(r.get("strength")),
                          "direction": "双向", "secret": secret, "from": "card"})
    return nodes, edges


def build_foreshadows(plot, fields):
    """伏笔回收对照：从剧情脉络 foreshadow 与设定库 foreshadow 字段，拆出「埋下」与「回收」两半；
    尽量识别回收章号（文本里的「第N章 / 第N回」）。"""
    out, seen = [], set()
    def _add(text):
        text = re.sub(r"\s+", " ", _s(text)).strip()
        if len(text) < 6 or text in seen:
            return
        seen.add(text)
        m = re.search(r"第?\s*(\d+)\s*[章回]", text)
        pay_ch = int(m.group(1)) if m else ""
        cut = re.split(r"(揭晓|回收|揭露|道出|水落石出|真相|浮出|最终|后来|终于|第\d+[章回])", text, 1)
        seed = cut[0].strip("，。；：、 ")
        payoff = (cut[1] + (cut[2] if len(cut) > 2 else "")).strip("，。；：、 ") if len(cut) > 1 else ""
        out.append({"text": text, "seed": seed[:42], "payoff": payoff[:42],
                    "chapter": pay_ch, "status": "已回收" if pay_ch or payoff else "待确认"})
    for s in _as_list((plot or {}).get("foreshadow")) or []:
        _add(s)
    for line in re.split(r"[\n；;]+", _s(fields.get("foreshadow"))):
        _add(line)
    return out[:12]


def build_item_links(items, names=None):
    """道具流向：持有变更（holder 里 A → B）+ 持有者（holder 里的角色名）+ 道具间克制 / 合成（effect 文本）。"""
    links, seen = [], set()
    def _add(l):
        k = (l["item"], l["type"], l["from"], l["to"])
        if not l["from"] or not l["to"] or l["from"] == l["to"] or k in seen:
            return
        seen.add(k); links.append(l)
    name_set = {_s(n) for n in (names or []) if _s(n)}
    for it in items or []:
        nm = _s(it.get("name"))
        if not nm:
            continue
        holder = _s(it.get("holder"))
        m = re.search(r"([^→\-—~]+?)\s*[→\-—~]\s*([^→\-—~]+)", holder)
        if m:
            _add({"item": nm, "type": "transfer", "from": _s(m.group(1)), "to": _s(m.group(2)), "note": "持有变更"})
        else:
            for seg in re.split(r"[、，,；;]", holder):
                who = _s(seg).strip()
                if who and who in name_set:
                    _add({"item": nm, "type": "owner", "from": nm, "to": who, "note": "持有"})
        effect = _s(it.get("effect"))
        for tgt in re.findall(r"克制\s*([\u4e00-\u9fa5A-Za-z0-9]{1,10})", effect):
            if tgt != nm:
                _add({"item": nm, "type": "counter", "from": nm, "to": tgt, "note": "克制"})
        for tgt in re.findall(r"被\s*([\u4e00-\u9fa5A-Za-z0-9]{1,10})\s*克制", effect):
            _add({"item": nm, "type": "counter", "from": tgt, "to": nm, "note": "被克制"})
    return links[:40]


def build_time_events(chapters, plot, volumes):
    """时间轴锚点：卷界 + 时间线事件（带章节坐标），供前端画 X 轴时间线。"""
    events = []
    for v in volumes or []:
        events.append({"chapter": _int(v.get("from")), "lane": "volume",
                       "text": _s(v.get("title")), "anchor": True})
    tls = _as_list((plot or {}).get("timeline")) or []
    for i, t in enumerate(tls):
        st = _s(t)
        m = re.search(r"第?\s*(\d+)\s*[章回]", st)
        no = int(m.group(1)) if m else (i + 1)
        events.append({"chapter": no, "lane": "event", "text": st[:40]})
    return events


def build_chmeta(chapters):
    return [{"no": _no_of(ch, i), "title": _s(ch.get("title")),
             "summary": _s(ch.get("summary")),
             "points": [_s(p) for p in (ch.get("points") or [])],
             "roles": [_s(r) for r in (ch.get("roles") or [])]}
            for i, ch in enumerate(chapters)]


def build_emotion_flow(chapters):
    """情绪流曲线 / 钩子 / 爽点 / 铺垫：直接吃拆解阶段标好的字段。

    不再让模型在这里重算一遍——同一份数据两处算，必然打架；
    而且这些字段是「读者体感」的锚点，程序搬运比模型复述可靠。
    """
    curve, hooks, payoffs, setups = [], [], [], []
    for i, ch in enumerate(chapters or []):
        no = _no_of(ch, i)
        emo, ten = _s(ch.get("emotion")), _int(ch.get("tension"))
        if emo or ten:
            curve.append({"chapter": no, "emotion": emo, "tension": ten})
        ht, hk = _s(ch.get("hook_type")), _s(ch.get("hook"))
        if ht or hk:
            hooks.append({"chapter": no, "type": ht, "text": hk[:90]})
        if _s(ch.get("payoff")):
            payoffs.append({"chapter": no, "text": _s(ch.get("payoff"))[:90]})
        if _s(ch.get("setup")):
            setups.append({"chapter": no, "text": _s(ch.get("setup"))[:90]})
    return curve, hooks, payoffs, setups


def build_fallback_plot(chapters, dec, volumes, conflicts=None):
    """程序统计版剧情脉络（无 AI 时的保底）：卷首/中/尾代表章摘要串成时间线，卷界生成主线阶段，一致性冲突并入冲突节点。"""
    n = len(chapters)
    if not n:
        return {}
    nums = [_no_of(c, i) for i, c in enumerate(chapters)]
    tl, seen_no = [], set()
    for v in (volumes or []):
        f, t = _int(v.get("from")), _int(v.get("to"))
        idxs = [i for i, no in enumerate(nums) if f <= no <= t]
        if not idxs:
            continue
        for j in (0, len(idxs) // 2, len(idxs) - 1):
            i = idxs[j]
            no = nums[i]
            if no in seen_no:
                continue
            s = _s(chapters[i].get("summary"))
            if not s:
                continue
            seen_no.add(no)
            tl.append(f"第{no}章《{_s(chapters[i].get('title'))}》：{s[:40]}")
            if len(tl) >= 12:
                break
        if len(tl) >= 12:
            break
    if len(tl) < 4:
        tl = [x.strip() for x in re.split(r"[。\n]", _s(dec.get("book_summary"))) if len(x.strip()) > 4][:10]
    mainline = [f"{_s(v.get('title'))}：第{_int(v.get('from'))}–{_int(v.get('to'))}章" for v in (volumes or [])][:6]
    conflict = [c.get("title") for c in (conflicts or []) if c.get("title")][:4]
    return {"timeline": tl, "mainline": mainline, "subplots": [], "foreshadow": [],
            "suspense": [], "conflict": conflict}


def _probe_keys(text):
    """从一条设定里取若干可检索片段：全句 → 按标点切出的分句 → 前缀。"""
    t = re.sub(r"[【】\[\]「」『』（）()《》]", " ", _s(text))
    t = re.sub(r"\s+", "", t).strip("·-—:：,，。;；、")
    if len(t) < 2:
        return []
    keys = [t] if len(t) <= 14 else []
    for seg in re.split(r"[：:，,。；;、]", t):
        seg = seg.strip()
        if len(seg) >= 4:
            keys.append(seg[:14])
    keys.append(t[:12])
    out = []
    for k in keys:
        if len(k) >= (2 if len(t) <= 6 else 3) and k not in out:
            out.append(k)
    return out[:6]


def chapters_mentioning(text, chapters, limit=6):
    """词条在哪些章被提及（标题+摘要+事件要点），用于「来源：第 N 章」。"""
    keys = _probe_keys(text)
    if not keys:
        return []
    hits = []
    for i, ch in enumerate(chapters):
        blob = " ".join([_s(ch.get("title")), _s(ch.get("summary")),
                         " ".join(_s(p) for p in (ch.get("points") or []))])
        if blob and any(k in blob for k in keys):
            hits.append(_no_of(ch, i))
    return hits[:limit]


def _split_points(line):
    """设定库常把同一类内容写成「甲、乙、丙」，拆成独立条目更好读也好溯源。"""
    out = []
    for seg in re.split(r"[\n；;。]+", _s(line)):
        seg = seg.strip().strip("·-、：: ")
        if not seg:
            continue
        # 括号里的顿号不切（如「底牌道具（命运火种、灰烬涅槃火）」）
        parts = [p.strip() for p in re.split(r"、(?![^（）()]*[）)])", seg) if p.strip()]
        if len(parts) >= 3 and all(len(p) <= 24 for p in parts):
            out.extend(parts)
        else:
            out.append(seg)
    return out


def fallback_worldview(fields, chapters):
    groups = []
    for gname, keys in (("修炼体系", ["power"]), ("地理势力", ["places"]),
                        ("核心规则", ["terms", "taboos"])):
        pts, seen = [], set()
        for k in keys:
            for line in _split_points(fields.get(k)):
                line = line.strip().strip("·-、：: ")
                if len(line) < 2 or line in seen:
                    continue
                seen.add(line)
                pts.append({"text": line,
                            "chapters": chapters_mentioning(line, chapters)})
        if pts:
            groups.append({"group": gname, "points": pts[:10]})
    return groups


def fallback_items(fields, chapters):
    """设定库「关键道具」常是一行「、」并列的清单，需拆成单件。"""
    items = []
    for line in re.split(r"[\n]+", _s(fields.get("items"))):
        line = line.strip().strip("·- ")
        if not line:
            continue
        parts = re.split(r"[：:——]", line, 1)
        names = [n.strip() for n in parts[0].split("、") if n.strip()]
        effect = parts[1].strip() if len(parts) > 1 else ""
        for name in names:
            if len(name) < 2 or len(name) > 18:
                continue
            items.append({"name": name, "holder": "", "effect": effect,
                          "chapters": chapters_mentioning(name, chapters), "note": ""})
    return items


def fallback_conflicts(fields, chapters):
    """无 AI 时的一致性保底：伏笔清单 → 待回收跟踪。"""
    out, seen = [], set()
    for line in re.split(r"[\n]+", _s(fields.get("foreshadow"))):
        line = line.strip().strip("·- ")
        if len(line) < 4 or line in seen:
            continue
        seen.add(line)
        # 标题带上伏笔前半句，避免八条卡片全叫「伏笔跟踪（待回收）」
        head = re.split(r"[，。；：、]", line, 1)[0][:14]
        out.append({"title": f"伏笔待回收：{head}", "detail": line,
                    "severity": "低", "chapters": chapters_mentioning(line, chapters)})
        if len(out) >= 8:
            break
    return out


MAP_LEVELS = ["世界", "区域", "地点"]


def _place_groups(text):
    """设定库「重要地点」→ [(父区域, [子地点…])] 或 [(地点, [])]。

    常见写法「江州市城区与郊区：旧巷出租房、栖霞里、仁济医院…；核心区：…」，
    冒号前是区域，冒号后是区域内的具体地点。
    """
    groups = []
    for seg in re.split(r"[；;\n]+", _s(text)):
        seg = seg.strip().strip("·- ")
        if not seg:
            continue
        m = re.match(r"^([^：:]{1,24})[：:](.+)$", seg)
        parent, rest = (m.group(1).strip(), m.group(2)) if m else ("", seg)
        kids = [x.strip(" ·-") for x in re.split(r"[、，,/]+", rest) if x.strip(" ·-")]
        kids = [k for k in kids if 1 < len(k) <= 24]
        if parent and kids:
            groups.append((parent, kids))
        else:
            groups.extend((k, []) for k in kids)
    return groups


def _map_region(name, parent, kind, desc="", chapters=None):
    return {"name": name, "parent": parent, "kind": kind, "desc": _s(desc),
            "chapters": sorted({int(x) for x in (chapters or []) if str(x).isdigit()})}


def fallback_map(fields, chapters, cards, factions):
    """无 AI 时的地图保底：从「重要地点 / 地图设定 / 世界观」拆出区域层级，
    再用逐章 roles / factions 把角色与势力落到章节摘要里出现的地点。"""
    text = _s(fields.get("places")) or _s(fields.get("map")) or _s(fields.get("world"))
    groups = _place_groups(text)
    regions, seen = [], set()

    def add(name, parent, kind, desc=""):
        name = _s(name)[:24]
        if not name or name in seen:
            return
        seen.add(name)
        regions.append(_map_region(name, parent if parent in seen else "", kind, desc))

    for parent, kids in groups:
        if not parent:
            for kid in kids:
                add(kid, "", "地点")
            continue
        add(parent, "", "区域")
        for kid in kids:
            add(kid, parent, "地点")
    if not regions:
        # 地点字段完全没写时，至少给出一个可用容器，避免地图页空着
        add("故事发生地", "", "区域")

    leaf_names = [r["name"] for r in regions if r["parent"]]
    all_names = [r["name"] for r in regions]
    order = sorted(leaf_names or all_names, key=len, reverse=True)
    card_names = [_s(c.get("name")) for c in cards if _s(c.get("name"))]
    fac_names = [_s(f.get("name")) for f in factions if _s(f.get("name"))]

    scenes = []
    for i, ch in enumerate(chapters):
        no = _no_of(ch, i)
        blob = " ".join([_s(ch.get("title")), _s(ch.get("summary"))]
                        + [_s(x) for x in (ch.get("points") or [])])
        region = next((n for n in order if n and n in blob), "")
        if not region:
            continue
        chars, facs = [], []
        for x in ch.get("roles") or []:
            n = _match_name(x, card_names)
            if n and n not in chars:
                chars.append(n)
        for x in ch.get("factions") or []:
            n = _match_name(x, fac_names)
            if n and n not in facs:
                facs.append(n)
        scenes.append({"chapter": no, "region": region, "characters": chars,
                       "factions": facs, "items": [],
                       "event": (_s(ch.get("title")) or _s(ch.get("summary"))[:40])[:120]})
    return {"levels": list(MAP_LEVELS), "regions": regions, "scenes": scenes[:600]}


def normalize_map(raw, chapters, cards, factions, fields):
    """AI 地图 JSON → 前端可渲染的层级；对不上的人物 / 势力 / 地点一律丢弃，
    保证地图上的每个点都能点回真实卡片。"""
    raw = _as_dict(raw)
    max_no = max((_no_of(c, i) for i, c in enumerate(chapters)), default=0)
    levels = [_s(x) for x in _as_list(raw.get("levels")) if _s(x)][:4]
    if not levels:
        levels = list(MAP_LEVELS)

    regions, seen = [], set()
    for r in _as_list(raw.get("regions")):
        r = _as_dict(r)
        name = _s(r.get("name"))[:24]
        if not name or name in seen:
            continue
        seen.add(name)
        regions.append(_map_region(name, _s(r.get("parent"))[:24],
                                   _s(r.get("kind")) or "地点",
                                   _s(r.get("desc"))[:200],
                                   _norm_chapters(r.get("chapters"), chapters)))
    if not regions:
        return fallback_map(fields, chapters, cards, factions)

    # 父级必须是已有区域；成环 / 指到自己的按根级处理
    names = {r["name"] for r in regions}
    for r in regions:
        p = r.get("parent") or ""
        if p not in names or p == r["name"]:
            r["parent"] = ""
    for r in regions:                       # 断开环（A→B→A）
        seen_chain, cur = set(), r
        while cur.get("parent"):
            if cur["name"] in seen_chain:
                r["parent"] = ""
                break
            seen_chain.add(cur["name"])
            cur = next((x for x in regions if x["name"] == cur["parent"]), None)
            if cur is None:
                r["parent"] = ""
                break

    card_names = [_s(c.get("name")) for c in cards if _s(c.get("name"))]
    fac_names = [_s(f.get("name")) for f in factions if _s(f.get("name"))]
    region_names = sorted(names, key=len, reverse=True)
    scenes, seen_scene = [], set()
    for s in _as_list(raw.get("scenes")):
        s = _as_dict(s)
        no = _int(s.get("chapter"), 0)
        if not (1 <= no <= max_no):
            continue
        region = _s(s.get("region"))
        if region and region not in names:
            region = next((n for n in region_names if n in region or region in n), "")
        chars, facs, its = [], [], []
        for x in _as_list(s.get("characters")):
            n = _match_name(x, card_names)
            if n and n not in chars:
                chars.append(n)
        for x in _as_list(s.get("factions")):
            n = _match_name(x, fac_names)
            if n and n not in facs:
                facs.append(n)
        for x in _as_list(s.get("items")):
            n = _s(x)[:24]
            if n and n not in its:
                its.append(n)
        event = _s(s.get("event"))[:120]
        key = (no, region, event)
        if key in seen_scene:
            continue
        seen_scene.add(key)
        scenes.append({"chapter": no, "region": region, "characters": chars,
                       "factions": facs, "items": its, "event": event})

    # AI 没写场景（或全部对不上）时，仍用逐章数据补一层，地图不至于只剩空区域
    if not scenes:
        scenes = fallback_map(fields, chapters, cards, factions)["scenes"]
    return {"levels": levels, "regions": regions, "scenes": scenes[:600]}


def fallback_volumes(chapters):
    n = len(chapters)
    if not n:
        return []
    nums = [_no_of(c, i) for i, c in enumerate(chapters)]
    if n < 6:
        return [{"title": "全部章节", "from": nums[0], "to": nums[-1]}]
    per = max(1, round(n / 3))
    out = []
    for k in range(0, n, per):
        part = nums[k:k + per]
        out.append({"title": f"第{len(out) + 1}卷", "from": part[0], "to": part[-1]})
    return out


def volumes_from_field(chapters):
    """章节自带 volume 字段时以它为准（与章节树的分卷一致）。"""
    vols, cur = [], None
    for i, ch in enumerate(chapters):
        name = _s(ch.get("volume") or ch.get("vol"))
        no = _no_of(ch, i)
        if not name:
            return []
        if cur and cur["title"] == name:
            cur["to"] = no
        else:
            cur = {"title": name, "from": no, "to": no}
            vols.append(cur)
    return vols


def normalize_volumes(volumes, chapters):
    """按章节顺序重新切分卷界：保证每章恰好属于一卷，无缝隙、无重叠。"""
    nums = [_no_of(c, i) for i, c in enumerate(chapters)]
    if not nums:
        return []
    if len(volumes) <= 1:
        title = _s(volumes[0].get("title")) if volumes else "全部章节"
        return [{"title": title or "全部章节", "from": nums[0], "to": nums[-1]}]
    lo, hi = nums[0], nums[-1]
    items = []
    for v in sorted([v for v in volumes if isinstance(v, dict)],
                    key=lambda x: _int(x.get("from"), 0))[:6]:
        try:
            f = int(v.get("from") or lo)
        except (TypeError, ValueError):
            f = lo
        f = min(max(f, lo), hi)
        idx = next((i for i, n in enumerate(nums) if n >= f), len(nums) - 1)
        title = _s(v.get("title")) or f"第{len(items) + 1}卷"
        if items and items[-1][0] == idx:
            continue
        items.append((idx, title))
    if not items:
        return fallback_volumes(chapters)
    if items[0][0] != 0:
        items[0] = (0, items[0][1])
    out = []
    for k, (s, title) in enumerate(items):
        e = (items[k + 1][0] - 1) if k + 1 < len(items) else len(nums) - 1
        if e >= s:
            out.append({"title": title, "from": nums[s], "to": nums[e]})
    return out or fallback_volumes(chapters)


# ---------------------------------------------------------------- AI 补齐
SYSTEM_PROMPT = """你是网文设定编辑与连续性校对。你只输出一个 JSON 对象，不要解释，不要代码块围栏。
判断标准：
1. 只依据给定材料，不脑补原著没有的设定、人物或道具；材料没有的字段留空数组。
2. 关系边与一致性冲突必须能在材料里找到依据（人物同章出场、摘要里明说、设定库写明）。
3. worldview 固定三组，group 只能是「修炼体系」「地理势力」「核心规则」，顺序不变，各 3~8 条；材料不足的分组可少写或留空，不凑数。
4. 冲突只报真矛盾（数量/年龄/境界/规则/时间线前后不一致），同一问题不重复报。"""

AI_SCHEMA_NOTE = """{
 "volumes": [{"title": "第一卷·xxx", "from": 1, "to": 30}],
 "edges": [{"a": "角色A", "b": "角色B", "type": "18 类关系之一，如 君臣/师徒/旧友/仇敌",
            "strength": 0.8, "direction": "双向|单向", "secret": false}],
 "items": [{"name": "道具名", "holder": "当前持有人或 A → B", "effect": "作用一句话",
            "chapters": [1, 45], "note": "数量/限制备注，没有则空"}],
 "worldview": [{"group": "修炼体系|地理势力|核心规则 三选一",
                "points": [{"text": "条目一句话", "chapters": [3]}]}],
 "era": "时代背景一句话（含时间跨度）",
 "conflicts": [{"title": "冲突标题", "detail": "第X章说…，第Y章说…",
                "severity": "高|中|低", "chapters": [40, 66]}],
 "plot": {
   "timeline": ["按因果/时序推进的关键事件，一句话一条，6~14 条"],
   "mainline": ["全书主线阶段，3~6 条"],
   "subplots": ["支线 / 情感线，3~8 条"],
   "foreshadow": ["伏笔与回收，3~8 条"],
   "suspense": ["核心悬念，2~6 条"],
   "conflict": ["核心冲突，2~4 条"]
 },
 "map": {
   "levels": ["世界", "区域", "地点"],
   "regions": [{"name": "区域或地点名（与材料一致）", "parent": "上一级区域名，顶级留空",
                "kind": "区域|城市|街区|建筑|秘境", "desc": "一句话说明",
                "chapters": [1, 30]}],
   "scenes": [{"chapter": 1, "region": "该章主要发生的地点名",
               "characters": ["出场角色"], "factions": ["出场势力"],
               "items": ["涉及的关键道具"], "event": "在此地发生了什么，一句话"}]
 }
}"""


CH_LINES_CAP = 400


def _sample_chapters(chapters, cap=CH_LINES_CAP):
    """超长书按等比抽样：既保住开篇与结尾，又不让 prompt 撑爆上下文。"""
    n = len(chapters)
    if n <= cap:
        return [(i, c) for i, c in enumerate(chapters)], ""
    step = n / cap
    idx = sorted({int(i * step) for i in range(cap)} | {0, n - 1})
    picked = [(i, chapters[i]) for i in idx]
    note = (f"\n（全书共 {n} 章，为控制篇幅按等比抽样 {len(picked)} 章展示；"
            f"引用章号时以真实章号为准，未展示的章节能判定就不判定。）")
    return picked, note


def build_ai_prompt(dec, cards, factions, fields, chapters):
    ch_lines = []
    picked, sample_note = _sample_chapters(chapters)
    for i, ch in picked:
        summ = re.sub(r"\s+", "", _s(ch.get("summary")))[:60]
        roles = "、".join(_s(r) for r in (ch.get("roles") or []))
        no = _no_of(ch, i)
        title = _s(ch.get("title"))
        # 拆解没拿到真实小标题时 title 就是「第N章」，别再重复一遍
        if title and not re.fullmatch(r"第\s*\d+\s*[章回节]", title):
            head = f"第{no}章 {title}"
        else:
            head = f"第{no}章"
        ch_lines.append(f"{head}｜出场：{roles}｜{summ}")
    # 带上剧情功能 / 九宫格人设倾向 / 势力两层 / 对主角态度 / 结构化关系：图谱画点、连边、判断动机都要用
    def _fac_tag(c):
        cat, nm = _s(c.get("factionCategory")), _s(c.get("factionName"))
        if not nm:
            return ""
        return f"｜{cat}·{nm}" + (f"（{_s(c.get('subFaction'))}）" if _s(c.get("subFaction")) else "")

    def _rel_tag(c):
        to, rt = _s(c.get("relationTo")), _s(c.get("relationType"))
        if not (to or rt):
            return ""
        s = f"；关键关系：{to}·{rt}"
        if _s(c.get("relationStrength")):
            s += f"·强度{_s(c.get('relationStrength'))}"
        if _s(c.get("isPublic")) == "否":
            s += "·不公开"
        if _s(c.get("relations")):
            s += f"；其他关系：{_s(c.get('relations'))}"
        return s

    card_lines = [f"- {_s(c.get('name'))}（{_s(c.get('role'))}"
                  + (f"｜{_s(c.get('alignment'))}" if _s(c.get("alignment")) else "")
                  + _fac_tag(c)
                  + (f"｜对主角{_s(c.get('stance'))}" if _s(c.get("stance")) else "")
                  + f"）{_s(c.get('identity'))}"
                  f"；性格：{_s(c.get('personality'))[:20]}；目标：{_s(c.get('goal'))[:24]}"
                  + _rel_tag(c)
                  + f"；口头禅：{_s(c.get('catchwords'))[:12]}"
                  for c in cards if _s(c.get("name"))]
    kinds = "、".join(lb for _, lb, _, _ in RELATION_KINDS)
    # 名单按整名截断（硬切 600 字会把最后一个人名切成半截，模型会照着半截名写边）
    all_names = [n for n in (_s(c.get("name")) for c in cards) if n]
    picked_names, used = [], 0
    for n in all_names:
        if used + len(n) + 1 > 600:
            break
        picked_names.append(n)
        used += len(n) + 1
    name_line = "、".join(picked_names)
    if len(picked_names) < len(all_names):
        name_line += f"（另有 {len(all_names) - len(picked_names)} 人见角色卡）"
    # 带上大类 / 立场 / 势力之间关系：图谱 AI 判断势力与主角的关系、制造冲突时需要这层信息
    def _f_rel(f):
        if not _s(f.get("relTo")):
            return ""
        s = f"；对{_s(f.get('relTo'))}：{_s(f.get('relType'))}"
        if _s(f.get("relPublic")) == "否":
            s += "（不公开）"
        # 其他势力关系合成一行，避免 AI 只看到主关系
        if _s(f.get("relations")):
            s += f"；其他：{_s(f.get('relations'))}"
        return s

    fac_lines = [f"- {_s(f.get('name'))}（{_s(f.get('category'))}"
                 + (f"｜对主角{_s(f.get('stance'))}" if _s(f.get("stance")) else "")
                 + "）" + _s(f.get("desc")) + _f_rel(f)
                 for f in factions if _s(f.get("name"))]
    sb_lines = [f"【{k}】{_s(fields.get(k))}"
                for k in ("world", "power", "places", "items", "terms", "foreshadow", "taboos")
                if _s(fields.get(k))]
    # 写作公式视角的抽取要求（craft.py，源自用户写作设定；可在提示词模板库覆盖 craft.*）
    try:
        import craft
        craft_note = craft.storymap_guide()
    except Exception:  # noqa —— craft 缺失时不影响图谱主流程
        craft_note = ""
    return f"""请基于这部小说的设定与逐章信息，输出设定图谱 JSON，结构严格如下：

{AI_SCHEMA_NOTE}

要求：
1. 人名必须从【人物名单】里原样照抄，不得自造、改名、加括注；势力 / 术语也必须与材料一致。
2. volumes：按剧情节奏把全书分成 2~4 卷，from/to 为章号闭区间；第一卷从第 1 章起，末卷到最后一章止，中间不留空档。全书不足 20 章时可只给 1 卷（from=1，to=末章）。
3. edges：只写主要人物两两关系，10~20 条。type 只能从这 {len(RELATION_KINDS)} 类里选一个：{kinds}；
   strength 填 0~1 的小数（关系有多重）；direction 填「双向」或「单向」（暗恋 / 监视 / 利用 / 救命 是单向）；
   secret 填 true 或 false，表面敌对、暗地合作的填 true。
   角色卡已给出 relationType + relationTo 的那条关系优先照用，不要改写成别的说法；不要重复同一对人物。有名有姓的人物不足时按实际能确定的关系写，宁少不编。
   注意：人设倾向（守序善良 / 中立邪恶 等九宫格）是这个人的性格坐标，不是关系边，不要写进 type；
   「敌对」「己方」是对主角态度（stance），也不是关系类型。
4. items：从设定库「关键道具」与正文反复出现的信物中挑 5~15 件；holder 变更写「A → B」；没有依据不要臆造持有人。
5. worldview 三个分组各 3~8 条（材料确实不够的分组可少写甚至留空，不要凑数）；points.text 一句话说清规则，不要写成段落；points.chapters 给出该设定被确立或提及的章号。
6. conflicts：严格核查道具数量、人物年龄、境界 / 规则、时间线的前后矛盾，detail 必须写出「第X章说…，第Y章说…」的对照，引用章号；宁缺毋滥，最多 8 条，没有就给空数组。
7. plot（剧情脉络）：timeline 依因果与时序把全书关键事件串成推进链（6~14 条，每条一句话，须能按顺序读通）；mainline 提炼全书主线阶段；subplots / foreshadow / suspense / conflict 分别给支线情感、伏笔回收、核心悬念、核心冲突；都只依据材料，不臆造。
8. map（设定地图）：把全书拆成 2~4 级地理层级（levels，从大到小，如 世界 / 国家 / 城市 / 街区）。
   regions 给 8~30 个区域，parent 必须是 regions 里已出现的上一级名称（顶级留空），不能成环；
   name / kind / desc 只写材料里有依据的内容。scenes 按章给 6~40 条：region 必须是 regions 里的名称，
   characters 必须从【人物名单】照抄，factions 必须与【势力】一致，items 只写设定库「关键道具」里出现过的；
   event 写清「谁在这一章、在这个地方、做了什么」，没有明确地点依据的章可以不给。
{craft_note}

【人物名单】{name_line or "（无）"}
【全书梗概】{_s(dec.get("book_summary"))}
【角色卡】
{chr(10).join(card_lines) or "（无）"}
【势力】
{chr(10).join(fac_lines) or "（无）"}
【设定库】
{chr(10).join(sb_lines) or "（无）"}
【逐章】{sample_note}
{chr(10).join(ch_lines)}"""


def _norm_chapters(v, chapters):
    """章号列表归一：只保留 1..max_no 范围内的整数（容忍「第3章」这类写法）。"""
    max_no = len(chapters) and max(_no_of(c, i) for i, c in enumerate(chapters)) or 0
    out = []
    for x in _as_list(v):
        n = _int(x, 0)
        if 1 <= n <= max_no and n not in out:
            out.append(n)
    return out[:8]


def run_ai(api_key, base_url, model, dec, cards, factions, fields, chapters, timeout=1200, retries=2):
    base_url = resolve_base_url(base_url)
    data = chat_json(api_key, base_url, model, SYSTEM_PROMPT,
                     build_ai_prompt(dec, cards, factions, fields, chapters),
                     timeout=timeout, retries=retries, temperature=0.3)
    return _as_dict(data)


GROUP_ORDER = ["修炼体系", "地理势力", "核心规则"]


def normalize_groups(groups):
    """把 AI 乱起的组名归到固定三类，并去掉重复条目。"""
    bag = {}
    for g in groups or []:
        name = _s(g.get("group"))
        key = next((x for x in GROUP_ORDER if name and (x in name or name in x)), "核心规则")
        bucket = bag.setdefault(key, [])
        texts = {_s(p.get("text")) for p in bucket if isinstance(p, dict)}
        for p in g.get("points") or []:
            if not isinstance(p, dict):
                continue
            t = _s(p.get("text"))
            if t and t not in texts and len(bucket) < 10:
                bucket.append(p)
                texts.add(t)
    return [{"group": k, "points": bag[k]} for k in GROUP_ORDER if bag.get(k)]


PLOT_KEYS = ("timeline", "mainline", "subplots", "foreshadow", "suspense", "conflict")
PLOT_CAPS = {"timeline": 14, "mainline": 8, "subplots": 10,
             "foreshadow": 10, "suspense": 6, "conflict": 4}


def normalize_plot(ai):
    """把 AI 返回的 plot 归一成前端泳道图要的字符串数组；不够成链则整体作废（回退程序解析）。"""
    raw = _as_dict(ai.get("plot"))
    out = {}
    for k in PLOT_KEYS:
        vals = []
        for x in _as_list(raw.get(k)):
            if isinstance(x, dict):
                x = x.get("text") or x.get("title") or x.get("detail") or ""
            s = re.sub(r"\s+", " ", _s(x)).strip("·。-—:： ")
            if len(s) >= 4 and s not in vals:
                vals.append(s[:90])
            if len(vals) >= PLOT_CAPS[k]:
                break
        if vals:
            out[k] = vals
    return out if out.get("timeline") else {}


def merge_ai(ai, fields, chapters):
    """AI 结果 + 程序统计合并：AI 字段优先，缺失/非法处用程序结果兜底。"""
    # volumes
    volumes = []
    for v in _as_list(ai.get("volumes")):
        v = _as_dict(v)
        t, f, tt = _s(v.get("title")), _int(v.get("from")), _int(v.get("to"))
        if t and 0 < f <= tt:
            volumes.append({"title": t, "from": f, "to": tt})
    if not volumes:
        volumes = fallback_volumes(chapters)

    # edges：两端都必须是已知人物（main 里再按 nodes 名单对齐、去重）
    edges, pairs = [], set()
    for e in _as_list(ai.get("edges")):
        e = _as_dict(e)
        a, b = _s(e.get("a")), _s(e.get("b"))
        label = _s(e.get("type")) or _s(e.get("label"))
        label = label[:10]
        if not (a and b and label) or a == b:
            continue
        pair = tuple(sorted((a, b)))
        if pair in pairs:
            continue
        pairs.add(pair)
        secret = e.get("secret")
        secret = secret is True or _s(secret).lower() in ("true", "1", "是", "秘密")
        edges.append({"a": a, "b": b, "label": label,
                      "strength": _s(e.get("strength")),
                      "direction": _s(e.get("direction")) or "双向",
                      "secret": secret, "from": "ai"})

    # items
    items, seen_items = [], set()
    for it in _as_list(ai.get("items")):
        it = _as_dict(it)
        name = _s(it.get("name"))
        if not name or name in seen_items:
            continue
        seen_items.add(name)
        items.append({"name": name, "holder": _s(it.get("holder")),
                      "effect": _s(it.get("effect")),
                      "chapters": sorted(_norm_chapters(it.get("chapters"), chapters)
                                         or chapters_mentioning(name, chapters)),
                      "note": _s(it.get("note"))})
    if not items:
        items = fallback_items(fields, chapters)

    # worldview
    worldview = []
    for g in _as_list(ai.get("worldview")):
        g = _as_dict(g)
        gname = _s(g.get("group")) or "核心规则"
        pts = []
        for p in _as_list(g.get("points")):
            p = _as_dict(p)
            text = _s(p.get("text"))
            if not text:
                continue
            pts.append({"text": text,
                        "chapters": _norm_chapters(p.get("chapters"), chapters)
                        or chapters_mentioning(text, chapters)})
        if pts:
            worldview.append({"group": gname, "points": pts})
    if not worldview:
        worldview = fallback_worldview(fields, chapters)

    # conflicts：同一问题（标题+引用对照相同）只报一次
    conflicts, seen_conf = [], set()
    for c in _as_list(ai.get("conflicts")):
        c = _as_dict(c)
        t, d = _s(c.get("title")), _s(c.get("detail"))
        if not (t and d):
            continue
        key = (t, re.sub(r"\s+", "", d)[:60])
        if key in seen_conf:
            continue
        seen_conf.add(key)
        sev = _s(c.get("severity"))
        conflicts.append({"title": t, "detail": d,
                          "severity": sev if sev in ("高", "中", "低") else "中",
                          "chapters": _norm_chapters(c.get("chapters"), chapters)})
    worldview = normalize_groups(worldview)
    order = {"高": 0, "中": 1, "低": 2}
    conflicts.sort(key=lambda c: order.get(c["severity"], 3))
    return volumes, edges, items, worldview, conflicts


# ---------------------------------------------------------------- CLI
def main():
    ap = argparse.ArgumentParser(description="设定图谱：人物关系 / 世界观 / 关键道具 / 一致性")
    ap.add_argument("--book", required=True, help="书名（data/<书名>/）")
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--base-url", default=None)
    ap.add_argument("--api-key", default=None)
    ap.add_argument("--dry-run", action="store_true", help="只打印 prompt，不调 AI、不落盘")
    args = ap.parse_args()

    dec = _read_json(book_decomposed(args.book), {})
    chd = _read_json(book_chapters(args.book), {})
    chapters = [c for c in (chd.get("chapters") or dec.get("chapters") or [])
                if isinstance(c, dict)]
    if not chapters:
        sys.exit("[x] 该书没有章节数据，请先拆解/编辑章节")
    chapters = sorted(chapters, key=lambda c: _no_of(c, 0))   # 章节目录与卷界都按章号排

    # 设定库：优先 UI 编辑后保存的 story_bible 原文，其次 decomposed 的结构化字段
    fields, cards, factions = {}, [], []
    raw_sb = chd.get("story_bible")
    if not (isinstance(raw_sb, str) and raw_sb.strip()):
        raw_sb = dec.get("story_bible") if isinstance(dec.get("story_bible"), str) else ""
    if isinstance(raw_sb, str) and raw_sb.strip():
        from story_bible import parse as parse_story_bible
        fields, cards, factions = parse_story_bible(raw_sb)
    if not fields and isinstance(dec.get("story_bible"), dict):
        fields = dec.get("story_bible") or {}
    cards = [c for c in (cards or dec.get("characters") or []) if isinstance(c, dict)]
    factions = [f for f in (factions or dec.get("factions") or []) if isinstance(f, dict)]

    print(f"[图谱] 《{args.book}》{len(chapters)} 章 · 角色 {len(cards)} · 势力 {len(factions)}")
    nodes = build_nodes(cards, chapters)
    names = {n["name"] for n in nodes}

    ai, ai_ok = {}, False
    key = (_s(args.api_key) or os.environ.get("DEEPSEEK_API_KEY", "")).strip()
    if args.dry_run:
        print(build_ai_prompt(dec, cards, factions, fields, chapters))
        return
    if key:
        try:
            ai = run_ai(key, args.base_url, args.model, dec, cards, factions, fields, chapters)
            ai_ok = True
            print("[OK] AI 图谱分析完成（卷分组 / 关系 / 道具 / 一致性 / 剧情脉络）")
        except Exception as e:  # noqa
            print(f"[!] AI 分析失败，降级为程序统计：{e}")
    else:
        print("[!] 未配置 API Key，降级为程序统计（出场统计 / 词条来源 / 伏笔跟踪）")

    plot = {}
    if ai_ok:
        volumes, edges, items, worldview, conflicts = merge_ai(ai, fields, chapters)
        # 角色卡里人工确认过的关系优先：AI 边只作补充（同类人物对由下面的去重保先出现者）
        edges = structured_edges(nodes, cards) + edges
        era = _s(ai.get("era"))
        plot = normalize_plot(ai)
        map_data = normalize_map(ai.get("map"), chapters, cards, factions, fields)
        print(f"[剧情脉络] AI 生成：时间线 {len(plot.get('timeline') or [])} 条"
              if plot else "[剧情脉络] AI 未返回有效剧情脉络，将由前端从设定库解析")
    else:
        volumes, edges, items, worldview = (fallback_volumes(chapters),
                                            fallback_edges(nodes, chapters, cards),
                                            fallback_items(fields, chapters),
                                            fallback_worldview(fields, chapters))
        conflicts = fallback_conflicts(fields, chapters)
        plot = build_fallback_plot(chapters, dec, volumes, conflicts)
        map_data = fallback_map(fields, chapters, cards, factions)
        era = re.split(r"[。\n]", _s(fields.get("world")))[0] if _s(fields.get("world")) \
            else _s(dec.get("book_summary"))[:80]
    if not era:
        era = re.split(r"[。\n]", _s(fields.get("world")))[0] if _s(fields.get("world")) else ""

    # 关系两端对齐到标准人名（AI 常写「陈实（主角）」或别名），对不上就丢弃
    fixed, pairs = [], set()
    for e in edges:
        a, b = _match_name(e["a"], names), _match_name(e["b"], names)
        if not a or not b or a == b:
            continue
        pair = tuple(sorted((a, b)))
        if pair in pairs:
            continue
        pairs.add(pair)
        fixed.append({"a": a, "b": b, "label": e["label"],
                      "strength": _s(e.get("strength")),
                      "direction": _s(e.get("direction")) or "双向",
                      "secret": bool(e.get("secret")),
                      "from": _s(e.get("from"))})
    edges = fixed

    # 卷：章节自带 volume 优先，其次 AI 分组，最后按章数均分；统一按章节顺序重切
    volumes = normalize_volumes(volumes_from_field(chapters) or volumes, chapters)

    # 势力图谱 / 伏笔回收 / 道具流向 / 时间轴锚点：程序统计即得，不依赖 AI
    faction_nodes, faction_edges = build_faction_graph(factions)
    foreshadows = build_foreshadows(plot, fields)
    item_links = build_item_links(items, [n.get("name") for n in nodes])
    time_events = build_time_events(chapters, plot, volumes)
    emotion_curve, hook_list, payoff_list, setup_list = build_emotion_flow(chapters)

    out = {
        "generated_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
        "ai": ai_ok, "n_chapters": len(chapters), "era": era,
        "volumes": volumes, "chapters": build_chmeta(chapters),
        "nodes": nodes, "edges": edges, "worldview": worldview,
        "items": items, "conflicts": conflicts, "plot": plot,
        "factionNodes": faction_nodes, "factionEdges": faction_edges,
        "foreshadows": foreshadows, "itemLinks": item_links, "timeEvents": time_events,
        "emotionCurve": emotion_curve, "hooks": hook_list,
        "payoffs": payoff_list, "setups": setup_list,
        "map": map_data,
    }
    out_path = os.path.join(book_dir(args.book), "storymap.json")
    os.makedirs(book_dir(args.book), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print(f"[完成] 设定图谱已写出：data/{args.book}/storymap.json"
          f"（人物 {len(nodes)} · 关系 {len(edges)} · 势力 {len(faction_nodes)} · 势力边 {len(faction_edges)}"
          f" · 伏笔 {len(foreshadows)} · 道具 {len(items)} · 流向 {len(item_links)} · 冲突 {len(conflicts)}"
          f" · 地图区域 {len((map_data or {}).get('regions') or [])}"
          f" / 场景 {len((map_data or {}).get('scenes') or [])}"
          f"{' · AI' if ai_ok else ' · 程序统计'}）")


if __name__ == "__main__":
    main()
