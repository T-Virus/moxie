# -*- coding: utf-8 -*-
"""管理员初始化 CLI：无需直接改库即可提升已注册账号。

用法：
    cd server
    python scripts/bootstrap_admin.py --email admin@example.com
    python scripts/bootstrap_admin.py --from-env
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

SERVER_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVER_DIR))

from app.bootstrap import bootstrap_admin, bootstrap_admins, parse_admin_emails  # noqa: E402
from app.config import Settings  # noqa: E402
from app.db import Database  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="提升已存在账号为管理员（幂等，写审计）")
    parser.add_argument("--email", help="已注册账号邮箱")
    parser.add_argument("--from-env", action="store_true", help="使用 BOOTSTRAP_ADMIN_EMAILS 白名单")
    args = parser.parse_args()

    settings = Settings()
    emails = parse_admin_emails(settings.bootstrap_admin_emails)
    if args.email:
        emails = [args.email]
    if not emails:
        parser.error("请提供 --email 或配置 BOOTSTRAP_ADMIN_EMAILS 后使用 --from-env")

    db = Database(settings)
    try:
        with db.session() as session:
            if args.email:
                results = [bootstrap_admin(session, args.email, source="cli")]
            else:
                results = bootstrap_admins(session, settings.bootstrap_admin_emails)
    finally:
        db.dispose()

    print(json.dumps(results, ensure_ascii=False, indent=2))
    return 0 if all(item.get("status") != "error" for item in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
