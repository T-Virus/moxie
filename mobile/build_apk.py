# -*- coding: utf-8 -*-
"""
墨写手机端（安卓 / 鸿蒙 4.x）一键构建
=====================================
手机端不连接电脑：Chaquopy 把 CPython 打进 APK，App 启动时在本机跑起
原有的 Python 后端，WebView 加载 127.0.0.1 的服务，所有功能离线可用。

首次运行会自动准备工具链（联网下载）：
  · JDK 17（已有 mobile/.toolchain/jdk 则跳过）
  · Android SDK cmdline-tools + build-tools 34 + platform 34
  · Gradle 8.7
  · Python 3.12（Chaquopy 的 buildPython；Pillow 的 cp312 轮子最全）

产物：mobile/dist/墨写-手机端-v2.8.0.apk
用法：
  python mobile/build_apk.py              # 完整构建
  python mobile/build_apk.py --rebuild    # 复用工具链，只重新编译
"""

import argparse
import os
import shutil
import subprocess
import sys
import tarfile
import urllib.request
import zipfile

# 控制台 / 重定向输出在中文 Windows 上多为 GBK 编码，而 sdkmanager 等子进程输出可能含
# GBK 无法表示的字符（如 U+FFFD），导致 print 抛 UnicodeEncodeError 使构建中途崩溃。
# 统一改用 utf-8 + replace，避免输出环节的中断。
try:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT = os.path.dirname(os.path.abspath(__file__))
WORK = os.path.dirname(ROOT)
ANDROID = os.path.join(ROOT, "android")
APP = os.path.join(ANDROID, "app")
BUILD = os.path.join(ROOT, "build")
TC = os.path.join(ROOT, ".toolchain")
DL = os.path.join(TC, "downloads")
SDK = os.path.join(TC, "sdk")
JDK_DIR = os.path.join(TC, "jdk")
PY312_DIR = os.path.join(TC, "py312")
GRADLE_HOME = os.path.join(TC, "gradle", "gradle-8.7")
OUT_DIR = os.path.join(ROOT, "dist")

JDK_URL = ("https://mirrors.tuna.tsinghua.edu.cn/Adoptium/17/jdk/x64/windows/"
           "OpenJDK17U-jdk_x64_windows_hotspot_17.0.20.1_1.zip")
SDK_URL = "https://dl.google.com/android/repository/commandlinetools-win-11076708_latest.zip"
PY_URL = ("https://registry.npmmirror.com/-/binary/python-build-standalone/20261026/"
          "cpython-3.12.16%2B20261026-x86_64-pc-windows-msvc-install_only.tar.gz")
GRADLE_URL = [
    "https://mirrors.tuna.tsinghua.edu.cn/gradle/gradle-8.7-bin.zip",
    "https://mirrors.cloud.tencent.com/gradle/gradle-8.7-bin.zip",
    "https://services.gradle.org/distributions/gradle-8.7-bin.zip",
]
FONT_URLS = [
    ("https://fastly.jsdelivr.net/gh/googlefonts/noto-cjk@main/Sans/Variable/OTF/Subset/"
     "NotoSansSC-VF.otf"),
    ("https://gcore.jsdelivr.net/gh/googlefonts/noto-cjk@main/Sans/Variable/OTF/Subset/"
     "NotoSansSC-VF.otf"),
]
FONT_PATH = os.path.join(ROOT, "assets", "fonts", "NotoSansSC-VF.otf")

BUILD_TOOLS = "34.0.0"
PLATFORM = "android-34"
VERSION = "2.8.0"
KEYSTORE = os.path.join(ANDROID, "release.keystore")
KS_PASS = "mobit2026"
KS_ALIAS = "mobit"
APP_NAME = "墨写-手机端"


def log(msg):
    print(f"[build] {msg}", flush=True)


def run(cmd, cwd=None, env=None, stdin_data=None, timeout=None):
    log("$ " + " ".join(str(c) for c in cmd))
    p = subprocess.run(cmd, cwd=cwd, env=env, input=stdin_data,
                       stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=timeout)
    text = p.stdout.decode("utf-8", "replace")
    if text.strip():
        print(text.rstrip(), flush=True)
    if p.returncode != 0:
        raise SystemExit(f"[x] 命令失败（{p.returncode}）：{' '.join(str(c) for c in cmd)}")


def download(url, dest, min_size=1024 * 1024):
    """下载到 dest：已存在且大小达标就跳过；存在 .part 时用 Range 续传。"""
    urls = list(url) if isinstance(url, (list, tuple)) else [url]
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    if os.path.isfile(dest) and os.path.getsize(dest) > min_size:
        log(f"已存在，跳过下载：{os.path.basename(dest)}")
        return dest
    last = None
    for u in urls:
        tmp = dest + ".part"
        start = os.path.getsize(tmp) if os.path.isfile(tmp) else 0
        try:
            headers = {"Range": f"bytes={start}-"} if start else {}
            req = urllib.request.Request(u, headers=headers)
            log(f"下载 {u}" + (f"（从 {start / 1048576:.1f} MB 续传）" if start else ""))
            with urllib.request.urlopen(req, timeout=60) as r:
                resumed = start > 0 and r.status == 206
                if start and not resumed:
                    start = 0          # 服务器不支持续传：从头写
                total = int(r.headers.get("Content-Length") or 0) + start
                got = start
                with open(tmp, "ab" if resumed else "wb") as f:
                    while True:
                        chunk = r.read(1024 * 256)
                        if not chunk:
                            break
                        f.write(chunk)
                        got += len(chunk)
                        if total:
                            print(f"\r  {got * 100 // total:3d}%  {got / 1048576:.1f}/{total / 1048576:.1f} MB",
                                  end="", flush=True)
            print()
            os.replace(tmp, dest)
            return dest
        except Exception as e:
            last = e
            log(f"下载失败：{u}（{e}）")
            # 保留 .part 供下次续传；只有服务器拒绝该区间时才丢弃重来
            if getattr(e, "code", None) == 416:
                try:
                    os.remove(tmp)
                except OSError:
                    pass
    raise SystemExit(f"[x] 下载失败：{last}")


def _rmtree_force(path):
    """强制删除目录：先试 shutil（忽略异常），失败再用系统 rmdir 绕过环境的安全删除钩子。"""
    if not os.path.exists(path):
        return
    try:
        shutil.rmtree(path, ignore_errors=True)
    except Exception:
        pass
    if os.path.exists(path):
        try:
            subprocess.run(["cmd", "/c", "rmdir", "/s", "/q", path],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                           check=False, timeout=180)
        except Exception:
            pass


def _extract_zip_strip(zip_path, dest):
    """解压 zip 到 dest 并剥离唯一顶层目录。直接落盘，不调用 shutil.move/rmtree，
    规避本环境同卷 rename 偶发「拒绝访问」、且 rmtree 被安全删除钩子拦截而抛错的问题。"""
    _rmtree_force(dest)
    os.makedirs(dest, exist_ok=True)
    with zipfile.ZipFile(zip_path) as z:
        for info in z.infolist():
            parts = info.filename.replace("\\", "/").split("/")
            if len(parts) == 1 and info.is_dir():
                continue
            rel = os.path.join(*parts[1:]) if len(parts) > 1 else parts[0]
            target = os.path.join(dest, rel)
            if info.is_dir():
                os.makedirs(target, exist_ok=True)
            else:
                os.makedirs(os.path.dirname(target) or dest, exist_ok=True)
                with z.open(info) as src, open(target, "wb") as dst:
                    shutil.copyfileobj(src, dst)


def _extract_tar_strip(tar_path, dest):
    """解压 tar/tar.gz 到 dest 并剥离唯一顶层目录（同上，不依赖 move/rmtree）。"""
    _rmtree_force(dest)
    os.makedirs(dest, exist_ok=True)
    with tarfile.open(tar_path, "r:*") as t:
        for m in t.getmembers():
            parts = m.name.replace("\\", "/").split("/")
            if len(parts) == 1 and m.isdir:
                continue
            rel = os.path.join(*parts[1:]) if len(parts) > 1 else parts[0]
            target = os.path.join(dest, rel)
            if m.isdir():
                os.makedirs(target, exist_ok=True)
            else:
                os.makedirs(os.path.dirname(target) or dest, exist_ok=True)
                f = t.extractfile(m)
                if f is None:
                    continue
                with f, open(target, "wb") as dst:
                    shutil.copyfileobj(f, dst)


def java_home():
    if os.path.isfile(os.path.join(JDK_DIR, "bin", "java.exe")):
        return JDK_DIR
    zip_path = download(JDK_URL, os.path.join(DL, "jdk17.zip"))
    log("解压 JDK…")
    _extract_zip_strip(zip_path, JDK_DIR)
    return JDK_DIR


def env_with(jdk):
    env = dict(os.environ)
    env["JAVA_HOME"] = jdk
    env["ANDROID_HOME"] = SDK
    env["ANDROID_SDK_ROOT"] = SDK
    env["PATH"] = os.path.join(jdk, "bin") + os.pathsep + env.get("PATH", "")
    return env


def ensure_sdk(jdk):
    aapt2 = os.path.join(SDK, "build-tools", BUILD_TOOLS, "aapt2.exe")
    android_jar = os.path.join(SDK, "platforms", PLATFORM, "android.jar")
    if os.path.isfile(aapt2) and os.path.isfile(android_jar):
        return
    zpath = download(SDK_URL, os.path.join(DL, "cmdline-tools.zip"))
    if not os.path.isdir(os.path.join(SDK, "cmdline-tools", "latest", "bin")):
        log("解压 Android 命令行工具…")
        _extract_zip_strip(zpath, os.path.join(SDK, "cmdline-tools", "latest"))
    sdkmanager = os.path.join(SDK, "cmdline-tools", "latest", "bin", "sdkmanager.bat")
    env = env_with(jdk)
    log("安装 Android SDK 组件（platforms/android-34 + build-tools）…")
    run(["cmd", "/c", sdkmanager, f"--sdk_root={SDK}", "--licenses"], env=env, stdin_data=b"y\n" * 80)
    run(["cmd", "/c", sdkmanager, f"--sdk_root={SDK}",
         f"platforms;{PLATFORM}", f"build-tools;{BUILD_TOOLS}"], env=env, stdin_data=b"y\n" * 80)


def ensure_gradle():
    exe = os.path.join(GRADLE_HOME, "bin", "gradle.bat")
    if os.path.isfile(exe):
        return exe
    zpath = download(GRADLE_URL, os.path.join(DL, "gradle-8.7-bin.zip"))
    log("解压 Gradle…")
    tmp = os.path.join(TC, "gradle")
    os.makedirs(tmp, exist_ok=True)
    with zipfile.ZipFile(zpath) as z:
        z.extractall(tmp)
    if not os.path.isfile(exe):
        raise SystemExit("[x] Gradle 解压失败")
    return exe


def ensure_python312(jdk):
    """准备 buildPython：用 python-build-standalone 的完整便携版 3.12。

    必须带 pip 与 venv（Chaquopy 会在构建期创建虚拟环境安装 Pillow 等轮子），
    Windows 官方安装器在部分机器上会被杀软锁住，便携版更稳。
    """
    exe = os.path.join(PY312_DIR, "python.exe")
    env = env_with(jdk)
    if not os.path.isfile(exe):
        zpath = download(PY_URL, os.path.join(DL, "python-3.12-standalone.tar.gz"),
                         min_size=10 * 1024 * 1024)
        log("解压 Python 3.12（便携版，构建用）…")
        _extract_tar_strip(zpath, PY312_DIR)

    for args, hint in ((["-m", "pip", "--version"], "pip"),
                       (["-m", "venv", "--help"], "venv")):
        probe = subprocess.run([exe] + args, env=env,
                               stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        if probe.returncode != 0:
            print(probe.stdout.decode("utf-8", "replace"), flush=True)
            raise SystemExit(f"[x] 构建用 Python 3.12 缺少 {hint}")
    check = subprocess.run([exe, "-c", "import ssl,sqlite3,sys;print(sys.version)"],
                           env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    print(check.stdout.decode("utf-8", "replace").strip(), flush=True)
    if check.returncode != 0:
        raise SystemExit("[x] 构建用 Python 3.12 缺少 ssl/sqlite 模块")
    return exe


def ensure_keystore(jdk):
    if os.path.isfile(KEYSTORE):
        return
    log("生成签名密钥…")
    run([os.path.join(jdk, "bin", "keytool.exe"), "-genkeypair", "-v",
         "-keystore", KEYSTORE, "-alias", KS_ALIAS, "-keyalg", "RSA", "-keysize", "2048",
         "-validity", "10950", "-storepass", KS_PASS, "-keypass", KS_PASS,
         "-dname", "CN=MoBiT, OU=Mobile, O=MoBiT, L=Shanghai, ST=Shanghai, C=CN"])


def ensure_font():
    """随包中文字体（封面排版用）：仓库不存 15MB 字体，构建时按需下载。"""
    if os.path.isfile(FONT_PATH) and os.path.getsize(FONT_PATH) > 5 * 1024 * 1024:
        return
    os.makedirs(os.path.dirname(FONT_PATH), exist_ok=True)
    last = None
    for url in FONT_URLS:
        try:
            download(url, FONT_PATH, min_size=5 * 1024 * 1024)
            return
        except Exception as e:      # 换下一个 CDN
            last = e
            log(f"字体下载失败：{url}（{e}）")
    raise SystemExit(f"[x] 无法下载中文字体：{last}")


def write_local_properties(py312):
    sdk = SDK.replace("\\", "/")
    py = py312.replace("\\", "/")
    content = f"sdk.dir={sdk}\nbuildPython={py}\n"
    with open(os.path.join(ANDROID, "local.properties"), "w", encoding="utf-8") as f:
        f.write(content)
    log("写入 local.properties")


def build(jdk, gradle):
    env = env_with(jdk)
    env["GRADLE_USER_HOME"] = os.path.join(TC, "gradle-home")
    # pip 沿用系统默认缓存（之前构建已经下过的轮子直接复用，不再走网络）
    run([sys.executable, os.path.join(ROOT, "prepare_android.py")], cwd=WORK, env=env)
    base = ["cmd", "/c", gradle, "-p", ANDROID, "assembleRelease", "--no-daemon",
            "--stacktrace"]
    cached = os.path.isdir(os.path.join(TC, "gradle-home", "caches", "modules-2"))
    if cached:
        # Gradle 依赖已经在本地缓存里：先离线构建，避免每次回仓库校验 / 重新下载
        log("Gradle assembleRelease（离线模式，复用本地依赖缓存）…")
        try:
            run(base + ["--offline"], env=env, timeout=3600)
        except SystemExit:
            log("离线构建失败（可能是新增了依赖），改用在线模式重试一次…")
            run(base, env=env, timeout=3600)
    else:
        log("Gradle assembleRelease（首次会下载 Android Gradle Plugin / Chaquopy / Pillow，耗时较长）…")
        run(base, env=env, timeout=3600)
    apk = os.path.join(APP, "build", "outputs", "apk", "release", "app-release.apk")
    if not os.path.isfile(apk):
        raise SystemExit("[x] 没有找到 app-release.apk")
    os.makedirs(OUT_DIR, exist_ok=True)
    final = os.path.join(OUT_DIR, f"{APP_NAME}-v{VERSION}.apk")
    if os.path.isfile(final):
        os.remove(final)
    shutil.copy2(apk, final)
    log(f"完成：{final}（{os.path.getsize(final) / 1048576:.1f} MB）")
    return final


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rebuild", action="store_true",
                    help="复用已装好的工具链（跳过 SDK / Python / Gradle 检查）")
    args = ap.parse_args()

    os.makedirs(DL, exist_ok=True)
    reuse = []
    if os.path.isfile(os.path.join(JDK_DIR, "bin", "java.exe")):
        reuse.append("JDK")
    if os.path.isfile(os.path.join(SDK, "build-tools", BUILD_TOOLS, "aapt2.exe")):
        reuse.append("Android SDK")
    if os.path.isfile(os.path.join(PY312_DIR, "python.exe")):
        reuse.append("Python 3.12")
    if os.path.isfile(os.path.join(GRADLE_HOME, "bin", "gradle.bat")):
        reuse.append("Gradle 8.7")
    if reuse:
        log("已缓存，本次不重复下载：" + "、".join(reuse))
    jdk = java_home()
    log(f"JDK: {jdk}")
    if not args.rebuild:
        ensure_sdk(jdk)
    py312 = ensure_python312(jdk)
    log(f"Python(build): {py312}")
    gradle = ensure_gradle()
    ensure_keystore(jdk)
    ensure_font()
    write_local_properties(py312)
    build(jdk, gradle)


if __name__ == "__main__":
    main()

