# -*- coding: utf-8 -*-
"""支付宝（电脑网站支付 / 当面付 + 退款 + 对账单）。

RSA2（SHA256withRSA）：参数按键名排序、剔除空值与 sign，拼 k=v& 后用应用私钥签名；
异步通知用支付宝公钥验签，并校验 app_id / seller_id / 金额 / 时间。
"""

from __future__ import annotations

import base64
import csv
import io
import json
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode

import httpx
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding

from ..errors import ApiError
from ..models import Order
from .base import (
    PaymentEvent,
    PaymentIntent,
    RefundResult,
    cents_from,
    external_order_no,
    money,
)

CN_TZ = timezone(timedelta(hours=8))


def _read(value: str, path: str) -> str:
    if value:
        return value.replace("\\n", "\n")
    if path and Path(path).is_file():
        return Path(path).read_text(encoding="utf-8")
    return ""


def _order_id_from_no(no: str) -> int | None:
    if no.startswith("MX") and no[2:].isdigit():
        return int(no[2:])
    return None


def build_sign_content(params: dict[str, Any]) -> str:
    items = []
    for key in sorted(params):
        value = params[key]
        if key == "sign" or value is None or str(value) == "":
            continue
        items.append(f"{key}={value}")
    return "&".join(items)


def rsa2_sign(content: str, private_key_pem: str) -> str:
    key = serialization.load_pem_private_key(private_key_pem.encode("utf-8"), password=None)
    signature = key.sign(content.encode("utf-8"), padding.PKCS1v15(), hashes.SHA256())
    return base64.b64encode(signature).decode()


def rsa2_verify(content: str, signature: str, public_key_pem: str) -> bool:
    try:
        key = serialization.load_pem_public_key(public_key_pem.encode("utf-8"))
        key.verify(
            base64.b64decode(signature),
            content.encode("utf-8"),
            padding.PKCS1v15(),
            hashes.SHA256(),
        )
        return True
    except Exception:  # noqa: BLE001
        return False


class AlipayProvider:
    name = "alipay"
    needs_credentials = True

    def __init__(self, settings, http_client=None):
        self.settings = settings
        self.http = http_client

    def _private_pem(self) -> str:
        pem = _read(self.settings.alipay_private_key_pem, self.settings.alipay_private_key_path)
        if not pem:
            raise ApiError(501, "provider_not_configured", "支付宝缺少应用私钥")
        return pem

    def _public_pem(self) -> str:
        pem = _read(self.settings.alipay_public_key_pem, self.settings.alipay_public_key_path)
        if not pem:
            raise ApiError(501, "provider_not_configured", "支付宝缺少支付宝公钥")
        return pem

    def configured(self) -> bool:
        return bool(
            self.settings.alipay_app_id
            and _read(self.settings.alipay_private_key_pem, self.settings.alipay_private_key_path)
            and _read(self.settings.alipay_public_key_pem, self.settings.alipay_public_key_path)
        )

    def require_configured(self) -> None:
        if not self.configured():
            raise ApiError(
                501,
                "provider_not_configured",
                "支付宝未配置：需要 app_id、应用私钥、支付宝公钥",
            )

    # ---- 公共参数与签名 ----------------------------------------------------
    def common_params(self, method: str, biz: dict[str, Any]) -> dict[str, str]:
        params = {
            "app_id": self.settings.alipay_app_id,
            "method": method,
            "format": "JSON",
            "charset": "utf-8",
            "sign_type": "RSA2",
            "timestamp": datetime.now(CN_TZ).strftime("%Y-%m-%d %H:%M:%S"),
            "version": "1.0",
            "notify_url": self.settings.alipay_notify_url,
            "biz_content": json.dumps(biz, ensure_ascii=False, separators=(",", ":")),
        }
        if method == "alipay.trade.page.pay" and self.settings.alipay_return_url:
            params["return_url"] = self.settings.alipay_return_url
        params["sign"] = rsa2_sign(build_sign_content(params), self._private_pem())
        return params

    def _request(self, method: str, biz: dict[str, Any]) -> dict[str, Any]:
        self.require_configured()
        params = self.common_params(method, biz)
        client = self.http or httpx.Client(timeout=self.settings.payment_timeout_seconds)
        try:
            response = client.post(self.settings.alipay_gateway, data=params)
        except httpx.HTTPError as exc:
            raise ApiError(502, "provider_unreachable", f"支付宝网络异常：{exc}") from exc
        try:
            payload = response.json()
        except ValueError as exc:
            raise ApiError(502, "provider_error", "支付宝返回非 JSON") from exc
        key = method.replace(".", "_") + "_response"
        body = payload.get(key) or payload
        if str(body.get("code")) not in ("10000", "20000"):
            raise ApiError(
                502, "provider_error", f"支付宝返回错误：{body.get('code')} {body.get('sub_msg') or ''}"
            )
        self._verify_response(method, body, payload.get("sign"))
        return body

    def _verify_response(self, method: str, body: dict, sign: str | None) -> None:
        if not sign:
            return
        content = json.dumps(body, ensure_ascii=False, separators=(",", ":"))
        if not rsa2_verify(content, sign, self._public_pem()):
            raise ApiError(502, "provider_signature_invalid", "支付宝响应验签失败")

    # ---- 下单 / 查单 / 关单 -------------------------------------------------
    def create_payment(self, order: Order, context: dict | None = None) -> PaymentIntent:
        self.require_configured()
        context = context or {}
        scene = str(context.get("scene") or self.settings.alipay_scene or "page")
        out_no = external_order_no(order)
        biz: dict[str, Any] = {
            "out_trade_no": out_no,
            "total_amount": money(order.amount_cents, order.currency),
            "subject": f"墨写订阅#{order.id}",
            "product_code": "FAST_INSTANT_TRADE_PAY" if scene == "page" else "FACE_TO_FACE_PAYMENT",
            "timeout_express": "30m",
        }
        if scene == "page":
            params = self.common_params("alipay.trade.page.pay", biz)
            order.external_order_no = out_no
            return PaymentIntent(
                provider=self.name,
                order_id=order.id,
                amount_cents=order.amount_cents,
                currency=order.currency,
                external_order_no=out_no,
                action="redirect",
                params={
                    "pay_url": self.settings.alipay_gateway + "?" + urlencode(params),
                    "out_trade_no": out_no,
                },
            )
        data = self._request("alipay.trade.precreate", biz)
        order.external_order_no = out_no
        return PaymentIntent(
            provider=self.name,
            order_id=order.id,
            amount_cents=order.amount_cents,
            currency=order.currency,
            external_order_no=out_no,
            action="qrcode",
            params={"qr_code": data.get("qr_code"), "out_trade_no": out_no},
        )

    def query_payment(self, order: Order) -> dict[str, Any]:
        return self._request("alipay.trade.query", {"out_trade_no": external_order_no(order)})

    def close_payment(self, order: Order) -> dict[str, Any]:
        return self._request("alipay.trade.close", {"out_trade_no": external_order_no(order)})

    # ---- 异步通知 ----------------------------------------------------------
    def parse_webhook(self, headers: dict[str, str], raw_body: bytes) -> PaymentEvent:
        text = raw_body.decode("utf-8", "replace")
        params = dict(parse_qsl(text, keep_blank_values=True))
        if not params:
            raise ApiError(400, "invalid_webhook", "支付宝回调参数为空")
        sign = params.pop("sign", "")
        sign_type = params.pop("sign_type", "RSA2")
        if sign_type != "RSA2" or not sign:
            raise ApiError(400, "invalid_signature", "支付宝回调缺少 RSA2 签名")
        if not rsa2_verify(build_sign_content(params), sign, self._public_pem()):
            raise ApiError(400, "invalid_signature", "支付宝回调验签失败")
        if params.get("app_id") != self.settings.alipay_app_id:
            raise ApiError(400, "app_id_mismatch", "支付宝回调 app_id 不匹配")
        seller = self.settings.alipay_seller_id
        if seller and params.get("seller_id") != seller:
            raise ApiError(400, "seller_mismatch", "支付宝回调 seller_id 不匹配")
        notify_time = params.get("notify_time")
        if notify_time:
            try:
                sent = datetime.strptime(notify_time, "%Y-%m-%d %H:%M:%S").replace(tzinfo=CN_TZ)
                if abs((datetime.now(CN_TZ) - sent).total_seconds()) > self.settings.webhook_tolerance_seconds:
                    raise ApiError(400, "webhook_expired", "支付宝回调时间超出容差")
            except ValueError:
                raise ApiError(400, "invalid_webhook", "支付宝 notify_time 格式错误")
        out_no = str(params.get("out_trade_no") or "")
        order_id = _order_id_from_no(out_no)
        event_id = str(params.get("notify_id") or f"{params.get('trade_no')}:{params.get('trade_status')}")
        refund_fee = params.get("refund_fee")
        if refund_fee and str(params.get("out_biz_no") or ""):
            return PaymentEvent(
                event_id=f"{event_id}:refund:{params.get('out_biz_no')}",
                event_type="refund",
                status="refunded",
                amount_cents=cents_from(refund_fee),
                currency="CNY",
                order_id=order_id,
                external_order_no=out_no or None,
                provider_txn_id=str(params.get("trade_no") or ""),
                refund_ref=str(params.get("out_biz_no")),
                raw={"trade_status": params.get("trade_status"), "notify_id": params.get("notify_id")},
            )
        status = {
            "TRADE_SUCCESS": "paid",
            "TRADE_FINISHED": "paid",
            "TRADE_CLOSED": "failed",
            "WAIT_BUYER_PAY": "pending",
        }.get(str(params.get("trade_status") or ""), "failed")
        return PaymentEvent(
            event_id=event_id,
            event_type="payment",
            status=status,
            amount_cents=cents_from(params.get("total_amount") or 0),
            currency="CNY",
            order_id=order_id,
            external_order_no=out_no or None,
            provider_txn_id=str(params.get("trade_no") or ""),
            raw={"trade_status": params.get("trade_status"), "notify_id": params.get("notify_id")},
        )

    # ---- 退款 --------------------------------------------------------------
    def create_refund(self, refund, order: Order) -> RefundResult:
        out_request_no = f"RF{refund.id:012d}"
        data = self._request(
            "alipay.trade.refund",
            {
                "out_trade_no": external_order_no(order),
                "out_request_no": out_request_no,
                "refund_amount": money(refund.amount_cents, order.currency),
                "refund_reason": (refund.reason or "用户退款")[:80],
            },
        )
        status = "succeeded" if str(data.get("code")) == "10000" else "failed"
        return RefundResult(
            provider_refund_id=str(data.get("trade_no") or out_request_no),
            status=status,
            amount_cents=refund.amount_cents,
            raw={"code": data.get("code"), "fund_change": data.get("fund_change")},
        )

    def query_refund(self, refund, order: Order) -> dict[str, Any]:
        return self._request(
            "alipay.trade.fastpay.refund.query",
            {"out_trade_no": external_order_no(order), "out_request_no": f"RF{refund.id:012d}"},
        )

    # ---- 对账单 ------------------------------------------------------------
    def download_bill(self, biz_date: str) -> list[dict[str, Any]]:
        data = self._request(
            "alipay.data.dataservice.bill.downloadurl.query",
            {"bill_type": "trade", "bill_date": biz_date},
        )
        url = data.get("bill_download_url")
        if not url:
            return []
        client = self.http or httpx.Client(timeout=self.settings.payment_timeout_seconds)
        response = client.get(url)
        if "zip" in response.headers.get("content-type", "") or url.endswith(".zip"):
            with zipfile.ZipFile(io.BytesIO(response.content)) as zf:
                name = next((n for n in zf.namelist() if n.endswith(".csv")), zf.namelist()[0])
                return parse_alipay_bill(zf.read(name).decode("gb18030", "replace"))
        return parse_alipay_bill(response.text)


def parse_alipay_bill(text: str) -> list[dict[str, Any]]:
    """解析支付宝对账单 CSV（GB18030）。"""
    lines = text.splitlines()
    header_index = next((i for i, line in enumerate(lines) if "商户订单号" in line), None)
    if header_index is None:
        return []
    rows = list(csv.reader(io.StringIO("\n".join(lines[header_index:]))))
    header = [cell.strip().lstrip("\ufeff") for cell in rows[0]]
    index = {name: i for i, name in enumerate(header)}
    out_col = next((index[k] for k in index if k.endswith("商户订单号")), None)
    amount_col = next((index[k] for k in index if k.endswith("订单金额")), None)
    txn_col = next((index[k] for k in index if k.endswith("支付宝交易号")), None)
    status_col = next((index[k] for k in index if "状态" in k), None)
    if out_col is None or amount_col is None:
        return []
    result = []
    for row in rows[1:]:
        if len(row) <= max(out_col, amount_col):
            continue
        record = {
            "external_order_no": row[out_col].strip().lstrip("`"),
            "amount_cents": cents_from(row[amount_col].strip().lstrip("`")),
            "provider_txn_id": row[txn_col].strip() if txn_col is not None and len(row) > txn_col else "",
            "status": "paid" if status_col is not None and "成功" in row[status_col] else "unknown",
        }
        if record["external_order_no"]:
            result.append(record)
    return result
