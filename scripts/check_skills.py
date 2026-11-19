#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""技能体系一致性校验（网文创作 10 环节）
==========================================

唯一事实源：config/skills_catalog.json。本脚本保证三件事不再漂移：

1. 环节清单完整：10 项、id/index 唯一且连续、触发词唯一、下游引用有效。
2. 配置对齐：config/studio.json#bindings 覆盖 src/studio.py#BIND_STAGES；
   清单声明的桌面工序有绑定，云端技能都在 SkillRegistry 注册。
3. 文档漂移（--drift）：扫描 docs/*.md 里带“已落盘/实际落盘/已可运行”等
   强声明的反引号路径，报告磁盘上并不存在的文件。该项只警告，不阻断提交。

用法：
    python scripts/check_skills.py            # check + drift
    python scripts/check_skills.py --check    # 仅硬校验，失败 exit 1
    python scripts/check_skills.py --drift    # 仅漂移报告，恒 exit 0

退出码：硬校验失败 1，全部通过 0。无第三方依赖，可在 CI 直接跑。
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CATALOG = ROOT / "config" / "skills_catalog.json"
STUDIO_JSON = ROOT / "config" / "studio.json"
STUDIO_PY = ROOT / "src" / "studio.py"
REGISTRY_PY = ROOT / "server" / "app" / "agents" / "registry.py"
SKILLS_DIR = ROOT / "server" / "app" / "agents" / "skills"
GRAPH_PY = ROOT / "server" / "app" / "agents" / "graph.py"
ARTIFACTS_PY = ROOT / "server" / "app" / "agents" / "artifacts.py"

EXPECTED_COUNT = 10
COVERAGE_VALUES = {"full", "partial", "cloud_gap"}
STRONG_CLAIM = re.compile(r"已落盘|实际落盘|已可运行|已实现|全部落盘|已落地|实际契约|真实可执行")
NEGATION = re.compile(r"未落盘|不存在|并不存在|缺失|规划|待实现|尚未")
PATH_TOKEN = re.compile(r"`([A-Za-z0-9_./-]+\.(?:py|json|md|sh|vue|ts|yaml|yml))`")


class Report:
    def __init__(self) -> None:
        self.ok = 0
        self.failures: list[str] = []
        self.warnings: list[str] = []

    def good(self, msg: str) -> None:
        self.ok += 1
        print(f"  [OK]   {msg}")

    def fail(self, msg: str) -> None:
        self.failures.append(msg)
        print(f"  [FAIL] {msg}")

    def warn(self, msg: str) -> None:
        self.warnings.append(msg)
        print(f"  [WARN] {msg}")


def _load_json(path: Path, report: Report, label: str) -> dict | None:
    if not path.exists():
        report.fail(f"{label} 不存在：{path.relative_to(ROOT)}")
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError) as exc:
        report.fail(f"{label} 读取失败：{exc}")
        return None


def _ast_assign(module: ast.Module, name: str):
    for node in module.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == name for t in node.targets
        ):
            return node.value
    return None


def _bind_stages() -> dict[str, str]:
    """从 src/studio.py 解析 BIND_STAGES，不导入模块（避免依赖 openai 等）。"""
    module = ast.parse(STUDIO_PY.read_text(encoding="utf-8"))
    value = _ast_assign(module, "BIND_STAGES")
    return ast.literal_eval(value) if value is not None else {}


def _registered_skill_names() -> set[str]:
    """解析 build_registry() 实例化的类，再取各类的 name 类属性。"""
    module = ast.parse(REGISTRY_PY.read_text(encoding="utf-8"))
    classes: set[str] = set()
    for node in module.body:
        if isinstance(node, ast.FunctionDef) and node.name == "build_registry":
            for call in ast.walk(node):
                if isinstance(call, ast.Call) and isinstance(call.func, ast.Name):
                    if call.func.id.endswith("Skill"):
                        classes.add(call.func.id)

    names: set[str] = set()
    for path in SKILLS_DIR.glob("*.py"):
        try:
            skill_module = ast.parse(path.read_text(encoding="utf-8"))
        except (OSError, SyntaxError):
            continue
        for cls in ast.walk(skill_module):
            if not isinstance(cls, ast.ClassDef) or cls.name not in classes:
                continue
            for stmt in cls.body:
                if not isinstance(stmt, ast.Assign):
                    continue
                if not any(isinstance(t, ast.Name) and t.id == "name" for t in stmt.targets):
                    continue
                if isinstance(stmt.value, ast.Constant) and isinstance(stmt.value.value, str):
                    names.add(stmt.value.value)
    return names


def _cloud_write_producers() -> tuple[set[str], set[str]]:
    """从代码反推云端真实产出：artifact 文件名 + checkpoint 节点 key。

    静态解析，不导入 server 依赖；只取字面量，足以发现“清单声明了不存在的产物”这类漂移。
    """
    artifacts: set[str] = set()
    nodes: set[str] = set()
    if ARTIFACTS_PY.exists():
        text = ARTIFACTS_PY.read_text(encoding="utf-8")
        artifacts.update(re.findall(r"[\"']([A-Za-z0-9_.-]+\.json)[\"']", text))
    if GRAPH_PY.exists():
        module = ast.parse(GRAPH_PY.read_text(encoding="utf-8"))
        for call in ast.walk(module):
            if not isinstance(call, ast.Call) or not isinstance(call.func, ast.Name):
                continue
            if call.func.id != "NodeSpec" or not call.args:
                continue
            first = call.args[0]
            if isinstance(first, ast.Constant) and isinstance(first.value, str):
                nodes.add(first.value)
        # _state(state, "<node>") 也是合法产出引用（如 chapter_expand 兼容分支）
        text = GRAPH_PY.read_text(encoding="utf-8")
        nodes.update(re.findall(r"_state\(state,\s*[\"']([A-Za-z0-9_]+)[\"']", text))
    return artifacts, nodes


def _check_writes(report: Report, items: list[dict]) -> None:
    """校验清单 writes 的云端声明都有代码产出方；桌面 data/ 路径由工序约定管，不在此列。"""
    artifacts, nodes = _cloud_write_producers()
    checked = 0
    stale: list[str] = []
    for item in items:
        iid = item.get("id", "?")
        for write in item.get("writes") or []:
            if not isinstance(write, str):
                continue
            if write.startswith("data/"):
                continue  # 桌面端落盘，非云端产物
            checked += 1
            m = re.match(r"^AgentRunStep\.output#([A-Za-z0-9_]+)", write)
            if m:
                if m.group(1) not in nodes:
                    stale.append(f"{iid}: 无产出节点 {m.group(1)}")
                continue
            name = write.strip()
            if name.endswith(".json") and name not in artifacts:
                stale.append(f"{iid}: 无写产物 {name}")
    if stale:
        for msg in stale:
            report.fail(f"writes 声明与代码产出不符 {msg}")
    else:
        report.good(f"清单 {checked} 项云端 writes 声明均有代码产出方")


def check(report: Report) -> None:
    print("== 硬校验：技能体系唯一事实源 ==")
    catalog = _load_json(CATALOG, report, "config/skills_catalog.json")
    if catalog is None:
        return

    items = catalog.get("items")
    if not isinstance(items, list):
        report.fail("skills_catalog.items 不是数组")
        return

    if len(items) != EXPECTED_COUNT:
        report.fail(f"环节数应为 {EXPECTED_COUNT}，实际 {len(items)}")
    else:
        report.good(f"环节数 {EXPECTED_COUNT}")

    ids = [item.get("id") for item in items]
    if len(set(ids)) != len(ids):
        report.fail(f"环节 id 重复：{ids}")
    else:
        report.good("环节 id 唯一")

    indexes = [item.get("index") for item in items]
    if indexes != list(range(1, EXPECTED_COUNT + 1)):
        report.fail(f"环节 index 应为 1..{EXPECTED_COUNT} 连续，实际 {indexes}")
    else:
        report.good("环节 index 连续")

    triggers = [t for item in items for t in (item.get("trigger") or [])]
    if len(set(triggers)) != len(triggers):
        dup = sorted({t for t in triggers if triggers.count(t) > 1})
        report.fail(f"触发词重复：{dup}")
    else:
        report.good(f"触发词唯一（{len(triggers)} 个）")

    for item in items:
        iid = item.get("id", "?")
        cov = item.get("coverage")
        if cov not in COVERAGE_VALUES:
            report.fail(f"{iid}: coverage 非法 {cov!r}")
        for nxt in item.get("next") or []:
            if nxt not in ids:
                report.fail(f"{iid}: next 引用不存在的环节 {nxt}")

    # 文件引用
    missing: list[str] = []
    for item in items:
        for section in ("desktop", "cloud"):
            for rel in (item.get(section) or {}).get("files") or []:
                if not (ROOT / rel).exists():
                    missing.append(f"{item.get('id')}/{section}: {rel}")
    if missing:
        for msg in missing:
            report.fail(f"引用文件不存在 {msg}")
    else:
        report.good("所有环节引用的文件均存在")

    # 桌面工序绑定对齐
    try:
        stages = _bind_stages()
    except (OSError, SyntaxError, ValueError) as exc:
        report.fail(f"解析 BIND_STAGES 失败：{exc}")
        stages = {}
    bindings_data = _load_json(STUDIO_JSON, report, "config/studio.json")
    bindings = (bindings_data or {}).get("bindings") or {}

    if stages:
        unbound = sorted(set(stages) - set(bindings))
        if unbound:
            report.fail(f"studio.json#bindings 缺少工序绑定：{unbound}")
        else:
            report.good(f"bindings 覆盖全部 {len(stages)} 个 BIND_STAGES")

    catalog_stages = sorted(
        {s for item in items for s in (item.get("desktop") or {}).get("stages") or []}
    )
    unknown_stage = sorted(set(catalog_stages) - set(stages))
    unbound_stage = sorted(set(catalog_stages) - set(bindings))
    if unknown_stage:
        report.fail(f"清单声明了不存在的桌面工序：{unknown_stage}")
    if unbound_stage:
        report.fail(f"清单声明的工序未绑定模型：{unbound_stage}")
    if not unknown_stage and not unbound_stage:
        report.good(f"清单声明的 {len(catalog_stages)} 个桌面工序均已绑定")

    # 写权声明 vs 代码真实产出
    _check_writes(report, items)

    # 云端技能注册对齐
    try:
        registered = _registered_skill_names()
    except (OSError, SyntaxError, ValueError) as exc:
        report.fail(f"解析 SkillRegistry 失败：{exc}")
        registered = set()
    declared = sorted(
        {s for item in items for s in (item.get("cloud") or {}).get("skills") or []}
    )
    unregistered = sorted(set(declared) - registered)
    if unregistered:
        report.fail(f"清单声明的云端技能未注册：{unregistered}")
    else:
        report.good(f"清单声明的 {len(declared)} 个云端技能均已注册")

    # 三端接线对齐：SSOT 改了但任一端没接上，就是"修改不同步"
    wiring = {
        "后端用户 API 路由": (ROOT / "server" / "app" / "api" / "skills.py", '"/skills"'),
        "后端管理 API 路由": (ROOT / "server" / "app" / "api" / "skills.py", '"/admin/skills"'),
        "后端 API 注册": (ROOT / "server" / "app" / "main.py", "skills.router"),
        "用户端 API 层": (ROOT / "client" / "src" / "services" / "agentApi.ts", "fetchSkills"),
        "用户端页面": (ROOT / "client" / "src" / "views" / "Skills.vue", "fetchSkills"),
        "用户端路由": (ROOT / "client" / "src" / "router.ts", "path: '/skills'"),
        "管理端 API 层": (ROOT / "admin" / "src" / "api.ts", "'/v1/admin/skills'"),
        "管理端页面": (ROOT / "admin" / "src" / "views" / "Skills.vue", "api.skills()"),
        "管理端路由": (ROOT / "admin" / "src" / "router.ts", "path: 'skills'"),
        "管理端权限": (ROOT / "admin" / "src" / "roles.ts", "skills:read"),
    }
    missed: list[str] = []
    for label, (path, needle) in wiring.items():
        if not path.exists() or needle not in path.read_text(encoding="utf-8"):
            missed.append(label)
    if missed:
        for label in missed:
            report.fail(f"三端接线缺失：{label}")
    else:
        report.good(f"技能目录三端接线齐全（{len(wiring)} 处）")

    # 用户端导航：技能页能力保留（API/页面/路由均在），但是否露出入口属产品决策。
    # 露出时须指向 /skills；移除入口不视为接线缺失。
    app_vue = ROOT / "client" / "src" / "App.vue"
    if app_vue.exists():
        app_text = app_vue.read_text(encoding="utf-8")
        if "to: '/skills'" in app_text:
            report.good("用户端导航露出技能入口且指向正确")
        else:
            report.good("用户端导航未露出技能入口（产品决策：能力保留但不露出）")


def drift(report: Report) -> None:
    print("== 漂移报告：文档强声明的文件路径 ==")
    docs = sorted((ROOT / "docs").glob("*.md")) if (ROOT / "docs").exists() else []
    claims = 0
    for path in docs:
        lines = path.read_text(encoding="utf-8").splitlines()
        for no, line in enumerate(lines, 1):
            if not STRONG_CLAIM.search(line):
                continue
            # 强声明常跨行书写：否定词可能落在下一行（如"声称已落盘…\n实际均不存在"）。
            # 取当前行前后各 2 行作为上下文，避免把事实核查段落误报为漂移。
            context = "\n".join(lines[max(0, no - 3): min(len(lines), no + 2)])
            if NEGATION.search(context):
                continue
            for rel in PATH_TOKEN.findall(line):
                target = (ROOT / rel).resolve()
                try:
                    target.relative_to(ROOT)
                except ValueError:
                    continue
                claims += 1
                if not target.exists():
                    report.warn(f"{path.name}:{no} 声称存在但缺失：{rel}")
    if claims == 0:
        report.good("未发现强声明路径")
    else:
        print(f"  （共扫描 {claims} 条强声明路径）")


def main() -> int:
    parser = argparse.ArgumentParser(description="技能体系一致性校验")
    parser.add_argument("--check", action="store_true", help="仅硬校验")
    parser.add_argument("--drift", action="store_true", help="仅漂移报告")
    args = parser.parse_args()

    report = Report()
    if not args.drift:
        check(report)
    if not args.check:
        drift(report)

    print()
    if report.failures:
        print(f"硬校验失败：{len(report.failures)} 项（漂移警告 {len(report.warnings)} 项）")
        return 1
    print(f"硬校验通过：{report.ok} 项；漂移警告 {len(report.warnings)} 项")
    return 0


if __name__ == "__main__":
    sys.exit(main())
