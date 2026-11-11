# -*- coding: utf-8 -*-
"""SQLite + 本地存储备份/恢复演练（无需 Docker / Postgres / MinIO）。

演练内容：
  1. 创建临时 SQLite 库（模拟服务端表结构与数据）；
  2. 用 sqlite3 在线备份 API 做一致性备份（等价于 VACUUM INTO / .backup）；
  3. 模拟误删：删除原库与本地产物目录；
  4. 从备份恢复数据库与产物文件；
  5. 校验行数、外键关联、文件 SHA-256 全部一致。

运行：
    python ops/backup/sqlite_drill.py

输出：每一步日志 + 最终 PASS/FAIL；全过程使用系统临时目录，不接触 data/。
"""

from __future__ import annotations

import hashlib
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path

REQUIRED_ROWS = {
    "accounts": 3,
    "tasks": 6,
    "usage_events": 6,
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(65536), b""):
            digest.update(block)
    return digest.hexdigest()


def _create_sample_db(db_path: Path) -> None:
    conn = sqlite3.connect(db_path)
    try:
        conn.executescript(
            """
            PRAGMA foreign_keys=ON;
            CREATE TABLE accounts (
                id INTEGER PRIMARY KEY,
                email TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL
            );
            CREATE TABLE tasks (
                id TEXT PRIMARY KEY,
                account_id INTEGER NOT NULL REFERENCES accounts(id),
                status TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE TABLE usage_events (
                id INTEGER PRIMARY KEY,
                account_id INTEGER NOT NULL REFERENCES accounts(id),
                metric TEXT NOT NULL,
                quantity INTEGER NOT NULL
            );
            """
        )
        for i in range(1, 4):
            conn.execute(
                "INSERT INTO accounts(id, email, password_hash) VALUES (?, ?, ?)",
                (i, f"loadtest-{i}@example.com", f"hash-{i}"),
            )
        for i in range(1, 7):
            account = (i % 3) + 1
            conn.execute(
                "INSERT INTO tasks(id, account_id, status, created_at) VALUES (?, ?, ?, ?)",
                (f"task-{i}", account, "succeeded", f"2026-11-0{i % 9 + 1}T00:00:00Z"),
            )
            conn.execute(
                "INSERT INTO usage_events(id, account_id, metric, quantity) VALUES (?, ?, ?, ?)",
                (i, account, "books_month", 1),
            )
        conn.commit()
    finally:
        conn.close()


def _backup_db(src: Path, dst: Path) -> None:
    """sqlite3 在线备份 API：读取过程中加共享锁，可安全热备份。"""
    source = sqlite3.connect(src)
    target = sqlite3.connect(dst)
    try:
        source.backup(target)
        cursor = target.execute("PRAGMA integrity_check")
        if cursor.fetchone()[0] != "ok":
            raise RuntimeError("备份库 integrity_check 失败")
    finally:
        target.close()
        source.close()


def _create_artifacts(artifacts_dir: Path) -> dict[str, str]:
    (artifacts_dir / "books").mkdir(parents=True)
    (artifacts_dir / "books" / "第一章.md").write_text("第一章 备份演练样例\n", encoding="utf-8")
    (artifacts_dir / "books" / "meta.json").write_text('{"book":"drill"}', encoding="utf-8")
    return {str(p.relative_to(artifacts_dir)): _sha256(p) for p in artifacts_dir.rglob("*") if p.is_file()}


def _count_rows(db_path: Path) -> dict[str, int]:
    conn = sqlite3.connect(db_path)
    try:
        return {
            table: conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in REQUIRED_ROWS
        }
    finally:
        conn.close()


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="moxie-backup-drill-"))
    live_db = tmp / "live" / "novel_server.db"
    backup_dir = tmp / "backup"
    live_artifacts = tmp / "live" / "artifacts"
    restored_db = tmp / "restore" / "novel_server.db"
    restored_artifacts = tmp / "restore" / "artifacts"

    try:
        live_db.parent.mkdir(parents=True)
        backup_dir.mkdir(parents=True)

        print("[1/6] 创建样例 SQLite 库与本地产物")
        _create_sample_db(live_db)
        before_hashes = _create_artifacts(live_artifacts)
        before_rows = _count_rows(live_db)
        print(f"      库：{live_db}")
        print(f"      行数：{before_rows}，产物文件：{len(before_hashes)}")

        print("[2/6] 数据库在线备份 + 产物目录同步")
        backup_db = backup_dir / "novel_server.db"
        _backup_db(live_db, backup_db)
        shutil.copytree(live_artifacts, backup_dir / "artifacts")
        print(f"      备份 DB：{backup_db.name}（{backup_db.stat().st_size} bytes）")

        print("[3/6] 模拟故障：删除原库与原产物目录")
        live_db.unlink()
        shutil.rmtree(live_artifacts)
        if live_db.exists() or live_artifacts.exists():
            raise RuntimeError("模拟删除未生效")

        print("[4/6] 从备份恢复")
        restored_db.parent.mkdir(parents=True)
        shutil.copy2(backup_db, restored_db)
        shutil.copytree(backup_dir / "artifacts", restored_artifacts)

        print("[5/6] 校验数据与文件一致性")
        after_rows = _count_rows(restored_db)
        after_hashes = {
            str(p.relative_to(restored_artifacts)): _sha256(p)
            for p in restored_artifacts.rglob("*")
            if p.is_file()
        }
        if after_rows != before_rows:
            raise RuntimeError(f"行数不一致：before={before_rows} after={after_rows}")
        if after_hashes != before_hashes:
            raise RuntimeError("产物文件哈希不一致")
        # 关联完整性：每条任务都能找到账号
        conn = sqlite3.connect(restored_db)
        try:
            orphan = conn.execute(
                "SELECT COUNT(*) FROM tasks t LEFT JOIN accounts a ON a.id=t.account_id WHERE a.id IS NULL"
            ).fetchone()[0]
        finally:
            conn.close()
        if orphan:
            raise RuntimeError(f"恢复后存在 {orphan} 条孤儿任务")

        print(f"      恢复行数：{after_rows}，产物文件哈希全部一致")
        print("[6/6] PASS：SQLite + 本地存储备份/恢复演练通过")
        return 0
    except Exception as exc:  # noqa: BLE001
        print(f"[6/6] FAIL：{exc}")
        return 1
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
        print(f"      临时目录已清理：{tmp}")


if __name__ == "__main__":
    sys.exit(main())
