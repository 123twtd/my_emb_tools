"""WebSocket 实时数据流 - 广播串口数据和波形"""

import asyncio
import threading
import json
import logging
from typing import Set, Optional, Callable
from collections import deque

from network.utils import check_port_available

logger = logging.getLogger(__name__)


class WebSocketBroadcaster:
    """
    WebSocket 广播器

    管理 WebSocket 连接，支持：
    - 广播串口原始数据
    - 广播示波器波形数据
    - 限流控制（避免高频推送导致卡顿）
    """

    def __init__(self, host: str = "127.0.0.1", port: int = 8001):
        self.host = host
        self.port = port
        self._clients: Set = set()
        self._thread: Optional[threading.Thread] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None

        # 限流：最多 10Hz（serial 和 scope 分离，避免互相干扰）
        self._rate_limit = 0.1  # 100ms
        self._last_serial_send_time = 0
        self._last_scope_send_time = 0

        # 数据缓冲区
        self._serial_buffer: deque = deque(maxlen=100)
        self._scope_buffer: deque = deque(maxlen=50)

    def start(self):
        """启动 WebSocket 服务器"""
        if self._thread and self._thread.is_alive():
            logger.warning("WebSocket server already running")
            return

        # 预先同步检查端口可用性，避免异步启动后才发现绑定失败
        check_port_available(self.host, self.port)

        def run_server():
            """在线程中运行 asyncio 事件循环"""
            self._loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self._loop)
            self._loop.run_until_complete(self._serve())

        self._thread = threading.Thread(target=run_server, daemon=True)
        self._thread.start()
        logger.info(f"WebSocket server started at ws://{self.host}:{self.port}")

    async def _serve(self):
        """运行 WebSocket 服务器"""
        import websockets
        async with websockets.serve(self._handler, self.host, self.port):
            await asyncio.Future()  # 永久运行

    async def _handler(self, websocket):
        """处理单个 WebSocket 连接"""
        self._clients.add(websocket)
        logger.info(f"WebSocket client connected: {websocket.remote_address}")

        try:
            # 发送欢迎消息
            await websocket.send(json.dumps({
                "type": "welcome",
                "message": "Connected to Serial Assistant V3.0"
            }))

            # 保持连接，处理客户端消息
            async for message in websocket:
                try:
                    data = json.loads(message)
                    await self._handle_client_message(websocket, data)
                except json.JSONDecodeError:
                    await websocket.send(json.dumps({
                        "type": "error",
                        "message": "Invalid JSON"
                    }))
        except websockets.exceptions.ConnectionClosed:
            logger.info("WebSocket client disconnected")
        finally:
            self._clients.discard(websocket)

    async def _handle_client_message(self, websocket, data: dict):
        """处理客户端消息"""
        msg_type = data.get("type")

        if msg_type == "subscribe_serial":
            await websocket.send(json.dumps({
                "type": "subscribed",
                "channel": "serial"
            }))
        elif msg_type == "subscribe_scope":
            await websocket.send(json.dumps({
                "type": "subscribed",
                "channel": "scope"
            }))
        else:
            await websocket.send(json.dumps({
                "type": "error",
                "message": f"Unknown message type: {msg_type}"
            }))

    def broadcast_serial_data(self, data: bytes):
        """广播串口数据（限流）"""
        import time
        current_time = time.time()

        if current_time - self._last_serial_send_time < self._rate_limit:
            return  # 限流

        self._last_serial_send_time = current_time

        # 转换为十六进制字符串
        hex_data = data.hex()

        message = json.dumps({
            "type": "serial_data",
            "data": hex_data,
            "length": len(data)
        })

        self._broadcast(message)

    def broadcast_scope_data(self, channels: dict):
        """广播示波器波形数据"""
        import time
        current_time = time.time()

        if current_time - self._last_scope_send_time < self._rate_limit:
            return  # 限流

        self._last_scope_send_time = current_time

        message = json.dumps({
            "type": "scope_data",
            "channels": channels
        })

        self._broadcast(message)

    def _broadcast(self, message: str):
        """向所有客户端广播消息"""
        if not self._loop or not self._clients:
            return

        async def send_all():
            tasks = [client.send(message) for client in self._clients]
            await asyncio.gather(*tasks, return_exceptions=True)

        asyncio.run_coroutine_threadsafe(send_all(), self._loop)

    def stop(self):
        """停止服务器并清理客户端连接"""
        if self._loop:
            self._loop.call_soon_threadsafe(self._loop.stop)
        if self._thread:
            self._thread.join(timeout=5)
        # 清空客户端集合，防止旧连接在下次 start() 后被误用
        self._clients.clear()
        logger.info("WebSocket server stopped")
