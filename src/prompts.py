# -*- coding: utf-8 -*-
"""
提示词模板库
============
把所有「影响生成质量的提示词」集中登记成可查看、可覆盖的清单：

  · GET 列表：每项 {key, label, stage, default, override, effective, overridden}
  · PUT 覆盖：override 非空 → 生效；置空 → 恢复默认
  · 生效路径：扩写系统提示词 / 文风指南在生成时实时读取覆盖（studio.prompt_override），
    workflow.json 里的本地管线提示词保持只读展示（那是另一条 ollama 旧管线的配置）

覆盖存在 config/studio.json 的 prompt_overrides 里——只存文本，不含任何密钥。
"""

import json

import craft
import studio
from paths import WORKFLOW


def _wf_prompts():
    try:
        with open(WORKFLOW, encoding="utf-8") as f:
            d = json.load(f)
        return d.get("prompts") or {}
    except (OSError, ValueError):
        return {}


def registry():
    """全部提示词条目（默认值 + 覆盖 + 生效值）。覆盖只读 studio，不反向写 workflow.json。

    expand 模块依赖 openai SDK：无 SDK 的环境（如纯 API 冒烟测试）里只列 workflow 项，
    扩写类条目留一条占位说明——覆盖本身存在 studio.json，不受 expand 能否导入影响。
    """
    items = []

    def _add(key, label, stage, default, editable=True, note=""):
        ov = studio.prompt_override(key)
        items.append({
            "key": key, "label": label, "stage": stage,
            "default": default or "", "override": ov,
            "effective": ov or default or "",
            "overridden": bool(ov), "editable": editable, "note": note,
        })

    try:
        import decompose
        _add("decompose.system", "拆解 · 系统提示词", "拆解", decompose.SYSTEM_PROMPT,
             note="全文拆解 / 大纲拆解 / 分段合并共用的系统角色，要求只输出 JSON")
        _add("decompose.reference", "拆解 · 全文分析提示词", "拆解", decompose.REFERENCE_PROMPT,
             note="上传全本正文时使用；保留 __SCHEMA__ / __SOURCE_TEXT__ 等占位符，系统会自动填充")
        _add("decompose.outline", "拆解 · 大纲整理提示词", "拆解", decompose.OUTLINE_PROMPT,
             note="上传大纲时使用；保留 __SCHEMA__ / __SOURCE_TEXT__ 等占位符")
        _add("decompose.merge", "拆解 · 分段合并提示词", "拆解", decompose.MERGE_PROMPT,
             note="超长文本分段分析后的合并提示词；保留 __PARTS__ / __SUMMARIES__ / __CAST__ 占位符")
    except Exception as e:  # noqa
        _add("decompose._unavailable", "拆解类提示词", "拆解", "", editable=False,
             note=f"当前环境无法导入拆解模块（{e}），拆解条目暂不可见；已保存的覆盖仍然有效")

    try:
        import adapt
        _add("adapt.system", "改编 · 系统提示词", "改编", adapt.SYSTEM_PROMPT,
             note="全文改编全部步骤共用的系统角色，要求只输出 JSON")
        _add("adapt.naming", "改编 · 统一命名", "改编", adapt.NAMING_TMPL,
             note="为人物 / 势力重新起名；保留 __STYLE__ / __CAST__ / __FACTIONS__ 等占位符")
        _add("adapt.cards", "改编 · 角色卡改写", "改编", adapt.CARDS_TMPL,
             note="按批次把原著角色卡改写成新题材；保留 __MAP__ / __CHARS__ 等占位符")
        _add("adapt.factions", "改编 · 势力卡改写", "改编", adapt.FACTIONS_TMPL,
             note="按批次把原著势力卡改写成新题材；保留 __MAP__ / __FACS__ 等占位符")
        _add("adapt.items", "改编 · 道具功法改写", "改编", adapt.ITEMS_TMPL,
             note="按批次把原著道具 / 功法卡改写成新题材；保留 __MAP__ / __ITEM_LIST__ 等占位符")
        _add("adapt.meta", "改编 · 新书总纲", "改编", adapt.META_TMPL,
             note="生成新书书名、梗概与设定库；保留 __CAST__ / __BIBLE__ / __SB__ 等占位符")
        _add("adapt.terms", "改编 · 术语映射", "改编", adapt.TERMS_TMPL,
             note="把地点 / 物品 / 功法等专有名词换成新名字；保留 __TERMS__ / __ROSTER__ 占位符")
        _add("adapt.chapters", "改编 · 逐章改写", "改编", adapt.CHAP_TMPL,
             note="按原著逐章改写；保留 __MAP__ / __CHAPS__ / __USED__ 等占位符")
        _add("adapt.plan", "改编 · 章数规划", "改编", adapt.PLAN_TMPL,
             note="目标章数与原著不同时先生成章节映射；保留 __N__ / __TOTAL__ / __INDEX__ 占位符")
        _add("adapt.map", "改编 · 规划映射改写", "改编", adapt.MAP_TMPL,
             note="按章节映射拆分 / 合并改写；保留 __PLAN__ / __CHAPS__ / __K__ 等占位符")
        _add("adapt.sequel", "改编 · 结局后续写", "改编", adapt.SEQUEL_TMPL,
             note="原著素材用完后续写新剧情；保留 __TAIL__ / __K__ / __FROM__ 等占位符")
    except Exception as e:  # noqa
        _add("adapt._unavailable", "改编类提示词", "改编", "", editable=False,
             note=f"当前环境无法导入改编模块（{e}），改编条目暂不可见；已保存的覆盖仍然有效")

    try:
        import expand  # 延迟导入：避免无 openai 环境下控制台起不来
        _add("expand.system", "正文扩写 · 系统提示词", "扩写", expand.SYSTEM_PROMPT,
             note="单章生成与批量扩写共用的「小说家」人格与文笔要求，改动影响全部正文产出")
        _add("expand.deai_brief", "真人表达校准（生成随行）", "扩写", expand.DE_AI_BRIEF,
             note="初稿 / 续写 / 扩写 / 选区操作时随行注入的去 AI 味要求：写的时候就避开 AI 腔")
        _add("expand.deai", "去 AI 味 · 深度校准（改写/润色）", "扩写", expand.DE_AI_GUIDE,
             note="整章与选区的改写 / 润色任务的深度重写标准：删机械表达、调节奏密度、补真实细节")
        for name, guide in expand.STYLE_GUIDE.items():
            _add(f"expand.style.{name}", f"文风指南 · {name}", "扩写", guide,
                 note="选中该文风时追加进提示词的写作侧重点")
    except ImportError as e:
        _add("expand._unavailable", "扩写类提示词", "扩写", "", editable=False,
             note=f"当前环境缺少 openai SDK（{e}），扩写条目暂不可见；已保存的覆盖仍然有效")
    for name, label in craft.LABELS.items():
        _add(f"craft.{name}", f"写作公式 · {label}", "写作公式", craft.DEFAULTS[name],
             note="用户写作设定蒸馏出的公式块，按需注入拆解 / 改编 / 图谱 / 正文生成 / 审查各流程，改动影响所有引用它的任务")
    for k, label in (("novel", "本地管线 · 正文生成"), ("point", "本地管线 · 单段生成"),
                     ("summary", "本地管线 · 三章摘要"), ("next_state", "本地管线 · 前情记忆")):
        v = _wf_prompts().get(k)
        if v:
            _add(f"workflow.{k}", label, "本地管线", v, editable=False,
                 note="workflow.json 的旧版本地（ollama）管线提示词，只读展示；改它请直接编辑 config/workflow.json")
    return items


def effective(key, default):
    """生成端读取某个提示词的生效值：有覆盖用覆盖，否则用传入的默认模板。"""
    try:
        ov = studio.prompt_override(key)
        return ov or default
    except Exception:  # noqa
        return default


def set_override(key, text):
    """设置 / 清除某条覆盖。key 必须已注册且可编辑。

    expand 不可导入（缺 openai SDK）时 registry 里没有 expand.* 条目，
    但覆盖本身只写 studio.json、与运行环境无关，这类 key 仍允许设置——
    等生成端环境装好 SDK，覆盖自然生效。"""
    items = {it["key"]: it for it in registry()}
    it = items.get(key)
    if not it:
        if key.startswith(("expand.", "craft.", "decompose.", "adapt.")):
            it = {"editable": True, "label": key}
        else:
            raise ValueError(f"未知提示词：{key}")
    if not it["editable"]:
        raise ValueError(f"「{it['label']}」来自 workflow.json，请直接编辑该文件")
    data = studio.load()
    po = dict(data.get("prompt_overrides") or {})
    text = str(text or "").strip()
    if text:
        po[key] = text
    else:
        po.pop(key, None)
    data["prompt_overrides"] = po
    studio.save(data)
    return {"key": key, "overridden": bool(text)}
