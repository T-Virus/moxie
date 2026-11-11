# -*- coding: utf-8 -*-
"""微信支付 v3（JSAPI / Native / H5，含退款与对账单）。

官方规范要点：
  · 请求签名：WECHATPAY2-SHA256-RSA2048，签名串 = 方法\\n路径\\n时间戳\\n随机串\\n请求体\\n
  · 回调验签：时间戳\\n随机串\\n原始请求体\\n，用平台证书/公钥验 RSA-SHA256；时间戳容差默认 300s
  · 回调解密：AEAD_AES_256_GCM，key=APIv3 密钥，nonce/associated_data 来自 resource
"""

from __future__ import annotations

import base64
import csv
import io
import json
import secrets
import time
from pathlib import Path
from typing import Any

import httpx
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from ..errors import ApiError
from ..models import Order
from .base import (
    PaymentEvent,
    PaymentIntent,
    RefundResult,
    cents_from,
    external_order_no,
)


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


class WeChatPayProvider:
    name = "wechat"
    needs_credentials = True

    def __init__(self, settings, http_client=None):
        self.settings = settings
        self.http = http_client

    # ---- 配置 --------------------------------------------------------------
    def _merchant_key(self):
        pem = _read(self.settings.wechat_private_key_pem, self.settings.wechat_private_key_path)
        if not pem:
            raise ApiError(501, "provider_not_configured", "微信支付缺少商户 API 私钥")
        return serialization.load_pem_private_key(pem.encode("utf-8"), password=None)

    def _platform_key(self):
        pem = _read(self.settings.wechat_platform_cert_pem, self.settings.wechat_platform_cert_path)
        if not pem:
            raise ApiError(501, "provider_not_configured", "微信支付缺少平台证书/公钥")
        if "BEGIN CERTIFICATE" in pem:
            from cryptography import x509

            return x509.load_pem_x509_certificate(pem.encode("utf-8")).public_key()
        return serialization.load_pem_public_key(pem.encode("utf-8"))

    def configured(self) -> bool:
        return all(
            [
                self.settings.wechat_mch_id,
                self.settings.wechat_app_id,
                self.settings.wechat_api_v3_key,
                bool(_read(self.settings.wechat_private_key_pem, self.settings.wechat_private_key_path)),
                bool(_read(self.settings.wechat_platform_cert_pem, self.settings.wechat_platform_cert_path)),
            ]
        )

    def require_configured(self) -> None:
        if not self.configured():
            raise ApiError(
                501,
                "provider_not_configured",
                "微信支付未配置：需要商户号、appid、APIv3 密钥、商户私钥、平台证书",
            )

    # ---- 请求签名 ----------------------------------------------------------
    def build_authorization(self, method: str, path: str, body: str) -> str:
        ts = str(int(time.time()))
        nonce = secrets.token_hex(16)
        message = f"{method}\n{path}\n{ts}\n{nonce}\n{body}\n".encode("utf-8")
        signature = base64.b64encode(
            self._merchant_key().sign(message, padding.PKCS1v15(), hashes.SHA256())
        ).decode()
        serial = self.settings.wechat_cert_serial_no
        return (
            f'WECHATPAY2-SHA256-RSA2048 mchid="{self.settings.wechat_mch_id}",'
            f'nonce_str="{nonce}",signature="{signature}",timestamp="{ts}",serial_no="{serial}"'
        )

    def _request(self, method: str, path: str, payload: dict | None = None) -> dict[str, Any]:
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")) if payload else ""
        headers = {
            "Authorization": self.build_authorization(method, path, body),
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": "moxie-server/1.0",
        }
        client = self.http or httpx.Client(timeout=self.settings.payment_timeout_seconds)
        try:
            response = client.request(
                method, self.settings.wechat_api_base + path, content=body or None, headers=headers
            )
        except httpx.HTTPError as exc:
            raise ApiError(502, "provider_unreachable", f"微信支付网络异常：{exc}") from exc
        text = response.text
        try:
            data = json.loads(text) if text else {}
        except json.JSONDecodeError:
            data = {"raw": text[:500]}
        if response.status_code >= 300:
            code = str(data.get("code") or "provider_error")
            raise ApiError(502, "provider_error", f"微信支付返回 {response.status_code}：{code}")
        return data

    # ---- 下单 / 查单 / 关单 -------------------------------------------------
    def create_payment(self, order: Order, context: dict | None = None) -> PaymentIntent:
        self.require_configured()
        context = context or {}
        scene = str(context.get("scene") or self.settings.wechat_pay_scene or "native")
        if scene not in ("native", "jsapi", "h5"):
            raise ApiError(422, "invalid_scene", f"不支持的微信支付场景：{scene}")
        out_no = external_order_no(order)
        payload: dict[str, Any] = {
            "appid": self.settings.wechat_app_id,
            "mchid": self.settings.wechat_mch_id,
            "description": f"墨写订阅#{order.id}",
            "out_trade_no": out_no,
            "notify_url": self.settings.wechat_notify_url,
            "amount": {"total": order.amount_cents, "currency": order.currency},
        }
        if scene == "jsapi":
            openid = context.get("openid")
            if not openid:
                raise ApiError(422, "openid_required", "JSAPI 下单需要 openid")
            payload["payer"] = {"openid": openid}
        data = self._request("POST", f"/v3/pay/transactions/{scene}", payload)
        params: dict[str, Any]
        if scene == "native":
            params = {"code_url": data.get("code_url"), "out_trade_no": out_no}
            action = "qrcode"
        elif scene == "h5":
            params = {"h5_url": data.get("h5_url"), "out_trade_no": out_no}
            action = "redirect"
        else:
            prepay_id = data.get("prepay_id")
            ts = str(int(time.time()))
            nonce = secrets.token_hex(16)
            message = f"{self.settings.wechat_app_id}\n{ts}\n{nonce}\nprepay_id={prepay_id}\n".encode()
            pay_sign = base64.b64encode(
                self._merchant_key().sign(message, padding.PKCS1v15(), hashes.SHA256())
            ).decode()
            params = {
                "appId": self.settings.wechat_app_id,
                "timeStamp": ts,
                "nonceStr": nonce,
                "package": f"prepay_id={prepay_id}",
                "signType": "RSA",
                "paySign": pay_sign,
            }
            action = "jsapi"
        order.external_order_no = out_no
        return PaymentIntent(
            provider=self.name,
            order_id=order.id,
            amount_cents=order.amount_cents,
            currency=order.currency,
            external_order_no=out_no,
            action=action,
            params=params,
        )

    def query_payment(self, order: Order) -> dict[str, Any]:
        self.require_configured()
        out_no = external_order_no(order)
        return self._request(
            "GET",
            f"/v3/pay/transactions/out-trade-no/{out_no}?mchid={self.settings.wechat_mch_id}",
        )

    def close_payment(self, order: Order) -> dict[str, Any]:
        self.require_configured()
        out_no = external_order_no(order)
        self._request("POST", f"/v3/pay/transactions/out-trade-no/{out_no}/close", {
            "mchid": self.settings.wechat_mch_id
        })
        return {"out_trade_no": out_no, "closed": True}

    # ---- 回调验签 / 解密 ---------------------------------------------------
    def parse_webhook(self, headers: dict[str, str], raw_body: bytes) -> PaymentEvent:
        ts = headers.get("wechatpay-timestamp", "")
        nonce = headers.get("wechatpay-nonce", "")
        signature = headers.get("wechatpay-signature", "")
        if not (ts.isdigit() and nonce and signature):
            raise ApiError(400, "invalid_signature", "缺少微信支付签名头")
        if abs(int(time.time()) - int(ts)) > self.settings.webhook_tolerance_seconds:
            raise ApiError(400, "webhook_expired", "回调时间戳超出容差")
        message = f"{ts}\n{nonce}\n".encode() + raw_body + b"\n"
        try:
            self._platform_key().verify(
                base64.b64decode(signature), message, padding.PKCS1v15(), hashes.SHA256()
            )
        except ApiError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise ApiError(400, "invalid_signature", "微信支付回调验签失败") from exc

        body = json.loads(raw_body.decode("utf-8") or "{}")
        resource = body.get("resource") or {}
        plain = self._decrypt(resource)
        event_type = str(body.get("event_type") or "")
        out_no = str(plain.get("out_trade_no") or "")
        order_id = _order_id_from_no(out_no)
        event_id = str(body.get("id") or f"{event_type}:{plain.get('transaction_id') or out_no}")
        if event_type.startswith("REFUND"):
            status = {
                "REFUND.SUCCESS": "refunded",
                "REFUND.ABNORMAL": "refund_failed",
                "REFUND.CLOSED": "refund_failed",
            }.get(event_type, "pending")
            return PaymentEvent(
                event_id=event_id,
                event_type="refund",
                status=status,
                amount_cents=int(plain.get("amount", {}).get("refund") or 0),
                currency=str(plain.get("amount", {}).get("currency") or "CNY"),
                order_id=order_id,
                external_order_no=out_no or None,
                provider_txn_id=str(plain.get("transaction_id") or ""),
                refund_ref=str(plain.get("out_refund_no") or ""),
                raw={"event_type": event_type, "resource": plain},
            )
        status = "paid" if event_type == "TRANSACTION.SUCCESS" else "failed"
        return PaymentEvent(
            event_id=event_id,
            event_type="payment",
            status=status,
            amount_cents=int(plain.get("amount", {}).get("total") or 0),
            currency=str(plain.get("amount", {}).get("currency") or "CNY"),
            order_id=order_id,
            external_order_no=out_no or None,
            provider_txn_id=str(plain.get("transaction_id") or ""),
            raw={"event_type": event_type, "resource": plain},
        )

    def _decrypt(self, resource: dict) -> dict[str, Any]:
        key = self.settings.wechat_api_v3_key.encode("utf-8")
        if len(key) != 32:
            raise ApiError(500, "provider_config_invalid", "微信 APIv3 密钥必须是 32 字节")
        try:
            plain = AESGCM(key).decrypt(
                str(resource.get("nonce")).encode(),
                base64.b64decode(str(resource.get("ciphertext"))),
                str(resource.get("associated_data") or "").encode(),
            )
        except Exception as exc:  # noqa: BLE001
            raise ApiError(400, "invalid_webhook", "微信回调解密失败") from exc
        return json.loads(plain.decode("utf-8"))

    # ---- 退款 --------------------------------------------------------------
    def create_refund(self, refund, order: Order) -> RefundResult:
        self.require_configured()
        out_refund_no = f"RF{refund.id:012d}"
        payload = {
            "out_trade_no": external_order_no(order),
            "out_refund_no": out_refund_no,
            "reason": (refund.reason or "用户退款")[:80],
            "notify_url": self.settings.wechat_notify_url,
            "amount": {
                "refund": refund.amount_cents,
                "total": order.amount_cents,
                "currency": order.currency,
            },
        }
        data = self._request("POST", "/v3/refund/domestic/refunds", payload)
        status = {"SUCCESS": "succeeded", "PROCESSING": "pending"}.get(
            str(data.get("status") or ""), "failed"
        )
        return RefundResult(
            provider_refund_id=str(data.get("refund_id") or out_refund_no),
            status=status,
            amount_cents=refund.amount_cents,
            raw=data,
        )

    def query_refund(self, refund, order: Order) -> dict[str, Any]:
        self.require_configured()
        out_refund_no = refund.meta.get("out_refund_no") or f"RF{refund.id:012d}"
        return self._request("GET", f"/v3/refund/domestic/refunds/{out_refund_no}")

    # ---- 对账单 ------------------------------------------------------------
    def download_bill(self, biz_date: str) -> list[dict[str, Any]]:
        self.require_configured()
        data = self._request("GET", f"/v3/bill/tradebill?bill_date={biz_date}&bill_type=ALL")
        url = data.get("download_url")
        if not url:
            return []
        client = self.http or httpx.Client(timeout=self.settings.payment_timeout_seconds)
        try:
            response = client.get(url)
        except httpx.HTTPError as exc:
            raise ApiError(502, "provider_unreachable", f"微信账单下载失败：{exc}") from exc
        return parse_tradebill(response.text)


def parse_tradebill(text: str) -> list[dict[str, Any]]:
    """解析微信交易账单 CSV。金额单位元 → 分。"""
    if not text.strip():
        return []
    lines = [line.lstrip("\ufeff") for line in text.splitlines()]
    header_index = next(
        (i for i, line in enumerate(lines) if "商户订单号" in line or "订单号" in line), None
    )
    if header_index is None:
        return []
    rows = list(csv.reader(io.StringIO("\n".join(lines[header_index:]))))
    header = [cell.strip().lstrip("`") for cell in rows[0]]
    index = {name: i for i, name in enumerate(header)}
    out_col = next((index[k] for k in index if k.endswith("商户订单号")), None)
    amount_col = next((index[k] for k in index if k.endswith("订单金额")), None)
    txn_col = next((index[k] for k in index if k.endswith("微信订单号")), None)
    status_col = next((index[k] for k in index if k.endswith("交易状态")), None)
    if out_col is None or amount_col is None:
        return []
    result = []
    for row in rows[1:]:
        if len(row) <= max(out_col, amount_col):
            continue
        record = {
            "external_order_no": row[out_col].strip(),
            "amount_cents": cents_from(row[amount_col].strip().lstrip("`")),
            "provider_txn_id": row[txn_col].strip() if txn_col is not None and len(row) > txn_col else "",
            "status": "paid" if status_col is not None and "成功" in row[status_col] else "unknown",
        }
        if record["external_order_no"]:
            result.append(record)
    return result
