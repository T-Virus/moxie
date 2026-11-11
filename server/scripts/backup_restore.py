#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""备份 / 恢复 / 演练 CLI（只依赖标准库）。

用法（在 server/ 目录）：
  python scripts/backup_restore.py backup  --out backups
  python scripts/backup_restore.py restore --backup backups/backup-<ts> [--force]
  python scripts/backup_restore.py drill   --backup backups/backup-<ts>

- SQLite：使用 sqlite3 在线备份 API 生成一致性快照，可直接恢复/演练；
- PostgreSQL：调用外部 pg_dump -Fc / pg_restore（需本机安装客户端）；
- 本地存储：复制 STORAGE_LOCAL_DIR 全量目录；
- S3/MinIO：生成 mc mirror 命令（安装 mc 并配置 alias 后执行），不内置云 SDK。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

SERVER_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SERVER_DIR))

from app.config import Settings  # noqa: E402

KEY_TABLES = ("accounts", "orders", "tasks", "credit_packs", "credit_grants", "notifications")


def _sqlite_path(url: str) -> Path | None:
    if not url.startswith("sqlite"):
        return None
    raw = url.split("///", 1)[-1]
    return Path(raw).expanduser().resolve()


def _is_postgres(url: str) -> bool:
    return url.startswith("postgresql") or url.startswith("postgres")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _sqlite_snapshot(source: Path, target: Path) -> None:
    if not source.is_file():
        raise SystemExit(f"SQLite 数据库不存在：{source}")
    target.parent.mkdir(parents=True, exist_ok=True)
    src_conn = sqlite3.connect(source)
    dst_conn = sqlite3.connect(target)
    try:
        src_conn.backup(dst_conn)
        dst_conn.commit()
        status = dst_conn.execute("PRAGMA integrity_check").fetchone()[0]
    finally:
        src_conn.close()
        dst_conn.close()
    if status != "ok":
        raise SystemExit(f"SQLite 备份完整性检查失败：{status}")


def _run(command: list[str], *, dry_run: bool = False) -> None:
    print("$", " ".join(command))
    if not dry_run:
        subprocess.run(command, check=True)


def cmd_backup(args: argparse.Namespace) -> int:
    settings = Settings()
    database_url = args.database_url or settings.database_url
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_root = Path(args.out).resolve()
    workdir = out_root / f"backup-{stamp}"
    workdir.mkdir(parents=True, exist_ok=True)
    manifest: dict = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "database_url": database_url,
        "storage_backend": (args.storage_backend or settings.storage_backend).lower(),
        "files": {},
    }

    if _is_postgres(database_url):
        pg_dump = shutil.which("pg_dump")
        if not pg_dump:
            raise SystemExit("未找到 pg_dump：请安装 PostgreSQL 客户端后重试（Postgres 全量备份必须用 pg_dump）")
        dump = workdir / "db.dump"
        _run([pg_dump, "-Fc", "-f", str(dump), database_url], dry_run=args.dry_run)
        manifest["database"] = {"kind": "postgres", "file": dump.name, "format": "custom"}
    else:
        db_path = _sqlite_path(database_url)
        if db_path is None:
            raise SystemExit(f"暂不支持该 DATABASE_URL：{database_url}")
        target = workdir / "db.sqlite"
        _sqlite_snapshot(db_path, target)
        manifest["database"] = {"kind": "sqlite", "file": target.name, "source": str(db_path)}
        manifest["files"][target.name] = _sha256(target)

    backend = manifest["storage_backend"]
    local_dir = Path(args.local_dir or settings.storage_local_dir)
    if backend in {"s3", "minio", "oss"}:
        bucket = settings.s3_bucket
        endpoint = settings.s3_endpoint_url
        mirror_cmd = (
            f"mc alias set backup {endpoint} $S3_ACCESS_KEY $S3_SECRET_KEY\n"
            f"mc mirror --overwrite backup/{bucket} {workdir.as_posix()}/minio\n"
        )
        (workdir / "minio-mirror.sh").write_text(mirror_cmd, encoding="utf-8")
        manifest["storage"] = {
            "kind": "s3",
            "bucket": bucket,
            "endpoint": endpoint,
            "note": "在装有 mc 的机器上执行 minio-mirror.sh；未自动执行云端同步",
        }
        print(f"[warn] S3/MinIO 未自动同步，已生成 {workdir / 'minio-mirror.sh'}")
    elif backend in {"db", "database"}:
        # 产物与上传源文件都在 stored_objects 表里，数据库快照即完整备份
        manifest["storage"] = {
            "kind": "db",
            "note": "产物已随数据库快照备份，无需单独复制文件",
        }
    else:
        if local_dir.is_dir():
            shutil.copytree(local_dir, workdir / "artifacts")
            count = sum(1 for path in (workdir / "artifacts").rglob("*") if path.is_file())
            manifest["storage"] = {"kind": "local", "dir": str(local_dir), "files": count}
        else:
            manifest["storage"] = {"kind": "local", "dir": str(local_dir), "files": 0, "note": "目录不存在"}

    (workdir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"[ok] 备份完成：{workdir}")

    if args.keep > 0:
        backups = sorted(out_root.glob("backup-*"))
        for old in backups[: max(0, len(backups) - args.keep)]:
            shutil.rmtree(old, ignore_errors=True)
            print(f"[prune] 删除旧备份 {old.name}")
    return 0


def cmd_restore(args: argparse.Namespace) -> int:
    settings = Settings()
    backup_dir = Path(args.backup).resolve()
    manifest_path = backup_dir / "manifest.json"
    if not manifest_path.is_file():
        raise SystemExit(f"备份目录缺少 manifest.json：{backup_dir}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    database = manifest.get("database", {})
    if database.get("kind") == "sqlite":
        source = backup_dir / database["file"]
        if not source.is_file():
            raise SystemExit(f"备份数据库不存在：{source}")
        database_url = args.database_url or settings.database_url
        target = _sqlite_path(database_url)
        if target is None:
            raise SystemExit(f"目标不是 SQLite：{database_url}")
        if target.exists() and not args.force:
            raise SystemExit(f"目标数据库已存在：{target}（确认覆盖请加 --force）")
        _sqlite_snapshot(source, target)
        print(f"[ok] SQLite 已恢复：{target}")
    elif database.get("kind") == "postgres":
        pg_restore = shutil.which("pg_restore")
        if not pg_restore:
            raise SystemExit("未找到 pg_restore：请安装 PostgreSQL 客户端")
        dump = backup_dir / database["file"]
        database_url = args.database_url or settings.database_url
        _run([pg_restore, "-c", "-d", database_url, str(dump)], dry_run=args.dry_run)
        print("[ok] PostgreSQL 已恢复（pg_restore -c）")
    else:
        raise SystemExit("manifest 中缺少可识别的 database 信息")

    storage_manifest = manifest.get("storage", {})
    if storage_manifest.get("kind") == "local":
        source_dir = backup_dir / "artifacts"
        target_dir = Path(args.local_dir or settings.storage_local_dir)
        if not source_dir.is_dir():
            print("[warn] 备份中没有 artifacts 目录，跳过本地存储恢复")
        else:
            if target_dir.exists() and any(target_dir.iterdir()) and not args.force:
                raise SystemExit(f"产物目录非空：{target_dir}（确认覆盖请加 --force）")
            shutil.copytree(source_dir, target_dir, dirs_exist_ok=True)
            print(f"[ok] 本地产物已恢复：{target_dir}")
    elif storage_manifest.get("kind") == "s3":
        print(f"[manual] 请在其他机器执行：{backup_dir / 'minio-mirror.sh'}（或 mc mirror 到目标 bucket）")
    return 0


def cmd_drill(args: argparse.Namespace) -> int:
    backup_dir = Path(args.backup).resolve()
    manifest = json.loads((backup_dir / "manifest.json").read_text(encoding="utf-8"))
    database = manifest.get("database", {})
    if database.get("kind") != "sqlite":
        raise SystemExit("演练当前只支持 SQLite 备份（本地可完整演练）；Postgres 请用 pg_restore --list 校验")

    snapshot = backup_dir / database["file"]
    expected = manifest.get("files", {}).get(snapshot.name)
    actual = _sha256(snapshot)
    if expected and expected != actual:
        raise SystemExit(f"备份文件校验失败：sha256 {actual} != {expected}")

    temp_dir = Path(tempfile.mkdtemp(prefix="moxie-drill-"))
    restored = temp_dir / "restored.sqlite"
    _sqlite_snapshot(snapshot, restored)
    conn = sqlite3.connect(restored)
    try:
        integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        missing = [name for name in KEY_TABLES if name not in tables]
        counts = {}
        for name in KEY_TABLES:
            if name in tables:
                counts[name] = conn.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0]
    finally:
        conn.close()

    artifacts = backup_dir / "artifacts"
    artifact_count = sum(1 for path in artifacts.rglob("*") if path.is_file()) if artifacts.is_dir() else 0
    if missing:
        raise SystemExit(f"恢复演练失败：缺少表 {missing}")
    if integrity != "ok":
        raise SystemExit(f"恢复演练失败：SQLite integrity_check={integrity}")

    print("[ok] 恢复演练通过")
    print(f"  integrity_check={integrity}  tables={len(tables)}  artifacts={artifact_count}")
    print(f"  关键表行数={counts}")
    print(f"  临时恢复目录={temp_dir}（可人工确认后删除）")
    if not args.keep:
        shutil.rmtree(temp_dir, ignore_errors=True)
        print("  已清理临时恢复目录")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="墨写服务端备份/恢复/演练")
    sub = parser.add_subparsers(dest="command", required=True)

    backup = sub.add_parser("backup", help="生成一份备份")
    backup.add_argument("--out", default="backups", help="备份根目录（默认 server/backups）")
    backup.add_argument("--database-url", default="", help="覆盖 DATABASE_URL")
    backup.add_argument("--storage-backend", default="", help="覆盖 STORAGE_BACKEND（local/s3）")
    backup.add_argument("--local-dir", default="", help="覆盖 STORAGE_LOCAL_DIR")
    backup.add_argument("--keep", type=int, default=7, help="保留最近 N 份备份（0=不清理）")
    backup.add_argument("--dry-run", action="store_true")
    backup.set_defaults(func=cmd_backup)

    restore = sub.add_parser("restore", help="从备份恢复")
    restore.add_argument("--backup", required=True, help="backup-<ts> 目录")
    restore.add_argument("--database-url", default="", help="覆盖 DATABASE_URL")
    restore.add_argument("--local-dir", default="", help="覆盖 STORAGE_LOCAL_DIR")
    restore.add_argument("--force", action="store_true", help="允许覆盖已有数据库/产物目录")
    restore.add_argument("--dry-run", action="store_true")
    restore.set_defaults(func=cmd_restore)

    drill = sub.add_parser("drill", help="恢复演练（SQLite）")
    drill.add_argument("--backup", required=True, help="backup-<ts> 目录")
    drill.add_argument("--keep", action="store_true", help="保留临时恢复目录")
    drill.set_defaults(func=cmd_drill)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
