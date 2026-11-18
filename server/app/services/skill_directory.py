# -*- coding: utf-8 -*-
"""统一技能目录：把 10 个创作环节编织成产品可发现的能力清单。

唯一事实源是仓库根 config/skills_catalog.json（由 scripts/check_skills.py 校验）。
本服务只做两件事：
  1. 读清单并按 mtime 增量缓存（改清单后下次请求即生效，避免重启）；
  2. 合并云端 SkillRegistry 的注册状态，让"清单声明"与"实际注册"可对照。

找不到清单 / JSON 损坏时返回 degraded，不抛 500——技能目录是产品展示层，
不能因为一个静态配置文件缺失就拖垮创作主流程（与 genres 的降级策略一致）。
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from ..agents.registry import registry as skill_registry
from ..config import Settings

_CATALOG_NAME = "skills_catalog.json"


def _resolve_catalog_path(settings: Settings) -> Path | None:
    """按显式配置 → 环境变量 → 常见部署布局的顺序找清单。"""
    configured = getattr(settings, "skills_catalog_path", None)
    candidates: list[Path] = []
    if configured:
        candidates.append(Path(configured))
    env = os.getenv("MOXIE_SKILLS_CATALOG")
    if env:
        candidates.append(Path(env))

    here = Path(__file__).resolve()
    cwd = Path.cwd()
    candidates.extend(
        [
            cwd / "config" / _CATALOG_NAME,
            cwd.parent / "config" / _CATALOG_NAME,
            here.parents[3] / "config" / _CATALOG_NAME,  # server/app/services → 仓库根
            here.parents[2] / "config" / _CATALOG_NAME,  # server/config
        ]
    )
    for path in candidates:
        if path.is_file():
            return path
    return None


# 进程内缓存：mtime 变化即重载，保证"改一处三端同步"无需重启服务。
_CACHE: dict[str, Any] = {"mtime": None, "doc": None, "error": None}


def _load_document(path: Path) -> tuple[dict | None, str | None]:
    try:
        mtime = path.stat().st_mtime_ns
    except OSError as exc:
        return None, f"无法读取技能清单时间戳：{exc}"

    if _CACHE["mtime"] == mtime and _CACHE["doc"] is not None:
        return _CACHE["doc"], None

    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(doc, dict) or not isinstance(doc.get("items"), list):
            raise ValueError("技能清单缺少 items 数组")
    except (OSError, ValueError) as exc:
        _CACHE.update(mtime=mtime, doc=None, error=str(exc))
        return None, f"技能清单解析失败：{exc}"

    _CACHE.update(mtime=mtime, doc=doc, error=None)
    return doc, None


def _registered_names() -> set[str]:
    try:
        return {row["name"] for row in skill_registry.catalog()}
    except Exception:  # 注册表是内部实现，异常不应影响目录展示
        return set()


def _user_item(raw: dict, registered: set[str]) -> dict:
    """用户端视图：只暴露产品能力语义，技术字段（ssot/gap/files）留给管理端。"""
    cloud_skills = list((raw.get("cloud") or {}).get("skills") or [])
    desktop_stages = list((raw.get("desktop") or {}).get("stages") or [])
    cloud_api = list((raw.get("cloud") or {}).get("api") or [])
    desktop_api = list((raw.get("desktop") or {}).get("api") or [])
    return {
        "id": raw.get("id"),
        "index": raw.get("index"),
        "name": raw.get("name"),
        "external": raw.get("external"),
        "trigger": list(raw.get("trigger") or []),
        "purpose": raw.get("purpose") or "",
        "coverage": raw.get("coverage"),
        "available": bool(registered.intersection(cloud_skills)) or bool(desktop_api or cloud_api),
        "entry": {
            "stages": desktop_stages,
            "cloud_skills": cloud_skills,
            "api": desktop_api + cloud_api,
        },
    }


def _admin_item(raw: dict, registered: set[str]) -> dict:
    """管理端视图：完整披露覆盖状态、缺口、写权与文件引用，供治理排查。"""
    item = _user_item(raw, registered)
    cloud_skills = item["entry"]["cloud_skills"]
    item.update(
        {
            "gap": raw.get("gap"),
            "ssot": raw.get("ssot") or "",
            "writes": list(raw.get("writes") or []),
            "next": list(raw.get("next") or []),
            "desktop_note": (raw.get("desktop") or {}).get("note") or "",
            "cloud_note": (raw.get("cloud") or {}).get("note") or "",
            "desktop_files": list((raw.get("desktop") or {}).get("files") or []),
            "cloud_files": list((raw.get("cloud") or {}).get("files") or []),
            "registered": bool(registered.intersection(cloud_skills)),
            "reference": raw.get("reference") or "",
        }
    )
    return item


def build_skill_catalog(settings: Settings, *, admin: bool = False) -> dict:
    """返回技能目录；degraded 非空时 items 为空，前端按降级态展示。"""
    path = _resolve_catalog_path(settings)
    if path is None:
        return {"items": [], "degraded": "未找到 config/skills_catalog.json", "schema_version": None, "updated_at": None}

    doc, error = _load_document(path)
    if error or doc is None:
        return {"items": [], "degraded": error or "技能清单不可用", "schema_version": None, "updated_at": None}

    registered = _registered_names()
    build = _admin_item if admin else _user_item
    items = [build(raw, registered) for raw in doc.get("items", []) if isinstance(raw, dict)]
    return {
        "items": items,
        "degraded": None,
        "schema_version": doc.get("schema_version"),
        "updated_at": doc.get("updated_at"),
    }
