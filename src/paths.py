# -*- coding: utf-8 -*-
"""
项目路径唯一来源
================
所有模块从这里取路径，避免各脚本各拼一套导致不一致。

目录约定：
    config/   工作流配置 workflow.json（只读：预算参数与章节质检要求）
    input/    源素材（全本 txt / 大纲 md，由素材页上传或手动放入）
    data/     拆解产出（decomposed.json / chapters.json，页面编辑的数据源）
    output/   历史生成批次（每批一个子目录，产出页只读浏览）
    web/      控制台前端
    src/      全部 Python 代码
"""

import os
import sys

FROZEN = bool(getattr(sys, "frozen", False) or "__compiled__" in globals())

SRC_DIR = os.path.dirname(os.path.abspath(__file__))
MOBILE_ROOT = os.environ.get("MOBIT_ROOT", "").strip()
APP_ROOT = os.environ.get("MOBIT_APP_ROOT", "").strip()
if MOBILE_ROOT:
    # 手机端：代码在 APK 的 Python 资源目录（只读），可写数据放在 App 私有目录
    ROOT = MOBILE_ROOT
    WEB_DIR = os.path.join(ROOT, "web")
    BUNDLED_CONFIG_DIR = os.path.join(ROOT, "config")
elif FROZEN:
    # 打包后：可写数据目录（input/data/output/config）放 exe 同级，
    # 前端页面与默认配置从只读的包内目录加载。
    # PyInstaller：sys.executable 与 argv[0] 都指向原始 exe，包内目录是 _MEIPASS；
    # Nuitka onefile：sys.executable 指向临时解包目录里的 python.exe，
    # 原始 exe 只在 argv[0]，而 __file__ 落在临时解包目录（数据文件也在那里）。
    # 子进程（拆解 / 改编）由主进程用 sys.executable 拉起，此时 argv[0] 也是临时路径，
    # 所以主进程把真正的 exe 目录写进 MOBIT_APP_ROOT，由子进程继承。
    ROOT = APP_ROOT or os.path.dirname(os.path.abspath(sys.argv[0] or sys.executable))
    os.environ.setdefault("MOBIT_APP_ROOT", ROOT)
    BUNDLE_DIR = getattr(sys, "_MEIPASS", None) or SRC_DIR
    WEB_DIR = os.path.join(BUNDLE_DIR, "web")
    BUNDLED_CONFIG_DIR = os.path.join(BUNDLE_DIR, "config")
else:
    ROOT = os.path.dirname(SRC_DIR)
    WEB_DIR = os.path.join(ROOT, "web")
    BUNDLED_CONFIG_DIR = None

CONFIG_DIR = os.path.join(ROOT, "config")
INPUT_DIR = os.path.join(ROOT, "input")
DATA_DIR = os.path.join(ROOT, "data")
OUTPUT_DIR = os.path.join(ROOT, "output")

WORKFLOW = os.path.join(CONFIG_DIR, "workflow.json")
CHAPTERS = os.path.join(DATA_DIR, "chapters.json")       # 旧版单书路径（仅供迁移兼容）
DECOMPOSED = os.path.join(DATA_DIR, "decomposed.json")   # 旧版单书路径（仅供迁移兼容）


def book_dir(name):
    """某本书的产出目录 data/<书名>/。"""
    return os.path.join(DATA_DIR, name)


def book_chapters(name):
    return os.path.join(DATA_DIR, name, "chapters.json")


def book_decomposed(name):
    return os.path.join(DATA_DIR, name, "decomposed.json")


def ensure_dirs():
    """确保运行所需目录存在；打包首启时把内置默认 workflow.json 播种到 exe 同级 config/。"""
    for d in (INPUT_DIR, DATA_DIR, OUTPUT_DIR):
        os.makedirs(d, exist_ok=True)
    if not os.path.isfile(WORKFLOW) and BUNDLED_CONFIG_DIR:
        src = os.path.join(BUNDLED_CONFIG_DIR, "workflow.json")
        if os.path.isfile(src):
            os.makedirs(CONFIG_DIR, exist_ok=True)
            import shutil
            shutil.copyfile(src, WORKFLOW)


def resolve(path):
    """相对路径按项目根解析；绝对路径原样返回。"""
    if not path:
        return path
    return path if os.path.isabs(path) else os.path.join(ROOT, path)
