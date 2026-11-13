# -*- coding: utf-8 -*-
"""定时与自愈任务（独立进程或 app 内可选启用）。

覆盖：
- 订阅到期清扫 `expire_due`；
- 宽限期结束：`past_due` 超过 `subscription_grace_days` → `expired`；
- 续费提醒：临近到期写审计（按订阅/天幂等）；
- worker 租约清扫：running 且租约超时的任务重新入队（避免双跑）；
- 异常用量告警（只记录 + 审计，不自动封禁）；
- 日对账：按渠道拉取账单并与本地订单比对。

运行方式：
    python -m app.scheduler --once
    python -m app.scheduler            # 常驻，间隔 SCHEDULER_INTERVAL_SECONDS
或设置 SCHEDULER_ENABLED=true 随 API 进程启动（单实例部署适用）。
"""

from __future__ import annotations

import argparse
import logging
import time
from datetime import datetime, time as dtime, timedelta, timezone

from sqlalchemy import func, select

from .config import Settings
from .db import Database, utcnow
from .metrics import increment
from .models import AgentRun, AuditLog, Subscription, Task, UsageEvent
from .services import credits as creditsvc
from .services import notifications as nsvc
from .services import reconcile as reconcilesvc
from .services import subscription as subsvc
from .services.audit import write_audit
from .services.tasks import append_event
from .worker import enqueue_agent_run, enqueue_task

logger = logging.getLogger("moxie.scheduler")


def _day_start(now: datetime) -> datetime:
    return datetime.combine(now.date(), dtime.min, tzinfo=timezone.utc)


def _recent_audit(session, action: str, target_id: str, now: datetime) -> bool:
    start = _day_start(now)
    return (
        session.scalar(
            select(AuditLog.id).where(
                AuditLog.action == action,
                AuditLog.target_id == target_id,
                AuditLog.created_at >= start,
                AuditLog.created_at < start + timedelta(days=1),
            )
        )
        is not None
    )


def sweep_leases(
    session, settings: Settings, now: datetime | None = None, requeued_out: list[str] | None = None
) -> int:
    """running 且租约超时的任务重新入队；条件更新 + 行锁避免双跑。

    requeued_out：调用方可传入列表收集被重排的 task_id，commit 后统一重新投递 RQ。
    """
    now = now or utcnow()
    rows = session.scalars(
        select(Task)
        .where(Task.status == "running", Task.lease_until.isnot(None), Task.lease_until < now)
        .with_for_update(skip_locked=True)
    ).all()
    if not rows:
        return 0
    for task in rows:
        task.status = "queued"
        task.lease_until = None
        task.heartbeat_at = now
        task.error_code = None
        append_event(session, task.id, "租约超时，任务重新入队（未完成的步骤保留）", level="warning")
        if requeued_out is not None:
            requeued_out.append(task.id)
        increment("moxie_tasks_requeued_total")
    write_audit(
        session,
        actor_id=None,
        action="task.lease_reclaim",
        target_type="scheduler",
        target_id="lease",
        meta={"count": len(rows), "task_ids": [t.id for t in rows]},
    )
    return len(rows)


def requeue_stuck_runs(
    session,
    settings: Settings,
    now: datetime | None = None,
    task_out: list[str] | None = None,
    run_out: list[str] | None = None,
) -> int:
    """孤儿任务自愈：重新投递滞留 queued / running 的任务与 Agent 运行。

    RQ job 只在创建/resume/retry 时投递；批量让出、历史缺陷或 worker 崩溃会让
    DB 里的 queued/running 行失去对应的 Redis job——看板显示队列有任务但永远
    没人领取。这里按时间阈值兜底重新入队（执行入口有原子认领，重复投递无副作用）。
    """
    now = now or utcnow()
    queued_deadline = now - timedelta(seconds=max(60, settings.stuck_queued_seconds))
    running_deadline = now - timedelta(seconds=max(600, settings.stuck_running_seconds))
    count = 0

    stuck_tasks = session.scalars(
        select(Task).where(
            Task.status == "queued",
            func.coalesce(Task.heartbeat_at, Task.created_at) < queued_deadline,
        ).limit(100)
    ).all()
    for task in stuck_tasks:
        if task_out is not None:
            task_out.append(task.id)
        count += 1

    stuck_runs = session.scalars(
        select(AgentRun).where(
            AgentRun.status == "queued", AgentRun.updated_at < queued_deadline
        ).limit(100)
    ).all()
    for run in stuck_runs:
        if run_out is not None:
            run_out.append(str(run.id))
        count += 1

    # worker 挂掉后 running 的 AgentRun 会永远卡住（Task 有租约清扫，AgentRun 此前没有）
    stale_runs = session.scalars(
        select(AgentRun).where(
            AgentRun.status == "running", AgentRun.updated_at < running_deadline
        ).limit(100)
    ).all()
    for run in stale_runs:
        run.status = "queued"
        run.error_code = None
        run.error_message = None
        run.updated_at = now
        append_event(session, run.id, "run", "执行超时无心跳，任务重新入队（已完成节点保留）", level="warning")
        if run_out is not None:
            run_out.append(str(run.id))
        count += 1
        increment("moxie_tasks_requeued_total")

    if count:
        write_audit(
            session,
            actor_id=None,
            action="task.stuck_requeue",
            target_type="scheduler",
            target_id="stuck",
            meta={"count": count},
        )
        logger.warning("requeue stuck runs: %s", count)
    return count


def _dispatch_requeued(settings: Settings, task_ids: list[str], run_ids: list[str]) -> None:
    """事务提交后重新投递 RQ；无 Redis（本地模式）时保持 queued，由 --loop 领取。"""
    for task_id in task_ids:
        if enqueue_task(settings, task_id):
            logger.info("re-enqueued task %s", task_id)
        else:
            logger.warning("re-enqueue task %s failed（本地模式可用 --loop 执行）", task_id)
    for run_id in run_ids:
        if enqueue_agent_run(settings, run_id):
            logger.info("re-enqueued agent run %s", run_id)
        else:
            logger.warning("re-enqueue agent run %s failed（本地模式可用 --loop 执行）", run_id)


def expire_grace_period(session, settings: Settings, now: datetime | None = None) -> int:
    """past_due 超过宽限期 → expired（到期清扫已处理 active/trialing/canceled）。"""
    now = now or utcnow()
    deadline = now - timedelta(days=max(0, settings.subscription_grace_days))
    rows = session.scalars(
        select(Subscription).where(
            Subscription.status == "past_due",
            Subscription.current_end_at <= deadline,
        )
    ).all()
    for sub in rows:
        sub.status = "expired"
        sub.cancel_at_period_end = False
        sub.version += 1
        sub.updated_at = now
        write_audit(
            session,
            actor_id=sub.account_id,
            action="subscription.expired",
            target_type="subscription",
            target_id=str(sub.id),
            meta={"reason": "grace_period_over", "grace_days": settings.subscription_grace_days},
        )
    return len(rows)


def send_renewal_reminders(session, settings: Settings, now: datetime | None = None) -> int:
    now = now or utcnow()
    count = 0
    for item in subsvc.reminders(session, settings, now):
        sub_id = str(item["subscription_id"])
        if _recent_audit(session, "subscription.renewal_reminder", sub_id, now):
            continue
        write_audit(
            session,
            actor_id=item["account_id"],
            action="subscription.renewal_reminder",
            target_type="subscription",
            target_id=sub_id,
            meta={
                "days_left": item["days_left"],
                "current_end_at": item["current_end_at"],
                "status": item["status"],
            },
        )
        nsvc.emit(
            session,
            account_id=item["account_id"],
            category="subscription_renewal_reminder",
            dedupe_key=f"renewal:{sub_id}:{now.date().isoformat()}",
            context={
                "days_left": item["days_left"],
                "current_end_at": item["current_end_at"],
            },
            settings=settings,
            now=now,
        )
        count += 1
    return count


def check_usage_alerts(session, settings: Settings, now: datetime | None = None) -> int:
    """日用量超过「月额度/30 × 阈值倍数」时写审计；只告警，不封禁。"""
    now = now or utcnow()
    start = _day_start(now)
    count = 0
    subs = session.scalars(
        select(Subscription).where(Subscription.status.in_(subsvc.ACTIVE_STATUSES))
    ).all()
    for sub in subs:
        ent = subsvc.get_entitlements(session, sub.plan_id).get("managed_chars")
        if ent is None or int(ent.limit_value or 0) <= 0:
            continue
        used_today = sum(
            session.scalars(
                select(UsageEvent.quantity).where(
                    UsageEvent.account_id == sub.account_id,
                    UsageEvent.metric.in_({"model_token", "managed_chars"}),
                    UsageEvent.occurred_at >= start,
                )
            ).all()
        )
        threshold = int(ent.limit_value) / 30 * settings.usage_alert_multiplier
        if used_today <= threshold:
            continue
        target = f"account:{sub.account_id}"
        if _recent_audit(session, "usage.anomaly", target, now):
            continue
        write_audit(
            session,
            actor_id=sub.account_id,
            action="usage.anomaly",
            target_type="account",
            target_id=target,
            meta={
                "used_today": used_today,
                "threshold": int(threshold),
                "limit": int(ent.limit_value),
                "multiplier": settings.usage_alert_multiplier,
            },
        )
        nsvc.emit(
            session,
            account_id=sub.account_id,
            category="usage_anomaly",
            dedupe_key=f"usage-alert:{sub.account_id}:{now.date().isoformat()}",
            context={
                "metric": "managed_chars",
                "used_today": used_today,
                "threshold": int(threshold),
                "limit": int(ent.limit_value),
            },
            settings=settings,
            now=now,
        )
        increment("moxie_usage_alerts_total")
        count += 1
    return count


def notify_expired_subscriptions(session, settings: Settings, now: datetime | None = None) -> int:
    """给已到期订阅发一次到期通知（按订阅去重，不按天重复）。"""
    now = now or utcnow()
    rows = session.scalars(
        select(Subscription).where(
            Subscription.status == "expired", Subscription.current_end_at <= now
        ).limit(200)
    ).all()
    for sub in rows:
        nsvc.emit(
            session,
            account_id=sub.account_id,
            category="subscription_expired",
            dedupe_key=f"sub-expired:{sub.id}",
            context={"current_end_at": sub.current_end_at.isoformat()},
            settings=settings,
            now=now,
        )
    return len(rows)


def sweep_credits(session, settings: Settings, now: datetime | None = None) -> dict:
    """额度包到期清扫 + 临近到期提醒（到期后剩余作废，不结转）。"""
    now = now or utcnow()
    expired = creditsvc.expire_grants(session, now)
    soon_deadline = now + timedelta(days=max(1, settings.subscription_reminder_days))
    from .models import CreditGrant

    rows = session.scalars(
        select(CreditGrant).where(
            CreditGrant.status == "active",
            CreditGrant.expires_at > now,
            CreditGrant.expires_at <= soon_deadline,
        )
    ).all()
    for grant in rows:
        remaining = max(grant.quantity_granted - grant.quantity_used - grant.quantity_reserved, 0)
        if remaining <= 0:
            continue
        days_left = max(int((grant.expires_at - now).total_seconds() // 86400), 0)
        nsvc.emit(
            session,
            account_id=grant.account_id,
            category="credit_pack_expiring",
            dedupe_key=f"grant-expiring:{grant.id}:{now.date().isoformat()}",
            context={"days_left": days_left, "remaining": remaining},
            settings=settings,
            now=now,
        )
    return {"expired": expired, "reminded": len(rows)}


def retry_notifications(session, settings: Settings, now: datetime | None = None) -> int:
    return nsvc.retry_deliveries(session, settings, now)


def cleanup_uploads(session, settings: Settings, now: datetime | None = None) -> int:
    """按保留期清理上传源文件；排队/执行中的任务引用会跳过。"""
    from .services.storage import build_storage
    from .services.uploads import cleanup_expired_uploads

    storage = build_storage(settings, session=session)
    return cleanup_expired_uploads(storage, session, settings, now)


def reconcile_daily(session, settings: Settings, now: datetime | None = None) -> list[str]:
    """按日拉取真实渠道账单；单个渠道失败不影响其它渠道。"""
    now = now or utcnow()
    biz_date = (now - timedelta(days=1)).date()
    providers = [p.strip() for p in settings.payment_reconcile_providers.split(",") if p.strip()]
    done: list[str] = []
    for provider in providers:
        try:
            from .payments import get_provider

            client = get_provider(provider, settings)
            if not client.configured():
                continue
            report = reconcilesvc.reconcile(session, provider=provider, biz_date=biz_date, settings=settings, source="scheduler")
            session.commit()
            done.append(provider)
            logger.info("对账完成 provider=%s date=%s diff=%s", provider, biz_date, report.summary.get("diff_count"))
        except Exception as exc:  # noqa: BLE001 - 单渠道失败继续其它渠道
            session.rollback()
            logger.exception("对账失败 provider=%s date=%s", provider, biz_date)
            write_audit(
                session,
                actor_id=None,
                action="payment.reconcile.failed",
                target_type="reconcile",
                target_id=provider,
                meta={"biz_date": biz_date.isoformat(), "error": type(exc).__name__},
            )
            session.commit()
    return done


def run_once(settings: Settings, db: Database | None = None, now: datetime | None = None) -> dict:
    """执行一轮全部自愈/定时任务；返回统计（便于测试与手动触发）。"""
    now = now or utcnow()
    own_db = db is None
    db = db or Database(settings)
    result: dict = {}
    session = db.session()
    # 重新入队的任务在对应事务 commit 成功后再投递 RQ，避免 worker 抢在提交前认领
    requeued_task_ids: list[str] = []
    requeued_run_ids: list[str] = []
    try:
        phases = [
            ("lease_reclaimed", lambda: sweep_leases(session, settings, now, requeued_task_ids)),
            ("stuck_requeued", lambda: requeue_stuck_runs(session, settings, now, requeued_task_ids, requeued_run_ids)),
            ("expired", lambda: subsvc.expire_due(session, now)),
            ("grace_expired", lambda: expire_grace_period(session, settings, now)),
            ("reminders", lambda: send_renewal_reminders(session, settings, now)),
            ("expired_notified", lambda: notify_expired_subscriptions(session, settings, now)),
            ("credits", lambda: sweep_credits(session, settings, now)),
            ("notifications_retried", lambda: retry_notifications(session, settings, now)),
            ("usage_alerts", lambda: check_usage_alerts(session, settings, now)),
            ("uploads_cleaned", lambda: cleanup_uploads(session, settings, now)),
            ("reconciled", lambda: reconcile_daily(session, settings, now)),
        ]
        for name, fn in phases:
            try:
                value = fn()
                session.commit()
                result[name] = value
                _dispatch_requeued(settings, requeued_task_ids, requeued_run_ids)
            except Exception:  # noqa: BLE001 - 单项失败不阻塞其它任务
                session.rollback()
                logger.exception("定时任务失败 phase=%s", name)
                result[name] = "error"
            finally:
                requeued_task_ids.clear()
                requeued_run_ids.clear()
    finally:
        session.close()
        if own_db:
            db.dispose()
    return result


def loop_forever(settings: Settings, interval: int | None = None, stop=None) -> None:
    seconds = max(5, int(interval or settings.scheduler_interval_seconds))
    while stop is None or not stop.is_set():
        started = time.monotonic()
        try:
            stats = run_once(settings)
            logger.info("scheduler tick done %s", stats)
        except Exception:  # noqa: BLE001
            logger.exception("scheduler tick failed")
        elapsed = time.monotonic() - started
        time.sleep(max(1, seconds - int(elapsed)))


def main() -> None:
    parser = argparse.ArgumentParser(description="墨写服务端定时任务")
    parser.add_argument("--once", action="store_true", help="只跑一轮后退出")
    parser.add_argument("--interval", type=int, default=0)
    args = parser.parse_args()
    settings = Settings()
    if args.once:
        print(run_once(settings))
        return
    loop_forever(settings, interval=args.interval or None)


if __name__ == "__main__":
    main()
