# -*- coding: utf-8 -*-
"""产物存储抽象：数据库（默认）、本地磁盘与 S3/MinIO 同接口。"""

from __future__ import annotations

import hashlib
import hmac
import posixpath
import re
import shutil
import time
from abc import ABC, abstractmethod
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from ..config import Settings
from ..errors import ApiError


def book_slug(name: str | None, fallback: str = "book") -> str:
    raw = (name or "").strip() or fallback
    cleaned = re.sub(r"[\\/:*?\"<>|\s]+", "_", raw).strip("._")
    return (cleaned or fallback)[:60]


def task_prefix(book: str | None, task_id: str) -> str:
    return f"{book_slug(book)}/{task_id}"


def _safe_key(key: str) -> str:
    key = key.replace("\\", "/").strip("/")
    if not key or posixpath.isabs(key) or ".." in key.split("/"):
        raise ApiError(400, "invalid_artifact_key", "产物 key 不合法")
    return key


class Storage(ABC):
    @abstractmethod
    def put_bytes(self, key: str, data: bytes, content_type: str = "application/octet-stream") -> str: ...

    @abstractmethod
    def put_stream(self, key: str, fileobj, content_type: str = "application/octet-stream") -> str:
        """流式写入（不把整个文件读进内存）；fileobj 只需实现 read(size)。"""

    @abstractmethod
    def get_bytes(self, key: str) -> bytes: ...

    @abstractmethod
    def exists(self, key: str) -> bool: ...

    @abstractmethod
    def delete(self, key: str) -> bool: ...

    @abstractmethod
    def list(self, prefix: str) -> list[dict]: ...

    @abstractmethod
    def presign_get(self, key: str, expires: int | None = None) -> str: ...

    def put_json(self, key: str, obj, content_type: str = "application/json") -> str:
        import json

        return self.put_bytes(key, json.dumps(obj, ensure_ascii=False, indent=2).encode("utf-8"), content_type)

    def get_json(self, key: str):
        import json

        return json.loads(self.get_bytes(key).decode("utf-8"))


class _SignedDownloadMixin:
    """HMAC 预签名下载：数据库与本地磁盘共用同一套签名与校验规则。"""

    public_base_url: str
    signing_secret: str

    def _sign(self, key: str, expires_at: int) -> str:
        msg = f"{key}:{expires_at}".encode("utf-8")
        return hmac.new(self.signing_secret.encode("utf-8"), msg, hashlib.sha256).hexdigest()

    def presign_get(self, key: str, expires: int | None = None) -> str:
        key = _safe_key(key)
        expires_at = int(time.time()) + (expires or 900)
        sig = self._sign(key, expires_at)
        url = f"/v1/artifacts/download?key={quote(key, safe='')}&expires={expires_at}&sig={sig}"
        return f"{self.public_base_url}{url}" if self.public_base_url else url

    def verify(self, key: str, expires_at: int, sig: str) -> bool:
        if expires_at < int(time.time()):
            return False
        return hmac.compare_digest(self._sign(key, expires_at), sig)


class LocalStorage(_SignedDownloadMixin, Storage):
    """本地磁盘 fallback。预签名 URL 指向本服务的签名下载接口。"""

    def __init__(self, root: Path, public_base_url: str = "", signing_secret: str = ""):
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)
        self.public_base_url = (public_base_url or "").rstrip("/")
        self.signing_secret = signing_secret

    def _path(self, key: str) -> Path:
        key = _safe_key(key)
        path = (self.root / key).resolve()
        if not str(path).startswith(str(self.root.resolve())):
            raise ApiError(400, "invalid_artifact_key", "产物 key 不合法")
        return path

    def put_bytes(self, key: str, data: bytes, content_type: str = "application/octet-stream") -> str:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return _safe_key(key)

    def put_stream(self, key: str, fileobj, content_type: str = "application/octet-stream") -> str:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with path.open("wb") as out:
                shutil.copyfileobj(fileobj, out, length=1024 * 1024)
        except Exception:
            path.unlink(missing_ok=True)
            raise
        return _safe_key(key)

    def get_bytes(self, key: str) -> bytes:
        path = self._path(key)
        if not path.is_file():
            raise ApiError(404, "artifact_not_found", "产物不存在")
        return path.read_bytes()

    def exists(self, key: str) -> bool:
        try:
            return self._path(key).is_file()
        except ApiError:
            return False

    def delete(self, key: str) -> bool:
        path = self._path(key)
        if not path.is_file():
            return False
        path.unlink()
        return True

    def list(self, prefix: str) -> list[dict]:
        base = self.root / _safe_key(prefix)
        if not base.exists():
            return []
        items = []
        for path in sorted(p for p in base.rglob("*") if p.is_file()):
            key = path.relative_to(self.root).as_posix()
            items.append(
                {
                    "key": key,
                    "name": path.name,
                    "size": path.stat().st_size,
                    "updated_at": datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat(),
                }
            )
        return items


class DBStorage(_SignedDownloadMixin, Storage):
    """产物全部落库（stored_objects 表），api / worker 只共享数据库即可。

    两种会话模式：
      · 传入 session：复用调用方事务（worker 执行期间避免 SQLite 写锁冲突），只 flush 不 commit；
      · 传入 session_factory：每次操作独立会话并提交（API 读写上传/产物）。
    """

    def __init__(
        self,
        session_factory: sessionmaker | None = None,
        *,
        session: Session | None = None,
        public_base_url: str = "",
        signing_secret: str = "",
    ):
        if session is None and session_factory is None:
            raise RuntimeError(
                "STORAGE_BACKEND=db 需要数据库会话：build_storage(settings, db.session_factory) "
                "或 build_storage(settings, session=session)"
            )
        self._session_factory = session_factory
        self._session = session
        self.public_base_url = (public_base_url or "").rstrip("/")
        self.signing_secret = signing_secret

    @contextmanager
    def _scope(self):
        if self._session is not None:
            yield self._session
            self._session.flush()
            return
        session = self._session_factory()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def put_bytes(self, key: str, data: bytes, content_type: str = "application/octet-stream") -> str:
        from ..models import StoredObject

        key = _safe_key(key)
        with self._scope() as session:
            row = session.get(StoredObject, key)
            if row is None:
                session.add(
                    StoredObject(key=key, data=data, content_type=content_type, size=len(data))
                )
            else:
                row.data = data
                row.content_type = content_type
                row.size = len(data)
        return key

    def put_stream(self, key: str, fileobj, content_type: str = "application/octet-stream") -> str:
        buf = bytearray()
        while True:
            chunk = fileobj.read(1024 * 1024)
            if not chunk:
                break
            buf.extend(chunk)
        return self.put_bytes(key, bytes(buf), content_type)

    def _fetch(self, session: Session, key: str):
        from ..models import StoredObject

        return session.get(StoredObject, _safe_key(key))

    def get_bytes(self, key: str) -> bytes:
        with self._scope() as session:
            row = self._fetch(session, key)
            if row is None:
                raise ApiError(404, "artifact_not_found", "产物不存在")
            return bytes(row.data)

    def content_type_of(self, key: str) -> str:
        with self._scope() as session:
            row = self._fetch(session, key)
            return row.content_type if row is not None else "application/octet-stream"

    def exists(self, key: str) -> bool:
        with self._scope() as session:
            return self._fetch(session, key) is not None

    def delete(self, key: str) -> bool:
        with self._scope() as session:
            row = self._fetch(session, key)
            if row is None:
                return False
            session.delete(row)
            return True

    def list(self, prefix: str) -> list[dict]:
        from ..models import StoredObject

        base = _safe_key(prefix).rstrip("/")
        with self._scope() as session:
            rows = session.scalars(
                select(StoredObject)
                .where(StoredObject.key.startswith(f"{base}/", autoescape=True))
                .order_by(StoredObject.key)
            ).all()
            return [
                {
                    "key": row.key,
                    "name": posixpath.basename(row.key),
                    "size": row.size,
                    "updated_at": row.updated_at.isoformat(),
                }
                for row in rows
            ]


class S3Storage(Storage):
    """S3 兼容存储（MinIO/OSS/S3）。

    启动即校验依赖与连通性：缺 boto3、缺 bucket 配置、服务不可达都会抛出
    带可执行提示的 RuntimeError，而不是在首次读写时抛出难以定位的底层异常。
    """

    def __init__(self, settings: Settings):
        if not (settings.s3_bucket or "").strip():
            raise RuntimeError("STORAGE_BACKEND=s3 必须配置 S3_BUCKET，或改用 STORAGE_BACKEND=local")
        try:
            import boto3
            from botocore.client import Config
            from botocore.exceptions import ClientError
        except ImportError as exc:  # pragma: no cover - 仅在启用 S3 且未装依赖时发生
            raise RuntimeError(
                "STORAGE_BACKEND=s3 需要 boto3：请执行 pip install -r requirements.txt"
                "（requirements.txt 已包含 boto3>=1.34）"
            ) from exc
        self._client_error = ClientError
        self.settings = settings
        self.bucket = settings.s3_bucket.strip()
        self.client = boto3.client(
            "s3",
            endpoint_url=settings.s3_endpoint_url,
            aws_access_key_id=settings.s3_access_key,
            aws_secret_access_key=settings.s3_secret_key,
            region_name=settings.s3_region,
            use_ssl=settings.s3_secure,
            config=Config(
                signature_version="s3v4",
                connect_timeout=3,
                read_timeout=5,
                retries={"max_attempts": 1, "mode": "standard"},
            ),
        )
        # 预签名必须用浏览器可达的 endpoint 计算 SigV4 host，否则改域名会导致 403
        public = (settings.s3_public_endpoint_url or "").strip()
        if public and public.rstrip("/") != (settings.s3_endpoint_url or "").rstrip("/"):
            self.presign_client = boto3.client(
                "s3",
                endpoint_url=public,
                aws_access_key_id=settings.s3_access_key,
                aws_secret_access_key=settings.s3_secret_key,
                region_name=settings.s3_region,
                use_ssl=settings.s3_secure,
                config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
            )
        else:
            self.presign_client = self.client
        try:
            self._ensure_bucket()
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(
                "S3 存储初始化失败："
                f"endpoint={settings.s3_endpoint_url} bucket={self.bucket}。"
                "请确认 MinIO/S3 已启动、S3_ACCESS_KEY/S3_SECRET_KEY 正确、bucket 可访问。"
                f"原始错误：{exc}"
            ) from exc

    def _ensure_bucket(self) -> None:
        try:
            self.client.head_bucket(Bucket=self.bucket)
            return
        except self._client_error as exc:
            code = str(exc.response.get("Error", {}).get("Code", ""))
            if code not in {"404", "NoSuchBucket", "NotFound", "NoSuchKey"}:
                raise
        self.client.create_bucket(Bucket=self.bucket)

    def put_bytes(self, key: str, data: bytes, content_type: str = "application/octet-stream") -> str:
        key = _safe_key(key)
        self.client.put_object(Bucket=self.bucket, Key=key, Body=data, ContentType=content_type)
        return key

    def put_stream(self, key: str, fileobj, content_type: str = "application/octet-stream") -> str:
        key = _safe_key(key)
        try:
            self.client.upload_fileobj(
                fileobj, self.bucket, key, ExtraArgs={"ContentType": content_type}
            )
        except Exception:
            try:
                self.client.delete_object(Bucket=self.bucket, Key=key)
            except Exception:  # noqa: BLE001 - 清理失败不覆盖原始错误
                pass
            raise
        return key

    def get_bytes(self, key: str) -> bytes:
        key = _safe_key(key)
        try:
            obj = self.client.get_object(Bucket=self.bucket, Key=key)
        except Exception as exc:
            raise ApiError(404, "artifact_not_found", "产物不存在") from exc
        return obj["Body"].read()

    def exists(self, key: str) -> bool:
        try:
            self.client.head_object(Bucket=self.bucket, Key=_safe_key(key))
            return True
        except Exception:
            return False

    def delete(self, key: str) -> bool:
        key = _safe_key(key)
        try:
            self.client.delete_object(Bucket=self.bucket, Key=key)
            return True
        except Exception:
            return False

    def list(self, prefix: str) -> list[dict]:
        prefix = _safe_key(prefix).rstrip("/") + "/"
        resp = self.client.list_objects_v2(Bucket=self.bucket, Prefix=prefix)
        return [
            {
                "key": obj["Key"],
                "name": posixpath.basename(obj["Key"]),
                "size": obj["Size"],
                "updated_at": obj["LastModified"].isoformat(),
            }
            for obj in resp.get("Contents", [])
        ]

    def presign_get(self, key: str, expires: int | None = None) -> str:
        return self.presign_client.generate_presigned_url(
            "get_object",
            Params={"Bucket": self.bucket, "Key": _safe_key(key)},
            ExpiresIn=expires or 900,
        )


def _artifact_signing_secret(settings: Settings) -> str:
    """产物下载签名密钥：优先独立配置，否则从 JWT 密钥单向派生。

    禁止把 JWT_SECRET 直接当作 HMAC 密钥复用（跨用途复用会让 JWT 伪造
    与下载签名伪造互相放大）。生产由闸门强制要求 ARTIFACT_SIGNING_SECRET。
    """
    configured = (settings.artifact_signing_secret or "").strip()
    if configured:
        return configured
    return hashlib.sha256(
        b"moxie-artifact-signing-v1:" + (settings.jwt_secret or "").encode("utf-8")
    ).hexdigest()


def build_storage(
    settings: Settings,
    session_factory: sessionmaker | None = None,
    *,
    session: Session | None = None,
) -> Storage:
    """按 STORAGE_BACKEND 选择后端；db 需要数据库会话（工厂或当前事务会话）。"""
    backend = (settings.storage_backend or "db").lower()
    signing_secret = _artifact_signing_secret(settings)
    if backend in {"s3", "minio", "oss"}:
        return S3Storage(settings)
    if backend in {"db", "database"}:
        return DBStorage(
            session_factory,
            session=session,
            public_base_url=settings.storage_public_base_url,
            signing_secret=signing_secret,
        )
    return LocalStorage(
        Path(settings.storage_local_dir),
        public_base_url=settings.storage_public_base_url,
        signing_secret=settings.artifact_signing_secret or settings.jwt_secret,
    )
