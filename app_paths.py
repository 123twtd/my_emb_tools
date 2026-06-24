"""应用路径：开发环境与 PyInstaller 打包环境"""

from __future__ import annotations

import os
import shutil
import sys


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def bundle_root() -> str:
    """只读资源根目录（打包后=_MEIPASS）"""
    if is_frozen():
        return sys._MEIPASS
    return os.path.dirname(os.path.abspath(__file__))


def app_root() -> str:
    """可写应用根目录（打包后=exe 所在目录）"""
    if is_frozen():
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


def config_dir() -> str:
    return os.path.join(app_root(), "config")


def config_path(filename: str) -> str:
    return os.path.join(config_dir(), filename)


def ensure_runtime_layout() -> None:
    """首次运行：将内置 config 复制到 exe 同目录，并创建 calib 目录"""
    dst = config_dir()
    src = os.path.join(bundle_root(), "config")
    os.makedirs(dst, exist_ok=True)
    os.makedirs(os.path.join(dst, "calib"), exist_ok=True)
    if not os.path.isdir(src):
        return
    for name in os.listdir(src):
        s = os.path.join(src, name)
        d = os.path.join(dst, name)
        if os.path.isdir(s):
            if not os.path.isdir(d):
                shutil.copytree(s, d)
        elif not os.path.exists(d):
            shutil.copy2(s, d)
