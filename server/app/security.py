# -*- coding: utf-8 -*-
"""密码哈希、JWT、Ed25519 License 签名。"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import secrets
from datetime import datetime, timedelta, timezone

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from .config import Settings

logger = logging.getLogger("moxie.security")

_SCRYPT_N = 2 ** 14
_SCRYPT_R = 8
_SCRYPT_P = 1


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.scrypt(
        password.encode("utf-8"), salt=salt.encode("utf-8"),
        n=_SCRYPT_N, r=_SCRYPT_R, p=_SCRYPT_P, dklen=32,
    )
    return f"scrypt${_SCRYPT_N}${_SCRYPT_R}${_SCRYPT_P}${salt}${digest.hex()}"


def verify_password(password: str, stored: str | None) -> bool:
    if not stored:
        return False
    try:
        algo, n, r, p, salt, digest_hex = stored.split("$")
        if algo != "scrypt":
            return False
        digest = hashlib.scrypt(
            password.encode("utf-8"), salt=salt.encode("utf-8"),
            n=int(n), r=int(r), p=int(p), dklen=32,
        )
        return hmac.compare_digest(digest.hex(), digest_hex)
    except Exception:  # noqa: BLE001
        return False


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def create_access_token(settings: Settings, account_id: int, session_id: str, device_id: int | None = None) -> str:
    now = utcnow()
    payload = {
        "sub": str(account_id),
        "typ": "access",
        "sid": session_id,
        "dev": device_id,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=settings.access_token_minutes)).timestamp()),
        "jti": secrets.token_hex(8),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def create_refresh_token(settings: Settings, account_id: int, session_id: str, device_id: int | None = None) -> str:
    now = utcnow()
    payload = {
        "sub": str(account_id),
        "typ": "refresh",
        "sid": session_id,
        "dev": device_id,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(days=settings.refresh_token_days)).timestamp()),
        "jti": secrets.token_hex(8),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_token(token: str, settings: Settings, expected_typ: str) -> dict:
    payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    if payload.get("typ") != expected_typ:
        raise jwt.InvalidTokenError("token type mismatch")
    return payload


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _canonical(payload: dict) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


class LicenseSigner:
    """Ed25519 签发/校验。私钥只存在服务端；客户端内置公钥。"""

    def __init__(
        self,
        private_key_pem: str | None = None,
        key_id: str = "moxie-license-1",
        *,
        allow_ephemeral: bool = False,
    ):
        self.key_id = key_id
        if private_key_pem:
            private_key = serialization.load_pem_private_key(
                private_key_pem.encode("utf-8"), password=None
            )
            if not isinstance(private_key, Ed25519PrivateKey):
                raise ValueError("license_private_key_pem 必须是 Ed25519 私钥")
            self._private = private_key
        elif allow_ephemeral:
            logger.warning("未配置 LICENSE_PRIVATE_KEY_PEM，使用进程内临时密钥（仅限单进程开发）")
            self._private = Ed25519PrivateKey.generate()
        else:
            raise ValueError(
                "缺少 LICENSE_PRIVATE_KEY_PEM：多 worker / 生产环境必须显式配置私钥，"
                "生成命令见 .env.example"
            )

    @staticmethod
    def generate_pem() -> str:
        key = Ed25519PrivateKey.generate()
        return key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        ).decode("utf-8")

    def sign(self, payload: dict) -> str:
        raw = self._private.sign(_canonical(payload))
        return base64.urlsafe_b64encode(raw).decode("ascii")

    def verify(self, payload: dict, signature: str) -> bool:
        try:
            raw = base64.urlsafe_b64decode(signature.encode("ascii"))
            self.public_key.verify(raw, _canonical(payload))
            return True
        except Exception:  # noqa: BLE001
            return False

    @property
    def public_key(self):
        return self._private.public_key()

    @property
    def public_key_b64(self) -> str:
        raw = self.public_key.public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
        return base64.urlsafe_b64encode(raw).decode("ascii")
