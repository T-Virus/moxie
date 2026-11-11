# -*- coding: utf-8 -*-
"""整本交付包：正文 + 章纲 + 角色/势力/道具 + 体检 + 权利/AIGC 声明，打包 zip。"""

from __future__ import annotations

import io
import json
import zipfile
from datetime import timezone

from sqlalchemy.orm import Session

from ..agents.artifacts import prefix_of
from ..agents.graph import RunView
from ..agents.store import ARTIFACT_NAMES, run_to_dict
from ..db import utcnow
from ..errors import ApiError
from ..models import AgentRun

AIGC_STATEMENT = """AI 生成合成内容声明

本交付包中的正文、章纲、角色/势力/道具设定等文字内容，由「墨写」AI 辅助创作工具生成或整理，
属于人工智能生成合成内容。请在对外发布时依据《人工智能生成合成内容标识办法》等适用规定，
以显著方式标注「AI 生成」或「AI 辅助生成」。

权利与合规说明：
1. 使用者应确保对输入作品、参考作品及相关素材拥有合法使用权或已获得授权；
2. 本工具不提供抄袭、洗稿或规避版权检测的能力，输出内容是否侵权由使用者自行判断并承担相应责任；
3. 敏感词与体检结果仅作辅助提示，不构成平台审核结论或法律意见；
4. 本文件由系统自动生成，导出时间以 manifest.json 为准。
"""


def _view(run: AgentRun) -> RunView:
    return RunView(
        id=run.id,
        mode=run.mode,
        title=run.title,
        audience=run.audience,
        length=run.length,
        genre_id=run.genre_id,
        genre_name=run.genre_name,
        source_key=run.source_key,
        brief=run.brief,
        meta=dict(run.meta or {}),
    )


def _read_artifact(storage, view: RunView, name: str) -> bytes | None:
    key = f"{prefix_of(view)}/{name}"
    try:
        if not storage.exists(key):
            return None
        return storage.get_bytes(key)
    except Exception:  # noqa: BLE001 - 单个产物缺失不应中断整包导出
        return None


def _read_json(storage, view: RunView, name: str):
    raw = _read_artifact(storage, view, name)
    if raw is None:
        return None
    try:
        return json.loads(raw.decode("utf-8"))
    except Exception:  # noqa: BLE001
        return None


def _markdown_to_text(md: str) -> str:
    lines: list[str] = []
    for line in md.splitlines():
        if line.startswith("# "):
            lines.append(line[2:].strip())
        elif line.startswith("## "):
            lines.append(line[3:].strip())
        elif line.startswith("### "):
            lines.append(line[4:].strip())
        elif line.startswith("> "):
            lines.append(line[2:].strip())
        else:
            lines.append(line)
    return "\n".join(lines).strip() + "\n"


def _render_outline_md(run: AgentRun, detail: dict) -> str:
    outline = detail.get("outline") or {}
    lines = [f"# 《{run.title}》章纲", ""]
    if outline.get("logline"):
        lines.extend([f"> {outline['logline']}", ""])
    for chapter in outline.get("chapters") or []:
        lines.append(f"## 第 {chapter.get('chapter')} 章 · {chapter.get('title') or ''}".rstrip())
        if chapter.get("summary"):
            lines.append(str(chapter["summary"]).strip())
        for event in chapter.get("key_events") or []:
            lines.append(f"- {event}")
        if chapter.get("hook"):
            lines.extend([f"> 钩子：{chapter['hook']}", ""])
        else:
            lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _render_review_md(run: AgentRun, detail: dict) -> str:
    meta = dict(run.meta or {})
    risks = meta.get("review_risks") or []
    suggestions = meta.get("review_suggestions") or []
    lines = [f"# 《{run.title}》体检报告", ""]
    lines.append(f"- 生成时间：{utcnow().isoformat()}")
    lines.append(f"- 章节数：{(detail.get('summary') or {}).get('chapters_count', 0)}")
    lines.append(f"- 总字数：{(detail.get('summary') or {}).get('word_count', 0)}")
    lines.append("")
    if meta.get("review_high_risk"):
        lines.append("## 结论")
        lines.append("发现高危问题，建议修改后再投稿或发布。")
        lines.append("")
    else:
        lines.append("## 结论")
        lines.append("本次运行未发现高危问题；体检结果为辅助提示，不构成平台审核结论。")
        lines.append("")
    if risks:
        lines.append("## 风险项")
        for item in risks:
            if isinstance(item, dict):
                level = item.get("level") or item.get("severity") or "提示"
                text = item.get("message") or item.get("reason") or item.get("text") or ""
                where = item.get("chapter") or item.get("location") or ""
                lines.append(f"- [{level}] {where} {text}".strip())
            else:
                lines.append(f"- {item}")
        lines.append("")
    if suggestions:
        lines.append("## 修改建议")
        for item in suggestions:
            lines.append(f"- {item}")
        lines.append("")
    lines.append("## 说明")
    lines.append("本报告由系统自动生成，仅作辅助参考，不替代人工审稿与法务意见。")
    return "\n".join(lines).rstrip() + "\n"


def build_book_export(
    db: Session, run: AgentRun, storage, *, aigc_label: bool = True
) -> tuple[str, bytes]:
    """返回 (下载文件名, zip 字节)；无任何可交付内容时抛 409。"""
    view = _view(run)
    detail = run_to_dict(db, run, storage=storage)

    artifacts: dict[str, bytes] = {}
    for name in ARTIFACT_NAMES:
        raw = _read_artifact(storage, view, name)
        if raw is not None:
            artifacts[name] = raw

    manuscript = artifacts.get("manuscript.md")
    if manuscript is None:
        chapters = [c for c in (detail.get("chapters") or []) if str(c.get("content") or "").strip()]
        if chapters:
            from ..agents.artifacts import render_manuscript_md

            manuscript = render_manuscript_md(view, chapters).encode("utf-8")

    outline = artifacts.get("outline.md")
    if outline is None:
        outline = _render_outline_md(run, detail).encode("utf-8")

    if not artifacts and not manuscript and not detail.get("characters"):
        raise ApiError(409, "run_not_ready", "作品尚未生成可交付内容，请等待完成后再下载")

    info = dict((run.meta or {}).get("info") or {})
    author = str(info.get("author") or "")
    summary = detail.get("summary") or {}
    exported_at = utcnow().replace(tzinfo=timezone.utc).astimezone().isoformat()

    manifest = {
        "generator": "墨写",
        "exported_at": exported_at,
        "run_id": run.id,
        "title": run.title,
        "author": author,
        "genre": {"id": run.genre_id, "name": run.genre_name},
        "mode": run.mode,
        "audience": run.audience,
        "length": run.length,
        "status": run.status,
        "chapters_count": summary.get("chapters_count", 0),
        "word_count": summary.get("word_count", 0),
        "aigc": {
            "label": "AI 生成合成内容" if aigc_label else "",
            "enabled": aigc_label,
            "statement_file": "AIGC声明.txt",
        },
        "rights": {
            "reference_mode": run.mode == "reference",
            "confirmed_by_user": True,
            "note": "参考作品使用权由用户在创建任务时确认；导出包不包含参考作品原文。",
        },
        "files": [],
    }

    buffer = io.BytesIO()
    written: list[str] = []

    def add(name: str, data: bytes) -> None:
        buffer_zip.writestr(name, data)
        written.append(name)

    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as buffer_zip:
        if manuscript:
            add("正文/正文.md", manuscript)
            add("正文/正文.txt", _markdown_to_text(manuscript.decode("utf-8")).encode("utf-8"))
        add("章纲/章纲.md", outline)

        characters = _read_json(storage, view, "characters.json") or {
            "book_title": run.title,
            "characters": detail.get("characters") or [],
        }
        factions = _read_json(storage, view, "factions.json") or {
            "book_title": run.title,
            "factions": detail.get("factions") or [],
        }
        items = _read_json(storage, view, "items.json") or {
            "book_title": run.title,
            "items": detail.get("items") or [],
        }
        add("设定/角色.json", json.dumps(characters, ensure_ascii=False, indent=2).encode("utf-8"))
        add("设定/势力.json", json.dumps(factions, ensure_ascii=False, indent=2).encode("utf-8"))
        add("设定/道具功法.json", json.dumps(items, ensure_ascii=False, indent=2).encode("utf-8"))
        add(
            "设定/设定集.json",
            json.dumps(
                {
                    "story_bible": detail.get("story_bible") or {},
                    "volumes": detail.get("volumes") or [],
                    "outline": detail.get("outline") or {},
                },
                ensure_ascii=False,
                indent=2,
            ).encode("utf-8"),
        )

        add("体检/体检报告.md", _render_review_md(run, detail).encode("utf-8"))
        if aigc_label:
            add("AIGC声明.txt", AIGC_STATEMENT.encode("utf-8"))

        for name, raw in sorted(artifacts.items()):
            add(f"原始产物/{name}", raw)

        manifest["files"] = written + ["manifest.json", "交付说明.md"]
        add("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8"))
        add(
            "交付说明.md",
            _render_readme(run, manifest, artifacts).encode("utf-8"),
        )

    filename = f"{run.title}-交付包-{utcnow().strftime('%Y%m%d')}.zip"
    return filename, buffer.getvalue()


def _render_readme(run: AgentRun, manifest: dict, artifacts: dict[str, bytes]) -> str:
    lines = [
        f"# 《{run.title}》交付说明",
        "",
        f"- 作者：{manifest.get('author') or '未填写'}",
        f"- 题材：{(manifest.get('genre') or {}).get('name') or ''}",
        f"- 章节数：{manifest.get('chapters_count')}",
        f"- 总字数：{manifest.get('word_count')}",
        f"- 导出时间：{manifest.get('exported_at')}",
        "",
        "## 目录",
        "- 正文/：正文 Markdown 与纯文本",
        "- 章纲/：分章章纲",
        "- 设定/：角色、势力、道具功法、设定集与分卷（JSON，可编辑）",
        "- 体检/：本次运行的体检结论与风险提示",
        "- 原始产物/：系统原始产物（outline/chapters/story_bible 等）",
        "- AIGC声明.txt：AI 生成合成内容声明（默认附带）",
        "",
        "## 使用提醒",
        "1. 对外发布时请保留 AI 生成标识；",
        "2. 参考写作模式导出的内容不包含参考作品原文，请确保已获得相应授权；",
        "3. 体检结果仅作辅助提示，不构成平台审核或法律意见。",
        "",
        f"共 {len(artifacts)} 个原始产物。",
    ]
    return "\n".join(lines).rstrip() + "\n"
