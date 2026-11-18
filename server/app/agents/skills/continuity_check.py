# -*- coding: utf-8 -*-
"""连续性核查表技能：角色/伏笔/时间线/设定 四维核查 + claim 交叉比对。

桌面 storymap.json#foreshadows 与云端 foreshadow_ledger.json 是两套台账，
本技能把两者归一到一张独立核查表：每维逐条列出结论、证据与来源（desktop/cloud），
并把 outline/设定/chapter_summarize 各自声称的事实（claim）交叉比对，标出冲突。
只产结论与证据，不改任何 owner 字段。
"""

from __future__ import annotations

import json

from pydantic import Field

from ..contracts import SkillContext, StrictModel, call_json, list_of_dicts, text_of
from ..entity_ids import (
    entity_id as _entity_id,
    normalize_ledger as _normalize_ledger,
)
from .base import BaseSkill

SYSTEM = "你是网文连续性审读编辑，只输出 JSON；逐条给出四维核查结论与证据，不改设定。"

PROMPT = """【技能 continuity_check】
书名：{title}
四维核查：① 角色（姓名/立场/成长）② 伏笔（埋设与回收）③ 时间线（时序与时长）④ 设定（世界规则/道具）。
claim 交叉比对：同一事实在多处声称不一致时，列出来源与冲突。

输出 JSON：
{{"checks":[{{"dimension":"character|foreshadow|timeline|setting","item":"","status":"pass|conflict|unknown",
"evidence":"","source":"desktop|cloud|both"}}],
"claims":[{{"subject":"","values":[{{"value":"","source":""}}],"conflict":false}}]}}

材料：
{material}
"""

DIMENSIONS = ("character", "foreshadow", "timeline", "setting")
MAX_CHAPTERS = 300
MAX_LEDGER = 60


class ContinuityInput(StrictModel):
    title: str = Field(min_length=1, max_length=120)
    chapters: list[dict] = Field(default_factory=list)
    outline: list[dict] = Field(default_factory=list)
    foreshadow_ledger: list[dict] = Field(default_factory=list)
    desktop_ledger: list[dict] = Field(default_factory=list)
    settings: dict = Field(default_factory=dict)
    characters: list[dict] = Field(default_factory=list)


class CheckRow(StrictModel):
    dimension: str
    item: str
    status: str = "unknown"
    evidence: str = ""
    source: str = "cloud"


class ClaimValue(StrictModel):
    value: str
    source: str


class ClaimRow(StrictModel):
    subject: str
    subject_id: str = ""  # 稳定实体 ID（char:/faction:/item:/fs:）；旧数据为空时回退名称比对
    values: list[ClaimValue] = Field(default_factory=list)
    conflict: bool = False


class ContinuityOutput(StrictModel):
    checks: list[CheckRow] = Field(default_factory=list)
    claims: list[ClaimRow] = Field(default_factory=list)
    dimension_summary: dict[str, int] = Field(default_factory=dict)
    conflict_count: int = 0
    model_used: bool = False


def _local_checks(payload: ContinuityInput) -> tuple[list[CheckRow], list[ClaimRow]]:
    """确定性核查：伏笔台账回收章校验 + 人物/设定 claim 交叉比对。"""
    checks: list[CheckRow] = []

    # 归一化两套台账：桌面 chapter=回收章、云端 planted/payoff 拆列，统一到同一结构。
    cloud_ledger = _normalize_ledger(list_of_dicts(payload.foreshadow_ledger, MAX_LEDGER), source="cloud", limit=MAX_LEDGER)
    desk_ledger = _normalize_ledger(list_of_dicts(payload.desktop_ledger, MAX_LEDGER), source="desktop", limit=MAX_LEDGER)
    total_chapters = len(payload.chapters) or len(payload.outline)

    # 建 ID→行 索引：跨端比对优先用稳定 ID，缺失时回退文本前 10 字。
    cloud_by_id = {row["id"]: row for row in cloud_ledger if row.get("id")}
    for row in cloud_ledger:
        planted = int(row.get("planted_chapter") or 0)
        payoff = int(row.get("payoff_chapter") or 0)
        desc = text_of(row.get("seed")) or "未命名伏笔"
        status = "pass"
        evidence = f"埋设第{planted}章 → 回收第{payoff}章"
        if planted and payoff and payoff < planted:
            status = "conflict"
            evidence = f"回收章({payoff})早于埋设章({planted})"
        elif planted and total_chapters and planted > total_chapters:
            status = "conflict"
            evidence = f"埋设章({planted})超出总章数({total_chapters})"
        elif not payoff:
            status = "unknown"
            evidence = "尚未给出回收章"
        checks.append(
            CheckRow(dimension="foreshadow", item=desc[:60], status=status, evidence=evidence, source="cloud")
        )

    # 桌面↔云端台账交叉：优先按稳定 ID 命中，缺失时回退 seed 前 10 字文本匹配。
    for row in desk_ledger:
        seed = text_of(row.get("seed"))
        if not seed:
            continue
        matched = cloud_by_id.get(row.get("id") or "")
        match_by = "稳定ID"
        if matched is None and row.get("legacy_id"):
            matched = cloud_by_id.get(row.get("legacy_id") or "") or next(
                (item for item in cloud_ledger if row["legacy_id"] == text_of(item.get("legacy_id"))), None
            )
            match_by = "旧ID"
        if matched is None:
            matched = next(
                (item for item in cloud_ledger if seed[:10] in text_of(item.get("seed")) or text_of(item.get("seed"))[:10] in seed),
                None,
            )
            match_by = "文本"
        # 命中后校验回收章语义：桌面 chapter=payoff，云端 payoff_chapter，按归一化值比对。
        payoff_conflict = bool(
            matched
            and row.get("payoff_chapter") and matched.get("payoff_chapter")
            and int(row["payoff_chapter"]) != int(matched["payoff_chapter"])
        )
        status = "conflict" if payoff_conflict else ("pass" if matched else "unknown")
        evidence = (
            f"桌面状态={text_of(row.get('status')) or '?'}；云端台账{'命中' if matched else '缺失'}"
            f"（{match_by}）"
        )
        if payoff_conflict:
            evidence += f"；回收章不一致：桌面{row['payoff_chapter']} vs 云端{matched['payoff_chapter']}"
        checks.append(
            CheckRow(
                dimension="foreshadow",
                item=seed[:60],
                status=status,
                evidence=evidence[:200],
                source="both" if matched else "desktop",
            )
        )

    # claim 交叉比对：以稳定实体 ID 为主键（缺失回退名称），在设定包/实体抽取之间比对立场。
    claims: list[ClaimRow] = []
    settings_roles: dict[str, set[str]] = {}
    subject_names: dict[str, str] = {}
    kind_of_key = {"characters": "char", "factions": "faction", "items": "item"}
    for key in ("characters", "factions", "items"):
        for row in list_of_dicts((payload.settings or {}).get(key), 40):
            name = text_of(row.get("name"))
            if not name:
                continue
            sid = text_of(row.get("id")) or _entity_id(kind_of_key[key], name)
            claim_key = sid or name
            subject_names.setdefault(claim_key, name)
            settings_roles.setdefault(claim_key, set()).add(text_of(row.get("stance") or row.get("role") or "设定包"))
    for row in list_of_dicts(payload.characters, 40):
        name = text_of(row.get("name"))
        if not name:
            continue
        sid = text_of(row.get("id")) or _entity_id("char", name)
        claim_key = sid or name
        subject_names.setdefault(claim_key, name)
        settings_roles.setdefault(claim_key, set()).add(text_of(row.get("stance") or row.get("role") or "实体抽取") or "实体抽取")
    for claim_key, values in list(settings_roles.items())[:40]:
        distinct = sorted(value for value in values if value)
        name = subject_names.get(claim_key, claim_key)
        claims.append(
            ClaimRow(
                subject=name[:60],
                subject_id=claim_key if ":" in claim_key else "",
                values=[ClaimValue(value=value[:80], source="cloud") for value in distinct[:5]],
                conflict=len(distinct) > 1,
            )
        )
    for claim in claims:
        checks.append(
            CheckRow(
                dimension="character" if (claim.subject_id or claim.subject) in settings_roles else "setting",
                item=claim.subject,
                status="conflict" if claim.conflict else "pass",
                evidence="；".join(item.value for item in claim.values)[:180],
                source="cloud",
            )
        )

    # 时间线：伏笔埋设/回收章顺序作为一个整体校验
    ordered = [row for row in cloud_ledger if row.get("planted_chapter") and row.get("payoff_chapter")]
    time_conflict = sum(1 for row in ordered if int(row["payoff_chapter"]) < int(row["planted_chapter"]))
    checks.append(
        CheckRow(
            dimension="timeline",
            item="伏笔埋设/回收时序",
            status="conflict" if time_conflict else ("pass" if ordered else "unknown"),
            evidence=f"{len(ordered)} 条带章号伏笔，逆序 {time_conflict} 条",
            source="cloud",
        )
    )

    if not checks:
        checks.append(
            CheckRow(dimension="setting", item="设定基准", status="unknown", evidence="无可用设定/台账材料", source="cloud")
        )
    return checks[:120], claims[:60]


class ContinuityCheckSkill(BaseSkill):
    name = "continuity_check"
    version = "1.0.0"
    input_model = ContinuityInput
    output_model = ContinuityOutput

    def run(self, payload: ContinuityInput, ctx: SkillContext) -> ContinuityOutput:
        local_checks, local_claims = _local_checks(payload)
        material = {
            "ledger_policy": "伏笔以稳定 ID（fs:）对齐；桌面 chapter 为回收章，云端 planted/payoff 分列。claim 以实体 ID 为主键。",
            "outline": [{"chapter": c.get("chapter"), "foreshadow": c.get("foreshadow")} for c in list_of_dicts(payload.outline, 60)],
            "chapters": [
                {
                    "chapter": c.get("chapter_no") or c.get("chapter"),
                    "roles": c.get("roles") or [],
                    "foreshadow_ids": c.get("foreshadow_ids") or [],
                    "continuity_check": c.get("continuity_check") or "",
                }
                for c in list_of_dicts(payload.chapters, 60)
            ],
            "cloud_ledger": list_of_dicts(payload.foreshadow_ledger, 30),
            "desktop_ledger": list_of_dicts(payload.desktop_ledger, 30),
        }
        data = call_json(
            ctx,
            system=SYSTEM,
            user=PROMPT.format(title=payload.title, material=json.dumps(material, ensure_ascii=False)[:12000]),
        )
        checks = list(local_checks)
        claims = list(local_claims)
        model_used = False
        if not ctx.settings.model_stub:
            for item in list_of_dicts(data.get("checks"), 60):
                dimension = text_of(item.get("dimension"))
                if dimension not in DIMENSIONS or not text_of(item.get("item")):
                    continue
                checks.append(
                    CheckRow(
                        dimension=dimension,
                        item=text_of(item.get("item"))[:80],
                        status=text_of(item.get("status")) if text_of(item.get("status")) in {"pass", "conflict", "unknown"} else "unknown",
                        evidence=text_of(item.get("evidence"))[:200],
                        source=text_of(item.get("source")) if text_of(item.get("source")) in {"desktop", "cloud", "both"} else "cloud",
                    )
                )
            for item in list_of_dicts(data.get("claims"), 40):
                subject = text_of(item.get("subject"))
                if not subject:
                    continue
                values = [
                    ClaimValue(value=text_of(value.get("value"))[:80], source=text_of(value.get("source"))[:20] or "cloud")
                    for value in list_of_dicts(item.get("values"), 5)
                ]
                sid = text_of(item.get("subject_id"))
                if not sid:
                    matched = next((c.subject_id for c in local_claims if c.subject == subject and c.subject_id), "")
                    sid = matched
                claims.append(ClaimRow(subject=subject[:60], subject_id=sid, values=values, conflict=bool(item.get("conflict")) or len({v.value for v in values}) > 1))
            model_used = bool(data)
        summary = {dimension: 0 for dimension in DIMENSIONS}
        for row in checks:
            summary[row.dimension] = summary.get(row.dimension, 0) + 1
        conflicts = sum(1 for row in checks if row.status == "conflict") + sum(1 for row in claims if row.conflict)
        ctx.log(f"连续性核查完成：四维 {len(checks)} 项，冲突 {conflicts} 处")
        return ContinuityOutput(
            checks=checks[:120],
            claims=claims[:60],
            dimension_summary=summary,
            conflict_count=conflicts,
            model_used=model_used,
        )
