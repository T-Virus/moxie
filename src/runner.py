# -*- coding: utf-8 -*-
"""
任务执行器（手机端：进程内执行）
================================

桌面版把拆解 / 改编 / 扩写 / 图谱跑成独立 Python 子进程，日志经管道回传。
手机上（Chaquopy 内嵌 Python）没有可用的 python 可执行文件，subprocess 起不来，
所以同一套 argv 改为在后台线程里直接调用模块的 main()，并把 stdout/stderr
接到任务日志上。

对外只暴露 run_module()；桌面端仍走 subprocess（见 webapp.spawn）。
"""

import importlib
import io
import os
import sys
import threading
import traceback

# 由 android_entry.py 在导入 webapp 之前设置
IN_PROCESS = bool(os.environ.get("MOBIT_ANDROID"))

# 进程内执行时共享 sys.argv / sys.stdout，多个任务必须串行
_LOCK = threading.RLock()


class _LineWriter(io.TextIOBase):
    """把模块的 print 按行转给回调（保留未换行的尾巴，flush 时补发）。

    只有「执行任务的那个线程」的输出才进任务日志；HTTP 服务等其他线程的
    print 原样写回终端，避免不同任务的日志互相串台。
    """

    def __init__(self, sink, passthrough=None):
        self.sink = sink
        self.passthrough = passthrough
        self.buf = ""
        self.owner = threading.current_thread()

    def write(self, s):
        if threading.current_thread() is not self.owner:
            if self.passthrough is not None:
                try:
                    return self.passthrough.write(s)
                except Exception:
                    pass
            return len(s)
        if not isinstance(s, str):
            s = str(s)
        self.buf += s
        while "\n" in self.buf:
            line, self.buf = self.buf.split("\n", 1)
            self.sink(line)
        return len(s)

    def flush(self):
        if threading.current_thread() is not self.owner:
            if self.passthrough is not None:
                try:
                    self.passthrough.flush()
                except Exception:
                    pass
            return
        if self.buf:
            line, self.buf = self.buf, ""
            self.sink(line)

    def isatty(self):
        return False

    @property
    def encoding(self):
        return "utf-8"

    def writable(self):
        return True


def run_module(module, argv, env=None, on_line=None):
    """在当前进程执行 module.main()，返回退出码。"""
    argv = [str(a) for a in (argv or [])]
    with _LOCK:
        old_argv, old_out, old_err = sys.argv, sys.stdout, sys.stderr
        old_env = {}

        def default_sink(line):
            # 必须是「原本的 stdout」而不是 print：此时 sys.stdout 已被替换成
            # 本函数的 writer，再 print 会写回自己造成无限递归。
            try:
                if old_out is not None:
                    old_out.write(line + "\n")
                    old_out.flush()
            except Exception:
                pass

        sink = on_line or default_sink
        out_writer = _LineWriter(sink, old_out)
        err_writer = _LineWriter(sink, old_err)
        try:
            if env:
                for k, v in env.items():
                    old_env[k] = os.environ.get(k)
                    os.environ[k] = "" if v is None else str(v)
            sys.argv = [module] + argv
            sys.stdout = out_writer
            sys.stderr = err_writer
            try:
                mod = importlib.import_module(module)
                mod.main()
                code = 0
            except SystemExit as e:
                if isinstance(e.code, str):
                    out_writer.sink(e.code)
                    code = 1
                else:
                    code = int(e.code or 0)
            except KeyboardInterrupt:
                # 用户点「停止」：不计为崩溃，也不打印 traceback
                code = 130
            except BaseException:
                traceback.print_exc()
                code = 1
            finally:
                # 进程内「停止」通过 _inproc_line 抛 KeyboardInterrupt 中断，
                # flush 可能把残留缓冲再次喂给 sink 而重抛；这里吞掉，
                # 避免退出码被改写成 1 并打印误导性 traceback（code 已在上面记为 130）。
                try:
                    out_writer.flush()
                    err_writer.flush()
                except KeyboardInterrupt:
                    pass
            return code
        finally:
            sys.argv, sys.stdout, sys.stderr = old_argv, old_out, old_err
            for k, v in old_env.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v
