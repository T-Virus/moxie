# -*- coding: utf-8 -*-
"""应用层载荷加密：ECDH(P-256) 派生会话密钥 + AES-256-GCM。

协议：
  · 客户端持有服务端公钥，生成临时 P-256 密钥对；
  · 双方通过 ECDH 得到共享密钥，再用 HKDF-SHA256 派生 32 字节 AES 密钥；
  · 请求体/响应体/SSE 事件均使用 AES-256-GCM，AAD 绑定请求方法与路径，防止跨接口重放；
  · URL 路径与查询参数仍由 HTTPS 保护，不在本层加密范围内。
"""

from __future__ import annotations

import base64
import hashlib
import os
from dataclasses import dataclass

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

HKDF_INFO = b"moxie-api-payload-v1"
ALGORITHM = "ECDH-P256+AES-256-GCM"
NONCE_LEN = 12


def b64url_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def b64url_decode(text: str) -> bytes:
    value = str(text or "").strip()
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)


@dataclass(frozen=True)
class StreamKey:
    """SSE 场景下只保留派生后的密钥与 key_id。"""

    key: bytes
    key_id: str


class PayloadCrypto:
    def __init__(
        self,
        private_key_pem: str | None,
        *,
        allow_ephemeral: bool = True,
    ) -> None:
        if private_key_pem:
            self.private_key = serialization.load_pem_private_key(
                private_key_pem.encode("utf-8"), password=None
            )
        elif allow_ephemeral:
            self.private_key = ec.generate_private_key(ec.SECP256R1())
        else:
            raise RuntimeError("生产环境必须配置 PAYLOAD_CRYPTO_PRIVATE_KEY_PEM")
        if not isinstance(self.private_key, ec.EllipticCurvePrivateKey):
            raise RuntimeError("PAYLOAD_CRYPTO_PRIVATE_KEY_PEM 必须是 EC P-256 私钥")

        spki = self.private_key.public_key().public_bytes(
            serialization.Encoding.DER,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        self.public_key_b64 = b64url_encode(spki)
        self.key_id = hashlib.sha256(spki).hexdigest()[:16]

    def public_key_payload(self) -> dict:
        return {
            "algorithm": ALGORITHM,
            "key_id": self.key_id,
            "public_key": self.public_key_b64,
        }

    def derive_key(self, client_public_b64: str) -> bytes:
        raw = b64url_decode(client_public_b64)
        public_key = serialization.load_der_public_key(raw)
        if not isinstance(public_key, ec.EllipticCurvePublicKey):
            raise ValueError("client public key must be EC")
        shared = self.private_key.exchange(ec.ECDH(), public_key)
        hkdf = HKDF(
            algorithm=hashes.SHA256(),
            length=32,
            salt=self.key_id.encode("ascii"),
            info=HKDF_INFO,
        )
        return hkdf.derive(shared)

    def encrypt(self, key: bytes, plaintext: bytes, aad: bytes) -> tuple[str, bytes]:
        nonce = os.urandom(NONCE_LEN)
        ciphertext = AESGCM(key).encrypt(nonce, plaintext, aad)
        return b64url_encode(nonce), ciphertext

    def decrypt(self, key: bytes, nonce_b64: str, ciphertext: bytes, aad: bytes) -> bytes:
        nonce = b64url_decode(nonce_b64)
        if len(nonce) != NONCE_LEN:
            raise ValueError("invalid nonce")
        return AESGCM(key).decrypt(nonce, ciphertext, aad)

    def encrypt_sse(self, key: bytes, payload: bytes, path_with_query: str) -> str:
        headers = f"GET\n{path_with_query}\n{self.key_id}\nstream".encode("utf-8")
        nonce = os.urandom(NONCE_LEN)
        ciphertext = AESGCM(key).encrypt(nonce, payload, headers)
        return b64url_encode(nonce + ciphertext)


def request_aad(method: str, path_with_query: str, key_id: str) -> bytes:
    return f"{method.upper()}\n{path_with_query}\n{key_id}".encode("utf-8")


def response_aad(method: str, path_with_query: str, key_id: str) -> bytes:
    return f"{method.upper()}\n{path_with_query}\n{key_id}\nresponse".encode("utf-8")
