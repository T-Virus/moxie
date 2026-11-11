# -*- coding: utf-8 -*-
"""
墨写 · Windows 桌面客户端入口
==================================
打包后的单一 exe 同时承担两个角色：

  · 主进程（双击启动）：本机起 HTTP 服务 + pywebview 原生窗口
  · 子进程（--decompose-child）：跑拆解任务，日志经 stdout 管道回传主进程

开发模式仍用 `python webapp.py`（浏览器访问），本文件只在打包形态使用。
"""

import os
import sys


def _ensure_utf8_stream(name, fd):
    """windowed 打包下 sys.stdout/stderr 可能按系统 ANSI（GBK）初始化；
    父进程通过管道按 UTF-8 读日志，这里统一强制接管 fd 为 UTF-8 行缓冲流。"""
    stream = getattr(sys, name, None)
    if stream is not None and (getattr(stream, "encoding", "") or "").replace("-", "").lower() == "utf8":
        return
    try:
        if stream is not None:
            try:
                stream.flush()
            except Exception:
                pass
        import io
        setattr(sys, name, io.TextIOWrapper(
            os.fdopen(os.dup(fd), "wb"),
            encoding="utf-8", errors="replace", line_buffering=True))
    except Exception:
        pass


def run_child(module):
    """--decompose-child / --adapt-child：把剩余参数原样交给对应任务脚本的 main()。"""
    # 父进程已把 fd 1/2 接到管道，dup 后重新包成 UTF-8 流即可回传日志
    _ensure_utf8_stream("stdout", 1)
    _ensure_utf8_stream("stderr", 2)
    sys.argv = [sys.argv[0]] + sys.argv[2:]
    import importlib
    import traceback
    try:
        mod = importlib.import_module(module)
        mod.main()
    except SystemExit:
        raise                       # 任务脚本自己 sys.exit(N) 时保留退出码
    except BaseException:
        # windowed 打包下未捕获异常会弹系统错误框并挂住进程：父进程读不到退出码，
        # 界面上的任务就会永远停在「运行中」。改成打印 traceback 后正常退出。
        traceback.print_exc()
        sys.exit(1)


def _logical_work_area():
    """当前主显示器可用区域的逻辑像素（已剔除任务栏）。
    兼容两种进程状态：DPI 感知时 API 返回物理像素，按系统 DPI 折算；
    非感知时系统已做虚拟化，返回值本身就是逻辑像素。
    1.5 倍缩放下的 1920×1080 会得到约 1280×688，正好用来算窗口上限。"""
    try:
        import ctypes
        from ctypes import wintypes
        u = ctypes.windll.user32
        r = wintypes.RECT()
        u.SystemParametersInfoW(0x0030, 0, ctypes.byref(r), 0)
        if r.right <= r.left or r.bottom <= r.top:
            return 1920, 1032
        scale = 1.0
        try:
            aware = ctypes.c_int(0)
            ctypes.windll.shcore.GetProcessDpiAwareness(None, ctypes.byref(aware))
            if aware.value:                      # 1/2 = 系统 / 每显示器 DPI 感知
                dpi = u.GetDpiForSystem() or 96
                scale = dpi / 96.0
        except Exception:
            pass
        return int((r.right - r.left) / scale), int((r.bottom - r.top) / scale)
    except Exception:
        return 1920, 1032


def run_desktop():
    import threading
    import webbrowser
    import urllib.request

    import guard
    import webview
    import webapp
    from http.server import ThreadingHTTPServer
    from paths import ensure_dirs

    guard.enforce()
    ensure_dirs()
    webapp.migrate_legacy_data()

    # 监听地址可能被 MOBIT_HOST 改成 0.0.0.0（手机同 Wi-Fi 访问）；窗口自身仍连回环地址
    _ui_host = "127.0.0.1" if webapp.HOST in ("0.0.0.0", "", "::") else webapp.HOST
    url = f"http://{_ui_host}:{webapp.PORT}"
    srv = None
    try:
        class Server(ThreadingHTTPServer):
            allow_reuse_address = False   # 同 webapp.main：宁可明确报错，不要旧进程静默接管
            daemon_threads = True

        srv = Server((webapp.HOST, webapp.PORT), webapp.Handler)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        # 与主进程 webapp.main() 对齐：恢复上次会话任务，并开启定期落盘线程，
        # 否则打包后的 exe 里「重启不丢任务 / 一键恢复」永远不工作。
        webapp._restore_tasks()
        threading.Thread(target=webapp._tasks_persist_loop, daemon=True).start()
    except OSError:
        # 端口被占：若已有本程序实例在服务，就直接开窗口连它；否则提示后退出
        # 注意：请求要带浏览器 UA，控制台的爬虫特征拦截会把 Python 默认 UA 挡在门外
        try:
            probe = urllib.request.Request(
                url + "/api/books",
                headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                                       "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"})
            with urllib.request.urlopen(probe, timeout=3):
                pass
        except Exception:
            import ctypes
            ctypes.windll.user32.MessageBoxW(
                0,
                f"端口 {webapp.PORT} 已被其它程序占用，无法启动「墨写」。\n"
                "请关闭占用该端口的程序（或结束另一个墨写进程）后重试。",
                "墨写", 0x10)
            sys.exit(1)

    # 最小宽度 1280：1920×1080@150% 的逻辑可用宽度正好约 1280，保证窗口一定放得下。
    # 屏幕更宽时默认开 1680×960，但最小宽度仍锁 1280，可自由缩到 1280 验证布局。
    avail_w, avail_h = _logical_work_area()
    min_w = min(1280, max(360, avail_w - 20))
    win_w = min(1680, max(min_w, avail_w - 40))
    win_h = min(960, max(600, avail_h - 60))
    webview.create_window("墨写", url, width=win_w, height=win_h,
                          min_size=(min_w, min(win_h, 780)))
    try:
        webview.start()
    except Exception:
        # WebView2 等原生窗口依赖不可用时，退回系统浏览器，服务保持运行
        webbrowser.open(url)
        try:
            threading.Event().wait()
        except KeyboardInterrupt:
            pass
    finally:
        if srv is not None:
            srv.shutdown()


def main():
    src = os.path.dirname(os.path.abspath(__file__))
    if src not in sys.path:
        sys.path.insert(0, src)
    if "--decompose-child" in sys.argv:
        run_child("decompose")
    elif "--adapt-child" in sys.argv:
        run_child("adapt")
    elif "--expand-child" in sys.argv:
        run_child("expand")
    elif "--storymap-child" in sys.argv:
        run_child("storymap")
    else:
        run_desktop()


if __name__ == "__main__":
    main()
