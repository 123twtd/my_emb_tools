"""服务管理器 - 统一管理 API / WebSocket / TCP / MCP 四类网络服务

职责划分：
- MainWindow 负责 UI 状态展示（LED + 按钮文字）
- ServiceManager 负责服务生命周期和回调路由
- 两者通过 Qt 信号解耦，便于后续 AI/MCP 集成扩展
"""

import logging
from typing import Optional, Callable, Dict

from PyQt5.QtCore import QObject, pyqtSignal, QTimer

logger = logging.getLogger(__name__)


class ServiceManager(QObject):
    """网络服务统一管理器

    管理 API、WebSocket、TCP、MCP 四类服务。
    主窗口通过连接信号实现 UI 同步，无需直接操作服务对象。

    扩展建议：
    - 新增服务类型只需在 SERVICE_KEYS 中注册并实现 _init_xxx()
    - MCP 工具可通过 get_service() 直接访问任意服务实例
    """

    # ── 信号 ─────────────────────────────────────────
    state_changed        = pyqtSignal(str, bool)   # (service_key, is_running)
    error_occurred       = pyqtSignal(str, str)    # (service_key, error_msg)
    tcp_client_count_changed = pyqtSignal(int)
    tcp_data_received    = pyqtSignal(bytes)        # TCP 客户端 → 串口透传

    SERVICE_KEYS = ("api", "ws", "tcp", "mcp")

    def __init__(self, parent=None):
        super().__init__(parent)

        self._services: Dict[str, object]  = {k: None for k in self.SERVICE_KEYS}
        self._running:  Dict[str, bool]    = {k: False for k in self.SERVICE_KEYS}

        # 回调（由 MainWindow 注入）
        self._get_ports_cb:      Optional[Callable] = None
        self._send_data_cb:      Optional[Callable] = None
        self._get_status_cb:     Optional[Callable] = None
        self._get_main_window_cb: Optional[Callable] = None
        self._camera_broadcaster = None

        # TCP 客户端数量轮询
        self._tcp_timer = QTimer(self)
        self._tcp_timer.setInterval(1000)
        self._tcp_timer.timeout.connect(self._poll_tcp_clients)

    # ── 回调注入 ──────────────────────────────────────

    def set_callbacks(self,
                      get_ports: Callable,
                      send_data: Callable,
                      get_status: Callable,
                      get_main_window: Optional[Callable] = None):
        """注入来自 MainWindow 的回调函数"""
        self._get_ports_cb      = get_ports
        self._send_data_cb      = send_data
        self._get_status_cb     = get_status
        self._get_main_window_cb = get_main_window

    # ── 初始化 ────────────────────────────────────────

    def init_network(self, network_config: dict) -> bool:
        """延迟导入并初始化 API / WS / TCP 服务（仅创建实例，不启动）

        Args:
            network_config: app.json["network"] 字典

        Returns:
            True 表示导入成功，False 表示缺少依赖
        """
        try:
            from network.api_server import APIServer
            from network.websocket_handler import WebSocketBroadcaster
            from network.tcp_server import TCPServer
            from network.camera_broadcaster import VideoStreamBroadcaster
        except ImportError as e:
            logger.warning(f"Network dependencies not available: {e}")
            return False

        try:
            cam_cfg = network_config.get("camera_broadcast", {})
            self._camera_broadcaster = VideoStreamBroadcaster(
                fps=cam_cfg.get("fps", 15),
                jpeg_quality=cam_cfg.get("jpeg_quality", 85),
                max_device_scan=cam_cfg.get("max_device_scan", 8),
            )
            logger.info("Video stream service ready (capture & API broadcast off by default)")

            api_cfg = network_config.get("api_server",       {"host": "127.0.0.1", "port": 8000})
            ws_cfg  = network_config.get("websocket_server", {"host": "127.0.0.1", "port": 8001})
            tcp_cfg = network_config.get("tcp_server",       {"host": "0.0.0.0",   "port": 9999})

            # API Server
            api = APIServer(
                host=api_cfg.get("host", "127.0.0.1"),
                port=api_cfg.get("port", 8000)
            )
            api.set_callbacks(
                get_ports=self._get_ports_cb,
                send_data=self._send_data_cb,
                get_status=self._get_status_cb,
                camera_broadcaster=self._camera_broadcaster,
            )
            self._services["api"] = api
            logger.info(f"API server ready: {api_cfg.get('host')}:{api_cfg.get('port', 8000)}")

            # WebSocket Broadcaster
            ws = WebSocketBroadcaster(
                host=ws_cfg.get("host", "127.0.0.1"),
                port=ws_cfg.get("port", 8001)
            )
            self._services["ws"] = ws
            logger.info(f"WebSocket server ready: {ws_cfg.get('host')}:{ws_cfg.get('port', 8001)}")

            # TCP Server
            tcp = TCPServer(
                host=tcp_cfg.get("host", "0.0.0.0"),
                port=tcp_cfg.get("port", 9999)
            )
            tcp.data_received.connect(self.tcp_data_received)
            tcp.error_occurred.connect(self._on_tcp_server_error)
            tcp.client_connected.connect(
                lambda addr: logger.info(f"TCP client connected: {addr}")
            )
            self._services["tcp"] = tcp
            logger.info(f"TCP server ready: {tcp_cfg.get('host')}:{tcp_cfg.get('port', 9999)}")

            return True

        except Exception as e:
            logger.error(f"Failed to init network services: {e}")
            return False

    def init_mcp(self) -> bool:
        """延迟导入并初始化 MCP 桥接服务

        Returns:
            True 表示初始化成功
        """
        if self._get_main_window_cb is None:
            logger.warning("init_mcp: get_main_window callback not set")
            return False

        try:
            from mcp_bridge.ui_exporter import UIExporter
            from mcp_bridge.mcp_server import MCPServerBridge
        except ImportError as e:
            logger.warning(f"MCP dependencies not available: {e}")
            return False

        try:
            exporter = UIExporter(get_main_window=self._get_main_window_cb)
            bridge   = MCPServerBridge(exporter)
            self._services["mcp"] = bridge
            logger.info("MCP server bridge ready (stdio mode)")
            return True
        except Exception as e:
            logger.error(f"Failed to init MCP: {e}")
            return False

    # ── 服务生命周期 ──────────────────────────────────

    def start(self, key: str):
        """启动指定服务，失败时发射 error_occurred 信号"""
        if key not in self.SERVICE_KEYS:
            return
        if self._running[key]:
            return
        service = self._services.get(key)
        if service is None:
            self.error_occurred.emit(key, "服务未初始化或缺少依赖")
            return

        try:
            service.start()
            self._running[key] = True
            if key == "tcp":
                self._tcp_timer.start()
            self.state_changed.emit(key, True)
            logger.info(f"Service '{key}' started")
        except Exception as e:
            logger.error(f"Failed to start service '{key}': {e}")
            self.error_occurred.emit(key, str(e))

    def stop(self, key: str):
        """停止指定服务"""
        if key not in self.SERVICE_KEYS:
            return
        if not self._running[key]:
            return
        service = self._services.get(key)
        if service:
            try:
                service.stop()
            except Exception as e:
                logger.error(f"Failed to stop service '{key}': {e}")

        self._running[key] = False
        if key == "tcp":
            self._tcp_timer.stop()
            self.tcp_client_count_changed.emit(0)
        self.state_changed.emit(key, False)
        logger.info(f"Service '{key}' stopped")

    def toggle(self, key: str):
        """切换服务启停状态（按钮点击时调用）"""
        if self._running.get(key):
            self.stop(key)
        else:
            self.start(key)

    def stop_all(self):
        """停止所有运行中的服务（应用退出时调用）"""
        if self._camera_broadcaster and self._camera_broadcaster.is_capturing:
            try:
                self._camera_broadcaster.stop()
            except Exception:
                pass
        for key in reversed(self.SERVICE_KEYS):
            if self._running.get(key):
                self.stop(key)

    def auto_start(self, network_config: dict):
        """根据配置 enabled 字段自动启动服务"""
        for key, cfg_key in [
            ("api", "api_server"),
            ("ws",  "websocket_server"),
            ("tcp", "tcp_server"),
        ]:
            cfg = network_config.get(cfg_key, {})
            if cfg.get("enabled", False) and self._services.get(key) is not None:
                self.start(key)

    # ── 数据广播 ──────────────────────────────────────

    def broadcast_serial_data(self, data: bytes):
        """将串口数据广播到 WebSocket 和 TCP 所有客户端"""
        if self._running.get("ws"):
            ws = self._services.get("ws")
            if ws:
                try:
                    ws.broadcast_serial_data(data)
                except Exception:
                    pass

        if self._running.get("tcp"):
            tcp = self._services.get("tcp")
            if tcp:
                try:
                    tcp.broadcast(data)
                except Exception:
                    pass

    # ── 查询接口（供 MCP / API 调用）─────────────────

    def is_running(self, key: str) -> bool:
        return self._running.get(key, False)

    def is_available(self, key: str) -> bool:
        return self._services.get(key) is not None

    def get_service(self, key: str) -> Optional[object]:
        """获取服务实例（供高级集成使用，如 MCP 工具直接查询 TCP 状态）"""
        return self._services.get(key)

    def get_network_port(self, key: str) -> Optional[int]:
        """获取服务监听端口"""
        svc = self._services.get(key)
        return getattr(svc, "port", None) if svc else None

    def get_camera_broadcaster(self):
        """获取本机摄像头广播服务（供图传 Tab / API 使用）"""
        return self._camera_broadcaster

    def export_status(self) -> dict:
        """导出所有服务状态（供 API /status 端点使用）"""
        status = {
            key: {
                "running":   self._running[key],
                "available": self._services[key] is not None,
                "port":      self.get_network_port(key),
            }
            for key in self.SERVICE_KEYS
        }
        cam = self._camera_broadcaster
        status["video_stream"] = {
            "available": cam is not None and cam.is_available(),
            "capturing": bool(cam and cam.is_capturing),
            "api_broadcast": bool(cam and cam.api_broadcast_enabled),
            "source_type": cam.source_type if cam else None,
        }
        return status

    # ── 内部定时器 ────────────────────────────────────

    def _on_tcp_server_error(self, message: str):
        """TCP 后台线程 bind/accept 失败时回滚状态"""
        if self._running.get("tcp"):
            self._running["tcp"] = False
            self._tcp_timer.stop()
            self.tcp_client_count_changed.emit(0)
            self.state_changed.emit("tcp", False)
        self.error_occurred.emit("tcp", message)

    def _poll_tcp_clients(self):
        tcp = self._services.get("tcp")
        if tcp and self._running.get("tcp"):
            try:
                self.tcp_client_count_changed.emit(tcp.get_client_count())
            except Exception:
                pass
