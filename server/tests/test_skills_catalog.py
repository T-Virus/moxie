# -*- coding: utf-8 -*-
"""网文创作技能体系：唯一事实源与一致性校验回归。

本文件只依赖标准库与仓库内文件，不启动 app、不连接数据库；
放在 server/tests 下是为了并入既有 pytest 基线。
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "check_skills.py"
CATALOG_PATH = ROOT / "config" / "skills_catalog.json"
STUDIO_PATH = ROOT / "config" / "studio.json"


@pytest.fixture(scope="module")
def checker():
    spec = importlib.util.spec_from_file_location("check_skills_under_test", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def catalog():
    return json.loads(CATALOG_PATH.read_text(encoding="utf-8"))


def test_catalog_declares_ten_unique_stages(catalog):
    items = catalog["items"]
    assert len(items) == 10
    assert [item["index"] for item in items] == list(range(1, 11))
    assert len({item["id"] for item in items}) == 10
    assert all(item["coverage"] in {"full", "partial", "cloud_gap"} for item in items)


def test_triggers_are_unique(catalog):
    triggers = [t for item in catalog["items"] for t in item["trigger"]]
    assert len(triggers) == len(set(triggers))


def test_next_references_resolve(catalog):
    ids = {item["id"] for item in catalog["items"]}
    for item in catalog["items"]:
        for nxt in item["next"]:
            assert nxt in ids, f"{item['id']} -> {nxt}"


def test_referenced_files_exist(catalog):
    for item in catalog["items"]:
        for section in ("desktop", "cloud"):
            for rel in item[section]["files"]:
                assert (ROOT / rel).exists(), f"{item['id']}/{section}: {rel}"


def test_bindings_cover_all_desktop_stages(checker):
    stages = checker._bind_stages()
    bindings = json.loads(STUDIO_PATH.read_text(encoding="utf-8"))["bindings"]
    assert stages, "BIND_STAGES 解析失败"
    assert set(stages) <= set(bindings)


def test_declared_desktop_stages_are_bound(catalog):
    bindings = json.loads(STUDIO_PATH.read_text(encoding="utf-8"))["bindings"]
    declared = {s for item in catalog["items"] for s in item["desktop"]["stages"]}
    assert declared <= set(bindings)


def test_declared_cloud_skills_are_registered(checker, catalog):
    registered = checker._registered_skill_names()
    declared = {s for item in catalog["items"] for s in item["cloud"]["skills"]}
    assert declared, "清单未声明任何云端技能"
    assert declared <= registered


def test_hard_check_has_no_failures(checker):
    report = checker.Report()
    checker.check(report)
    assert not report.failures, report.failures


def test_docs_have_no_missing_strong_claims(checker):
    report = checker.Report()
    checker.drift(report)
    assert not report.warnings, report.warnings


def test_cli_check_exits_zero():
    proc = subprocess.run(
        [sys.executable, str(SCRIPT), "--check"],
        capture_output=True,
        text=True,
        cwd=ROOT,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
