# -*- coding: utf-8 -*-
"""异常追踪：把 Tk 回调里的异常写进「错误日志.txt」。

为什么需要它：Tkinter 的回调异常默认只打印到 stderr。用 bat 双击启动时
没有控制台，用户什么都看不到，只会觉得"点了没反应"。
这类静默异常还会把面板状态（比如 _building 标志）留在损坏状态，
导致后续所有操作都失效——排查起来极其困难。

所以这里做两件事：
  1. 把所有未捕获异常（含 Tk 回调）追加写入 错误日志.txt
  2. 提供开关式日志，方便定位界面状态问题
"""
from __future__ import annotations

import os
import sys
import time
import traceback

LOG_NAME = "错误日志.txt"
_MAX_SIZE = 512 * 1024      # 超过就归档，避免无限增长


def log_path() -> str:
    """日志文件位置：优先程序目录（用户好找），失败则退到临时目录。"""
    try:
        from core.paths import base_dir
        return os.path.join(base_dir(), LOG_NAME)
    except Exception:  # noqa: BLE001
        import tempfile
        return os.path.join(tempfile.gettempdir(), LOG_NAME)


def _rotate(path: str) -> None:
    try:
        if os.path.exists(path) and os.path.getsize(path) > _MAX_SIZE:
            os.replace(path, path.replace(".txt", ".old.txt"))
    except Exception:  # noqa: BLE001
        pass


def write(text: str) -> None:
    """写一条日志（异常安全——日志本身绝不能再把程序搞崩）。"""
    path = log_path()
    try:
        _rotate(path)
        with open(path, "a", encoding="utf-8") as f:
            f.write(text if text.endswith("\n") else text + "\n")
    except Exception:  # noqa: BLE001
        pass


def log_exception(context: str = "") -> None:
    """记录当前正在处理的异常。"""
    text = "".join(traceback.format_exception(*sys.exc_info()))
    header = "\n" + "=" * 60 + "\n%s  未捕获的异常%s\n" % (
        time.strftime("%Y-%m-%d %H:%M:%S"),
        "（%s）" % context if context else "")
    write(header + text)


def log_event(message: str) -> None:
    """记录一条普通事件，用于追踪界面状态变化。"""
    write("[%s] %s" % (time.strftime("%H:%M:%S"), message))


def install() -> None:
    """安装 sys.excepthook（覆盖非 Tk 回调的异常）。"""
    original = sys.excepthook

    def hook(exc_type, exc, tb):
        try:
            text = "".join(traceback.format_exception(exc_type, exc, tb))
            write("\n" + "=" * 60 + "\n%s  未捕获的异常（主线程）\n%s"
                  % (time.strftime("%Y-%m-%d %H:%M:%S"), text))
        except Exception:  # noqa: BLE001
            pass
        if original:
            original(exc_type, exc, tb)

    sys.excepthook = hook
