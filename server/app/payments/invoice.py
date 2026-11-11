# -*- coding: utf-8 -*-
"""电子发票渠道抽象。

业务层只依赖 InvoiceResult，不感知渠道差异。回调必须接收**原始字节**验签。
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from dataclasses import dataclass, field
from typing import Any

from ..errors import ApiError
from ..models import InvoiceRequest
from .base import hmac_hex


@dataclass
class InvoiceResult:
    provider: str
    status: str  # issuing|issued|voided|failed
    provider_invoice_id: str = ""
    invoice_url: str | None = None
    message: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)


class InvoiceProvider:
    """申请开票 / 查询 / 作废 / 回调验签的统一接口。"""

    name = "base"
    needs_credentials = False

    def __init__(self, settings, http_client=None):
        self.settings = settings
        self.http = http_client

    def configured(self) -> bool:
        return True

    def require_configured(self) -> None:
        if not self.configured():
            raise ApiError(
                501,
                "invoice_provider_not_configured",
                f"{self.name} 开票渠道未配置：请补齐 INVOICE_APP_KEY / INVOICE_APP_SECRET "
                "（见 docs/invoicing.md）",
            )

    def apply(self, invoice: InvoiceRequest) -> InvoiceResult:
        raise ApiError(501, "invoice_provider_not_configured", f"{self.name} 开票接口未接入")

    def query(self, invoice: InvoiceRequest) -> InvoiceResult:
        raise ApiError(501, "invoice_provider_not_configured", f"{self.name} 发票查询未接入")

    def void(self, invoice: InvoiceRequest) -> InvoiceResult:
        raise ApiError(501, "invoice_provider_not_configured", f"{self.name} 发票作废未接入")

    def verify_callback(self, headers: dict[str, str], raw_body: bytes) -> None:
        raise ApiError(501, "invoice_provider_not_configured", f"{self.name} 回调验签未接入")

    # ---- 公共工具 ---------------------------------------------------------
    def _callback_secret(self) -> str:
        secret = (getattr(self.settings, "invoice_callback_secret", "") or "").strip()
        if not secret:
            raise ApiError(
                501,
                "invoice_provider_not_configured",
                "回调验签需要配置 INVOICE_CALLBACK_SECRET",
            )
        return secret

    def _verify_hmac(self, headers: dict[str, str], raw_body: bytes) -> None:
        secret = self._callback_secret()
        signature = (
            headers.get("x-invoice-signature")
            or headers.get("x-signature")
            or headers.get("sign")
            or ""
        ).strip()
        expected = hmac_hex(secret, raw_body)
        if not signature or not hmac.compare_digest(signature, expected):
            raise ApiError(403, "invoice_callback_signature_invalid", "发票回调签名校验失败")


class StubInvoiceProvider(InvoiceProvider):
    """本地 stub 渠道。

    默认纯内存返回；配置 INVOICE_STUB_URL 后会真实调用一个本地 HTTP 服务，
    便于联调时模拟服务商异步返回。
    """

    name = "stub"

    def apply(self, invoice: InvoiceRequest) -> InvoiceResult:
        if (self.settings.invoice_stub_url or "").strip():
            data = self._post_local("/invoice/apply", invoice)
            return self._from_dict(data, default_status="issued")
        return InvoiceResult(
            provider=self.name,
            status="issued",
            provider_invoice_id=f"STUB-{invoice.id:08d}",
            message="stub 渠道即时开票",
            raw={"stub": True, "order_id": invoice.order_id},
        )

    def query(self, invoice: InvoiceRequest) -> InvoiceResult:
        if (self.settings.invoice_stub_url or "").strip():
            data = self._post_local("/invoice/query", invoice)
            return self._from_dict(data, default_status=invoice.status)
        status = invoice.status if invoice.status in {"issued", "voided", "failed"} else "issuing"
        return InvoiceResult(
            provider=self.name,
            status=status,
            provider_invoice_id=(invoice.meta or {}).get("provider_invoice_id") or f"STUB-{invoice.id:08d}",
            raw={"stub": True},
        )

    def void(self, invoice: InvoiceRequest) -> InvoiceResult:
        if (self.settings.invoice_stub_url or "").strip():
            data = self._post_local("/invoice/void", invoice)
            return self._from_dict(data, default_status="voided")
        return InvoiceResult(
            provider=self.name,
            status="voided",
            provider_invoice_id=(invoice.meta or {}).get("provider_invoice_id") or f"STUB-{invoice.id:08d}",
            message="stub 渠道作废成功",
            raw={"stub": True},
        )

    def verify_callback(self, headers: dict[str, str], raw_body: bytes) -> None:
        self._verify_hmac(headers, raw_body)

    # ---- 内部 -------------------------------------------------------------
    def _payload(self, invoice: InvoiceRequest) -> dict[str, Any]:
        return {
            "invoice_id": invoice.id,
            "order_id": invoice.order_id,
            "account_id": invoice.account_id,
            "title": invoice.title,
            "tax_no": invoice.tax_no,
            "email": invoice.email,
            "amount_cents": invoice.amount_cents,
            "note": invoice.note,
        }

    def _post_local(self, path: str, invoice: InvoiceRequest) -> dict[str, Any]:
        import httpx

        url = self.settings.invoice_stub_url.rstrip("/") + path
        client = self.http
        try:
            if client is not None:
                response = client.post(url, json=self._payload(invoice), timeout=10.0)
            else:
                response = httpx.post(url, json=self._payload(invoice), timeout=10.0)
            response.raise_for_status()
            data = response.json()
        except Exception as exc:  # noqa: BLE001
            raise ApiError(502, "invoice_provider_error", f"stub 开票服务调用失败：{exc}")
        if not isinstance(data, dict):
            raise ApiError(502, "invoice_provider_error", "stub 开票服务返回格式错误")
        return data

    @staticmethod
    def _from_dict(data: dict[str, Any], default_status: str) -> InvoiceResult:
        status = str(data.get("status") or default_status)
        if status not in {"issuing", "issued", "voided", "failed"}:
            status = default_status
        return InvoiceResult(
            provider="stub",
            status=status,
            provider_invoice_id=str(data.get("provider_invoice_id") or data.get("invoice_no") or ""),
            invoice_url=data.get("invoice_url"),
            message=data.get("message"),
            raw=data,
        )


class NuonuoInvoiceProvider(InvoiceProvider):
    """诺诺开放平台风格的真实渠道适配位（可按服务商实际字段微调）。

    凭据：INVOICE_APP_KEY / INVOICE_APP_SECRET / INVOICE_API_BASE；
    缺失任意一项时配置校验失败，接口返回 501 invoice_provider_not_configured。
    """

    name = "nuonuo"
    needs_credentials = True

    def configured(self) -> bool:
        return bool(
            (self.settings.invoice_app_key or "").strip()
            and (self.settings.invoice_app_secret or "").strip()
            and (self.settings.invoice_api_base or "").strip()
        )

    def apply(self, invoice: InvoiceRequest) -> InvoiceResult:
        payload = {
            "orderNo": f"INV{invoice.id:012d}",
            "buyerName": invoice.title,
            "buyerTaxNum": invoice.tax_no or "",
            "email": invoice.email or "",
            "invoiceAmount": f"{invoice.amount_cents / 100:.2f}",
            "remark": invoice.note or "",
            "sellerTaxNum": self.settings.invoice_seller_tax_no or "",
            "orderId": invoice.order_id,
        }
        return self._call("/api/invoice/apply", payload, "issued")

    def query(self, invoice: InvoiceRequest) -> InvoiceResult:
        meta = invoice.meta or {}
        payload = {
            "orderNo": f"INV{invoice.id:012d}",
            "invoiceNo": meta.get("provider_invoice_id") or "",
        }
        return self._call("/api/invoice/query", payload, invoice.status)

    def void(self, invoice: InvoiceRequest) -> InvoiceResult:
        meta = invoice.meta or {}
        payload = {
            "orderNo": f"INV{invoice.id:012d}",
            "invoiceNo": meta.get("provider_invoice_id") or "",
            "reason": meta.get("void_reason") or "作废",
        }
        return self._call("/api/invoice/void", payload, "voided")

    def verify_callback(self, headers: dict[str, str], raw_body: bytes) -> None:
        self.require_configured()
        self._verify_hmac(headers, raw_body)

    def _call(self, path: str, payload: dict[str, Any], default_status: str) -> InvoiceResult:
        self.require_configured()
        import httpx

        timestamp = str(int(time.time() * 1000))
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        sign_src = f"{self.settings.invoice_app_key}{timestamp}{body}"
        signature = hmac.new(
            self.settings.invoice_app_secret.encode("utf-8"),
            sign_src.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        url = self.settings.invoice_api_base.rstrip("/") + path
        headers = {
            "X-App-Key": self.settings.invoice_app_key,
            "X-Timestamp": timestamp,
            "X-Signature": signature,
            "Content-Type": "application/json",
        }
        try:
            if self.http is not None:
                response = self.http.post(url, content=body, headers=headers, timeout=20.0)
            else:
                response = httpx.post(url, content=body, headers=headers, timeout=20.0)
            response.raise_for_status()
            data = response.json()
        except Exception as exc:  # noqa: BLE001
            raise ApiError(502, "invoice_provider_error", f"{self.name} 开票服务调用失败：{exc}")
        if not isinstance(data, dict):
            raise ApiError(502, "invoice_provider_error", f"{self.name} 开票服务返回格式错误")
        status = str(data.get("status") or default_status)
        if status not in {"issuing", "issued", "voided", "failed"}:
            status = default_status
        return InvoiceResult(
            provider=self.name,
            status=status,
            provider_invoice_id=str(data.get("invoiceNo") or data.get("invoice_no") or ""),
            invoice_url=data.get("invoiceUrl") or data.get("pdfUrl"),
            message=data.get("message"),
            raw=data,
        )
