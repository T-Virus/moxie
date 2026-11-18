# -*- coding: utf-8 -*-
"""源文件上传：命名清洗、大小/扩展名校验、流式写存储、归属与清理。

存储 key 统一为 ``uploads/<account_id>/<uuid>-<safe_name>``：
  · 账号前缀本身即为归属边界，跨账号既不能创建任务引用，也不能删除；
  · 上传对象只通过对象存储内部读取，对外不暴露 bucket 路径；
    客户端拿到的是 ``source_key``，下载/查看仍走已有产物接口。
"""

from __future__ import annotations

import codecs
import posixpath
import re
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import Settings
from ..errors import ApiError
from ..models import Task
from .storage import Storage

UPLOAD_ROOT = "uploads"

# 头部嗅探字节数：足以识别魔数与编码，又不至于把大文件读进内存
SNIFF_BYTES = 4096

# 文本白名单扩展名出现这些二进制魔数即判为伪装（EXE/ELF/压缩包/PDF/图片/媒体等）
_BINARY_SIGNATURES = (
    b"MZ",                  # DOS/PE 可执行文件
    b"\x7fELF",             # ELF
    b"PK\x03\x04",          # ZIP / DOCX / JAR / APK
    b"PK\x05\x06",
    b"PK\x07\x08",
    b"%PDF",                # PDF
    b"\x89PNG\r\n\x1a\n",   # PNG
    b"\xff\xd8\xff",        # JPEG
    b"GIF87a", b"GIF89a",   # GIF
    b"RIFF",                # WAV / WEBP / AVI
    b"\x1f\x8b",            # GZIP
    b"BZh",                 # BZIP2
    b"Rar!\x1a\x07",        # RAR
    b"7z\xbc\xaf\x27\x1c",  # 7-Zip
    b"\xca\xfe\xba\xbe",    # Java class / Mach-O fat
    b"\x00asm",             # WebAssembly
)


class UploadTooLarge(Exception):
    """流式读取时超过大小上限（由 API 层转成 413）。"""


class UploadContentRejected(Exception):
    """内容嗅探判定为伪装/二进制（由 save_upload 转成 422）。"""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def sniff_text_head(head: bytes) -> None:
    """校验文本上传的头部：禁 NUL、禁二进制魔数、须为合法 UTF-8。

    允许末尾截断的多字节字符（incremental decoder，final=False），避免恰好
    在 4096 字节边界切断 UTF-8 多字节序列造成误判。
    """
    if not head:
        return
    if b"\x00" in head:
        raise UploadContentRejected("source_content_binary", "文件含二进制内容（NUL 字节），拒绝上传")
    for signature in _BINARY_SIGNATURES:
        if head.startswith(signature):
            raise UploadContentRejected(
                "source_content_binary", "文件头与声明的文本类型不符，拒绝上传"
            )
    decoder = codecs.getincrementaldecoder("utf-8")("strict")
    try:
        decoder.decode(head, final=False)
    except UnicodeDecodeError as exc:
        raise UploadContentRejected(
            "source_content_encoding", "文件不是有效的 UTF-8 文本，拒绝上传"
        ) from exc


def upload_prefix(account_id: int) -> str:
    return f"{UPLOAD_ROOT}/{account_id}"


def safe_filename(name: str) -> str:
    """只保留 basename，去控制字符/路径分隔符/前导点，限制长度。"""
    base = posixpath.basename(str(name or "").replace("\\", "/")).strip()
    base = re.sub(r"[^0-9A-Za-z\u4e00-\u9fff._-]+", "_", base)
    base = re.sub(r"_+", "_", base).strip("._")
    if not base:
        base = "upload.txt"
    if len(base) > 100:
        stem, dot, suffix = base.rpartition(".")
        if dot and len(suffix) <= 10:
            base = stem[: 100 - len(suffix) - 1] + "." + suffix
        else:
            base = base[:100]
    return base


def allowed_extensions(settings: Settings) -> set[str]:
    items = {item.strip().lower() for item in (settings.upload_allowed_extensions or "").split(",")}
    return {item if item.startswith(".") else f".{item}" for item in items if item}


def validate_filename(filename: str, settings: Settings) -> tuple[str, str]:
    """返回 (safe_name, extension)。扩展名不在白名单时抛 415。"""
    safe = safe_filename(filename)
    suffix = posixpath.splitext(safe)[1].lower()
    allowed = allowed_extensions(settings)
    if allowed and suffix not in allowed:
        raise ApiError(
            415,
            "unsupported_file_type",
            f"仅支持以下扩展名：{', '.join(sorted(allowed))}",
        )
    return safe, suffix


def is_upload_key(account_id: int, key: str) -> bool:
    normalized = str(key or "").replace("\\", "/").strip("/")
    return normalized.startswith(f"{upload_prefix(account_id)}/")


def owns_source_key(session: Session | None, account_id: int, key: str) -> bool:
    """上传 key 按账号前缀校验；历史产物 key 按「第二段 task_id」校验归属。"""
    normalized = str(key or "").replace("\\", "/").strip("/")
    if normalized.startswith(f"{UPLOAD_ROOT}/"):
        return is_upload_key(account_id, normalized)
    parts = normalized.split("/")
    if session is None or len(parts) < 3:
        return False
    task_id = parts[1]
    return (
        session.scalar(select(Task.id).where(Task.id == task_id, Task.account_id == account_id))
        is not None
    )


class _LimitedReader:
    """包装文件对象：边读边计数，超限立即中断（存储层会清理半成品）。"""

    def __init__(self, src, max_bytes: int):
        self.src = src
        self.max_bytes = max_bytes
        self.read_bytes = 0

    def read(self, size: int = -1):
        chunk = self.src.read(size if size is None or size > 0 else 1024 * 1024)
        if not chunk:
            return chunk
        self.read_bytes += len(chunk)
        if self.read_bytes > self.max_bytes:
            raise UploadTooLarge()
        return chunk


class _PrefixedReader:
    """把已嗅探的头部字节拼回流首，保证 content 与写入一致且不重复读源文件。"""

    def __init__(self, head: bytes, src):
        self._head = head
        self._offset = 0
        self._src = src

    def read(self, size: int = -1):
        if self._offset < len(self._head):
            if size is None or size < 0:
                out = self._head[self._offset :]
            else:
                out = self._head[self._offset : self._offset + size]
            self._offset += len(out)
            return out
        return self._src.read(size)


def save_upload(
    storage: Storage,
    settings: Settings,
    *,
    account_id: int,
    filename: str,
    fileobj,
) -> dict:
    """流式写入对象存储并返回元信息；超限时删除已写半成品并抛 413。

    写入前先嗅探头部：内容为二进制伪装或非 UTF-8 文本时直接拒绝（422），
    此时尚未调用 put_stream，无半成品需要清理。
    """
    safe, suffix = validate_filename(filename, settings)
    key = f"{upload_prefix(account_id)}/{uuid.uuid4().hex}-{safe}"

    # 预读头部（不超上限），嗅探通过后把头部拼回流首重新消费
    head = fileobj.read(SNIFF_BYTES)
    try:
        sniff_text_head(head)
    except UploadContentRejected as exc:
        raise ApiError(422, exc.code, exc.message) from exc

    reader = _LimitedReader(_PrefixedReader(head, fileobj), settings.upload_max_bytes)
    try:
        storage.put_stream(
            key,
            reader,
            content_type=_content_type(suffix),
        )
    except UploadTooLarge:
        storage.delete(key)
        raise ApiError(
            413, "source_too_large", f"源文件超过大小限制（{settings.upload_max_bytes} 字节）"
        )
    if reader.read_bytes <= 0:
        storage.delete(key)
        raise ApiError(422, "source_empty", "源文件为空")
    return {
        "source_key": key,
        "filename": safe,
        "size": reader.read_bytes,
        "content_type": _content_type(suffix),
    }


def _content_type(suffix: str) -> str:
    return {
        ".txt": "text/plain; charset=utf-8",
        ".md": "text/markdown; charset=utf-8",
        ".markdown": "text/markdown; charset=utf-8",
        ".csv": "text/csv; charset=utf-8",
        ".json": "application/json",
    }.get(suffix, "application/octet-stream")


def delete_upload(storage: Storage, account_id: int, key: str) -> bool:
    normalized = str(key or "").replace("\\", "/").strip("/")
    if not is_upload_key(account_id, normalized):
        raise ApiError(404, "upload_not_found", "上传文件不存在")
    return storage.delete(normalized)


def active_source_keys(session: Session, limit: int = 1000) -> set[str]:
    """仍在排队/执行的任务所引用的 source_key（清理时保护，避免删掉待读文件）。"""
    rows = session.scalars(
        select(Task.params).where(Task.status.in_({"queued", "running"})).limit(limit)
    ).all()
    keys: set[str] = set()
    for params in rows:
        if isinstance(params, dict) and params.get("source_key"):
            keys.add(str(params["source_key"]).replace("\\", "/").strip("/"))
    return keys


def cleanup_expired_uploads(
    storage: Storage,
    session: Session,
    settings: Settings,
    now: datetime | None = None,
    *,
    prefix: str = UPLOAD_ROOT,
) -> int:
    """删除超过保留期且未被排队/执行中任务引用的上传源文件。

    `upload_retention_days <= 0` 表示关闭自动清理，只能显式 DELETE。
    """
    retention = int(settings.upload_retention_days or 0)
    if retention <= 0:
        return 0
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(days=retention)
    protected = active_source_keys(session)
    deleted = 0
    for item in storage.list(prefix):
        key = str(item.get("key") or "").replace("\\", "/").strip("/")
        if not key.startswith(f"{UPLOAD_ROOT}/") or key in protected:
            continue
        updated = item.get("updated_at")
        if not isinstance(updated, str):
            continue
        try:
            updated_at = datetime.fromisoformat(updated)
        except ValueError:
            continue
        if updated_at.tzinfo is None:
            updated_at = updated_at.replace(tzinfo=timezone.utc)
        if updated_at < cutoff and storage.delete(key):
            deleted += 1
    return deleted
