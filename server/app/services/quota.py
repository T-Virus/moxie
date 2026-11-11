# -*- coding: utf-8 -*-
"""额度：预占 → 结算 → 释放。

账本口径：
  · usage_aggregates 是实时校验口径（used + reserved + 本次 ≤ limit）；
  · usage_events 是权威明细，唯一键 (account_id, idempotency_key) 保证重放不重复扣费；
  · 所有键都按 account_id，不按设备——换设备额度一致。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..db import utcnow
from ..errors import ApiError
from ..models import UsageAggregate, UsageEvent
from . import subscription as subsvc


@dataclass(frozen=True)
class Reservation:
    account_id: int
    metric: str
    quantity: int
    period_start: date
    period_end: date
    unit: str
    # 拆分：套餐额度先扣，不足部分落到额度包
    plan_quantity: int = 0
    pack_items: tuple[dict, ...] = ()


def period_of(now: datetime) -> tuple[date, date]:
    start = date(now.year, now.month, 1)
    if now.month == 12:
        end = date(now.year + 1, 1, 1)
    else:
        end = date(now.year, now.month + 1, 1)
    return start, end


class QuotaService:
    def __init__(self, session: Session):
        self.session = session

    def _limit(self, account_id: int, metric: str) -> tuple[int, str]:
        sub = subsvc.get_active_subscription(self.session, account_id)
        if sub is None:
            raise ApiError(402, "no_active_subscription", "没有生效中的订阅，无法使用该能力")
        entitlements = subsvc.get_entitlements(self.session, sub.plan_id)
        ent = entitlements.get(metric)
        if ent is None:
            raise ApiError(402, "entitlement_missing", f"当前套餐不包含 {metric} 权益")
        return ent.limit_value, ent.unit

    def _aggregate(self, account_id: int, metric: str, start: date, end: date) -> UsageAggregate:
        agg = self.session.scalar(
            select(UsageAggregate)
            .where(
                UsageAggregate.account_id == account_id,
                UsageAggregate.metric == metric,
                UsageAggregate.period_start == start,
            )
            .with_for_update()
        )
        if agg is None:
            agg = UsageAggregate(
                account_id=account_id,
                metric=metric,
                period_start=start,
                period_end=end,
                used=0,
                reserved=0,
            )
            self.session.add(agg)
            self.session.flush()
        return agg

    def reserve(
        self, account_id: int, metric: str, quantity: int = 1, now: datetime | None = None
    ) -> Reservation:
        if quantity <= 0:
            raise ApiError(422, "invalid_quantity", "预占数量必须大于 0")
        now = now or utcnow()
        start, end = period_of(now)
        limit, unit = self._limit(account_id, metric)
        agg = self._aggregate(account_id, metric, start, end)

        plan_remaining = quantity if limit < 0 else max(limit - agg.used - agg.reserved, 0)
        plan_quantity = min(quantity, plan_remaining)
        pack_items: tuple[dict, ...] = ()
        pack_needed = quantity - plan_quantity
        if pack_needed > 0:
            from . import credits

            try:
                pack_items = credits.reserve_pack(self.session, account_id, metric, pack_needed, now)
            except ApiError as exc:
                remaining = plan_remaining
                self._notify_quota_exceeded(account_id, metric, limit, agg, remaining, quantity, now)
                from ..metrics import increment

                increment("moxie_quota_rejections_total", metric=metric)
                if exc.code == "credit_pack_insufficient":
                    raise ApiError(
                        402,
                        "quota_exceeded",
                        f"额度不足：{metric} 套餐剩余 {remaining}、额度包余额不足，本次需要 {quantity}",
                    ) from exc
                raise

        agg.reserved += plan_quantity
        agg.updated_at = now
        self.session.flush()
        return Reservation(
            account_id, metric, quantity, start, end, unit, plan_quantity, pack_items
        )

    def _notify_quota_exceeded(
        self, account_id, metric, limit, agg, remaining, quantity, now
    ) -> None:
        """额度不足时发站内信/邮件；通知失败不影响 402 主流程。"""
        try:
            from . import notifications

            key = f"quota:{account_id}:{metric}:{now.date().isoformat()}"
            notifications.emit(
                self.session,
                account_id=account_id,
                category="quota_insufficient",
                dedupe_key=key,
                context={
                    "metric": metric,
                    "limit": limit,
                    "used": agg.used,
                    "reserved": agg.reserved,
                    "remaining": remaining,
                    "requested": quantity,
                },
            )
            # 该通知必须独立落库：调用方随后会抛 402，不会 commit
            self.session.commit()
        except Exception:  # noqa: BLE001 - 通知通道故障不能影响额度判断
            self.session.rollback()

    def commit(
        self,
        reservation: Reservation,
        *,
        idempotency_key: str,
        task_id: str | None = None,
        meta: dict | None = None,
        now: datetime | None = None,
    ) -> bool:
        """结算。返回 True=本次真正入账；False=幂等重放，未重复扣费。"""
        now = now or utcnow()

        existing = self.session.scalar(
            select(UsageEvent).where(
                UsageEvent.account_id == reservation.account_id,
                UsageEvent.idempotency_key == idempotency_key,
            )
        )
        if existing is not None:
            return False

        allocation = {
            "plan_quantity": reservation.plan_quantity,
            "pack_quantity": reservation.quantity - reservation.plan_quantity,
            "pack_items": [dict(item) for item in reservation.pack_items],
        }
        event = UsageEvent(
            account_id=reservation.account_id,
            task_id=task_id,
            metric=reservation.metric,
            quantity=reservation.quantity,
            unit=reservation.unit,
            idempotency_key=idempotency_key,
            occurred_at=now,
            meta={**(meta or {}), "allocation": allocation},
        )
        try:
            with self.session.begin_nested():
                self.session.add(event)
                self.session.flush()
        except IntegrityError:
            # 并发重放：唯一键兜底，不重复计数（savepoint 回滚，不影响本事务其他改动）
            return False

        agg = self._aggregate(
            reservation.account_id, reservation.metric, reservation.period_start, reservation.period_end
        )
        agg.reserved = max(agg.reserved - reservation.plan_quantity, 0)
        agg.used += reservation.plan_quantity
        agg.updated_at = now
        from . import credits

        credits.commit_pack(self.session, reservation.pack_items, now)
        self.session.flush()
        return True

    def release(self, reservation: Reservation, now: datetime | None = None) -> None:
        agg = self.session.scalar(
            select(UsageAggregate)
            .where(
                UsageAggregate.account_id == reservation.account_id,
                UsageAggregate.metric == reservation.metric,
                UsageAggregate.period_start == reservation.period_start,
            )
            .with_for_update()
        )
        if agg is None:
            return
        agg.reserved = max(agg.reserved - reservation.plan_quantity, 0)
        agg.updated_at = now or utcnow()
        from . import credits

        credits.release_pack(self.session, reservation.pack_items)
        self.session.flush()

    def summary(self, account_id: int, now: datetime | None = None) -> dict:
        now = now or utcnow()
        start, end = period_of(now)
        sub = subsvc.get_active_subscription(self.session, account_id)
        plan_rows = []
        if sub is not None:
            plan = subsvc.get_plan(self.session, sub.plan_id)
            for key, ent in subsvc.get_entitlements(self.session, sub.plan_id).items():
                agg = self.session.scalar(
                    select(UsageAggregate).where(
                        UsageAggregate.account_id == account_id,
                        UsageAggregate.metric == key,
                        UsageAggregate.period_start == start,
                    )
                )
                plan_rows.append(
                    {
                        "metric": key,
                        "unit": ent.unit,
                        "limit": ent.limit_value,
                        "used": agg.used if agg else 0,
                        "reserved": agg.reserved if agg else 0,
                        "remaining": (max(ent.limit_value - (agg.used if agg else 0) - (agg.reserved if agg else 0), 0)
                                      if ent.limit_value >= 0 else -1),
                    }
                )
            plan_info = {"code": plan.code, "name": plan.name, "status": sub.status}
        else:
            plan_info = None

        from . import credits

        pack_rows = credits.summary(self.session, account_id, now)
        pack_by_metric = {row["metric"]: row for row in pack_rows}
        for row in plan_rows:
            pack = pack_by_metric.get(row["metric"])
            row["pack_remaining"] = pack["remaining"] if pack else 0
            row["total_remaining"] = (
                row["remaining"] + row["pack_remaining"] if row["remaining"] >= 0 else row["pack_remaining"]
            )
        return {
            "plan": plan_info,
            "period_start": start.isoformat(),
            "period_end": end.isoformat(),
            "metrics": plan_rows,
            # 额度包合并视图（与套餐额度独立计量，优先消耗套餐）
            "credits": pack_rows,
            "server_time": now.astimezone(timezone.utc).isoformat(),
        }
