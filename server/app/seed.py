# -*- coding: utf-8 -*-
"""套餐与权益的初始化数据（幂等写入）。"""

from __future__ import annotations

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from .models import CreditPack, Entitlement, Plan, Preset
from .preset_data import PRESET_DATA

# Postgres 多进程（uvicorn --workers / 多副本）初始化时用事务级 advisory lock，
# 避免 check-then-insert 竞态触发 plans_code_key 唯一约束冲突。
_SEED_LOCK_KEY = 918273645


def _acquire_seed_lock(session: Session) -> None:
    if session.get_bind().dialect.name == "postgresql":
        session.execute(text(f"SELECT pg_advisory_xact_lock({_SEED_LOCK_KEY})"))

PLAN_SEEDS: list[dict] = [
    {
        "code": "experience",
        "name": "体验版",
        "price_month_cents": 990,
        "price_year_cents": 9900,
        "features": {"byok": True, "managed": True, "support": "community"},
        "entitlements": {
            "books_month": (1, "book"),
            "adapt_chapters": (20, "chapter"),
            "review_month": (1, "call"),
            "concurrency": (1, "count"),
            "seats": (1, "seat"),
            "managed_chars": (50000, "char"),
            "storage_gb": (2, "gb"),
        },
    },
    {
        "code": "creator",
        "name": "创作版",
        "price_month_cents": 2990,
        "price_year_cents": 29900,
        "features": {"byok": True, "managed": True, "support": "community"},
        "entitlements": {
            "books_month": (5, "book"),
            "adapt_chapters": (120, "chapter"),
            "review_month": (5, "call"),
            "concurrency": (2, "count"),
            "seats": (1, "seat"),
            "managed_chars": (500000, "char"),
            "storage_gb": (5, "gb"),
        },
    },
    {
        "code": "professional",
        "name": "专业版",
        "price_month_cents": 6990,
        "price_year_cents": 69900,
        "features": {"byok": True, "managed": True, "support": "priority"},
        "entitlements": {
            "books_month": (15, "book"),
            "adapt_chapters": (400, "chapter"),
            "review_month": (15, "call"),
            "concurrency": (4, "count"),
            "seats": (3, "seat"),
            "managed_chars": (2000000, "char"),
            "storage_gb": (20, "gb"),
        },
    },
]


CREDIT_PACK_SEEDS: list[dict] = [
    {
        "code": "books_5",
        "name": "+5 本书（拆解额度）",
        "metric": "books_month",
        "quantity": 5,
        "price_cents": 9900,
    },
    {
        "code": "adapt_200",
        "name": "+200 章（改编额度）",
        "metric": "adapt_chapters",
        "quantity": 200,
        "price_cents": 9900,
    },
    {
        "code": "managed_2m",
        "name": "+200 万字（托管模型额度）",
        "metric": "managed_chars",
        "quantity": 2_000_000,
        "price_cents": 19900,
    },
]


def ensure_credit_packs(session: Session, validity_days: int = 365) -> None:
    _acquire_seed_lock(session)
    for spec in CREDIT_PACK_SEEDS:
        existing = session.scalar(select(CreditPack).where(CreditPack.code == spec["code"]))
        if existing:
            continue
        session.add(
            CreditPack(
                code=spec["code"],
                name=spec["name"],
                metric=spec["metric"],
                quantity=spec["quantity"],
                price_cents=spec["price_cents"],
                currency="CNY",
                validity_days=validity_days,
            )
        )
    session.commit()


def ensure_plans(session: Session) -> None:
    """幂等同步套餐：按 code 更新，旧套餐下架但不删除。"""
    _acquire_seed_lock(session)
    for spec in PLAN_SEEDS:
        existing = session.scalar(select(Plan).where(Plan.code == spec["code"]))
        if existing is None:
            plan = Plan(
                code=spec["code"],
                name=spec["name"],
                price_month_cents=spec["price_month_cents"],
                price_year_cents=spec["price_year_cents"],
                currency="CNY",
                features=spec["features"],
                active=True,
            )
            session.add(plan)
            session.flush()
        else:
            plan = existing
            plan.name = spec["name"]
            plan.price_month_cents = spec["price_month_cents"]
            plan.price_year_cents = spec["price_year_cents"]
            plan.currency = "CNY"
            plan.features = spec["features"]
            plan.active = True

        current = {
            row.key: row
            for row in session.scalars(
                select(Entitlement).where(Entitlement.plan_id == plan.id)
            ).all()
        }
        for key, (limit_value, unit) in spec["entitlements"].items():
            ent = current.pop(key, None)
            if ent is None:
                session.add(
                    Entitlement(
                        plan_id=plan.id,
                        key=key,
                        limit_value=limit_value,
                        unit=unit,
                        reset_period="month",
                    )
                )
            else:
                ent.limit_value = limit_value
                ent.unit = unit
                ent.reset_period = "month"
        for stale in current.values():
            session.delete(stale)

        seeded_codes = {spec["code"] for spec in PLAN_SEEDS}
        for plan in session.scalars(select(Plan).where(Plan.code.notin_(seeded_codes))).all():
            plan.active = False
        session.commit()


def seed_presets(session: Session, *, only_if_empty: bool = False) -> dict:
    """把 ``preset_data.PRESET_DATA`` 的系统预设写入 presets 表。

    ``only_if_empty=True``：仅在尚无任何系统级预设时灌入（启动首次初始化）。
    之后预设完全由管理端维护，避免管理员的增删改在下一次重启时被种子
    覆盖或"复活"。

    默认 ``False``：按 ``(type, value)`` 只补缺失项，绝不覆盖已有项、也不删除，
    供管理端「同步内置预设」手动调用（例如程序升级后新增了预设类型）。

    用户私有自定义预设（account_id 非 NULL）不参与同步，始终保留。
    """
    _acquire_seed_lock(session)
    system_rows = session.scalars(
        select(Preset).where(Preset.account_id.is_(None))
    ).all()
    existing = {(row.type, row.value) for row in system_rows}

    total = sum(len(items) for items in PRESET_DATA.values())
    if only_if_empty and existing:
        return {"inserted": 0, "skipped": total}

    inserted = 0
    skipped = 0
    for ptype, items in PRESET_DATA.items():
        for idx, spec in enumerate(items):
            value = spec["value"]
            if (ptype, value) in existing:
                skipped += 1
                continue
            session.add(
                Preset(
                    type=ptype,
                    value=value,
                    label=spec.get("label", value),
                    audience=spec.get("audience", "all") or "all",
                    sort=idx,
                    builtin=True,
                    account_id=None,
                )
            )
            existing.add((ptype, value))
            inserted += 1
    session.commit()
    return {"inserted": inserted, "skipped": skipped}


def ensure_presets(session: Session) -> None:
    """启动钩子：仅在预设表为空时初始化，此后交由后台管理端维护。"""
    seed_presets(session, only_if_empty=True)
