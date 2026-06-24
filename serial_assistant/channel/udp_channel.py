"""UDP 数据通道 - 绑定本地端口收发，支持固定远端或回包到最近对端"""

import socket
import threading
from typing import Optional, Tuple

from PyQt5.QtCore import QThread

from serial_assistant.channel.base_channel import DataChannel


class UdpWorker(DataChannel):
    """UDP 通道工作对象，在后台线程中 recvfrom，避免阻塞 UI"""

    def __init__(self):
        super().__init__()
        self._sock: Optional[socket.socket] = None
        self._local_host = "0.0.0.0"
        self._local_port = 8888
        self._remote_host = ""
        self._remote_port = 0
        self._reply_to_last = True
        self._last_peer: Optional[Tuple[str, int]] = None
        self._write_lock = threading.Lock()

    def is_open(self) -> bool:
        return self._sock is not None

    def open_channel(
        self,
        local_host: str = "0.0.0.0",
        local_port: int = 8888,
        remote_host: str = "",
        remote_port: int = 0,
        reply_to_last: bool = True,
    ) -> bool:
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind((local_host, int(local_port)))
            sock.settimeout(0.05)
            self._sock = sock
            self._local_host = local_host
            self._local_port = int(local_port)
            self._remote_host = (remote_host or "").strip()
            self._remote_port = int(remote_port or 0)
            self._reply_to_last = bool(reply_to_last)
            self._last_peer = None
            self._running = True
            return True
        except OSError as e:
            self.error_occurred.emit(f"UDP 打开失败: {e}")
            self._sock = None
            return False

    def close_channel(self):
        self._running = False
        if self._sock is not None:
            try:
                self._sock.close()
            except Exception:
                pass
        self._sock = None
        self._last_peer = None

    def send_data(self, data: bytes) -> bool:
        with self._write_lock:
            if not self._sock:
                return False
            target = None
            if self._remote_host and self._remote_port > 0:
                target = (self._remote_host, self._remote_port)
            elif self._reply_to_last and self._last_peer:
                target = self._last_peer
            if target is None:
                return False
            try:
                self._sock.sendto(data, target)
                return True
            except OSError as e:
                self.error_occurred.emit(f"UDP 发送失败: {e}")
                return False

    def read_loop(self):
        while self._running:
            try:
                if self._sock is None:
                    break
                try:
                    data, addr = self._sock.recvfrom(65535)
                except socket.timeout:
                    continue
                if data:
                    self._last_peer = (addr[0], addr[1])
                    self.data_received.emit(data)
            except OSError:
                if self._running:
                    self.closed_unexpected.emit()
                break
            except Exception:
                break
