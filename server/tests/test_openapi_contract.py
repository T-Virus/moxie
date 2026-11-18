# -*- coding: utf-8 -*-
"""OpenAPI 出参契约：稳定接口应在 schema 中声明 response_model。"""

from __future__ import annotations

from app.models import Account


def _promote(app, account_id: int) -> None:
    """把测试账号提升为 admin，以便访问后台只读列表验证运行时契约。"""
    with app.state.db.session() as session:
        row = session.get(Account, account_id)
        row.role = "admin"
        session.commit()


def test_public_key_has_response_schema(client):
    spec = client.get("/openapi.json").json()
    op = spec["paths"]["/v1/crypto/public-key"]["get"]
    resp = op["responses"]["200"]
    schema_ref = resp["content"]["application/json"]["schema"]
    # 出参应指向 PublicKeyResponse 组件，而不是空的/隐式 any
    assert schema_ref.get("$ref", "").endswith("PublicKeyResponse")
    model = spec["components"]["schemas"]["PublicKeyResponse"]
    assert set(model["properties"]) == {"algorithm", "key_id", "public_key"}
    assert set(model.get("required", [])) == {"algorithm", "key_id", "public_key"}


def test_public_key_response_still_matches_runtime(client):
    # response_model 不能裁剪掉真实字段
    data = client.get("/v1/crypto/public-key").json()
    assert set(data) == {"algorithm", "key_id", "public_key"}
    assert data["algorithm"] and data["key_id"] and data["public_key"]


def test_healthz_has_response_schema(client):
    spec = client.get("/openapi.json").json()
    op = spec["paths"]["/healthz"]["get"]
    schema_ref = op["responses"]["200"]["content"]["application/json"]["schema"]
    assert schema_ref.get("$ref", "").endswith("HealthResponse")
    model = spec["components"]["schemas"]["HealthResponse"]
    assert set(model["properties"]) == {"status", "env", "app"}
    # 运行时字段不被裁剪
    data = client.get("/healthz").json()
    assert set(data) == {"status", "env", "app"}


def test_genres_has_response_schema(client):
    spec = client.get("/openapi.json").json()
    op = spec["paths"]["/v1/genres"]["get"]
    schema_ref = op["responses"]["200"]["content"]["application/json"]["schema"]
    assert schema_ref.get("$ref", "").endswith("GenresResponse")
    props = spec["components"]["schemas"]["GenresResponse"]["properties"]
    assert set(props) == {"items", "custom_allowed", "degraded"}
    # 运行时：response_model 会给可选字段补 degraded=null（前端 Boolean(null)=false，兼容）
    data = client.get("/v1/genres").json()
    assert "items" in data and isinstance(data["items"], list)
    assert data["custom_allowed"] is True
    assert set(data) == {"items", "custom_allowed", "degraded"}
    assert data["degraded"] is None


def test_payment_providers_has_response_schema(client):
    spec = client.get("/openapi.json").json()
    op = spec["paths"]["/v1/payments/providers"]["get"]
    schema_ref = op["responses"]["200"]["content"]["application/json"]["schema"]
    assert schema_ref.get("$ref", "").endswith("PaymentProvidersResponse")
    model = spec["components"]["schemas"]["PaymentProviderView"]
    assert set(model["properties"]) == {"id", "name", "test_only"}


def test_payment_providers_runtime_shape(client):
    data = client.get("/v1/payments/providers").json()
    assert set(data) == {"items"}
    for item in data["items"]:
        assert set(item) == {"id", "name", "test_only"}


def test_notifications_have_response_schema(client):
    spec = client.get("/openapi.json").json()
    list_ref = spec["paths"]["/v1/notifications"]["get"]["responses"]["200"]["content"]["application/json"]["schema"]
    assert list_ref.get("$ref", "").endswith("NotificationListResponse")
    read_ref = spec["paths"]["/v1/notifications/{notification_id}/read"]["post"]["responses"]["200"]["content"]["application/json"]["schema"]
    assert read_ref.get("$ref", "").endswith("NotificationReadResponse")
    view = spec["components"]["schemas"]["NotificationView"]
    # meta 为动态 dict：契约保留字段但不裁剪其内容
    assert set(view["properties"]) == {
        "id", "category", "title", "body", "level", "status", "meta", "created_at", "read_at"
    }


def test_notifications_runtime_shape(client, headers):
    data = client.get("/v1/notifications", headers=headers).json()
    assert set(data) == {"items", "unread_count"}
    for item in data["items"]:
        assert set(item) == {
            "id", "category", "title", "body", "level", "status", "meta", "created_at", "read_at"
        }


def test_plans_has_response_schema(client):
    spec = client.get("/openapi.json").json()
    ref = spec["paths"]["/v1/plans"]["get"]["responses"]["200"]["content"]["application/json"]["schema"]
    assert ref.get("$ref", "").endswith("PlansResponse")
    view = spec["components"]["schemas"]["PlanView"]
    assert set(view["properties"]) == {
        "code", "name", "price_month_cents", "price_year_cents", "currency", "features", "entitlements"
    }
    ent = spec["components"]["schemas"]["PlanEntitlementView"]
    assert set(ent["properties"]) == {"key", "limit", "unit", "reset_period"}


def test_plans_runtime_shape(client):
    data = client.get("/v1/plans").json()
    assert set(data) == {"plans"}
    assert data["plans"], "测试环境应种出套餐"
    for plan in data["plans"]:
        assert set(plan) == {
            "code", "name", "price_month_cents", "price_year_cents", "currency", "features", "entitlements"
        }
        assert isinstance(plan["features"], dict), "features 动态字典不被裁剪"
        for ent in plan["entitlements"]:
            assert set(ent) == {"key", "limit", "unit", "reset_period"}


def test_entitlements_and_usage_summary_share_contract(client, headers):
    spec = client.get("/openapi.json").json()
    for path in ("/v1/entitlements", "/v1/usage/summary"):
        ref = spec["paths"][path]["get"]["responses"]["200"]["content"]["application/json"]["schema"]
        assert ref.get("$ref", "").endswith("QuotaSummaryResponse")
    view = spec["components"]["schemas"]["QuotaSummaryResponse"]
    assert set(view["properties"]) == {
        "plan", "period_start", "period_end", "metrics", "credits", "server_time"
    }
    # 两个同源接口运行时结构一致，动态值不被裁剪
    for path in ("/v1/entitlements", "/v1/usage/summary"):
        data = client.get(path, headers=headers).json()
        assert set(data) == {
            "plan", "period_start", "period_end", "metrics", "credits", "server_time"
        }
        for metric in data["metrics"]:
            assert set(metric) == {
                "metric", "unit", "limit", "used", "reserved", "remaining", "pack_remaining", "total_remaining"
            }


def test_admin_plans_has_response_schema(client, headers, app, account):
    _promote(app, account["account"]["id"])
    spec = client.get("/openapi.json").json()
    ref = spec["paths"]["/v1/admin/plans"]["get"]["responses"]["200"]["content"]["application/json"]["schema"]
    assert ref.get("$ref", "").endswith("AdminPlansResponse")
    view = spec["components"]["schemas"]["AdminPlanView"]
    assert {"active", "status", "features", "entitlements"}.issubset(set(view["properties"]))
    data = client.get("/v1/admin/plans", headers=headers).json()
    assert set(data) == {"plans"}
    for plan in data["plans"]:
        assert set(plan) == {
            "code", "name", "price_month_cents", "price_year_cents", "currency",
            "features", "active", "status", "entitlements"
        }


def test_audit_logs_has_response_schema(client, headers, app, account):
    _promote(app, account["account"]["id"])
    spec = client.get("/openapi.json").json()
    ref = spec["paths"]["/v1/admin/audit-logs"]["get"]["responses"]["200"]["content"]["application/json"]["schema"]
    assert ref.get("$ref", "").endswith("AuditLogsResponse")
    view = spec["components"]["schemas"]["AuditLogView"]
    assert set(view["properties"]) == {
        "id", "actor_id", "action", "target_type", "target_id", "ip", "meta", "created_at"
    }
    data = client.get("/v1/admin/audit-logs", headers=headers).json()
    assert set(data) == {"items", "total", "page", "page_size"}
    for row in data["items"]:
        assert set(row) == {
            "id", "actor_id", "action", "target_type", "target_id", "ip", "meta", "created_at"
        }


def _schema_ref(spec, path: str, method: str) -> str:
    """取 200/201 其中一个成功响应的 $ref；201 用于声明 status_code=201 的创建路由。"""
    responses = spec["paths"][path][method]["responses"]
    code = "200" if "200" in responses else "201"
    return responses[code]["content"]["application/json"]["schema"].get("$ref", "")


def test_subscriptions_have_response_schema(client, headers):
    """订阅 6 路由声明契约；动态 params/meta 不被裁剪，current 多 renewal_reminder。"""
    spec = client.get("/openapi.json").json()
    cases = {
        ("/v1/subscriptions", "post"): "CreateSubscriptionResponse",
        ("/v1/subscriptions/current", "get"): "CurrentSubscriptionResponse",
        ("/v1/subscriptions/{subscription_id}/cancel", "post"): "SubscriptionActionResponse",
        ("/v1/subscriptions/{subscription_id}/resume", "post"): "SubscriptionActionResponse",
        ("/v1/subscriptions/{subscription_id}/renew", "post"): "RenewSubscriptionResponse",
        ("/v1/subscriptions/{subscription_id}/upgrade", "post"): "UpgradeSubscriptionResponse",
    }
    for (path, method), name in cases.items():
        assert _schema_ref(spec, path, method).endswith(name), (path, method)

    sub_view = spec["components"]["schemas"]["SubscriptionView"]
    assert set(sub_view["properties"]) == {
        "id", "status", "plan", "seats", "cancel_at_period_end",
        "current_start_at", "current_end_at", "days_left", "provider", "version",
        "renewal_reminder",
    }
    order_view = spec["components"]["schemas"]["OrderView"]
    assert "meta" in order_view["properties"]
    assert "params" in spec["components"]["schemas"]["PaymentIntentView"]["properties"]

    # 运行时：下单响应结构固定，payment.params 动态字段保留
    from .helpers import subscribe

    created = subscribe(client, headers)["response"]
    assert set(created) == {"subscription", "order", "payment"}
    assert set(created["subscription"]) == {
        "id", "status", "plan", "seats", "cancel_at_period_end",
        "current_start_at", "current_end_at", "days_left", "provider", "version",
        "renewal_reminder",
    }
    assert created["subscription"]["renewal_reminder"] is None  # 非 current 接口补 null
    assert set(created["order"]) == {
        "id", "subscription_id", "amount_cents", "currency", "status", "provider",
        "kind", "cycle", "refunded_cents", "meta", "paid_at", "created_at",
    }
    assert set(created["payment"]) == {"provider", "amount_cents", "currency", "params"}
    assert "webhook_path" in created["payment"]["params"]  # 动态参数未被裁剪

    current = client.get("/v1/subscriptions/current", headers=headers).json()
    assert isinstance(current["renewal_reminder"], bool)  # current 必出 bool


def test_tasks_have_response_schema(client, headers):
    """任务 4 路由声明契约；task.params 动态字段保留。"""
    spec = client.get("/openapi.json").json()
    cases = {
        ("/v1/tasks", "post"): "CreateTaskResponse",
        ("/v1/tasks/{task_id}", "get"): "TaskDetailResponse",
        ("/v1/tasks/{task_id}/logs", "get"): "TaskLogsResponse",
        ("/v1/tasks/{task_id}/cancel", "post"): "CancelTaskResponse",
    }
    for (path, method), name in cases.items():
        assert _schema_ref(spec, path, method).endswith(name), (path, method)

    task_view = spec["components"]["schemas"]["TaskView"]
    assert set(task_view["properties"]) == {
        "id", "type", "status", "book_id", "progress", "params", "input_artifact",
        "output_artifact", "error_code", "cancel_requested", "attempts", "next_retry_at",
        "prompt_version", "cost_estimate_cents", "cost_actual_cents",
        "created_at", "started_at", "finished_at",
    }

    from .helpers import subscribe

    subscribe(client, headers)
    body = {"type": "decompose", "params": {"title": "契约任务", "aigc_label": True}}
    created = client.post(
        "/v1/tasks", headers={**headers, "Idempotency-Key": "contract-task-1"}, json=body
    ).json()
    assert set(created) == {"task", "created", "enqueued"}
    task = created["task"]
    assert set(task) == set(task_view["properties"])
    assert task["params"]["aigc_label"] is True  # 动态参数保留
    assert task["next_retry_at"] is None

    logs = client.get(f"/v1/tasks/{task['id']}/logs", headers=headers).json()
    assert set(logs) == {"events", "next_seq"}
    for event in logs["events"]:
        assert set(event) == {"seq", "level", "message", "created_at"}


def test_agent_run_fixed_routes_have_response_schema(client, headers, app):
    """写作运行仅固定结构路由契约化；run_to_dict 动态详情/列表保持 dict 不裁剪。"""
    spec = client.get("/openapi.json").json()
    cases = {
        ("/v1/agent-runs", "post"): "CreateAgentRunResponse",
        ("/v1/agent-runs/{run_id}/cancel", "post"): "AgentRunActionResponse",
        ("/v1/agent-runs/{run_id}/pause", "post"): "AgentRunActionResponse",
        ("/v1/agent-runs/{run_id}/cover", "post"): "AgentRunCoverResponse",
        ("/v1/agent-runs/{run_id}/cover/upload", "post"): "AgentRunCoverResponse",
        ("/v1/agent-runs/{run_id}/cover", "delete"): "AgentRunCoverDeleteResponse",
        ("/v1/agent-runs/{run_id}", "delete"): "AgentRunDeleteResponse",
    }
    for (path, method), name in cases.items():
        assert _schema_ref(spec, path, method).endswith(name), (path, method)

    # 动态详情/列表/SSE 不声明响应模型（避免裁剪 outline/chapters 等动态字段）
    assert _schema_ref(spec, "/v1/agent-runs/{run_id}", "get") == ""
    assert _schema_ref(spec, "/v1/agent-runs", "get") == ""
    assert _schema_ref(spec, "/v1/agent-runs/{run_id}/events", "get") == ""

    created_schema = spec["components"]["schemas"]["CreateAgentRunResponse"]
    assert set(created_schema["properties"]) == {
        "run_id", "status", "mode", "created_at", "created", "enqueued"
    }

    from .helpers import subscribe

    # mock 掉 worker 入队与模型调用，只验证出参结构
    from .test_agent_runs import _stub

    _stub(app)
    subscribe(client, headers)
    created = client.post(
        "/v1/agent-runs",
        headers={**headers, "Idempotency-Key": "contract-run-1"},
        json={
            "mode": "custom", "title": "契约作品", "audience": "female",
            "length": "long", "genre": {"id": None, "name": "古言"},
        },
    )
    assert created.status_code == 201, created.text
    assert set(created.json()) == set(created_schema["properties"])


def test_orders_and_usage_have_response_schema(client, headers, app, account):
    """订单详情/列表 + 用量列表声明契约；meta 动态字段（含 None）均保留不裁剪。"""
    spec = client.get("/openapi.json").json()
    cases = {
        ("/v1/orders/{order_id}", "get"): "GetOrderResponse",
        ("/v1/orders", "get"): "OrderListResponse",
        ("/v1/usage", "get"): "UsageListResponse",
    }
    for (path, method), name in cases.items():
        assert _schema_ref(spec, path, method).endswith(name), (path, method)

    usage_view = spec["components"]["schemas"]["UsageEventView"]
    assert set(usage_view["properties"]) == {
        "id", "task_id", "metric", "quantity", "unit", "occurred_at", "meta"
    }

    from .helpers import subscribe

    order = subscribe(client, headers)["order"]
    detail = client.get(f"/v1/orders/{order['id']}", headers=headers).json()
    assert set(detail) == {"order"}
    assert set(detail["order"]) == {
        "id", "subscription_id", "amount_cents", "currency", "status", "provider",
        "kind", "cycle", "refunded_cents", "meta", "paid_at", "created_at",
    }
    listing = client.get("/v1/orders", headers=headers).json()
    assert set(listing) == {"orders"}  # 顶层是 orders，不是 items
    assert all(set(o) == set(detail["order"]) for o in listing["orders"])

    # 用量事件：直接种一条 meta=None 的记录，验证 None 不被 response_model 裁掉/报错
    from datetime import timedelta

    from app.db import utcnow
    from app.models import UsageEvent

    with app.state.db.session() as session:
        session.add(
            UsageEvent(
                account_id=account["account"]["id"],
                task_id=None,
                metric="model_token",
                quantity=12,
                unit="token",
                idempotency_key="contract-usage-1",
                occurred_at=utcnow() - timedelta(minutes=1),
                meta=None,
            )
        )
        session.commit()
    usage = client.get("/v1/usage", headers=headers).json()
    assert set(usage) == {"items", "next_before_id"}
    assert set(usage["items"][0]) == set(usage_view["properties"])
    assert usage["items"][0]["meta"] is None  # 关键：None 原样保留


def test_admin_lists_have_response_schema(client, headers, app, account):
    """后台用户/订阅/订单/任务/告警列表声明契约；分页字段与动态字段完整。"""
    _promote(app, account["account"]["id"])
    spec = client.get("/openapi.json").json()
    cases = {
        "/v1/admin/users": ("AdminUsersResponse", "AdminAccountView"),
        "/v1/admin/subscriptions": ("AdminSubscriptionsResponse", "AdminSubscriptionView"),
        "/v1/admin/orders": ("AdminOrdersResponse", "AdminOrderView"),
        "/v1/admin/tasks": ("AdminTasksResponse", "TaskBriefView"),
        "/v1/admin/alerts": ("AdminAlertsResponse", "AdminAlertView"),
    }
    for path, (resp_name, view_name) in cases.items():
        assert _schema_ref(spec, path, "get").endswith(resp_name), path
        assert view_name in spec["components"]["schemas"], view_name

    # 关键动态字段不裁剪：后台订单 meta 可 None、订阅 days_left 是 int
    assert "meta" in spec["components"]["schemas"]["AdminOrderView"]["properties"]
    assert spec["components"]["schemas"]["AdminSubscriptionView"]["properties"]["days_left"]["type"] == "integer"
    # 告警响应额外计数字段完整声明
    alert_props = spec["components"]["schemas"]["AdminAlertsResponse"]["properties"]
    assert {"window_hours", "failed_notifications", "webhook_failures"} <= set(alert_props)

    # 运行时：typecheck 注入的 Optional 字段补全后字段集与 View 一致
    from .helpers import subscribe

    subscribe(client, headers)
    users = client.get("/v1/admin/users", headers=headers).json()
    assert set(users) == {"items", "total", "page", "page_size"}
    assert set(users["items"][0]) == set(spec["components"]["schemas"]["AdminAccountView"]["properties"])
    subs = client.get("/v1/admin/subscriptions", headers=headers).json()
    assert set(subs["items"][0]) == set(spec["components"]["schemas"]["AdminSubscriptionView"]["properties"])
    orders = client.get("/v1/admin/orders", headers=headers).json()
    assert set(orders["items"][0]) == set(spec["components"]["schemas"]["AdminOrderView"]["properties"])
    tasks = client.get("/v1/admin/tasks", headers=headers).json()
    assert set(tasks) == {"items", "total", "page", "page_size"}
    if tasks["items"]:
        assert set(tasks["items"][0]) == set(spec["components"]["schemas"]["TaskBriefView"]["properties"])
    alerts = client.get("/v1/admin/alerts", headers=headers).json()
    assert set(alerts) == {"items", "total", "page", "page_size", "window_hours", "failed_notifications", "webhook_failures"}


# —— 第十三批：对账/额度/预设/退款/发票契约 -----------------------------------

def _contract_op(client: object, path: str, method: str, model: str) -> None:
    spec = client.get("/openapi.json").json()  # type: ignore[attr-defined]
    op = spec["paths"][path][method]
    # 201 路由的 schema 挂在 responses["201"]，200 挂在 ["200"]
    key = "201" if "201" in op["responses"] else "200"
    ref = op["responses"][key]["content"]["application/json"]["schema"].get("$ref", "")
    assert ref.endswith(model), (path, ref)
    assert model in spec["components"]["schemas"]


def test_batch13_admin_contracts(client):
    # OpenAPI 是静态文档，无需鉴权即可核对契约声明
    cases = [
        ("/v1/admin/reconcile-reports", "get", "AdminReconcileReportsResponse"),
        ("/v1/admin/accounts/{account_id}/quota-adjustments", "get", "AdminQuotaAdjustmentsResponse"),
        ("/v1/admin/accounts/{account_id}/quota-adjustments", "post", "AdminQuotaAdjustResponse"),
        ("/v1/admin/presets", "get", "AdminPresetListResponse"),
        ("/v1/admin/presets", "post", "AdminPresetView"),
        ("/v1/admin/presets/sync-seeds", "post", "AdminPresetSyncResponse"),
    ]
    for path, method, model in cases:
        _contract_op(client, path, method, model)


def test_health_report_contract(client):
    _contract_op(
        client,
        "/v1/agent-runs/{run_id}/health-report",
        "get",
        "AgentRunHealthReportResponse",
    )


def test_dead_letter_contract(client):
    _contract_op(client, "/v1/admin/tasks/dead-letters", "get", "AdminDeadLettersResponse")


def test_four_ledger_contract(client):
    _contract_op(
        client,
        "/v1/admin/payments/four-ledger-reconcile",
        "get",
        "FourLedgerReconcileResponse",
    )


def test_batch13_notification_batch_contracts(client):
    cases = [
        ("/v1/admin/notifications/batch", "post", "AdminNotificationBatchResponse"),
        ("/v1/admin/notifications/{delivery_id}/receipts", "get", "PushReceiptHistoryResponse"),
    ]
    for path, method, model in cases:
        _contract_op(client, path, method, model)


def test_batch13_payments_presets_contracts(client):
    cases = [
        ("/v1/refunds", "get", "RefundListResponse"),
        ("/v1/invoices", "get", "InvoiceListResponse"),
        ("/v1/invoices/{invoice_id}", "get", "InvoiceDetailResponse"),
        ("/v1/presets", "get", "PresetsResponse"),
    ]
    for path, method, model in cases:
        _contract_op(client, path, method, model)
    # 字段边界：退款/发票契约存在，且保留旧前端别名不因契约裁剪
    spec = client.get("/openapi.json").json()
    for name in ("RefundView", "InvoiceView"):
        assert spec["components"]["schemas"][name]["properties"]
    assert "refunds" in spec["components"]["schemas"]["RefundListResponse"]["properties"]


# —— 第十六批：dashboard / offline-packages / model-configs 契约 ---------------

def test_batch16_dashboard_contracts(client, headers, app, account):
    """两个看板只读端点声明顶层 response_model，明细复用 TaskBriefView。"""
    _promote(app, account["account"]["id"])
    spec = client.get("/openapi.json").json()
    cases = [
        ("/v1/admin/tasks/dashboard", "get", "AdminTasksDashboardResponse"),
        ("/v1/admin/dashboard", "get", "AdminDashboardResponse"),
    ]
    for path, method, model in cases:
        _contract_op(client, path, method, model)

    board = spec["components"]["schemas"]["AdminTasksDashboardResponse"]
    assert set(board["properties"]) == {
        "queue_depth", "running_count", "failed_count", "retryable_count",
        "generated_at", "running", "failed", "by_status",
    }
    overview = spec["components"]["schemas"]["AdminDashboardResponse"]
    assert set(overview["properties"]) == {
        "tasks", "alerts", "pending_refunds", "paid_orders_24h",
    }
    assert "TaskBriefView" in spec["components"]["schemas"]

    # 运行时：response_model 不裁剪真实字段
    data = client.get("/v1/admin/tasks/dashboard", headers=headers).json()
    assert set(data) == set(board["properties"])
    for row in data["running"] + data["failed"]:
        assert set(row) == set(spec["components"]["schemas"]["TaskBriefView"]["properties"])


def test_batch16_offline_packages_contracts(client):
    """离线包 JSON 端点声明契约；二进制下载保持无 response_model。"""
    spec = client.get("/openapi.json").json()
    # 数组返回：顶层 schema 为 array，元素 $ref 指向 OfflinePackageView
    listing = spec["paths"]["/v1/admin/offline-packages"]["get"]["responses"]["200"]["content"]["application/json"]["schema"]
    assert listing["type"] == "array"
    assert listing["items"]["$ref"].endswith("OfflinePackageView")
    _contract_op(client, "/v1/admin/offline-packages/limits", "get", "OfflinePackageLimitsResponse")
    _contract_op(client, "/v1/admin/offline-packages", "post", "OfflinePackageView")
    _contract_op(client, "/v1/admin/offline-packages/{pkg_id}", "delete", "OfflinePackageDeleteResponse")
    # 下载是二进制流，不应挂 JSON response_model
    assert _schema_ref(spec, "/v1/admin/offline-packages/{pkg_id}/download", "get") == ""
    view = spec["components"]["schemas"]["OfflinePackageView"]
    assert set(view["properties"]) == {
        "id", "platform", "version", "filename", "size", "content_type",
        "is_active", "release_notes", "uploaded_by", "created_at", "updated_at", "download_url",
    }


def test_batch16_model_configs_contracts(client):
    """模型配置：列表返回 array-of-ref，PUT direct-ref，DELETE/测试补齐新契约。"""
    spec = client.get("/openapi.json").json()
    listing = spec["paths"]["/v1/admin/model-configs"]["get"]["responses"]["200"]["content"]["application/json"]["schema"]
    assert listing["type"] == "array"
    assert listing["items"]["$ref"].endswith("AdminModelConfigView")
    assert _schema_ref(spec, "/v1/admin/model-configs/{step_key}", "put").endswith("AdminModelConfigView")
    _contract_op(client, "/v1/admin/model-configs/{step_key}", "delete", "AdminModelConfigDeleteResponse")
    _contract_op(client, "/v1/admin/model-configs/{step_key}/test", "post", "AdminModelConfigTestResponse")
    assert set(spec["components"]["schemas"]["AdminModelConfigDeleteResponse"]["properties"]) == {
        "deleted", "step_key",
    }
    assert set(spec["components"]["schemas"]["AdminModelConfigTestResponse"]["properties"]) == {
        "ok", "model", "tokens",
    }
