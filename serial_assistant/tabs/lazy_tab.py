"""延迟加载 Tab 包装器 - 仅在用户首次切换时创建真实 Tab"""

import importlib
import logging

from PyQt5.QtWidgets import QWidget, QVBoxLayout, QLabel
from PyQt5.QtCore import Qt

from .base_tab import SerialTab

logger = logging.getLogger(__name__)


class LazyTabWrapper(SerialTab):
    """
    延迟加载的 Tab 包装器

    启动时仅显示轻量级占位符，当用户首次切换到该 Tab 时
    才动态导入模块并创建真实实例，避免主线程长时间阻塞。
    """

    def __init__(self, module_name: str, class_name: str, title: str, parent=None):
        super().__init__(parent)
        self._module_name = module_name
        self._class_name = class_name
        self._title = title
        self._loaded_tab = None
        self._event_buffer = []  # [("method", args)] 缓存未加载期间的事件
        self._camera_broadcaster = None
        self._api_host = "127.0.0.1"
        self._api_port = 8000
        self._get_api_bases = None

        self._show_placeholder()

    # ────────────── 占位符 UI ──────────────

    def _show_placeholder(self):
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignCenter)

        icon_label = QLabel("\u23F3")  # hourglass
        icon_label.setAlignment(Qt.AlignCenter)
        icon_label.setStyleSheet("font-size: 48px; color: #888;")
        layout.addWidget(icon_label)

        status_label = QLabel(f'"{self._title}" \u5373\u5c06\u52a0\u8f7d\u2026')
        status_label.setAlignment(Qt.AlignCenter)
        status_label.setStyleSheet("color: #999; font-size: 14px;")
        layout.addWidget(status_label)

    # ────────────── 延迟加载 ──────────────

    def ensure_loaded(self):
        """确保真实 Tab 已加载（幂等调用）"""
        if self._loaded_tab is not None:
            return True

        logger.info(f"Lazy loading: {self._module_name}.{self._class_name}")

        try:
            module = importlib.import_module(self._module_name)
            tab_class = getattr(module, self._class_name, None)
            if tab_class is None:
                raise AttributeError(
                    f"Class {self._class_name} not found in {self._module_name}"
                )
            self._loaded_tab = tab_class()
        except Exception as e:
            logger.error(f"Failed to lazy load {self._title}: {e}", exc_info=True)
            self._show_error(str(e))
            return False

        # 注入串口工作对象
        if self._serial_worker and hasattr(self._loaded_tab, 'set_serial_worker'):
            self._loaded_tab.set_serial_worker(self._serial_worker)

        if self._camera_broadcaster and hasattr(self._loaded_tab, 'set_camera_broadcaster'):
            self._loaded_tab.set_camera_broadcaster(
                self._camera_broadcaster, self._api_host, self._api_port, self._get_api_bases
            )

        # 重放缓存的事件
        for method_name, args in self._event_buffer:
            method = getattr(self._loaded_tab, method_name, None)
            if method:
                try:
                    method(*args)
                except Exception:
                    pass
        self._event_buffer.clear()

        # 替换占位符内容：将真实 Tab 的布局转移到本容器
        # 先清空占位符子部件
        while self.layout().count():
            item = self.layout().takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

        # 将真实 Tab 设为子部件并转移其布局
        self._loaded_tab.setParent(self)
        self.layout().addWidget(self._loaded_tab)

        logger.info(f"Lazy loaded: {self._title}")
        return True

    def _show_error(self, error_msg: str):
        """加载失败时显示错误提示"""
        while self.layout().count():
            item = self.layout().takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

        error_label = QLabel(f"\u26A0 \u52a0\u8f7d\u5931\u8d25")
        error_label.setAlignment(Qt.AlignCenter)
        error_label.setStyleSheet("color: #CC4444; font-size: 16px;")
        self.layout().addWidget(error_label)

        detail_label = QLabel(error_msg)
        detail_label.setAlignment(Qt.AlignCenter)
        detail_label.setWordWrap(True)
        detail_label.setStyleSheet("color: #999; font-size: 11px;")
        self.layout().addWidget(detail_label)

    @property
    def is_loaded(self) -> bool:
        return self._loaded_tab is not None

    # ────────────── SerialTab 接口覆写 ──────────────

    def set_serial_worker(self, worker):
        super().set_serial_worker(worker)
        if self._loaded_tab and hasattr(self._loaded_tab, 'set_serial_worker'):
            self._loaded_tab.set_serial_worker(worker)

    def set_camera_broadcaster(self, broadcaster, api_host: str = "127.0.0.1",
                               api_port: int = 8000, get_api_bases=None):
        self._camera_broadcaster = broadcaster
        self._api_host = api_host
        self._api_port = api_port
        self._get_api_bases = get_api_bases
        if self._loaded_tab and hasattr(self._loaded_tab, 'set_camera_broadcaster'):
            self._loaded_tab.set_camera_broadcaster(
                broadcaster, api_host, api_port, get_api_bases
            )

    def on_data_received(self, data: bytes):
        if self._loaded_tab is not None:
            self._loaded_tab.on_data_received(data)
        else:
            self._event_buffer.append(("on_data_received", (data,)))

    def on_port_toggled(self, is_open: bool):
        if self._loaded_tab is not None:
            self._loaded_tab.on_port_toggled(is_open)
        else:
            self._event_buffer.append(("on_port_toggled", (is_open,)))

    def reset_state(self):
        if self._loaded_tab is not None:
            self._loaded_tab.reset_state()

    def cleanup(self):
        if self._loaded_tab and hasattr(self._loaded_tab, 'cleanup'):
            try:
                self._loaded_tab.cleanup()
            except Exception:
                pass
