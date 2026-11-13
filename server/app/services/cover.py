# -*- coding: utf-8 -*-
"""AI 封面：模型出图优先，Pollinations 兜底，最后本地绘制。

复用桌面端 src/cover.py 的中文提示词翻译、底图抓取与本地排版能力，
服务端只负责组装提示词、落库存储与返回元信息。
"""

from __future__ import annotations

import importlib
import io
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path

from ..config import Settings
from ..errors import ApiError
from .model_config import _get_row, decrypt_key

STYLE_KEYS = ("gold", "white", "ink")
LAYOUT_KEYS = ("top", "middle", "bottom")
MAX_SIDE = 4096
MIN_SIDE = 256

_lock = threading.Lock()
_module = None


def _cover_module(settings: Settings):
    """延迟导入 src/cover.py：避免服务启动时强依赖 Pillow 与桌面端目录。"""
    global _module
    with _lock:
        if _module is not None:
            return _module
        # 配置路径可能来自容器（/src）；本地开发时回退到仓库根目录的 src/
        candidates = [
            Path(settings.src_path),
            Path(__file__).resolve().parents[3] / "src",
        ]
        src = next((item for item in candidates if (item / "cover.py").is_file()), None)
        if src is None:
            raise ApiError(500, "cover_module_missing", "服务端未找到封面生成模块")
        if str(src) not in sys.path:
            sys.path.insert(0, str(src))
        module = importlib.import_module("cover")
        # 容器内常见的 CJK 字体目录；桌面端与 macOS 的字体由 cover.py 自行探测
        for extra in (
            "/usr/share/fonts",
            "/usr/share/fonts/opentype/noto",
            "/usr/share/fonts/truetype/noto",
            "/usr/share/fonts/truetype/wqy",
            "/usr/share/fonts/truetype/dejavu",
        ):
            if extra not in module.FONT_DIRS:
                module.FONT_DIRS.append(extra)
        _module = module
        return module


def _text(value) -> str:
    return str(value or "").strip()


def build_prompt(run, outline: dict, extra: str = "") -> str:
    """优先用用户填写的提示词；否则按题材/世界观/梗概自动组装。"""
    if _text(extra):
        return _text(extra)
    bible = outline.get("story_bible") if isinstance(outline, dict) else {}
    if not isinstance(bible, dict):
        bible = {}
    themes = outline.get("themes") if isinstance(outline, dict) else []
    if isinstance(themes, str):
        themes = [themes]
    parts = [
        run.genre_name,
        "、".join(_text(item) for item in (themes or [])[:3]),
        _text(outline.get("genre_tone") or bible.get("genre_tone")),
        _text(bible.get("world") or outline.get("world")),
        _text(bible.get("core_hook") or outline.get("core_hook")),
        _text(outline.get("logline")),
        _text(outline.get("synopsis") or bible.get("synopsis"))[:180],
    ]
    return "，".join(item for item in parts if item)


def _author_of(outline: dict) -> str:
    bible = outline.get("story_bible") if isinstance(outline, dict) else {}
    if not isinstance(bible, dict):
        bible = {}
    return _text(outline.get("author") or bible.get("author"))


def _resolve_cover_model(session, settings: Settings) -> tuple[str, str, str]:
    """返回 (model, base_url, api_key) 用于封面 AI 出图。

    优先取后台「封面生成」工序配置，未配置时回退到传统 image_* 环境变量；
    不套用 default（文本模型）兜底，因为封面是图片模型、网关不同。
    """
    if session is not None:
        row = _get_row(session, "cover")
        if row is not None and row.enabled:
            return (
                row.model or settings.image_model,
                row.base_url or settings.image_api_base,
                decrypt_key(row.api_key, settings) or settings.image_api_key,
            )
    return (settings.image_model, settings.image_api_base, settings.image_api_key)


def _sniff_ext(data: bytes) -> str:
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "png"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    return "jpg"


def _media_type(ext: str) -> str:
    return {
        "png": "image/png",
        "webp": "image/webp",
    }.get(ext, "image/jpeg")


def _clamp(value: int, default: int) -> int:
    try:
        size = int(value)
    except (TypeError, ValueError):
        return default
    return max(MIN_SIDE, min(MAX_SIDE, size))


def generate_cover(
    *,
    run,
    outline: dict,
    settings: Settings,
    storage,
    prompt: str = "",
    style: str = "gold",
    layout: str = "top",
    width: int | None = None,
    height: int | None = None,
    session=None,
) -> dict:
    """生成封面并写入存储，返回可直接回给前端的元信息。"""
    cover = _cover_module(settings)
    W = _clamp(width if width is not None else settings.cover_width, settings.cover_width)
    H = _clamp(height if height is not None else settings.cover_height, settings.cover_height)
    style = style if style in STYLE_KEYS else "gold"
    layout = layout if layout in LAYOUT_KEYS else "top"

    raw_prompt = build_prompt(run, outline, prompt)
    if not raw_prompt:
        raw_prompt = f"{run.genre_name} 小说封面，电影感构图，氛围光，高细节"
    translated = cover.translate_prompt(raw_prompt)
    en = _text(translated.get("prompt_en")) or cover.GENERIC_PROMPT
    theme_key = next(
        (item["key"] for item in cover.THEMES if item["name"] == translated.get("theme")),
        "",
    )
    rw, rh = cover._request_size(W, H)

    base = b""
    source = ""
    model_used = ""
    notice = ""
    fallback = False

    if session is not None:
        img_model, img_base, img_key = _resolve_cover_model(session, settings)
    else:
        img_model, img_base, img_key = settings.image_model, settings.image_api_base, settings.image_api_key
    if img_key and img_model:
        try:
            base = cover.fetch_ai_base(
                en,
                rw,
                rh,
                img_key,
                img_base,
                img_model,
                timeout=settings.cover_timeout_seconds,
            )
            source = "ai"
            model_used = img_model
        except cover.CoverError as exc:
            notice = _text(exc)[:120]

    if not base and settings.cover_pollinations_enabled:
        try:
            base = cover.fetch_base(
                en, rw, rh, model="flux", seed=None, timeout=settings.cover_timeout_seconds
            )
            source = "pollinations"
            model_used = "flux"
        except cover.CoverError as exc:
            notice = _text(exc)[:120]

    if not base:
        base = cover.fallback_base(rw, rh, theme_key, en)
        source = "local"
        model_used = "local"
        fallback = True

    # 本地排版：字体缺失 / 容器无 CJK 字体时退回模型原图，保证封面仍可下载
    ext = "jpg"
    data = base
    compose_note = ""
    try:
        img = cover.compose(base, W, H, run.title, _author_of(outline), style, layout)
        data, ext = cover.encode(img, "jpg")
    except Exception as exc:  # noqa: BLE001 - 字体/Pillow 缺失都退回原图
        ext = _sniff_ext(base)
        compose_note = f"未叠加书名文字：{_text(exc)[:80]}"

    key = f"covers/{run.account_id}/{run.id}.{ext}"
    storage.put_bytes(key, data, _media_type(ext))
    updated = datetime.now(timezone.utc).isoformat()
    meta = {
        "key": key,
        "fmt": ext,
        "size": len(data),
        "width": W,
        "height": H,
        "source": source,
        "model": model_used,
        "fallback": fallback,
        "prompt": en,
        "style": style,
        "layout": layout,
        "updated_at": updated,
        "notice": "；".join(item for item in (notice, compose_note) if item),
    }
    run.meta = {**(run.meta or {}), "cover": meta}
    return {**meta, "url": f"/agent-runs/{run.id}/cover?v={int(datetime.now().timestamp())}"}


def save_uploaded_cover(
    *,
    run,
    settings: Settings,
    storage,
    data: bytes,
    original_name: str = "",
) -> dict:
    """保存用户上传的封面：校验图片、统一转为 JPEG 并落库。"""
    if not data:
        raise ApiError(422, "cover_empty", "上传的封面文件为空")
    if len(data) > settings.cover_upload_max_bytes:
        limit = settings.cover_upload_max_bytes / 1024 / 1024
        raise ApiError(413, "cover_too_large", f"封面文件不能超过 {limit:.0f}MB")
    try:
        from PIL import Image, ImageOps

        image = Image.open(io.BytesIO(data))
        image.load()
    except Exception:
        raise ApiError(415, "cover_invalid_image", "仅支持 JPG / PNG / WebP 图片") from None
    if getattr(image, "is_animated", False):
        raise ApiError(415, "cover_invalid_image", "不支持动图封面，请上传静态图片")
    if min(image.size) < 100:
        raise ApiError(422, "cover_too_small", "封面尺寸太小，宽高至少 100px")

    image = ImageOps.exif_transpose(image).convert("RGB")
    if max(image.size) > MAX_SIDE:
        image.thumbnail((MAX_SIDE, MAX_SIDE), Image.LANCZOS)
    buf = io.BytesIO()
    image.save(buf, "JPEG", quality=92, optimize=True, progressive=True)
    payload = buf.getvalue()

    key = f"covers/{run.account_id}/{run.id}.jpg"
    old_key = ((run.meta or {}).get("cover") or {}).get("key")
    storage.put_bytes(key, payload, "image/jpeg")
    if old_key and old_key != key and storage.exists(old_key):
        storage.delete(old_key)

    updated = datetime.now(timezone.utc).isoformat()
    meta = {
        "key": key,
        "fmt": "jpg",
        "size": len(payload),
        "width": image.width,
        "height": image.height,
        "source": "upload",
        "model": "",
        "fallback": False,
        "prompt": "",
        "style": "",
        "layout": "",
        "updated_at": updated,
        "original_name": Path(original_name).name[:120],
        "notice": "",
    }
    run.meta = {**(run.meta or {}), "cover": meta}
    return {**meta, "url": f"/agent-runs/{run.id}/cover?v={int(datetime.now().timestamp())}"}
