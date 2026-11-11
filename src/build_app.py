# -*- coding: utf-8 -*-
"""
「墨写」Windows / Android 客户端全流程打包（被 build_exe.bat 调用，也可单独执行）
================================================================================
一条命令跑完全部环节，不需要分步执行：

    python src/build_app.py                    # 默认：Windows exe + 安卓 APK 一起打
    python src/build_app.py --target win       # 只打 Windows exe
    python src/build_app.py --target android   # 只打安卓 APK
    python src/build_app.py --target all       # 同默认：两个平台都打
    python src/build_app.py --skip-web         # 只改了 Python 时跳过前端构建（web/dist 必须已存在）
    python src/build_app.py --force-web        # 强制重新构建前端（忽略新鲜度检测）
    python src/build_app.py --target android --android-rebuild   # 复用安卓工具链快速重打
    python src/build_app.py --target win --packager pyinstaller  # 跳过 Nuitka，直接用 PyInstaller

两个平台共用同一份前端产物 web/dist（安卓包由 prepare_android.py 复制进 assets/www），
所以前端只构建一次。安卓工具链（JDK / SDK / Gradle / 构建用 Python）由
mobile/build_apk.py 首次运行时自动下载。

Windows 客户端优先用 Nuitka 原生编译（需要 MSVC：VS Build Tools 的 C++ 工作负载），
产物是机器码，包里没有可反编译的 Python 字节码；Nuitka 失败（例如杀软占用刚生成的
DLL 导致资源写入被拒）时自动回退 PyInstaller，保证始终能出包。安卓端仍由 Chaquopy 打包。

前端新鲜度检测：web/src、web/assets、vite 配置、package.json 有任一文件比
web/dist/index.html 新，就自动重跑 npm build——杜绝「代码新、界面旧」的包。
打包逻辑放这里而不是写在 .bat 里：批处理的 ^ 续行 / 代码页编码太脆弱，
Python 源码统一 UTF-8，参数用列表传递，不存在转义与乱码问题。

产物：dist/墨写.exe、mobile/dist/墨写-手机端-v*.apk
"""

import argparse
import glob
import os
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXE = os.path.join(ROOT, "dist", "墨写.exe")
# Nuitka 的中间产物与最终 exe 放系统临时目录：
#   1) 不污染 dist/（dist 只留可交付的 exe 与用户数据）；
#   2) 避开项目目录被同步盘 / 杀软目录级钩子盯上的问题。
BUILD_ROOT = os.path.join(tempfile.gettempdir(), "mowrite-nuitka")
APK_SCRIPT = os.path.join(ROOT, "mobile", "build_apk.py")
APK_DIR = os.path.join(ROOT, "mobile", "dist")

# 子进程入口（desktop_app --xxx-child）用 importlib 动态导入任务脚本，
# 静态分析看不到这些 import。以前只手动列了 decompose / adapt，
# 结果「生成图谱」在 exe 里报 ModuleNotFoundError: storymap。
# 这里直接收集 src 下全部本地模块，新增脚本不必再记得改打包参数。
_SRC = os.path.join(ROOT, "src")
_SKIP = {"build_app", "desktop_app", "selftest"}   # 打包脚本本身与开发自检不进包
LOCAL_MODULES = sorted(
    os.path.splitext(f)[0] for f in os.listdir(_SRC)
    if f.endswith(".py") and not f.startswith("_")
    and os.path.splitext(f)[0] not in _SKIP
)


def _pkg_dir(name):
    """取已安装包的目录（打包参数里要显式带上包的运行期 DLL / JS 资源）。"""
    try:
        mod = __import__(name)
    except ImportError:
        return ""
    return os.path.dirname(os.path.abspath(mod.__file__))


# Nuitka 原生编译参数：Python 先编成 C 再编成机器码，产物里没有可反编译的 .pyc。
# --include-data-dir 只带 web/dist，不会把 node_modules 打进包里。
def _nuitka_args():
    args = [
        sys.executable, "-m", "nuitka",
        "--onefile",
        "--assume-yes-for-downloads",
        # 3.13+ 的 CPython 是 MSVC 构建的，不能再用 MinGW，必须走 MSVC
        "--msvc=latest",
        "--windows-console-mode=disable",
        "--windows-icon-from-ico=" + os.path.join("icon", "icon.ico"),
        "--output-dir=" + BUILD_ROOT,
        "--output-filename=墨写.exe",
        # 去掉文档字符串：减少从产物里能直接读出的实现说明
        "--python-flag=no_docstrings",
        "--include-data-dir=" + os.path.join("web", "dist") + "=web",
        "--include-data-file=" + os.path.join("config", "workflow.json")
        + "=config/workflow.json",
        "--jobs=%d" % min(8, os.cpu_count() or 2),
    ]
    # pywebview 在 Windows 上走 pythonnet + WebView2：Nuitka 的 pywebview 插件只负责
    # 平台模块，运行时 DLL 与 JS 资源属于数据文件，必须显式带上，否则窗口起不来。
    webview_dir = _pkg_dir("webview")
    pythonnet_dir = _pkg_dir("pythonnet")
    clr_loader_dir = _pkg_dir("clr_loader")
    for name in ("pythonnet", "clr_loader", "Crypto"):
        args.append("--include-package=" + name)
    args.append("--include-module=clr")
    if webview_dir:
        args.append("--include-data-dir=" + os.path.join(webview_dir, "lib") + "=webview/lib")
        args.append("--include-data-dir=" + os.path.join(webview_dir, "js") + "=webview/js")
    if pythonnet_dir:
        args.append("--include-data-dir=" + os.path.join(pythonnet_dir, "runtime")
                    + "=pythonnet/runtime")
    if clr_loader_dir:
        args.append("--include-data-dir=" + os.path.join(clr_loader_dir, "ffi", "dlls")
                    + "=clr_loader/ffi/dlls")
    for name in LOCAL_MODULES:
        args.append("--include-module=" + name)
    args.append(os.path.join("src", "desktop_app.py"))
    return args


# ---------------------------------------------------------------- ① 前端构建
def _web_inputs():
    """影响前端产物的全部输入文件（源码 / 静态资源 / 构建配置）。"""
    for base in (os.path.join("web", "src"), os.path.join("web", "assets")):
        for dp, _, fns in os.walk(base):
            for fn in fns:
                yield os.path.join(dp, fn)
    for f in ("index.html", "package.json", "vite.config.ts", "vite.config.js",
              "tsconfig.json", "tsconfig.app.json"):
        p = os.path.join("web", f)
        if os.path.isfile(p):
            yield p


def build_web(force=False):
    """构建前端产物。返回 0 成功（或无需构建）；非 0 失败。"""
    dist_index = os.path.join("web", "dist", "index.html")
    newest_src = max((os.path.getmtime(p) for p in _web_inputs()), default=0)
    dist_t = os.path.getmtime(dist_index) if os.path.isfile(dist_index) else 0
    if not force and dist_t >= newest_src:
        print("[前端] 产物已是最新（web/dist 不旧于 web/src），跳过 npm build")
        return 0
    npm = shutil.which("npm") or shutil.which("npm.cmd")
    if not npm:
        print("[x] 未找到 npm：请先安装 Node.js，或手动在 web/ 下执行 npm run build 后用 --skip-web 打包")
        return 1
    if not os.path.isdir(os.path.join("web", "node_modules")):
        print("[前端] 首次构建：安装前端依赖（npm install）...")
        if subprocess.call([npm, "install"], cwd="web") != 0:
            print("[x] npm install 失败")
            return 1
    print("[前端] 构建前端（npm run build）...")
    if subprocess.call([npm, "run", "build"], cwd="web") != 0:
        print("[x] 前端构建失败")
        return 1
    if not os.path.isfile(dist_index):
        print("[x] 前端构建结束但 web/dist/index.html 不存在")
        return 1
    return 0


def _audit_web_output():
    """产物加固校验：不能带 sourcemap，业务包必须经过混淆。返回 True 表示通过。"""
    if not os.path.isdir(os.path.join("web", "dist")):
        print("[x] web/dist 不存在")
        return False
    maps = glob.glob(os.path.join("web", "dist", "**", "*.map"), recursive=True)
    if maps:
        print(f"[x] web/dist 里仍有 {len(maps)} 个 sourcemap：等于直接附带源码，请检查 vite 配置")
        return False
    sources = (glob.glob(os.path.join("web", "dist", "**", "*.vue"), recursive=True)
               + glob.glob(os.path.join("web", "dist", "**", "*.ts"), recursive=True))
    if sources:
        print(f"[x] web/dist 里混入了源码文件（{sources[0]}），请检查构建配置")
        return False
    scripts = glob.glob(os.path.join("web", "dist", "assets", "*.js"))
    if not scripts:
        print("[x] web/dist/assets 下没有 JS 产物")
        return False
    # 混淆器用十六进制标识符（_0x...）：业务包至少应命中一次
    hit = False
    for path in scripts:
        try:
            with open(path, encoding="utf-8", errors="ignore") as f:
                if "_0x" in f.read(200000):
                    hit = True
                    break
        except OSError:
            continue
    if not hit:
        print("[x] 业务包未检出混淆特征：请确认 web/ 已 npm install 且 vite 混淆插件生效")
        return False
    print("[前端] 加固校验通过：无 sourcemap，业务包已混淆")
    return True


# ---------------------------------------------------------------- ② Windows exe
def _exe_locked():
    if not os.path.isfile(EXE):
        return False
    try:
        with open(EXE, "ab"):
            return False            # 能打开说明没被运行中的进程锁定
    except OSError:
        return True


def _build_with_nuitka():
    """Nuitka 原生编译：机器码，包里没有可反编译的字节码。返回 0 成功。"""
    try:
        import nuitka  # noqa: F401
    except ImportError:
        print("[x] 未安装 Nuitka。请先执行：pip install nuitka")
        return 1
    print("[Windows] Nuitka 原生编译（先转 C 再编机器码，耗时明显长于 PyInstaller）...")
    shutil.rmtree(BUILD_ROOT, ignore_errors=True)
    rc = subprocess.call(_nuitka_args())
    built = os.path.join(BUILD_ROOT, "墨写.exe")
    print()
    if rc == 0 and os.path.isfile(built):
        os.makedirs(os.path.dirname(EXE), exist_ok=True)
        shutil.copy2(built, EXE)
        shutil.rmtree(BUILD_ROOT, ignore_errors=True)
        mb = os.path.getsize(EXE) / 1024 / 1024
        print(f"[OK] Windows 客户端（Nuitka 原生）：{EXE}（{mb:.0f} MB）")
        return 0
    print("[x] Nuitka 编译失败，请检查上方 MSVC / 资源写入输出。")
    print("    常见原因 1：未安装 VS Build Tools 的 C++ 工作负载（MSVC + Windows SDK）。")
    print("    常见原因 2：杀软（QQ 电脑管家 / 360 / Defender）扫描刚生成的 DLL，")
    print("                导致第二次 UpdateResource 被拒（error 22 / access denied）。")
    print("                退出实时防护或把 %TEMP%\\mowrite-nuitka 加入信任区后重试。")
    return 1


def _pyinstaller_args():
    work = os.path.join(tempfile.gettempdir(), "mowrite-pyinstaller")
    # spec 文件在临时目录，PyInstaller 会把相对路径按 spec 所在目录解析：
    # 所有输入路径都用绝对路径，避免找不到 web/dist。
    args = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm", "--clean", "--onefile", "--windowed",
        "--name", "墨写",
        "--icon", os.path.join(ROOT, "icon", "icon.ico"),
        # 字节码优化级别 2：去掉文档字符串与 assert
        "--optimize", "2",
        "--add-data", os.path.join(ROOT, "web", "dist") + os.pathsep + "web",
        "--add-data", os.path.join(ROOT, "config", "workflow.json")
        + os.pathsep + "config",
        "--collect-all", "webview",
        # 中间产物放临时目录，dist/ 只留可交付的 exe
        "--distpath", os.path.join(ROOT, "dist"),
        "--workpath", work,
        "--specpath", work,
    ]
    for name in LOCAL_MODULES:
        args += ["--hidden-import", name]
    args.append(os.path.join(ROOT, "src", "desktop_app.py"))
    return args


def _build_with_pyinstaller():
    """PyInstaller 兜底：字节码级防护（无源码、去文档字符串）+ 前端混淆。"""
    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        print("[x] 未安装 PyInstaller。请先执行：pip install pyinstaller")
        return 1
    print("[Windows] PyInstaller 打包（兜底方案；Nuitka 受杀软干扰时使用）...")
    rc = subprocess.call(_pyinstaller_args())
    print()
    if rc == 0 and os.path.isfile(EXE):
        mb = os.path.getsize(EXE) / 1024 / 1024
        print(f"[OK] Windows 客户端（PyInstaller）：{EXE}（{mb:.0f} MB）")
        return 0
    print("[x] PyInstaller 打包失败，请检查上方输出。")
    return 1


def build_exe(packager="auto"):
    """打包 Windows 客户端。auto = 先试 Nuitka，失败回退 PyInstaller。"""
    if _exe_locked():
        print("[x] 检测到 dist/墨写.exe 正在运行，请先关闭客户端窗口再打包。")
        return 1
    if packager == "pyinstaller":
        return _build_with_pyinstaller()
    rc = _build_with_nuitka()
    if rc == 0 or packager == "nuitka":
        return rc
    print()
    print("[!] Nuitka 未产出 exe，自动回退 PyInstaller（前端混淆与运行期防护不受影响）。")
    return _build_with_pyinstaller()


# ---------------------------------------------------------------- ③ Android APK
def build_apk(rebuild=False):
    """调用 mobile/build_apk.py 打安卓 APK。返回 0 成功。"""
    if not os.path.isfile(APK_SCRIPT):
        print(f"[x] 未找到安卓打包脚本：{APK_SCRIPT}")
        return 1
    before = set(glob.glob(os.path.join(APK_DIR, "*.apk")))
    cmd = [sys.executable, APK_SCRIPT] + (["--rebuild"] if rebuild else [])
    print("[*] 安卓打包（首次会下载 JDK / Android SDK / Gradle / 构建用 Python，耗时较长）...")
    rc = subprocess.call(cmd)
    print()
    if rc != 0:
        print("[x] APK 打包失败，请检查上方 Gradle / Chaquopy 输出。")
        return 1
    apks = sorted(glob.glob(os.path.join(APK_DIR, "*.apk")),
                  key=os.path.getmtime, reverse=True)
    if not apks:
        print(f"[x] 打包结束但 {APK_DIR} 下没有找到 .apk")
        return 1
    top = apks[0]
    mb = os.path.getsize(top) / 1024 / 1024
    print(f"[OK] 安卓客户端：{top}（{mb:.1f} MB）")
    if before and top in before:
        print("     注意：本次产物与上次同名，已覆盖旧的 APK。")
    return 0


# ---------------------------------------------------------------- 主流程
def main():
    ap = argparse.ArgumentParser(
        description="「墨写」客户端全流程打包：前端构建 → exe / APK 打包 → 校验")
    ap.add_argument("--target", choices=("win", "android", "all"), default="all",
                    help="打包目标：all = Windows exe + 安卓 APK（默认）/ win = 只打 exe / android = 只打 APK")
    ap.add_argument("--skip-web", action="store_true",
                    help="跳过前端构建（只改了 Python 时用；web/dist 必须已存在）")
    ap.add_argument("--force-web", action="store_true",
                    help="忽略新鲜度检测，强制重新构建前端")
    ap.add_argument("--android-rebuild", action="store_true",
                    help="安卓复用已装好的工具链（跳过 SDK / Python / Gradle 检查）")
    ap.add_argument("--packager", choices=("auto", "nuitka", "pyinstaller"), default="auto",
                    help="Windows 打包方式：auto = 先 Nuitka，失败回退 PyInstaller（默认）")
    args = ap.parse_args()
    os.chdir(ROOT)

    want_win = args.target in ("win", "all")
    want_apk = args.target in ("android", "all")
    total = 1 + int(want_win) + int(want_apk) + 1      # 前端 + 各平台 + 汇总
    step = 0

    def head(text):
        nonlocal step
        step += 1
        print(f"[{step}/{total}] {text}")

    # ① 前端（两个平台共用同一份产物）
    if args.skip_web:
        if not os.path.isfile(os.path.join("web", "dist", "index.html")):
            print("[x] web/dist 不存在，无法跳过前端构建；去掉 --skip-web 重试")
            return 1
        head("按参数跳过前端构建（--skip-web）")
    else:
        head("构建前端" if not args.force_web else "构建前端（--force-web）")
        rc = build_web(force=args.force_web)
        if rc:
            return rc
    # 无论是否跳过构建，产物都必须过加固校验（sourcemap / 未混淆直接失败）
    if not _audit_web_output():
        return 1

    ok = True
    if want_win:
        head("打包 Windows 客户端")
        ok = build_exe(args.packager) == 0 and ok
    if want_apk:
        head("打包安卓客户端")
        ok = build_apk(rebuild=args.android_rebuild) == 0 and ok

    head("打包结果")
    if ok:
        print("全部目标打包成功。")
    else:
        print("有目标打包失败，请查看上方日志。")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
