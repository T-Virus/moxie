# -*- coding: utf-8 -*-
"""S3 存储启动校验：缺依赖 / 缺配置 / 服务不可达时给出明确 RuntimeError。"""

from __future__ import annotations

import importlib.util
import sys

import pytest

from app.config import Settings
from app.services.storage import S3Storage


def _s3_settings(**overrides) -> Settings:
    values = dict(
        env="test",
        storage_backend="s3",
        s3_endpoint_url="http://127.0.0.1:59999",
        s3_bucket="moxie",
        s3_access_key="test-key",
        s3_secret_key="test-secret",
        s3_secure=False,
    )
    values.update(overrides)
    return Settings(**values)


def test_missing_boto3_reports_clear_error(monkeypatch):
    monkeypatch.setitem(sys.modules, "boto3", None)
    with pytest.raises(RuntimeError, match="boto3"):
        S3Storage(_s3_settings())


def test_empty_bucket_reports_clear_error():
    with pytest.raises(RuntimeError, match="S3_BUCKET"):
        S3Storage(_s3_settings(s3_bucket=""))


@pytest.mark.skipif(importlib.util.find_spec("boto3") is None, reason="boto3 未安装")
def test_unreachable_endpoint_reports_clear_error():
    with pytest.raises(RuntimeError, match="S3 存储初始化失败"):
        S3Storage(_s3_settings())


def test_presign_uses_public_endpoint(monkeypatch):
    class _Client:
        def __init__(self, url):
            self.url = url

        def generate_presigned_url(self, *_args, **_kwargs):
            return self.url

    storage = S3Storage.__new__(S3Storage)
    storage.settings = _s3_settings(s3_public_endpoint_url="http://127.0.0.1:9000")
    storage.bucket = "moxie"
    storage.client = _Client("http://minio:9000/moxie/demo.txt?X-Amz-Signature=abc")
    storage.presign_client = _Client("http://127.0.0.1:9000/moxie/demo.txt?X-Amz-Signature=abc")
    url = storage.presign_get("demo.txt")
    assert url.startswith("http://127.0.0.1:9000/moxie/demo.txt")
    assert "X-Amz-Signature=abc" in url

