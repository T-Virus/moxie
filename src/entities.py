# -*- coding: utf-8 -*-
"""
实体数据一致性
============
角色卡 / 势力表 / 道具功法共用一套「以名称为主键」的引用规则：

  · chapters[].roles / factions / items 都是对实体名称的引用；
  · 角色卡的 factionName、relationTo、relations，势力卡的 relTo、relations，
    道具卡的 owner、faction 也都是引用。

因此批量改名 / 删除必须走 apply_renames()：在同一遍里把全部引用一起改掉，
避免 A→B、B→C 这种链条互相覆盖，也不会留下指向旧名字的孤儿引用。

sync_document() 在保存前统一做三件事：
  1) 名称清洗：折叠模型复读出来的「孟孟孟皇后」「慈懿慈懿慈懿太后」；
  2) 按名称合并重复卡，补全后出现的非空字段；
  3) 章节引用去重、清理空值，保证落盘数据自洽。
"""

import re

from story_bible import CARD_FIELDS as _CARD_FIELDS, FACTION_FIELDS as _FACTION_FIELDS

# ---------------------------------------------------------------- 道具 / 功法卡
# 与角色卡、势力卡同一层级：拆解 / 改编时一起提取，支持批量改名与关联同步。
ITEM_FIELDS = [
    ("name", "名称", ["名字"]),
    ("kind", "类别", ["类型", "种类"]),
    ("grade", "品阶", ["等级", "品级", "稀有度"]),
    ("owner", "持有者", ["拥有者", "使用者", "习得者", "掌握者"]),
    ("faction", "所属势力", ["势力", "归属势力"]),
    ("chapter", "首次出现", ["首次出现章节", "出现章节"]),
    ("effect", "效果用途", ["功能", "作用", "效果"]),
    ("origin", "来历", ["来源", "出处", "来历说明"]),
    ("desc", "简介", ["描述", "说明"]),
]

ITEM_LABEL = "道具功法"

ITEM_KINDS = [
    ("plot", "剧情道具", "推动剧情的关键物件：信物、钥匙、地图、账本"),
    ("martial", "武学功法", "可修炼的功法 / 心法 / 秘术"),
    ("skill", "战技", "具体的招式、身法、杀招"),
    ("weapon", "兵器", "刀剑枪戟等随身武器"),
    ("pill", "丹药", "疗伤、突破、解毒类丹药"),
    ("artifact", "法宝", "有特殊能力的法宝 / 异宝"),
    ("clue", "线索", "指向真相的证物、密信、名单"),
    ("other", "其他", "归不进以上类别的关键物件"),
]

ITEM_GROUPS = [
    ["基本", ["kind", "grade"]],
    ["归属", ["owner", "faction", "chapter"]],
    ["说明", ["effect", "origin", "desc"]],
]

_ITEM_KIND_ALIAS = [
    ("武学功法", ("功法", "心法", "秘术", "内功", "修行法", "武学", "神通")),
    ("战技", ("战技", "招式", "身法", "杀招", "剑法", "刀法", "拳法", "步法")),
    ("兵器", ("兵器", "武器", "刀", "剑", "枪", "戟", "弓", "鞭")),
    ("丹药", ("丹药", "丹", "药丸", "疗伤药", "解毒")),
    ("法宝", ("法宝", "异宝", "灵器", "法器", "宝物")),
    ("线索", ("线索", "证物", "密信", "名单", "账本", "地图", "钥匙", "信物")),
    ("剧情道具", ("剧情道具", "道具", "物件", "物品")),
]


def normalize_item_kind(v):
    """自由表述 → 8 类道具类别之一；认不出原样保留（前端会显示灰色标签）。"""
    s = str(v or "").strip()
    if not s:
        return ""
    for key, lb, _ in ITEM_KINDS:
        if s == key or s == lb:
            return lb
    for lb, kws in _ITEM_KIND_ALIAS:
        if any(k in s for k in kws):
            return lb
    return s


def normalize_item(it):
    """就地规范化一张道具 / 功法卡。"""
    if not isinstance(it, dict):
        return it
    for k, _, _ in ITEM_FIELDS:
        it.setdefault(k, "")
    it["name"] = clean_name(it.get("name"), 24)
    it["kind"] = normalize_item_kind(it.get("kind"))
    for k in ("grade", "owner", "faction", "chapter", "effect", "origin", "desc"):
        v = it.get(k)
        it[k] = str(v).strip() if v is not None else ""
    return it


def schema_extra():
    """给前端 /api/schema 追加的道具字段定义。"""
    return {
        "item_fields": [[k, lb] for k, lb, _ in ITEM_FIELDS],
        "item_label": ITEM_LABEL,
        "item_groups": ITEM_GROUPS,
        "item_kinds": [[k, lb, note] for k, lb, note in ITEM_KINDS],
    }


# ---------------------------------------------------------------- 名称清洗
def collapse_repeats(s):
    """折叠紧邻的复读片段（模型退化输出的典型形态）。

    · 连续三次以上的单字：孟孟孟皇后 → 孟皇后
    · 两字以上的紧邻复读：慈懿慈懿慈懿太后 → 慈懿太后 / 盘发传话传话嬷嬷 → 盘发传话嬷嬷
    · 保留正常的叠字人名（娜娜、芳芳）与「慢慢」这类两字重复
    """
    s = str(s or "")
    if not s:
        return s
    changed = True
    while changed:
        changed = False
        n = len(s)
        # 整串就是同一片段重复两遍（高高兴兴 → 高兴）；单字叠词（娜娜）保留
        if n % 2 == 0 and n // 2 >= 2 and s == s[:n // 2] * 2:
            s = s[:n // 2]
            changed = True
            continue
        for unit in range(n // 2, 0, -1):
            for i in range(0, n - 2 * unit + 1):
                if s[i:i + unit] != s[i + unit:i + 2 * unit]:
                    continue
                if unit == 1:
                    triple = i + 2 < n and s[i + 2] == s[i]
                    at_head = i == 0 and n > 2
                    if not (triple or at_head):
                        continue
                s = s[:i + unit] + s[i + 2 * unit:]
                changed = True
                break
            if changed:
                break
    return s


def clean_name(s, limit=32):
    """实体名称清洗：去空白 / 包裹标点、折叠复读、限长。"""
    v = re.sub(r"[\s\u3000]+", "", str(s or ""))
    v = v.strip("：:·•-—_、，,。.；;\"'“”‘’《》〈〉()（）[]【】{}")
    v = collapse_repeats(v)
    return v[:limit]


def clean_names(values):
    """引用数组清洗：逐个清洗、去空、去重，保持原顺序。"""
    out, seen = [], set()
    for v in values or []:
        n = clean_name(v)
        if n and n not in seen:
            seen.add(n)
            out.append(n)
    return out


# ---------------------------------------------------------------- 批量改名 / 删除
_REF_KEYS = ("characters", "factions", "items")
_TEXT_KEYS = ("title", "summary", "scene", "conflict", "hook", "payoff", "setup", "emotion",
              "chapter_id", "grade", "effect", "origin", "desc", "identity", "personality",
              "speech", "catchwords", "weakness", "goal", "subFaction")


def _build_mapping(renames):
    """{kind: {old: new}} → 一张全局替换表；new 为空串表示删除后清空引用。"""
    mapping = {}
    for kind in _REF_KEYS:
        for old, new in (renames.get(kind) or {}).items():
            old = str(old or "").strip()
            new = clean_name(new, 32)
            if old and old != new:
                mapping[old] = new
    return mapping


def _make_sub(mapping):
    """长名优先的一次性替换（同遍替换，避免 A→B、B→C 连锁）。
    只处理「改名」；映射到空串表示删除，不应在正文里抹掉人名。"""
    renames = {k: v for k, v in mapping.items() if v}
    olds = sorted((k for k in renames if k), key=len, reverse=True)
    if not olds:
        return None
    rx = re.compile("|".join(re.escape(o) for o in olds))

    def sub(s):
        return rx.sub(lambda m: renames.get(m.group(0), m.group(0)), s)
    return sub


def _fix_relations_text(text, mapping):
    """关系行「对象｜类型｜强度」：只换首列名称，删除的对象整行去掉。"""
    if not isinstance(text, str) or not text.strip():
        return text
    out = []
    for line in text.splitlines():
        raw = line.strip()
        if not raw:
            continue
        sep = "｜" if "｜" in raw else ("|" if "|" in raw else "")
        if not sep:
            out.append(raw)
            continue
        parts = [p.strip() for p in raw.split(sep)]
        target = parts[0]
        nv = clean_name(mapping.get(target, target))
        if not nv:
            continue
        parts[0] = nv
        out.append(sep.join(parts))
    return "\n".join(out)


def _drop_name_tokens(text, names):
    """从「名称清单」型字段里去掉已删除实体的整名。

    只删被分隔符（、，,；;/｜| 换行）包住的独立名称；夹在描述句里的名字
    （「主角林辰，十九岁…」）原样保留，避免删卡时把整段文案改坏。
    """
    out = str(text or "")
    for name in names:
        nm = clean_name(name)
        if not nm:
            continue
        esc = re.escape(nm)
        # 整行只有这个名字：连行一起删
        out = re.sub(r"(?m)^[ \t\u3000]*" + esc + r"[ \t\u3000]*(?=\n|$)\n?", "", out)
        # 名字在前：连同紧跟的分隔符删掉
        out = re.sub(r"(^|[\s、，,；;/｜|])" + esc + r"[ \t]*[、，,；;/｜|][ \t]*", r"\1", out)
        # 名字在后：连同前面的分隔符删掉
        out = re.sub(r"[ \t]*[、，,；;/｜|][ \t]*" + esc + r"(?=$|[\s、，,；;/｜|])", "", out)
    return re.sub(r"\n{3,}", "\n\n", out).strip()


def apply_renames(doc, renames):
    """把批量改名 / 删除应用到整份文档（章节引用 + 卡片字段 + 设定库文本）。

    doc 兼容两种形态：chapters.json（story_bible_cards）与 decomposed.json（characters）。
    """
    mapping = _build_mapping(renames or {})
    sub = _make_sub(mapping) or (lambda s: s)
    if not mapping:
        return doc
    # 删除（new 为空）的实体：大纲里的「人物设定 / 关键道具」清单要同步摘掉，避免留下孤儿名称
    deleted = {}
    for kind in _REF_KEYS:
        deleted[kind] = [str(old) for old, new in (renames.get(kind) or {}).items()
                         if str(old or "").strip() and not clean_name(new, 32)]

    def fix_text(v):
        return sub(v) if isinstance(v, str) and v else v

    def fix_refs(arr):
        out = []
        for x in arr or []:
            s = str(x).strip()
            nv = mapping.get(s, s)
            nv = clean_name(nv)
            if nv and nv not in out:
                out.append(nv)
        return out

    # 章节：引用数组整项换，文本字段子串换
    for ch in doc.get("chapters") or []:
        if not isinstance(ch, dict):
            continue
        for k in ("roles", "factions", "items"):
            if isinstance(ch.get(k), list):
                ch[k] = fix_refs(ch[k])
        if isinstance(ch.get("points"), list):
            ch["points"] = [fix_text(x) for x in ch["points"]]
        for k in _TEXT_KEYS:
            if isinstance(ch.get(k), str):
                ch[k] = fix_text(ch[k])

    # 设定库文本字段（删除实体时保留原文，只做改名替换）
    fields = doc.get("story_bible_fields")
    if isinstance(fields, dict):
        for k, v in list(fields.items()):
            if isinstance(v, str):
                fields[k] = fix_text(v)
        # 人物设定三栏只清角色删除，关键道具只清道具删除（按类分开，避免同名互相误删）
        for k, kinds in (("protagonist", ("characters",)), ("supporting", ("characters",)),
                         ("antagonist", ("characters",)), ("items", ("items",))):
            gone = [n for kd in kinds for n in deleted.get(kd, [])]
            if gone and isinstance(fields.get(k), str):
                fields[k] = _drop_name_tokens(fields[k], gone)

    # 实体卡：name / 关系对象 / 归属势力按整项换；简介类文本只做改名替换
    REF_KEYS = ("relationTo", "factionName", "relTo", "owner", "faction")
    TEXT_KEYS = ("identity", "personality", "speech", "catchwords", "weakness", "goal",
                 "desc", "effect", "origin", "grade", "subFaction")

    def fix_entities(key):
        for ent in doc.get(key) or []:
            if not isinstance(ent, dict):
                continue
            for k, v in list(ent.items()):
                if not isinstance(v, str) or not v:
                    continue
                if k == "name":
                    ent[k] = clean_name(mapping.get(v.strip(), v))
                elif k == "relations":
                    ent[k] = _fix_relations_text(v, mapping)
                elif k in REF_KEYS:
                    ent[k] = clean_name(mapping.get(v.strip(), v))
                elif k in TEXT_KEYS:
                    ent[k] = fix_text(v)

    for key in ("story_bible_cards", "characters"):
        fix_entities(key)
    for key in ("story_bible_factions", "factions"):
        fix_entities(key)
    fix_entities("items")

    if isinstance(doc.get("story_bible"), str):
        doc["story_bible"] = fix_text(doc["story_bible"])
    if isinstance(doc.get("book_summary"), str):
        doc["book_summary"] = fix_text(doc["book_summary"])
    opening = doc.get("opening")
    if isinstance(opening, dict):
        for k, v in list(opening.items()):
            if isinstance(v, str):
                opening[k] = fix_text(v)
    return doc


# ---------------------------------------------------------------- 章号变动同步
def _no_of_ch(c, fallback):
    """章节号：优先 no，其次从 chapter_id / id 提取数字，最后位置兜底。"""
    for k in ("no", "chapter_id", "id"):
        m = re.search(r"\d+", str(c.get(k) or ""))
        if m:
            return int(m.group(0))
    return fallback


def chapter_no_remap(old_chapters, new_chapters):
    """旧章号 → 新章号映射：章节改序号 / 上下移后，道具卡「首次出现」等章号引用跟随内容走。

    对齐优先级：chapter_id（前端改 no 不动它，是最稳的身份）→ 标题唯一匹配 → 原位兜底。
    只对旧新章号都在且不一致的章节产出映射；新增 / 删除的章不产生映射。
    """
    old_chs = [c for c in (old_chapters or []) if isinstance(c, dict)]
    new_chs = [c for c in (new_chapters or []) if isinstance(c, dict)]
    if not old_chs or not new_chs:
        return {}
    by_cid, by_title = {}, {}
    for i, c in enumerate(old_chs):
        cid = str(c.get("chapter_id") or "").strip()
        if cid and cid not in by_cid:
            by_cid[cid] = i
        t = str(c.get("title") or "").strip()
        if t and t not in by_title:
            by_title[t] = i
    mapping, used = {}, set()
    for j, c in enumerate(new_chs):
        cid = str(c.get("chapter_id") or "").strip()
        t = str(c.get("title") or "").strip()
        i = by_cid.get(cid) if cid else None
        if i is None and t:
            i = by_title.get(t)
        if i is None and j < len(old_chs):
            i = j                     # 老数据没有 chapter_id / 标题时的原位兜底
        if i is None or i in used:
            continue
        used.add(i)
        old_no = _no_of_ch(old_chs[i], i + 1)
        m = re.search(r"\d+", str(c.get("no") or ""))
        new_no = int(m.group(0)) if m else _no_of_ch(c, j + 1)
        if old_no and new_no and old_no != new_no:
            mapping[old_no] = new_no
    return mapping


def apply_chapter_no_map(doc, mapping, valid=None):
    """把章号映射应用到章号引用字段：目前只有道具卡的 chapter（首次出现）。

    valid 给出本书现有章号集合时，指向已删除章节的引用会被清空，避免留下死链。
    """
    if not isinstance(doc, dict):
        return doc
    valid = set(valid) if valid else None
    for it in doc.get("items") or []:
        if not isinstance(it, dict):
            continue
        v = it.get("chapter")
        m = re.search(r"\d+", str(v if v is not None else ""))
        if not m:
            continue
        num = int(m.group(0))
        new_no = (mapping or {}).get(num, num)
        if valid is not None and new_no not in valid:
            it["chapter"] = ""
            continue
        if new_no == num:
            continue
        it["chapter"] = new_no if isinstance(v, int) else re.sub(r"\d+", str(new_no), str(v), count=1)
    return doc


# ---------------------------------------------------------------- 保存前同步
def entity_names(doc, kind):
    """取出一份文档里某类实体的全部名称（去重前）。"""
    keys = {
        "characters": ("story_bible_cards", "characters"),
        "factions": ("story_bible_factions", "factions"),
        "items": ("items",),
    }[kind]
    out = []
    for key in keys:
        for ent in doc.get(key) or []:
            if isinstance(ent, dict):
                n = clean_name(ent.get("name"), 24)
                if n:
                    out.append(n)
    return out


def _dedupe_entities(items, fields):
    """按名称合并重复卡：保留首次出现，空字段用后续卡补齐。"""
    out, index = [], {}
    field_keys = [k for k, _, _ in fields]
    for raw in items or []:
        if not isinstance(raw, dict):
            continue
        ent = dict(raw)
        name = clean_name(ent.get("name"), 24)
        if not name:
            continue
        ent["name"] = name
        if name not in index:
            index[name] = len(out)
            out.append(ent)
            continue
        keep = out[index[name]]
        for k in field_keys:
            if not str(keep.get(k) or "").strip() and str(ent.get(k) or "").strip():
                keep[k] = ent[k]
    return out


def _cleanup_reference_fields(doc, rename_map):
    """清理引用类字段：改名后的旧值、已删除实体留下的空值。"""
    def fix_ref(v):
        s = str(v or "").strip()
        if not s:
            return ""
        s = rename_map.get(s, s)
        return clean_name(s)

    for ent in doc.get("story_bible_cards") or []:
        if not isinstance(ent, dict):
            continue
        if "factionName" in ent:
            ent["factionName"] = fix_ref(ent.get("factionName"))
        if "relationTo" in ent:
            ent["relationTo"] = fix_ref(ent.get("relationTo"))
    for ent in doc.get("characters") or []:
        if not isinstance(ent, dict):
            continue
        if "factionName" in ent:
            ent["factionName"] = fix_ref(ent.get("factionName"))
        if "relationTo" in ent:
            ent["relationTo"] = fix_ref(ent.get("relationTo"))
    for ent in doc.get("story_bible_factions") or []:
        if isinstance(ent, dict) and "relTo" in ent:
            ent["relTo"] = fix_ref(ent.get("relTo"))
    for ent in doc.get("factions") or []:
        if isinstance(ent, dict) and "relTo" in ent:
            ent["relTo"] = fix_ref(ent.get("relTo"))
    for ent in doc.get("items") or []:
        if not isinstance(ent, dict):
            continue
        if "owner" in ent:
            ent["owner"] = fix_ref(ent.get("owner"))
        if "faction" in ent:
            ent["faction"] = fix_ref(ent.get("faction"))


def sync_document(doc):
    """保存前统一自洽：名称清洗、重复卡合并、引用去重。

    清洗时同时收集「脏名 → 干净名」，用同一张表改章节引用与关系字段，
    保证不会出现「卡片叫孟皇后、章节还写孟孟孟皇后」的错位。
    """
    if not isinstance(doc, dict):
        return doc

    # 1) 收集所有出现过的名称（实体名 + 章节引用 + 关系对象），算出清洗映射
    raw_names = {"characters": [], "factions": [], "items": []}
    raw_names["characters"].extend(entity_names(doc, "characters"))
    raw_names["factions"].extend(entity_names(doc, "factions"))
    raw_names["items"].extend(entity_names(doc, "items"))
    for ch in doc.get("chapters") or []:
        if not isinstance(ch, dict):
            continue
        for ref_key, kind in (("roles", "characters"), ("factions", "factions"), ("items", "items")):
            raw_names[kind].extend(str(x) for x in (ch.get(ref_key) or []) if str(x).strip())
    for ent in doc.get("story_bible_cards") or []:
        if isinstance(ent, dict):
            raw_names["characters"].extend([str(ent.get("relationTo") or "")])
            raw_names["factions"].extend([str(ent.get("factionName") or "")])
    for ent in doc.get("story_bible_factions") or []:
        if isinstance(ent, dict):
            raw_names["factions"].extend([str(ent.get("relTo") or "")])
    for ent in doc.get("items") or []:
        if isinstance(ent, dict):
            raw_names["characters"].extend([str(ent.get("owner") or "")])
            raw_names["factions"].extend([str(ent.get("faction") or "")])

    rename_map = {}
    for kind in _REF_KEYS:
        pairs = {}
        for raw in raw_names[kind]:
            raw = str(raw or "").strip()
            clean = clean_name(raw)
            if raw and clean and raw != clean:
                pairs[raw] = clean
        rename_map.update(pairs)
        if pairs:
            apply_renames(doc, {kind: pairs})

    # 2) 去重合并实体卡
    if isinstance(doc.get("story_bible_cards"), list):
        doc["story_bible_cards"] = _dedupe_entities(doc["story_bible_cards"], _CARD_FIELDS)
    if isinstance(doc.get("characters"), list):
        doc["characters"] = _dedupe_entities(doc["characters"], _CARD_FIELDS)
    if isinstance(doc.get("story_bible_factions"), list):
        doc["story_bible_factions"] = _dedupe_entities(doc["story_bible_factions"], _FACTION_FIELDS)
    if isinstance(doc.get("factions"), list):
        doc["factions"] = _dedupe_entities(doc["factions"], _FACTION_FIELDS)
    if isinstance(doc.get("items"), list):
        doc["items"] = _dedupe_entities(doc["items"], ITEM_FIELDS)

    # 3) 引用字段清理 + 章节引用去重
    _cleanup_reference_fields(doc, rename_map)
    for ch in doc.get("chapters") or []:
        if not isinstance(ch, dict):
            continue
        for k in ("roles", "factions", "items"):
            if isinstance(ch.get(k), list):
                ch[k] = clean_names(ch[k])
        if isinstance(ch.get("points"), list):
            ch["points"] = [str(x).strip() for x in ch["points"] if str(x).strip()]
    for ent in doc.get("items") or []:
        normalize_item(ent)
    return doc
