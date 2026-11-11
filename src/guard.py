# -*- coding: utf-8 -*-
"""
运行期防护
==========
把「随手抓包 / 解包 / 批量抓取」的门槛抬高一档，共三件事：

  1) 启动体检：调试器已附加，或逆向 / 抓包工具进程在跑时，提示并拒绝启动；
  2) 请求准入：拦截爬虫 / 抓包工具的 User-Agent；打包形态下写请求必须带首页注入的
     会话令牌，且 Origin 必须与 Host 同源；
  3) 频率限制：滑动窗口限流，连续越界后给出冷却时间，挡住批量抓取与暴力枚举。

这只是「抬高门槛」，不是绝对安全：本地防护总能被绕过。开发调试时可设置
环境变量 MOBIT_NO_AUDIT=1 跳过启动体检。
"""

import json
import os
import secrets
import subprocess
import sys
import threading
import time
from urllib.parse import urlsplit

# 打包形态：PyInstaller 会设 sys.frozen；Nuitka 编成机器码后 sys.frozen 不存在，
# 但每个被编译的模块都有 __compiled__；手机端由 MainActivity 注入 MOBIT_ROOT。
IS_PACKAGED = bool(getattr(sys, "frozen", False) or "__compiled__" in globals()
                   or os.environ.get("MOBIT_ROOT"))

# 每次运行一个随机令牌：首页注入给前端，写请求必须带回。
# 重启即失效，不做持久化，避免令牌落盘后被直接复用。
SESSION_TOKEN = secrets.token_urlsafe(32)
TOKEN_HEADER = "X-MW-Token"

# 逆向 / 调试 / 抓包工具的可执行文件名（小写、不含扩展名）
TOOL_PROCESSES = {
    "x64dbg": "x64dbg", "x32dbg": "x32dbg", "x96dbg": "x96dbg",
    "ollydbg": "OllyDbg", "ida": "IDA Pro", "ida64": "IDA Pro", "idag": "IDA Pro",
    "ghidra": "Ghidra", "jadx": "JADX", "jadx-gui": "JADX",
    "apktool": "Apktool", "dex2jar": "dex2jar", "jd-gui": "JD-GUI",
    "dnspy": "dnSpy", "ilspy": "ILSpy", "cheatengine": "Cheat Engine",
    "processhacker": "Process Hacker", "systeminformer": "System Informer",
    "frida": "Frida", "frida-server": "Frida", "frida-helper": "Frida",
    "mitmproxy": "mitmproxy", "mitmdump": "mitmproxy",
    "charles": "Charles", "fiddler": "Fiddler", "httpdebugger": "HTTP Debugger",
    "wireshark": "Wireshark", "tshark": "Wireshark", "dumpcap": "Wireshark",
}

# 爬虫 / 脚本客户端 / 抓包工具的 UA 特征（小写子串匹配）
CRAWLER_UA = (
    "python-requests", "python-urllib", "urllib3", "aiohttp", "httpx",
    "scrapy", "curl/", "wget/", "libwww-perl", "go-http-client",
    "apache-httpclient", "okhttp/", "node-fetch", "axios/",
    "selenium", "puppeteer", "playwright", "phantomjs", "headlesschrome",
    "htmlunit", "jsdom", "crawler", "scraping", "spider",
    "baiduspider", "googlebot", "bingbot", "bytespider",
)

# 限流：同一个来源 IP 在窗口内的请求数上限
_WINDOW = 10.0
_READ_MAX = 600          # 读：前端任务轮询约 1 次/秒，留足余量
_WRITE_MAX = 120
_STRIKE_LIMIT = 20       # 连续越界次数达到后给一次长冷却
_STRIKE_COOLDOWN = 120
_BUCKET_MAX = 2048

_LOCK = threading.Lock()
_BUCKETS = {}
_STRIKES = {}


# ---------------------------------------------------------------- 启动体检
def _process_names():
    """当前所有进程的可执行文件名（小写，去 .exe）；拿不到就返回空表。"""
    try:
        if os.name == "nt":
            flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            out = subprocess.check_output(
                ["tasklist", "/FO", "CSV", "/NH"],
                stdin=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                timeout=6, creationflags=flags)
            names = []
            for line in out.decode("ascii", "ignore").splitlines():
                if not line.startswith('"'):
                    continue
                names.append(line[1:].split('","', 1)[0])
            return names
        names = []
        for pid in os.listdir("/proc"):
            if not pid.isdigit():
                continue
            try:
                with open("/proc/%s/cmdline" % pid, "rb") as f:
                    raw = f.read()
            except OSError:
                continue
            if raw:
                arg0 = raw.split(b"\x00", 1)[0].decode("utf-8", "ignore")
                names.append(os.path.basename(arg0))
        return names
    except Exception:
        return []


def _running_tools():
    """命中的逆向 / 抓包工具（去重后的展示名）。"""
    found = []
    for name in _process_names():
        stem = name.lower()
        if stem.endswith(".exe"):
            stem = stem[:-4]
        label = TOOL_PROCESSES.get(stem)
        if label and label not in found:
            found.append(label)
    return found


def _debugger_attached():
    """调试器附加检测：Python 跟踪钩子 + 系统 API / TracerPid。"""
    try:
        if sys.gettrace() is not None:
            return True
    except Exception:
        pass
    if os.name == "nt":
        try:
            import ctypes
            k32 = ctypes.windll.kernel32
            if k32.IsDebuggerPresent():
                return True
            remote = ctypes.c_int(0)
            if (k32.CheckRemoteDebuggerPresent(k32.GetCurrentProcess(),
                                               ctypes.byref(remote)) and remote.value):
                return True
        except Exception:
            pass
        return False
    try:
        with open("/proc/self/status", encoding="utf-8", errors="ignore") as f:
            for line in f:
                if line.startswith("TracerPid:"):
                    return line.split(":", 1)[1].strip() not in ("", "0")
    except OSError:
        pass
    return False


def audit():
    """返回阻断启动的原因列表；空列表表示环境正常。"""
    problems = []
    if _debugger_attached():
        problems.append("检测到调试器正在附加本进程")
    tools = _running_tools()
    if tools:
        problems.append("检测到逆向 / 抓包工具正在运行：" + "、".join(tools))
    return problems


def _alert(title, text):
    if os.name == "nt":
        try:
            import ctypes
            ctypes.windll.user32.MessageBoxW(0, text, title, 0x10)
            return
        except Exception:
            pass
    try:
        sys.stderr.write("[安全校验] " + text + "\n")
        sys.stderr.flush()
    except Exception:
        pass


def enforce():
    """启动体检：命中即提示并退出。MOBIT_NO_AUDIT=1 可跳过（开发调试用）。"""
    if os.environ.get("MOBIT_NO_AUDIT") == "1":
        return
    problems = audit()
    if not problems:
        return
    _alert("墨写 · 安全校验",
           "为保护程序与作品数据，「墨写」拒绝在当前环境启动：\n\n"
           + "\n".join("· " + p for p in problems)
           + "\n\n请关闭上述软件后重新打开墨写。")
    sys.exit(3)


# ---------------------------------------------------------------- 请求准入
def _allow(ip, bucket, limit):
    """滑动窗口限流 → (是否放行, Retry-After 秒)。"""
    now = time.monotonic()
    key = (ip or "-", bucket)
    with _LOCK:
        hits = [t for t in (_BUCKETS.get(key) or []) if now - t < _WINDOW]
        hits.append(now)
        _BUCKETS[key] = hits
        if len(_BUCKETS) > _BUCKET_MAX:
            _BUCKETS.clear()
            _STRIKES.clear()
            _BUCKETS[key] = hits
        if len(hits) <= limit:
            return True, 0
        strikes = _STRIKES.get(ip or "-", 0) + 1
        _STRIKES[ip or "-"] = strikes
        if strikes >= _STRIKE_LIMIT:
            _STRIKES[ip or "-"] = 0
            _BUCKETS[key] = []
            return False, _STRIKE_COOLDOWN
        return False, 5


def inject_token(html):
    """把本次运行的会话令牌注入首页；写请求靠它区分「界面内操作」与「外部脚本」。"""
    snippet = "<script>window.__mwToken=%s;</script>" % json.dumps(SESSION_TOKEN)
    if "</head>" in html:
        return html.replace("</head>", snippet + "</head>", 1)
    return snippet + html


def request_verdict(method, path, headers, ip):
    """请求准入判断。放行返回 None，否则返回 (状态码, 响应体, 额外响应头)。"""
    ua = (headers.get("User-Agent") or "").lower()
    for sig in CRAWLER_UA:
        if sig in ua:
            return (403, {"error": "拒绝非浏览器客户端访问（命中爬虫 / 抓包工具特征）",
                          "code": "ua_blocked"}, {})

    write = method not in ("GET", "HEAD", "OPTIONS")
    ok, retry = _allow(ip, "write" if write else "read",
                       _WRITE_MAX if write else _READ_MAX)
    if not ok:
        return (429, {"error": "请求过于频繁，请稍后再试", "code": "rate_limited"},
                {"Retry-After": str(retry)})

    if write and IS_PACKAGED and (path or "").startswith("/api/"):
        token = headers.get(TOKEN_HEADER) or ""
        if not token or not secrets.compare_digest(token, SESSION_TOKEN):
            return (403, {"error": "缺少有效会话令牌，请从墨写客户端界面内操作",
                          "code": "token_required"}, {})

    origin = headers.get("Origin") or ""
    if write and origin:
        host = (headers.get("Host") or "").lower()
        try:
            same = urlsplit(origin).netloc.lower() == host
        except ValueError:
            same = False
        if not same:
            return (403, {"error": "跨站请求已被拒绝", "code": "bad_origin"}, {})
    return None
