from PyQt5.QtCore import QObject, pyqtSignal

class DataChannel(QObject):
    """
    Abstract base class for all data channels (UART, UDP, etc.)
    Provides a unified interface for the main application to interact with
    different communication protocols without being tightly coupled.
    """
    # 通用信号
    data_received = pyqtSignal(bytes)          # 接收到数据
    error_occurred = pyqtSignal(str)           # 发生错误
    closed_unexpected = pyqtSignal()           # 意外关闭断开连接

    def __init__(self, parent=None):
        super().__init__(parent)
        self._running = False

    def open_channel(self, *args, **kwargs) -> bool:
        """
        初始化并打开通道。
        返回 True 表示成功。
        """
        raise NotImplementedError

    def close_channel(self):
        """
        关闭通道并停止接收线程。
        """
        raise NotImplementedError

    def send_data(self, data: bytes) -> bool:
        """
        发送数据。
        """
        raise NotImplementedError

    def is_open(self) -> bool:
        """
        通道当前是否处于打开状态。
        """
        raise NotImplementedError

    def read_loop(self):
        """
        后台读取循环，由 QThread 调用
        """
        raise NotImplementedError
