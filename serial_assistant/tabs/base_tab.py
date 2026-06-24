"""Tab 基类 - 定义 MainWindow 与各模式 Tab 之间的接口契约"""

from PyQt5.QtWidgets import QWidget


class SerialTab(QWidget):
    """所有模式 Tab 的抽象基类"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._serial_worker = None

    def set_serial_worker(self, worker):
        """由 MainWindow 调用，注入串口工作对象引用"""
        self._serial_worker = worker

    def on_data_received(self, data: bytes):
        """串口数据到达时由 MainWindow 分发调用"""
        pass

    def on_port_toggled(self, is_open: bool):
        """串口打开/关闭状态变化时调用"""
        pass

    def reset_state(self):
        """串口关闭时调用，清理缓冲区和状态"""
        pass

    def cleanup(self):
        """窗口关闭时调用，释放资源（如网络连接、线程等）"""
        pass
