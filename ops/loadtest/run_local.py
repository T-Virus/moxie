# -*- coding: utf-8 -*-
"""一键本地压测：临时 SQLite + 本地存储启动服务端 → Locust headless → 清理。

不依赖 Docker / Postgres / Redis / MinIO，也不写项目 data/ 目录：
数据库、产物、源文件目录全部在系统临时目录下，脚本退出时删除。

用法：
    python ops/loadtest/run_local.py
    python ops/loadtest/run_local.py --vus 20 --duration 60s
    python ops/loadtest/run_local.py --server-python server/.venv/Scripts/python.exe

结果 CSV 默认写到 ops/reports/loadtest/（可提交/归档），控制台同时打印汇总。
"""

from __future__ import annotations

import argparse
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _default_server_python() -> str:
    candidates = [
        ROOT / "server" / ".venv" / "Scripts" / "python.exe",
        ROOT / "server" / ".venv" / "bin" / "python",
    ]
    for candidate in candidates:
        if candidate.exists():
            return str(candidate)
    return sys.executable


def _port_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind(("127.0.0.1", port))
            return True
        except OSError:
            return False


def _wait_health(url: str, timeout: float = 30.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url + "/healthz", timeout=2) as response:
                if response.status == 200:
                    return
        except Exception:  # noqa: BLE001
            time.sleep(0.5)
    raise RuntimeError("服务端在 30 秒内未就绪（检查端口 / 依赖是否安装）")


def main() -> int:
    parser = argparse.ArgumentParser(description="墨写服务端本地基准压测")
    parser.add_argument("--port", type=int, default=8798)
    parser.add_argument("--vus", type=int, default=10)
    parser.add_argument("--rate", type=float, default=2.0, help="每秒启动用户数")
    parser.add_argument("--duration", default="30s")
    parser.add_argument("--accounts", type=int, default=10, help="预置账号数量（每个账号独立额度）")
    parser.add_argument("--server-python", default=_default_server_python())
    parser.add_argument("--out", default=str(ROOT / "ops" / "reports" / "loadtest"))
    args = parser.parse_args()

    if not _port_free(args.port):
        print(f"[x] 端口 {args.port} 已被占用，请先停止旧服务或换 --port")
        return 2

    tmp = Path(tempfile.mkdtemp(prefix="moxie-loadtest-"))
    db_path = (tmp / "loadtest.db").as_posix()
    env = {
        **os.environ,
        "DATABASE_URL": f"sqlite:///{db_path}",
        "AUTO_CREATE_TABLES": "true",
        "REDIS_ENABLED": "false",
        "SCHEDULER_ENABLED": "false",
        "STORAGE_BACKEND": "local",
        "STORAGE_LOCAL_DIR": str(tmp / "artifacts"),
        "TASK_SOURCE_DIRS": str(tmp),
        "MODEL_STUB": "true",
        "METRICS_ENABLED": "true",
        "LOG_LEVEL": "WARNING",
        "JWT_SECRET": "loadtest-only-secret-at-least-32-bytes",
        # 压测账号准备需要远高于默认值的限流阈值（仅限本机临时库）
        "REGISTER_RATE_LIMIT_PER_MINUTE": "100000",
        "LOGIN_RATE_LIMIT_PER_MINUTE": "100000",
        "GATEWAY_RATE_LIMIT_PER_MINUTE": "100000",
    }

    base_url = f"http://127.0.0.1:{args.port}"
    print(f"[run] 启动服务端（SQLite: {db_path}）…")
    server = subprocess.Popen(
        [args.server_python, "-m", "uvicorn", "app.main:app",
         "--host", "127.0.0.1", "--port", str(args.port), "--log-level", "warning"],
        cwd=ROOT / "server",
        env=env,
    )

    try:
        _wait_health(base_url)
        print(f"[run] 服务端就绪：{base_url}")

        out_dir = Path(args.out)
        out_dir.mkdir(parents=True, exist_ok=True)
        csv_base = str(out_dir / "local")
        locust_cmd = [
            sys.executable, "-m", "locust",
            "-f", str(ROOT / "ops" / "loadtest" / "locustfile.py"),
            "--headless",
            "-H", base_url,
            "-u", str(args.vus),
            "-r", str(args.rate),
            "-t", args.duration,
            "--csv", csv_base,
            "--only-summary",
            "--loglevel", "WARNING",
        ]
        locust_env = {**os.environ, "MOXIE_BASE_URL": base_url, "LOADTEST_ACCOUNTS": str(args.accounts)}
        print(f"[run] locust: -u {args.vus} -r {args.rate} -t {args.duration}")
        result = subprocess.run(locust_cmd, env=locust_env)
        print(f"[run] CSV 结果：{csv_base}_*.csv")
        return result.returncode
    finally:
        server.terminate()
        try:
            server.wait(timeout=10)
        except subprocess.TimeoutExpired:
            server.kill()
        shutil.rmtree(tmp, ignore_errors=True)
        print(f"[run] 临时数据已清理：{tmp}")


if __name__ == "__main__":
    raise SystemExit(main())
