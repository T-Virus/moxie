# -*- coding: utf-8 -*-
"""
工作台设置（studio.json）
============================
跨模块共用的「用户可调参数」唯一来源，落盘 config/studio.json：

  profiles       模型档案库：{id: {name, provider, base_url, model, temperature,
                 price_in, price_out}} —— 每家服务商一条（Kimi / DeepSeek / 豆包 /
                 千问 / ChatGPT…），单价用于成本统计。**Key 不落盘**（存浏览器），
                 服务端只记「该档案配没配 Key」这件事前端自己管。
  bindings       工序绑定：{工序key: profile_id} —— 每道工序用哪家的模型。
                 粒度：拆解 / 改编 / 图谱 / 初稿 / 续写 / 扩写 / 改写 / 润色 / 选区 / 审查。
  prices         兜底单价（元 / 百万 tokens）：{in, out}，档案没填单价时用。
  daily_goal     日更码字目标（字），配合码字统计。
  memory         跨章记忆检索：{enabled, top_k, max_chars}。
  prompt_overrides  提示词覆盖：{key: text}，key 见 prompts.py；空 = 用内置默认。
  stage_models   （旧版兼容）分阶段 {model, base_url}：profile 绑定优先，它兜底。

安全约定：服务端只存模型名 / 端点 / 单价，绝不写 API Key
（Key 仍只走前端 localStorage，请求时随调用传入，作为子进程环境变量使用）。
"""

import copy
import json
import os
import threading

from paths import CONFIG_DIR

_LOCK = threading.RLock()
_STUDIO = os.path.join(CONFIG_DIR, "studio.json")

DEFAULTS = {
    "profiles": {},              # id -> {name, provider, base_url, model, temperature, price_in, price_out}
    "bindings": {},              # 工序 key -> profile id
    "stage_models": {},          # （旧版兼容）stage -> {model, base_url, temperature}
    "prices": {"in": 2.0, "out": 8.0},   # 兜底单价（元/百万 tokens）
    "daily_goal": 3000,
    "memory": {"enabled": True, "top_k": 3, "max_chars": 1600},
    "prompt_overrides": {},      # key -> 覆盖文本
}

# 可绑定模型的工序（粒度到「操作」：初稿和续写/扩写/改写/润色、选区操作都可以分开绑）
BIND_STAGES = {
    "decompose": "拆解大纲",
    "adapt": "改编全文",
    "storymap": "设定图谱",
    "expand_outline": "正文初稿（按大纲生成 / 批量扩写）",
    "expand_continue": "正文续写",
    "expand_expand": "正文扩写",
    "expand_rewrite": "正文改写",
    "expand_polish": "正文润色",
    "expand_selection": "选区操作（续写/扩写/改写/润色选中文字）",
    "review": "正文审查 / 全书体检",
    "cover": "AI 封面底图",
}

# 旧版 stage → 新工序 key（兼容映射）
STAGE_ALIAS = {"expand": "expand_outline", "review": "review",
               "decompose": "decompose", "adapt": "adapt", "storymap": "storymap"}

STAGE_LABEL = dict(BIND_STAGES)

# 常见服务商预设：选个服务商就自动带出 base_url 与推荐模型，作者只用填 Key
PROVIDER_PRESETS = [
    {"provider": "DeepSeek", "base_url": "https://api.deepseek.com",
     "models": ["deepseek-v4-flash", "deepseek-chat", "deepseek-reasoner"],
     "price_in": 2.0, "price_out": 8.0, "note": "长上下文拆解 / 逻辑推理性价比高"},
    {"provider": "Kimi（月之暗面）", "base_url": "https://api.moonshot.cn/v1",
     "models": ["kimi-k2-0905-preview", "moonshot-v1-128k", "moonshot-v1-32k"],
     "price_in": 4.0, "price_out": 16.0, "note": "超长上下文，适合整本拆解 / 改编"},
    {"provider": "豆包（火山方舟）", "base_url": "https://ark.cn-beijing.volces.com/api/v3",
     "models": ["doubao-seed-1-6-250615", "doubao-1.5-pro-32k"],
     "price_in": 0.8, "price_out": 2.0, "note": "网文文风顺、价格低，适合正文扩写/改写"},
    {"provider": "腾讯元宝（混元）", "base_url": "https://api.hunyuan.cloud.tencent.com/v1",
     "models": ["hunyuan-turbos-latest", "hunyuan-lite"],
     "price_in": 0.8, "price_out": 2.0, "note": "混元 lite 适合高频低成本调用"},
    {"provider": "文心一言（百度千帆）", "base_url": "https://qianfan.baidubce.com/v2",
     "models": ["ernie-4.5-turbo-128k", "ernie-speed-128k"],
     "price_in": 0.8, "price_out": 2.0, "note": "ERNIE Speed 免费额度可跑骨架"},
    {"provider": "通义千问（阿里百炼）", "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
     "models": ["qwen-plus", "qwen-turbo", "qwen-max"],
     "price_in": 0.8, "price_out": 2.0, "note": "qwen-turbo 便宜快，适合选区润色等小动作"},
    {"provider": "ChatGPT（OpenAI）", "base_url": "https://api.openai.com/v1",
     "models": ["gpt-4o", "gpt-4o-mini", "gpt-5"],
     "price_in": 18.0, "price_out": 72.0, "note": "审查 / 逻辑校验质量高（需可访问的端点）"},
    {"provider": "OpenRouter（聚合）", "base_url": "https://openrouter.ai/api/v1",
     "models": ["anthropic/claude-sonnet-4.5", "google/gemini-2.5-pro"],
     "price_in": 22.0, "price_out": 110.0, "note": "一个 Key 用多家模型"},
    {"provider": "本地 / 自定义（Ollama 等）", "base_url": "http://127.0.0.1:11434/v1",
     "models": ["qwen2.5:14b"],
     "price_in": 0.0, "price_out": 0.0, "note": "本地模型零成本，速度取决于显卡"},
]

_cache = {"ts": 0.0, "data": None}


def _merge(base, over):
    out = copy.deepcopy(base)
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


def load():
    """读设置：文件缺失 / 损坏都回落默认值；带 1 秒缓存（页面轮询不反复读盘）。"""
    with _LOCK:
        try:
            ts = os.path.getmtime(_STUDIO)
        except OSError:
            ts = -1.0
        if _cache["data"] is not None and ts == _cache["ts"]:
            return copy.deepcopy(_cache["data"])
        data = copy.deepcopy(DEFAULTS)
        try:
            with open(_STUDIO, encoding="utf-8") as f:
                data = _merge(DEFAULTS, json.load(f))
        except (OSError, ValueError):
            pass
        _cache["data"], _cache["ts"] = data, ts
        return copy.deepcopy(data)


def save(data):
    """整体写回（只接受 dict；未知键丢弃，防止前端把杂数据写进来）。"""
    if not isinstance(data, dict):
        raise ValueError("设置必须是对象")
    cur = load()
    for k in DEFAULTS:
        if k in data:
            cur[k] = data[k]
    # 安全兜底：任何混进来的 api_key 字段一律剥掉，Key 永不落盘
    for p in (cur.get("profiles") or {}).values():
        if isinstance(p, dict):
            p.pop("api_key", None)
            p.pop("key", None)
    with _LOCK:
        os.makedirs(CONFIG_DIR, exist_ok=True)
        tmp = _STUDIO + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(cur, f, ensure_ascii=False, indent=2)
        os.replace(tmp, _STUDIO)
        _cache["data"], _cache["ts"] = None, 0.0
    return cur


def get_profile(pid):
    p = (load().get("profiles") or {}).get(pid)
    return dict(p) if isinstance(p, dict) else None


def profile_for(stage_key):
    """某道工序当前绑定的模型档案。返回 (profile_id, profile) 或 (None, None)。"""
    b = load().get("bindings") or {}
    pid = b.get(stage_key) or b.get(STAGE_ALIAS.get(stage_key, "")) or ""
    if not pid:
        return None, None
    p = get_profile(pid)
    return (pid, p) if p else (None, None)


def stage_conf(stage):
    """旧接口兼容：某阶段的模型绑定（{model, base_url, temperature}，可能为空）。

    解析顺序：新「档案绑定」→ 旧 stage_models 直填。"""
    pid, p = profile_for(stage)
    if p:
        return {"model": p.get("model") or "", "base_url": p.get("base_url") or "",
                "temperature": p.get("temperature"), "profile": pid,
                "profile_name": p.get("name") or ""}
    s = load().get("stage_models") or {}
    conf = s.get(stage) or s.get(STAGE_ALIAS.get(stage, ""))
    return dict(conf) if isinstance(conf, dict) else {}


def find_profile_by_model(model):
    """按模型名反查档案（用量记账时把调用归到档案头上，并带出单价快照）。"""
    model = (model or "").strip()
    if not model:
        return None, None
    for pid, p in (load().get("profiles") or {}).items():
        if isinstance(p, dict) and str(p.get("model") or "").strip() == model:
            return pid, p
    return None, None


def memory_conf():
    m = load().get("memory") or {}
    return {"enabled": bool(m.get("enabled", True)),
            "top_k": max(1, min(8, int(m.get("top_k") or 3))),
            "max_chars": max(400, min(6000, int(m.get("max_chars") or 1600)))}


def prompt_override(key):
    v = (load().get("prompt_overrides") or {}).get(key)
    return str(v) if isinstance(v, str) and v.strip() else ""
