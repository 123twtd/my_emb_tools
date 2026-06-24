"""串口助手 - 程序入口"""

import os
import sys

# 保证工程根目录在 sys.path 中（aruco_loc 等顶层包可导入）
_ROOT = os.path.dirname(os.path.abspath(__file__))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import logging

# 必须在创建 QApplication 之前设置，否则高 DPI 缩放不生效
os.environ["QT_ENABLE_HIGHDPI_SCALING"] = "1"

# 配置日志，使所有模块的 logger 输出可见
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QApplication
from serial_assistant.main_window_v3 import MainWindow
from serial_assistant.style import DARK_STYLESHEET


def main():
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)
    app = QApplication(sys.argv)

    # 应用全局暗色主题
    app.setStyleSheet(DARK_STYLESHEET)

    window = MainWindow()
    window.show()
    # 强制处理事件，确保窗口先渲染出来
    app.processEvents()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
