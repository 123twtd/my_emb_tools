"""UI 状态导出器 - 导出应用状态供 AI 理解"""

import json
import base64
import io
import logging
from typing import Optional, Callable

from PyQt5.QtWidgets import QApplication, QWidget
from PyQt5.QtGui import QPixmap
from PyQt5.QtCore import QBuffer, QByteArray

logger = logging.getLogger(__name__)


class UIExporter:
    """
    UI 状态导出器

    功能：
    - 截取应用窗口截图
    - 导出结构化 UI 状态（JSON）
    - 提取控件信息
    """

    def __init__(self, get_main_window: Optional[Callable] = None):
        """
        Args:
            get_main_window: 获取主窗口实例的回调函数
        """
        self._get_main_window = get_main_window

    def set_main_window_provider(self, get_main_window: Callable):
        """设置主窗口提供者"""
        self._get_main_window = get_main_window

    def capture_screenshot(self) -> Optional[str]:
        """
        截取应用窗口截图

        Returns:
            base64 编码的 PNG 图片，失败返回 None
        """
        try:
            if not self._get_main_window:
                logger.error("Main window provider not set")
                return None

            window = self._get_main_window()
            if not window:
                logger.error("Main window is None")
                return None

            # 截取窗口
            pixmap = window.grab()

            # 转换为 PNG
            buffer = QBuffer()
            buffer.open(QBuffer.ReadWrite)
            pixmap.save(buffer, "PNG")

            # 转换为 base64
            png_data = buffer.data().data()
            return base64.b64encode(png_data).decode('utf-8')

        except Exception as e:
            logger.error(f"Failed to capture screenshot: {e}")
            return None

    def export_ui_state(self) -> dict:
        """
        导出结构化 UI 状态

        Returns:
            包含应用状态的字典
        """
        try:
            if not self._get_main_window:
                return {"error": "Main window provider not set"}

            window = self._get_main_window()
            if not window:
                return {"error": "Main window is None"}

            state = {
                "window_title": window.windowTitle(),
                "window_size": {
                    "width": window.width(),
                    "height": window.height()
                },
                "active_tab_index": window._tab_widget.currentIndex(),
                "active_tab_title": window._tab_widget.tabText(
                    window._tab_widget.currentIndex()
                ),
                "tab_count": window._tab_widget.count(),
                "tabs": [],
                "serial_config": {
                    "port": window.cb_port.currentText(),
                    "baudrate": window.cb_baudrate.currentText(),
                    "databits": window.cb_databits.currentText(),
                    "stopbits": window.cb_stopbits.currentText(),
                    "parity": window.cb_parity.currentText(),
                    "is_open": window._worker.is_open
                },
                "network_services": {
                    "api_server": window._api_server is not None,
                    "websocket_server": window._ws_broadcaster is not None,
                    "tcp_server": window._tcp_server is not None,
                    "tcp_clients": window._tcp_server.get_client_count() if window._tcp_server else 0
                }
            }

            # 提取 Tab 信息
            for i in range(window._tab_widget.count()):
                state["tabs"].append({
                    "index": i,
                    "title": window._tab_widget.tabText(i),
                    "is_active": i == window._tab_widget.currentIndex()
                })

            return state

        except Exception as e:
            logger.error(f"Failed to export UI state: {e}")
            return {"error": str(e)}

    def get_serial_ports(self) -> list:
        """获取可用串口列表"""
        try:
            from serial_assistant.serial_core import get_available_ports
            return get_available_ports()
        except Exception as e:
            logger.error(f"Failed to get serial ports: {e}")
            return []

    def send_serial_data(self, port: str, data: str, mode: str = "text") -> dict:
        """
        发送串口数据

        Args:
            port: 串口名称
            data: 要发送的数据
            mode: "text" 或 "hex"

        Returns:
            结果字典
        """
        try:
            if not self._get_main_window:
                return {"success": False, "error": "Main window provider not set"}

            window = self._get_main_window()
            if not window:
                return {"success": False, "error": "Main window is None"}

            if not window._worker.is_open:
                return {"success": False, "error": "Serial port not open"}

            # 转换数据
            if mode == "hex":
                raw_data = bytes.fromhex(data.replace(" ", ""))
            else:
                raw_data = data.encode("utf-8")

            # 发送
            window._worker.send(raw_data)

            return {
                "success": True,
                "bytes_sent": len(raw_data)
            }

        except Exception as e:
            logger.error(f"Failed to send serial data: {e}")
            return {"success": False, "error": str(e)}
