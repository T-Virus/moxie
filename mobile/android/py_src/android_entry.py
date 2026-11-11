# -*- coding: utf-8 -*-
"""Android 启动入口：在 App 进程里拉起本机 HTTP 服务。

手机端不连接电脑：Python（Chaquopy 内嵌）直接跑在 App 里，
WebView 只是这个本机服务的界面壳，所以所有功能（拆解 / 改编 / 正文 / 审查 /
封面 / 导出）都在这台手机上完成。
"""

import os
import socket
import threading
import traceback

_state = {"error": "", "started": False}
_lock = threading.Lock()


def _port_open(port, timeout=0.8):
    """端口上是否真的有人监听：上次的服务线程没了但标记还在时，靠它识别并重来。"""
    try:
        with socket.create_connection(("127.0.0.1", int(port)), timeout=timeout):
            return True
    except OSError:
        return False


def _prepare_env(root, port):
    os.environ["MOBIT_ROOT"] = str(root)
    os.environ["MOBIT_ANDROID"] = "1"
    os.environ["MOBIT_HOST"] = "127.0.0.1"
    os.environ["MOBIT_PORT"] = str(port)
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    os.environ.setdefault("PYTHONDONTWRITEBYTECODE", "1")
    # Android 没有 /etc/ssl/certs：显式指定随包的 CA 证书，否则 HTTPS 请求会
    # 报 unable to get local issuer certificate，AI 调用全部失败。
    cert = os.path.join(str(root), "certs", "cacert.pem")
    if os.path.isfile(cert):
        os.environ["SSL_CERT_FILE"] = cert
        os.environ["REQUESTS_CA_BUNDLE"] = cert


def _spawn():
    def run():
        try:
            import webapp
            webapp.main()
        except SystemExit as e:
            _state["error"] = str(e) or "本地引擎已退出"
            print("[server] 退出：", e, flush=True)
        except BaseException:
            _state["error"] = traceback.format_exc()
            traceback.print_exc()
        finally:
            # 服务线程结束（绑端口失败 / 启动报错）后放开标记，
            # 否则重试时 start_server 会误以为「已经在跑」而直接返回。
            with _lock:
                _state["started"] = False

    threading.Thread(target=run, name="mobit-server", daemon=True).start()


def start_server(root, port=8765):
    """设置可写根目录并启动服务线程。

    返回 True = 本次新起了服务线程；False = 已有服务在跑，Java 侧直接复用即可。
    """
    with _lock:
        if _state["started"]:
            if _port_open(port):
                return False
            _state["started"] = False   # 标记残留但端口已没人听：允许重新拉起
        _state["started"] = True
        _state["error"] = ""
    _prepare_env(root, port)
    _spawn()
    return True


def force_restart(root, port=8765):
    """Java 侧等待超时后调用：清掉遗留状态，强制重新拉起一次服务。"""
    with _lock:
        alive = _state["started"] and _port_open(port)
        if alive:
            return False        # 端口上确实有服务，别再抢绑一次
        _state["started"] = False
        _state["error"] = ""
    _prepare_env(root, port)
    with _lock:
        _state["started"] = True
    _spawn()
    return True


def last_error():
    return _state.get("error") or ""
