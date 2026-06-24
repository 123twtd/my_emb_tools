"""TCP Socket 服务器 - 转发串口数据到多个客户端"""

import socket
import threading
import logging
from typing import Set, Optional
from PyQt5.QtCore import QObject, pyqtSignal

from network.utils import check_port_available

logger = logging.getLogger(__name__)


class TCPServer(QObject):
    """
    TCP Socket 服务器

    功能：
    - 监听指定端口
    - 接受多个客户端连接
    - 将串口数据转发给所有连接的客户端
    - 接收客户端发送的数据并转发到串口
    """

    client_connected = pyqtSignal(str)      # 客户端连接信号
    client_disconnected = pyqtSignal(str)   # 客户端断开信号
    data_received = pyqtSignal(bytes)       # 接收到客户端数据
    error_occurred = pyqtSignal(str)        # 错误信号

    def __init__(self, host: str = "0.0.0.0", port: int = 9999):
        super().__init__()
        self.host = host
        self.port = port
        self._server_socket: Optional[socket.socket] = None
        self._clients: Set[socket.socket] = set()
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()

    def start(self):
        """启动 TCP 服务器"""
        if self._running:
            logger.warning("TCP server already running")
            return

        check_port_available(self.host, self.port)

        self._running = True
        self._thread = threading.Thread(target=self._run_server, daemon=True)
        self._thread.start()

    def stop(self):
        """停止 TCP 服务器"""
        self._running = False

        # 关闭所有客户端连接
        with self._lock:
            for client in self._clients:
                try:
                    client.close()
                except Exception:
                    pass
            self._clients.clear()

        # 关闭服务器 socket，打断 accept 阻塞
        if self._server_socket:
            try:
                self._server_socket.close()
            except Exception:
                pass
            self._server_socket = None

        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)
        self._thread = None

        logger.info("TCP server stopped")

    def _run_server(self):
        """运行 TCP 服务器（在工作线程中）"""
        try:
            self._server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self._server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self._server_socket.bind((self.host, self.port))
            self._server_socket.listen(5)
            self._server_socket.settimeout(1.0)  # 超时以便检查 running 标志

            logger.info(f"TCP server listening on {self.host}:{self.port}")

            while self._running:
                try:
                    client, addr = self._server_socket.accept()
                    client_addr = f"{addr[0]}:{addr[1]}"

                    # 创建处理线程
                    handler = threading.Thread(
                        target=self._handle_client,
                        args=(client, client_addr),
                        daemon=True
                    )
                    handler.start()

                    with self._lock:
                        self._clients.add(client)

                    self.client_connected.emit(client_addr)
                    logger.info(f"TCP client connected: {client_addr}")

                except socket.timeout:
                    continue
                except Exception as e:
                    if self._running:
                        logger.error(f"Accept error: {e}")
                    break

        except Exception as e:
            self._running = False
            self.error_occurred.emit(f"Server error: {str(e)}")
            logger.error(f"TCP server error: {e}")

    def _handle_client(self, client: socket.socket, addr: str):
        """处理单个客户端连接"""
        try:
            client.settimeout(1.0)

            while self._running:
                try:
                    data = client.recv(4096)
                    if not data:
                        break  # 客户端断开

                    # 发送数据到串口
                    self.data_received.emit(data)

                except socket.timeout:
                    continue
                except Exception as e:
                    logger.debug(f"Client {addr} error: {e}")
                    break

        finally:
            with self._lock:
                self._clients.discard(client)
            try:
                client.close()
            except Exception:
                pass

            self.client_disconnected.emit(addr)
            logger.info(f"TCP client disconnected: {addr}")

    def broadcast(self, data: bytes):
        """向所有连接的客户端广播数据"""
        with self._lock:
            disconnected = []
            for client in self._clients:
                try:
                    client.sendall(data)
                except Exception as e:
                    logger.debug(f"Broadcast error: {e}")
                    disconnected.append(client)

            # 清理断开的连接
            for client in disconnected:
                self._clients.discard(client)

    def get_client_count(self) -> int:
        """获取当前连接的客户端数量"""
        with self._lock:
            return len(self._clients)
