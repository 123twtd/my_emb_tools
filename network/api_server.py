"""FastAPI HTTP Server - 提供 REST API 接口"""

import asyncio
import threading
import logging
from typing import Optional, Callable, Dict, Any
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, Response
from pydantic import BaseModel, Field
import uvicorn

from network.utils import check_port_available

logger = logging.getLogger(__name__)


class SendRequest(BaseModel):
    """发送数据请求"""
    port: str
    data: str
    mode: str = "text"  # "text" or "hex"
    baud_rate: int = 9600


class SerialPortInfo(BaseModel):
    """串口信息"""
    name: str
    description: str = ""


class StatusResponse(BaseModel):
    """状态响应"""
    status: str
    message: str = ""
    data: Optional[Dict[str, Any]] = None


class VideoBroadcastRequest(BaseModel):
    """视频流广播控制（支持本机摄像头 / HTTP MJPEG）"""
    enabled: bool
    source_type: str = "local"          # "local" | "http"
    device_index: int = Field(default=0, ge=0)
    url: Optional[str] = None
    width: Optional[int] = Field(default=None, ge=160, le=3840)
    height: Optional[int] = Field(default=None, ge=120, le=2160)
    fps: Optional[int] = Field(default=None, ge=1, le=60)
    jpeg_quality: Optional[int] = Field(default=None, ge=10, le=100)
    capture_only: bool = False          # True=仅捕获不开启 API 广播


class APIServer:
    """
    FastAPI HTTP 服务器

    提供 REST API 接口，支持：
    - 列出可用串口
    - 发送串口数据
    - 获取应用状态
    - 获取 UI 截图（后续实现）
    """

    def __init__(self, host: str = "127.0.0.1", port: int = 8000):
        self.host = host
        self.port = port
        self.app = FastAPI(title="Serial Assistant API", version="3.0")
        self._thread: Optional[threading.Thread] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._server: Optional[uvicorn.Server] = None

        # 回调函数（由 MainWindow / ServiceManager 注入）
        self._get_serial_ports: Optional[Callable] = None
        self._send_serial_data: Optional[Callable] = None
        self._get_app_status: Optional[Callable] = None
        self._camera_broadcaster = None

        # CORS 中间件
        self.app.add_middleware(
            CORSMiddleware,
            allow_origins=["*"],
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

        self._setup_routes()

    def set_callbacks(self, get_ports: Callable, send_data: Callable,
                      get_status: Callable, camera_broadcaster=None):
        """设置回调函数"""
        self._get_serial_ports = get_ports
        self._send_serial_data = send_data
        self._get_app_status = get_status
        self._camera_broadcaster = camera_broadcaster

    def _setup_routes(self):
        """设置路由"""

        @self.app.get("/api/status")
        async def get_status():
            """获取应用状态"""
            if self._get_app_status:
                status = self._get_app_status()
                return StatusResponse(status="ok", data=status)
            return StatusResponse(status="ok", data={"message": "Serial Assistant V3.0"})

        @self.app.get("/api/serial/ports")
        async def list_ports():
            """列出可用串口"""
            if self._get_serial_ports:
                ports = self._get_serial_ports()
                return {"ports": ports}
            return {"ports": []}

        @self.app.post("/api/serial/send")
        async def send_data(request: SendRequest):
            """发送串口数据"""
            if self._send_serial_data:
                success = self._send_serial_data(
                    port=request.port,
                    data=request.data,
                    mode=request.mode
                )
                if success:
                    return StatusResponse(status="ok", message="Data sent")
                else:
                    raise HTTPException(status_code=400, detail="Failed to send data")
            raise HTTPException(status_code=503, detail="Serial port not available")

        @self.app.get("/api/health")
        async def health_check():
            """健康检查"""
            return {"status": "healthy"}

        @self.app.get("/api/camera/devices")
        async def list_camera_devices(refresh: bool = True):
            """列出本机可用摄像头（refresh=true 时重新扫描，支持热插拔）"""
            cam = self._camera_broadcaster
            if cam is None:
                raise HTTPException(status_code=503, detail="Video service not available")
            if not cam.is_available():
                raise HTTPException(status_code=503, detail="opencv-python not installed")
            return {"devices": cam.enumerate_devices(refresh=refresh)}

        @self.app.get("/api/camera/status")
        async def get_camera_status():
            """获取视频捕获与 API 广播状态"""
            cam = self._camera_broadcaster
            if cam is None:
                raise HTTPException(status_code=503, detail="Video service not available")
            return StatusResponse(status="ok", data=cam.get_status())

        @self.app.post("/api/camera/broadcast")
        async def set_camera_broadcast(request: VideoBroadcastRequest):
            """控制视频捕获与 API 广播（默认均关闭，需显式开启）"""
            cam = self._camera_broadcaster
            if cam is None:
                raise HTTPException(status_code=503, detail="Video service not available")

            if request.fps is not None or request.jpeg_quality is not None:
                cam.configure(
                    fps=request.fps,
                    jpeg_quality=request.jpeg_quality,
                    width=request.width,
                    height=request.height,
                )
            elif request.width is not None or request.height is not None:
                cam.configure(width=request.width, height=request.height)

            if not request.enabled:
                cam.stop()
                return StatusResponse(
                    status="ok",
                    message="Video capture stopped",
                    data=cam.get_status(),
                )

            if request.source_type == "http":
                if not request.url:
                    raise HTTPException(status_code=400, detail="url is required for http source")
                if not cam.start_http(request.url):
                    raise HTTPException(
                        status_code=400,
                        detail=cam.get_status().get("last_error", "Failed to start HTTP stream"),
                    )
            else:
                if not cam.is_available():
                    raise HTTPException(status_code=503, detail="opencv-python not installed")
                if not cam.start_local(
                    device_index=request.device_index,
                    width=request.width,
                    height=request.height,
                ):
                    raise HTTPException(
                        status_code=400,
                        detail=cam.get_status().get("last_error", "Failed to start camera"),
                    )

            if not request.capture_only:
                cam.set_api_broadcast(True)

            return StatusResponse(
                status="ok",
                message="Video capture started",
                data=cam.get_status(),
            )

        @self.app.post("/api/camera/api-broadcast")
        async def toggle_api_broadcast(enabled: bool):
            """单独开关 API 广播（需已处于捕获状态）"""
            cam = self._camera_broadcaster
            if cam is None:
                raise HTTPException(status_code=503, detail="Video service not available")
            if not cam.set_api_broadcast(enabled):
                raise HTTPException(
                    status_code=400,
                    detail=cam.get_status().get("last_error", "Cannot toggle API broadcast"),
                )
            return StatusResponse(status="ok", data=cam.get_status())

        @self.app.get("/api/camera/snapshot")
        async def get_camera_snapshot():
            """获取当前帧 JPEG 快照（需已开启 API 广播）"""
            cam = self._camera_broadcaster
            if cam is None:
                raise HTTPException(status_code=503, detail="Video service not available")
            if not cam.api_broadcast_enabled:
                raise HTTPException(status_code=503, detail="API broadcast is not enabled")
            jpeg = cam.get_snapshot()
            if jpeg is None:
                raise HTTPException(status_code=503, detail="No frame available yet")
            return Response(content=jpeg, media_type="image/jpeg")

        @self.app.get("/api/camera/stream")
        async def get_camera_stream():
            """MJPEG 视频流（需已开启 API 广播）"""
            cam = self._camera_broadcaster
            if cam is None:
                raise HTTPException(status_code=503, detail="Video service not available")
            if not cam.api_broadcast_enabled:
                raise HTTPException(status_code=503, detail="API broadcast is not enabled")

            return StreamingResponse(
                cam.iter_mjpeg(),
                media_type="multipart/x-mixed-replace; boundary=frame",
            )

    def start(self):
        """启动服务器（在独立线程）"""
        if self._thread and self._thread.is_alive():
            logger.warning("API server already running")
            return

        # 预先同步检查端口可用性，避免异步启动后才发现绑定失败
        check_port_available(self.host, self.port)

        def run_server():
            """在线程中运行 asyncio 事件循环"""
            self._loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self._loop)

            config = uvicorn.Config(
                self.app,
                host=self.host,
                port=self.port,
                log_level="info",
                loop="asyncio"
            )
            self._server = uvicorn.Server(config)
            self._loop.run_until_complete(self._server.serve())

        self._thread = threading.Thread(target=run_server, daemon=True)
        self._thread.start()
        logger.info(f"API server started at http://{self.host}:{self.port}")

    def stop(self):
        """停止服务器"""
        # 先触发 uvicorn 优雅关闭
        if self._server and self._loop:
            asyncio.run_coroutine_threadsafe(
                self._server.shutdown(), self._loop
            )
        # 再停止事件循环
        if self._loop:
            self._loop.call_soon_threadsafe(self._loop.stop)
        if self._thread:
            self._thread.join(timeout=5)
        self._server = None
        logger.info("API server stopped")
