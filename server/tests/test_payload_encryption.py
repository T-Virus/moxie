# -*- coding: utf-8 -*-
"""应用层加密：明文拒绝、密文请求/响应、SSE 事件加解密。"""

from __future__ import annotations

import base64
import json
import os

import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.services.payload_crypto import PayloadCrypto

HKDF_INFO = b"moxie-api-payload-v1"


def b64e(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def b64d(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


class ClientCrypto:
    def __init__(self, client: TestClient, base: str = "/v1") -> None:
        info = client.get(f"{base}/crypto/public-key")
        assert info.status_code == 200, info.text
        data = info.json()
        self.key_id = data["key_id"]
        server_public = serialization.load_der_public_key(b64d(data["public_key"]))
        self.private_key = ec.generate_private_key(ec.SECP256R1())
        self.client_public = b64e(
            self.private_key.public_key().public_bytes(
                serialization.Encoding.DER,
                serialization.PublicFormat.SubjectPublicKeyInfo,
            )
        )
        shared = self.private_key.exchange(ec.ECDH(), server_public)
        self.key = HKDF(
            algorithm=hashes.SHA256(),
            length=32,
            salt=self.key_id.encode("ascii"),
            info=HKDF_INFO,
        ).derive(shared)

    def headers(self) -> dict[str, str]:
        return {"X-Payload-Key": self.key_id, "X-Payload-Client": self.client_public}

    def encrypt_request(
        self, method: str, path: str, payload: dict
    ) -> tuple[bytes, dict[str, str]]:
        nonce = os.urandom(12)
        aad = f"{method.upper()}\n{path}\n{self.key_id}".encode("utf-8")
        body = AESGCM(self.key).encrypt(
            nonce, json.dumps(payload, ensure_ascii=False).encode("utf-8"), aad
        )
        headers = {
            **self.headers(),
            "Content-Type": "application/octet-stream",
            "X-Payload-Nonce": b64e(nonce),
            "X-Payload-Encrypted": "1",
        }
        return body, headers

    def decrypt_response(self, method: str, path: str, response) -> dict:
        assert response.headers.get("x-payload-encrypted") == "1", response.text
        nonce = b64d(response.headers["x-payload-nonce"])
        aad = f"{method.upper()}\n{path}\n{self.key_id}\nresponse".encode("utf-8")
        raw = AESGCM(self.key).decrypt(nonce, response.content, aad)
        return json.loads(raw.decode("utf-8"))


@pytest.fixture
def encrypted_app(tmp_path):
    settings = Settings(
        env="dev",
        database_url=f"sqlite:///{(tmp_path / 'crypto.db').as_posix()}",
        auto_create_tables=True,
        redis_enabled=False,
        jwt_secret="test-jwt-secret-at-least-32-bytes-long",
        license_private_key_pem="",
        license_allow_ephemeral_key=True,
        legal_gate_enabled=False,
        email_verification_required=False,  # 本用例验证载荷加解密，注册需直接返回 token
        storage_backend="local",
        storage_local_dir=str(tmp_path / "artifacts"),
        task_source_dirs=str(tmp_path),
        log_level="WARNING",
        notifications_enabled=False,
        scheduler_enabled=False,
    )
    return create_app(settings)


def test_plaintext_request_is_rejected(encrypted_app):
    with TestClient(encrypted_app) as client:
        response = client.post(
            "/v1/auth/register",
            json={"email": "plain@example.com", "password": "password123"},
        )
        assert response.status_code == 400
        assert response.json()["error"]["code"] == "payload_encryption_required"


def test_encrypted_register_login_and_get(encrypted_app):
    with TestClient(encrypted_app) as client:
        crypto = ClientCrypto(client)

        body, headers = crypto.encrypt_request(
            "POST",
            "/v1/auth/register",
            {"email": "crypto@example.com", "password": "password123"},
        )
        registered = client.post("/v1/auth/register", content=body, headers=headers)
        assert registered.status_code == 201, registered.text
        account = crypto.decrypt_response("POST", "/v1/auth/register", registered)
        assert account["access_token"]
        assert account["account"]["email"] == "crypto@example.com"

        me = client.get(
            "/v1/auth/me",
            headers={
                **crypto.headers(),
                "Authorization": f"Bearer {account['access_token']}",
            },
        )
        assert me.status_code == 200, me.text
        detail = crypto.decrypt_response("GET", "/v1/auth/me", me)
        assert detail["email"] == "crypto@example.com"

        genres = client.get("/v1/genres", headers=crypto.headers())
        assert genres.status_code == 200, genres.text
        payload = crypto.decrypt_response("GET", "/v1/genres", genres)
        assert isinstance(payload.get("items"), list)


def test_wrong_key_id_is_rejected(encrypted_app):
    with TestClient(encrypted_app) as client:
        crypto = ClientCrypto(client)
        headers = {**crypto.headers(), "X-Payload-Key": "stale-key-id"}
        response = client.get("/v1/genres", headers=headers)
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "payload_key_mismatch"


def test_sse_event_roundtrip_and_no_plaintext_leak(encrypted_app):
    """SSE 帧只输出 nonce+ciphertext，客户端可解出原始事件。"""
    crypto = PayloadCrypto(None, allow_ephemeral=True)
    client_private = ec.generate_private_key(ec.SECP256R1())
    client_public = b64e(
        client_private.public_key().public_bytes(
            serialization.Encoding.DER,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        )
    )
    key = crypto.derive_key(client_public)
    path = "/v1/agent-runs/demo/events?since=0"
    event = {"seq": 1, "stage": "outline", "message": "生成中"}
    frame = crypto.encrypt_sse(
        key, json.dumps(event, ensure_ascii=False).encode("utf-8"), path
    )
    assert "生成中" not in frame

    raw = b64d(frame)
    nonce, ciphertext = raw[:12], raw[12:]
    aad = f"GET\n{path}\n{crypto.key_id}\nstream".encode("utf-8")
    plain = AESGCM(key).decrypt(nonce, ciphertext, aad)
    assert json.loads(plain.decode("utf-8")) == event
