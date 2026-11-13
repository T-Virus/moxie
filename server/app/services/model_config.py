# -*- coding: utf-8 -*-
"""工序级模型配置：每个工序模块可独立选择模型/供应商/Key，入库纳管。

解析优先级（由高到低）：
  1. 专用 step_key 配置（enabled）中解析出的模型/Key；
  2. default 兜底行（enabled）；
  3. 环境变量 settings.llm_*（传统全局配置）。

Key 解析优先级：请求态 BYOK Key > 工序专用存储 Key > 环境变量 Key。
api_key 落库前加密；无口令（本地开发）或不支持 cryptography 时回退明文。
"""

from __future__ import annotations

import base64
import hashlib
from dataclasses import dataclass
from typing import TypedDict

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import Settings
from ..models import ModelProviderConfig


def _get_row(session: Session, step_key: str) -> ModelProviderConfig | None:
    return session.scalars(
        select(ModelProviderConfig).where(ModelProviderConfig.step_key == step_key)
    ).one_or_none()

try:  # cryptography 为可选依赖，缺失时不阻断启动（仅不加密）
    from cryptography.fernet import Fernet
except ImportError:  # pragma: no cover
    Fernet = None


DEFAULT_STEP_KEY = "default"

# 接入方案统一网关（EdgeOne Makers）：OpenAI 兼容，Bearer MAKERS_MODELS_KEY
EDGEONE_BASE_URL = "https://ai-gateway.edgeone.link/v1"

# 所有可被后台纳管的工序模块（step_key → 中文名）。
# 键需与 agents/graph.py 的 node.skill（注册表 key）、runners 传入的 step_key 对齐。
STEP_REGISTRY: dict[str, str] = {
    DEFAULT_STEP_KEY: "默认模型网关（兜底）",
    "outline": "大纲规划",
    "chapter_write": "章节正文",
    "chapter_summarize": "章节概括",
    "lore_extract": "角色/势力/道具抽取",
    "review": "签约体检",
    "genre_research": "同题材调研",
    "outline_decompose": "参考作品拆解",
    "adaptation": "去抄袭改编",
    "hot_preview": "前三章概览",
    "decompose": "任务拆解（decompose）",
    "adapt": "改编任务（adapt）",
    "review_run": "审查任务（review）",
    "cover": "封面生成（图片模型）",
    "rename": "一键改名（人物/书名重命名）",
    "continue_write": "续写",
    "naming": "起名/灵感/脑洞（创意类）",
    "polish": "润色/改写/扩写（文本精修）",
}


class ModelEntry(TypedDict):
    """模型目录条目：描述一个具体模型的接入信息与适用特点。"""

    provider: str
    model: str
    base_url: str
    kind: str
    traits: list[str]
    note: str


class StepRecommendation(TypedDict, total=False):
    """工序推荐条目；primary 为 None 表示该工序无对应文本模型（如图片封面）。"""

    primary: str | None
    alternatives: list[str]
    reason: str
    optional: bool


class RecommendationPayload(TypedDict):
    """对外输出的推荐结构，供后台接口与前端直接消费。"""

    primary: ModelEntry | None
    alternatives: list[ModelEntry]
    reason: str
    optional: bool


# 模型特点目录：按「速度 / 成本 / 推理 / 结构化 / 文笔」描述候选模型。
# key 形如 "provider:model"，便于同一模型在不同供应商下区分；
# 后台「模型配置」据此给出工序级推荐，管理员可一键套用后再改。
MODEL_CATALOG: dict[str, ModelEntry] = {
    "edgeone:hy3": {
        "provider": "edgeone",
        "model": "@makers/hy3",
        "base_url": EDGEONE_BASE_URL,
        "kind": "text",
        "traits": ["中文长文", "文笔自然", "正式版"],
        "note": "中文长文本表达自然、文风稳定，适合正文、改编、续写、润色等文笔优先工序",
    },
    "edgeone:hy3-preview": {
        "provider": "edgeone",
        "model": "@makers/hy3-preview",
        "base_url": EDGEONE_BASE_URL,
        "kind": "text",
        "traits": ["能力前沿", "预览版", "可容忍重试"],
        "note": "预览版能力更新但稳定性待观察，适合起名/脑洞等创意发散、失败可重试的工序",
    },
    "edgeone:deepseek-v4-pro": {
        "provider": "edgeone",
        "model": "@makers/deepseek-v4-pro",
        "base_url": EDGEONE_BASE_URL,
        "kind": "text",
        "traits": ["思考型", "强推理", "强结构", "较慢较贵"],
        "note": "推理与结构约束强，适合体检、审查等需要判断与挑错的推理密集工序",
    },
    "edgeone:deepseek-v4-flash": {
        "provider": "edgeone",
        "model": "@makers/deepseek-v4-flash",
        "base_url": EDGEONE_BASE_URL,
        "kind": "text",
        "traits": ["非思考", "低延迟", "低成本"],
        "note": "上一代 flash，便宜稳定，适合概括、改名等调用量大且输出短的工序",
    },
    "edgeone:deepseek-v4.1-flash": {
        "provider": "edgeone",
        "model": "@makers/deepseek-v4.1-flash",
        "base_url": EDGEONE_BASE_URL,
        "kind": "text",
        "traits": ["非思考", "低延迟", "格式更稳"],
        "note": "v4-flash 升级版，保持低延迟的同时长文与 JSON 格式更稳，适合作为通用主力",
    },
    "edgeone:minimax-m3": {
        "provider": "edgeone",
        "model": "@makers/minimax-m3",
        "base_url": EDGEONE_BASE_URL,
        "kind": "text",
        "traits": ["长上下文", "强创作", "角色一致"],
        "note": "长上下文与角色/风格一致性突出，适合大纲、整本拆解与长篇改编",
    },
    "edgeone:minimax-m2.7": {
        "provider": "edgeone",
        "model": "@makers/minimax-m2.7",
        "base_url": EDGEONE_BASE_URL,
        "kind": "text",
        "traits": ["长上下文", "成本更低", "上一代"],
        "note": "上一代长上下文模型，成本更低，可作 minimax-m3 的降本备选",
    },
    "edgeone:kimi-k2.6": {
        "provider": "edgeone",
        "model": "@makers/kimi-k2.6",
        "base_url": EDGEONE_BASE_URL,
        "kind": "text",
        "traits": ["长上下文", "结构化强", "多字段稳"],
        "note": "长上下文与结构化输出稳，适合多字段 JSON 拆解与逐章审查",
    },
    "edgeone:zhuque-text": {
        "provider": "edgeone",
        "model": "@makers/zhuque-text",
        "base_url": EDGEONE_BASE_URL,
        "kind": "text",
        "traits": ["轻量纯文本", "成本最低", "短任务"],
        "note": "轻量文本模型，适合改名、概览等规则明确、输入输出都短的任务",
    },
}

# 图片模型目录：封面走 images/generations，与上面的文本模型不通用，单独维护。
# 留空即回退 Pollinations 免费 flux（无需 Key），所以不配置也能出图；
# 需要稳定/商用出图质量时在此登记国内图片模型，后台「封面生成」行可一键套用。
# 尺寸由 src/cover.py 的 _ai_size 统一取 1024x1024 / 864x1152 / 1152x864。
IMAGE_CATALOG: dict[str, ModelEntry] = {
    "zhipu:cogview-3-flash": {
        "provider": "zhipu",
        "model": "cogview-3-flash",
        "base_url": "https://open.bigmodel.cn/api/paas/v4",
        "kind": "image",
        "traits": ["国内", "图片生成", "有免费额度", "速度较快"],
        "note": "智谱 CogView-3-Flash，OpenAI 兼容 images/generations；自带免费额度，适合封面这类低频调用",
    },
}

# 工序 → 推荐（首选 + 备选 + 理由）。理由按模型特点与工序负载特征给出：
#   · 大批量/短输出（正文、概括、抽取、改名）→ 低延迟低成本的非思考模型；
#   · 推理密集/超长结构（体检、拆解、大纲、改编）→ 思考型或长文强模型；
#   · 封面为独立图片接口，属「按需配置」。
STEP_RECOMMENDATIONS: dict[str, StepRecommendation] = {
    "default": {
        "primary": "edgeone:deepseek-v4.1-flash",
        "alternatives": ["edgeone:deepseek-v4-flash", "edgeone:zhuque-text"],
        "reason": "兜底行会同时服务正文、抽取、概括等多类调用，选低延迟、低成本且格式更稳的 v4.1-flash，避免兜底行既慢又贵。",
    },
    "outline": {
        "primary": "edgeone:minimax-m3",
        "alternatives": ["edgeone:deepseek-v4-pro", "edgeone:kimi-k2.6"],
        "reason": "大纲要一次产出卷/章/钩子等强结构长文本，minimax-m3 的长上下文与角色一致性最能压住结构塌陷、前后矛盾。",
    },
    "chapter_write": {
        "primary": "edgeone:hy3",
        "alternatives": ["edgeone:deepseek-v4.1-flash", "edgeone:minimax-m3"],
        "reason": "正文最吃文笔与长文连贯性，hy3 中文表达最自然；要压成本或求速度时换 v4.1-flash。",
    },
    "chapter_summarize": {
        "primary": "edgeone:deepseek-v4-flash",
        "alternatives": ["edgeone:zhuque-text", "edgeone:deepseek-v4.1-flash"],
        "reason": "概括是压缩任务：输入长、输出短，用最便宜的 flash 足够，不必为推理能力付费。",
    },
    "lore_extract": {
        "primary": "edgeone:deepseek-v4.1-flash",
        "alternatives": ["edgeone:zhuque-text", "edgeone:kimi-k2.6"],
        "reason": "抽取依赖稳定 JSON 而非深度推理，v4.1-flash 格式更稳且便宜；字段特别多时再换 kimi-k2.6。",
    },
    "review": {
        "primary": "edgeone:deepseek-v4-pro",
        "alternatives": ["edgeone:kimi-k2.6", "edgeone:minimax-m3"],
        "reason": "签约体检要发现逻辑漏洞与人设崩塌，属推理密集型，值得用思考型 pro 换更低的误报与漏报。",
    },
    "genre_research": {
        "primary": "edgeone:deepseek-v4.1-flash",
        "alternatives": ["edgeone:zhuque-text", "edgeone:deepseek-v4-flash"],
        "reason": "题材调研以归纳公开套路、输出结构化要点为主，不需要推理模型，快模型即可胜任。",
    },
    "outline_decompose": {
        "primary": "edgeone:minimax-m3",
        "alternatives": ["edgeone:kimi-k2.6", "edgeone:minimax-m2.7"],
        "reason": "整本拆解是超长文档结构化，最依赖长上下文；minimax-m3 最稳，预算紧时用 m2.7 降本。",
    },
    "adaptation": {
        "primary": "edgeone:hy3",
        "alternatives": ["edgeone:minimax-m3", "edgeone:deepseek-v4-pro"],
        "reason": "去抄袭改编要求同义重写且保留剧情骨架，hy3 的中文改写最不容易把原意改跑。",
    },
    "hot_preview": {
        "primary": "edgeone:deepseek-v4.1-flash",
        "alternatives": ["edgeone:zhuque-text", "edgeone:deepseek-v4-flash"],
        "reason": "概览只做前三章提炼，输入输出都短，用快模型可明显降低等待，且不影响后续生成。",
    },
    "decompose": {
        "primary": "edgeone:kimi-k2.6",
        "alternatives": ["edgeone:deepseek-v4-pro", "edgeone:minimax-m3"],
        "reason": "任务拆解输出全书结构 JSON，字段多、易截断，kimi-k2.6 的结构化输出最稳。",
    },
    "adapt": {
        "primary": "edgeone:hy3",
        "alternatives": ["edgeone:minimax-m3", "edgeone:deepseek-v4-pro"],
        "reason": "改编篇幅长、要求文风统一，hy3 改写质量高，可减少二次返工。",
    },
    "review_run": {
        "primary": "edgeone:deepseek-v4-pro",
        "alternatives": ["edgeone:kimi-k2.6", "edgeone:minimax-m3"],
        "reason": "审查要逐章下判断，pro 的推理结论更稳，返工成本远高于模型差价。",
    },
    "cover": {
        "primary": "zhipu:cogview-3-flash",
        "alternatives": [],
        "reason": "封面走独立图片生成接口，@makers 文本模型不适用。留空即用 Pollinations 免费 flux 兜底；要稳定出图就套用国内图片模型（智谱 CogView，自带免费额度）并填入该平台 Key。",
        "optional": True,
    },
    "rename": {
        "primary": "edgeone:zhuque-text",
        "alternatives": ["edgeone:deepseek-v4-flash", "edgeone:deepseek-v4.1-flash"],
        "reason": "改名只需按规则产出映射表，是最简单的短任务，用成本最低的 zhuque-text 即可，出错由本地校验兜底。",
    },
    "continue_write": {
        "primary": "edgeone:hy3",
        "alternatives": ["edgeone:deepseek-v4.1-flash", "edgeone:minimax-m3"],
        "reason": "续写要贴住既有文风，hy3 的连贯性最好；追求响应速度时再用 v4.1-flash。",
    },
    "naming": {
        "primary": "edgeone:hy3-preview",
        "alternatives": ["edgeone:hy3", "edgeone:deepseek-v4.1-flash"],
        "reason": "起名/脑洞靠发散与数量，hy3-preview 能力更新、适合创意探索，且候选名可多轮重试，容错高。",
    },
    "polish": {
        "primary": "edgeone:hy3",
        "alternatives": ["edgeone:minimax-m3", "edgeone:deepseek-v4-pro"],
        "reason": "润色/扩写要改得准且不跑偏，hy3 语言能力强，最不容易改坏原意。",
    },
}


@dataclass
class StepModel:
    step_key: str
    model: str
    base_url: str
    api_key: str
    provider: str
    enabled: bool
    source: str  # 'step' | 'default' | 'env'


def _secret(settings: Settings) -> str:
    return settings.model_key_secret or settings.artifact_signing_secret or ""


def encrypt_key(plain: str | None, settings: Settings) -> str | None:
    if not plain:
        return None
    secret = _secret(settings)
    if not secret or Fernet is None:
        return plain  # 未配置口令或不支持加密：明文存储（仅本地开发）
    key = base64.urlsafe_b64encode(hashlib.sha256(secret.encode()).digest())
    return Fernet(key).encrypt(plain.encode()).decode()


def decrypt_key(cipher: str | None, settings: Settings) -> str | None:
    if not cipher:
        return None
    secret = _secret(settings)
    if not secret or Fernet is None:
        return cipher
    try:
        key = base64.urlsafe_b64encode(hashlib.sha256(secret.encode()).digest())
        return Fernet(key).decrypt(cipher.encode()).decode()
    except Exception:
        # 口令变更导致解密失败：返回原文，由管理员重新保存该工序 Key
        return cipher


def resolve_step_model(
    session: Session | None,
    step_key: str,
    settings: Settings,
    *,
    api_key: str | None = None,
) -> StepModel:
    """解析某工序实际使用的 (model, base_url, api_key)。

    api_key 优先使用调用方传入的（通常是请求态 BYOK Key），否则回退到
    存储配置 / 环境变量。
    """
    byok_key = api_key or ""
    row: ModelProviderConfig | None = None
    if session is not None:
        found = _get_row(session, step_key)
        if found is not None and found.enabled:
            row = found
        elif found is None or not found.enabled:
            default_row = _get_row(session, DEFAULT_STEP_KEY)
            if default_row is not None and default_row.enabled:
                row = default_row
    if row is not None and row.enabled:
        return StepModel(
            step_key=row.step_key,
            model=row.model or settings.llm_model,
            base_url=row.base_url or settings.llm_base_url,
            api_key=byok_key or decrypt_key(row.api_key, settings) or settings.llm_api_key,
            provider=row.provider,
            enabled=True,
            source="step" if row.step_key == step_key else "default",
        )
    return StepModel(
        step_key=step_key,
        model=settings.llm_model,
        base_url=settings.llm_base_url,
        api_key=byok_key or settings.llm_api_key,
        provider="env",
        enabled=True,
        source="env",
    )


def _model_key(model: str | None) -> str:
    """归一模型名：去供应商前缀（如 @makers/），用于判断当前配置是否命中推荐。"""
    return (model or "").strip().split("/")[-1].lower()


def _catalog_entry(catalog_key: str) -> ModelEntry:
    """按目录 key 取模型条目；文本与图片目录分开维护，这里统一查找。"""
    entry = MODEL_CATALOG.get(catalog_key) or IMAGE_CATALOG.get(catalog_key)
    if entry is None:
        raise KeyError(f"模型目录中不存在：{catalog_key}")
    return entry


def recommendation_for(step_key: str) -> RecommendationPayload | None:
    """返回某工序的推荐模型（首选 + 备选 + 理由），无推荐时返回 None。"""
    rec = STEP_RECOMMENDATIONS.get(step_key)
    if not rec:
        return None

    def pack(catalog_key: str) -> ModelEntry:
        item = _catalog_entry(catalog_key)
        return ModelEntry(
            provider=item["provider"],
            model=item["model"],
            base_url=item["base_url"],
            kind=item["kind"],
            traits=list(item["traits"]),
            note=item["note"],
        )

    primary = rec.get("primary")
    return RecommendationPayload(
        # 图片等无对应文本模型的工序，primary 为 None，前端只展示理由
        primary=pack(primary) if primary else None,
        alternatives=[pack(k) for k in (rec.get("alternatives") or [])],
        reason=rec.get("reason", ""),
        optional=bool(rec.get("optional", False)),
    )


def recommended_match(
    step_key: str,
    model: str | None,
    *,
    provider: str | None = None,
    configured: bool = True,
) -> bool:
    """当前生效模型是否命中该工序的推荐（含备选）。

    文本推荐均托管在 EdgeOne 网关，同名模型若走其它供应商直连不算命中
    （避免显示「已采用」但实际没走统一网关）；图片模型端点各异，只比模型名。
    """
    rec = STEP_RECOMMENDATIONS.get(step_key)
    if not rec:
        return False
    # 可选工序（封面）：不配置即推荐做法（走免费兜底）
    if rec.get("optional") and not configured:
        return True
    primary = rec.get("primary")
    # 无推荐模型（如图片工序）：不做推荐判定，避免误报「可优化」
    if not primary:
        return True
    if not model:
        return False
    catalog_keys = [primary, *(rec.get("alternatives") or [])]
    matched = _model_key(model)
    if matched not in {_model_key(_catalog_entry(k)["model"]) for k in catalog_keys}:
        return False
    # 命中的若是文本模型，还须走统一网关才算数
    text_models = {
        _model_key(_catalog_entry(k)["model"])
        for k in catalog_keys
        if _catalog_entry(k)["kind"] == "text"
    }
    if matched in text_models:
        return provider in (None, "", "edgeone", "env")
    return True


def _effective_model(session: Session, key: str, settings: Settings) -> StepModel:
    """工序当前生效配置。

    封面走独立图片接口，不套用 default 文本兜底，回退到 image_* 环境变量，
    与 services/cover.py 的实际解析保持一致。
    """
    if key == "cover":
        row = _get_row(session, key)
        if row is not None and row.enabled:
            return StepModel(
                step_key=key,
                model=row.model or settings.image_model,
                base_url=row.base_url or settings.image_api_base,
                api_key=decrypt_key(row.api_key, settings) or settings.image_api_key,
                provider=row.provider,
                enabled=True,
                source="step",
            )
        return StepModel(
            step_key=key,
            model=settings.image_model,
            base_url=settings.image_api_base,
            api_key=settings.image_api_key,
            provider="env",
            enabled=True,
            source="env",
        )
    return resolve_step_model(session, key, settings)


def describe_configs(
    session: Session, settings: Settings
) -> list[dict[str, object]]:
    """后台列表：返回所有工序的当前生效配置（含是否已被后台覆盖、Key 是否已填、推荐模型）。"""
    out: list[dict[str, object]] = []
    for key, label in STEP_REGISTRY.items():
        row = _get_row(session, key)
        eff = _effective_model(session, key, settings)
        active = bool(row is not None and row.enabled)
        out.append(
            {
                "step_key": key,
                "label": label,
                "configured": row is not None,
                "provider": row.provider if row else eff.provider,
                "model": eff.model,
                "base_url": eff.base_url,
                "enabled": row.enabled if row else True,
                "key_set": bool(row and row.api_key),
                "updated_at": row.updated_at.isoformat() if row and row.updated_at else None,
                "source": eff.source,
                "recommendation": recommendation_for(key),
                "recommended_match": recommended_match(
                    key,
                    eff.model,
                    provider=eff.provider,
                    configured=active and bool(eff.model),
                ),
            }
        )
    return out


def _validate_recommendations() -> None:
    """静态数据自检：推荐表必须与工序注册表、模型目录完全对齐。"""
    for step_key, rec in STEP_RECOMMENDATIONS.items():
        if step_key not in STEP_REGISTRY:
            raise ValueError(f"推荐表包含未注册的工序：{step_key}")
        # primary 允许为 None（如图片工序），备选仍须可解析
        keys: list[str] = list(rec.get("alternatives") or [])
        primary = rec.get("primary")
        if primary:
            keys.append(primary)
        for catalog_key in keys:
            if catalog_key not in MODEL_CATALOG and catalog_key not in IMAGE_CATALOG:
                raise ValueError(f"工序 {step_key} 引用了不存在的模型：{catalog_key}")


_validate_recommendations()
