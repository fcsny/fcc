# -*- coding: utf-8 -*-
"""安卓版路径：数据放 App 私有目录，另设一个"可分享"的对外交换区。

与桌面版的三点关键差异：

1. 数据目录 = App 私有目录（卸载才清空，安全可靠）
2. 导出/导入走公共目录，这样微信、QQ、文件管理器都能看到
3. 安卓上私有目录用户用文件管理器看不到，所以「导出到公共目录」
   不是可选功能，而是**数据互通的生命线**

路径来源优先级：
    configure() 显式注入  →  Kivy 的 user_data_dir  →  程序目录下的 data/
"""
from __future__ import annotations

import json
import os
import sys

APP_NAME = "AI写作工作台"
SETTINGS_NAME = "settings.json"
PROJECT_EXT = ".aiwriter.json"
DATA_DIRNAME = "data"
EXPORT_DIRNAME = "AI写作工作台"

_PRIVATE_DIR = ""
_PUBLIC_DIR = ""


def configure(private_dir: str = "", public_dir: str = "") -> None:
    """由启动代码注入真实路径（安卓上来自 MainActivity）。"""
    global _PRIVATE_DIR, _PUBLIC_DIR
    if private_dir:
        _PRIVATE_DIR = private_dir
    if public_dir:
        _PUBLIC_DIR = public_dir


def base_dir() -> str:
    """程序根目录：可用环境变量 AIWRITER_HOME 覆盖（测试用）。"""
    env = os.environ.get("AIWRITER_HOME", "").strip()
    if env:
        return os.path.abspath(env)
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _kivy_user_data_dir() -> str:
    """Kivy 提供的 App 私有目录——安卓上唯一保证可写的位置。"""
    try:
        from kivy.app import App
        app = App.get_running_app()
        if app is not None and getattr(app, "user_data_dir", None):
            return app.user_data_dir
    except Exception:  # noqa: BLE001
        pass
    return ""


def _public_candidates() -> list[str]:
    """安卓公共目录候选：优先系统 Documents（微信/QQ 能扫到）。"""
    cands = []
    try:
        from android.storage import primary_external_storage_path  # type: ignore
        root = primary_external_storage_path()
        if root:
            cands.append(os.path.join(root, "Documents", EXPORT_DIRNAME))
            cands.append(os.path.join(root, EXPORT_DIRNAME))
    except Exception:  # noqa: BLE001
        pass
    cands.append(os.path.join(base_dir(), "export"))
    return cands


def data_dir() -> str:
    """项目文件的存放目录（App 私有，安全）。"""
    if _PRIVATE_DIR:
        return _PRIVATE_DIR
    kivy_dir = _kivy_user_data_dir()
    if kivy_dir:
        return os.path.join(kivy_dir, DATA_DIRNAME)
    env = os.environ.get("AIWRITER_HOME", "").strip()
    if env:
        return os.path.join(os.path.abspath(env), DATA_DIRNAME)
    return os.path.join(base_dir(), DATA_DIRNAME)


def export_dir() -> str:
    """对外交换区：导出/导入都经过这里，用户能在文件管理器里看到。

    逐个试候选目录，取第一个可写的——不同厂商的安卓机
    外部存储路径差异很大，硬编码一个必然在某些机器上失败。
    """
    if _PUBLIC_DIR:
        return _PUBLIC_DIR
    for cand in _public_candidates():
        ok, _reason = is_writable(cand)
        if ok:
            return cand
    return os.path.join(base_dir(), "export")


def is_writable(directory: str) -> tuple[bool, str]:
    """探测目录是否真的可写（写临时文件再读回，光看权限不够）。"""
    try:
        os.makedirs(directory, exist_ok=True)
        probe = os.path.join(directory, ".write_probe.tmp")
        with open(probe, "w", encoding="utf-8") as f:
            f.write("ok")
        with open(probe, "r", encoding="utf-8") as f:
            ok = f.read() == "ok"
        os.remove(probe)
        return (True, "") if ok else (False, "读回内容不一致")
    except Exception as e:  # noqa: BLE001
        return False, "%r" % e


def data_dir_warnings() -> list[str]:
    """启动体检：把"存不下"在第一秒暴露出来，不能等用户写完才发现。"""
    warnings = []
    ok, reason = is_writable(data_dir())
    if not ok:
        warnings.append("数据目录无法写入，内容存不下来！\n%s\n原因：%s"
                        % (data_dir(), reason))
    return warnings


def settings_path() -> str:
    return os.path.join(data_dir(), SETTINGS_NAME)


DEFAULT_SETTINGS = {"last_project": "", "recent": []}


def load_settings() -> dict:
    settings = dict(DEFAULT_SETTINGS)
    try:
        with open(settings_path(), "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            settings.update(data)
    except Exception:  # noqa: BLE001
        pass
    return settings


def save_settings(settings: dict) -> None:
    try:
        os.makedirs(data_dir(), exist_ok=True)
        with open(settings_path(), "w", encoding="utf-8") as f:
            json.dump(settings, f, ensure_ascii=False, indent=2)
    except Exception:  # noqa: BLE001
        pass


def list_projects() -> list[str]:
    """数据目录里所有项目文件的完整路径。"""
    out = []
    try:
        for name in sorted(os.listdir(data_dir())):
            if name.endswith(PROJECT_EXT):
                out.append(os.path.join(data_dir(), name))
    except Exception:  # noqa: BLE001
        pass
    return out


def list_importable() -> list[str]:
    """对外交换区里等待导入的项目文件。

    必须同时认 .aiwriter.json 和 .zip：带图片的导出会打成 zip，
    只认前者的话，用户挂了图导出后再导入，列表里空空如也，会以为数据丢了。
    """
    out = []
    try:
        d = export_dir()
        names = sorted(os.listdir(d), reverse=True)      # 新的排前面
        for name in names:
            low = name.lower()
            if low.endswith(PROJECT_EXT) or low.endswith(".zip"):
                out.append(os.path.join(d, name))
    except Exception:  # noqa: BLE001
        pass
    return out
