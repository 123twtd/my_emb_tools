"""MCP Server - Model Context Protocol 桥接服务"""

import asyncio
import json
import logging
import threading
from typing import Optional, Callable

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent, ImageContent, Resource

logger = logging.getLogger(__name__)


class MCPServerBridge:
    """
    MCP Server 桥接器

    功能：
    - 暴露串口操作为 MCP Tools
    - 暴露 UI 状态为 MCP Resources
    - 支持 stdio 传输模式
    """

    def __init__(self, ui_exporter):
        """
        Args:
            ui_exporter: UIExporter 实例
        """
        self.server = Server("serial-assistant-v3")
        self.ui_exporter = ui_exporter
        self._thread: Optional[threading.Thread] = None
        self._running = False

        self._setup_tools()
        self._setup_resources()

    def _setup_tools(self):
        """设置 MCP Tools"""

        @self.server.list_tools()
        async def list_tools():
            return [
                Tool(
                    name="get_serial_ports",
                    description="列出所有可用串口",
                    inputSchema={
                        "type": "object",
                        "properties": {},
                        "required": []
                    }
                ),
                Tool(
                    name="send_serial_data",
                    description="通过串口发送数据",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "port": {
                                "type": "string",
                                "description": "串口名称，如 COM3"
                            },
                            "data": {
                                "type": "string",
                                "description": "要发送的数据"
                            },
                            "mode": {
                                "type": "string",
                                "enum": ["text", "hex"],
                                "description": "发送模式：text 或 hex",
                                "default": "text"
                            }
                        },
                        "required": ["port", "data"]
                    }
                ),
                Tool(
                    name="capture_ui_snapshot",
                    description="捕获当前 UI 状态（截图 + 配置）",
                    inputSchema={
                        "type": "object",
                        "properties": {},
                        "required": []
                    }
                ),
                Tool(
                    name="get_app_status",
                    description="获取应用状态信息",
                    inputSchema={
                        "type": "object",
                        "properties": {},
                        "required": []
                    }
                )
            ]

        @self.server.call_tool()
        async def call_tool(name: str, arguments: dict):
            try:
                if name == "get_serial_ports":
                    ports = self.ui_exporter.get_serial_ports()
                    return [TextContent(
                        type="text",
                        text=json.dumps({"ports": ports}, ensure_ascii=False)
                    )]

                elif name == "send_serial_data":
                    result = self.ui_exporter.send_serial_data(
                        port=arguments.get("port", ""),
                        data=arguments.get("data", ""),
                        mode=arguments.get("mode", "text")
                    )
                    return [TextContent(
                        type="text",
                        text=json.dumps(result, ensure_ascii=False)
                    )]

                elif name == "capture_ui_snapshot":
                    # 获取截图
                    screenshot_b64 = self.ui_exporter.capture_screenshot()
                    # 获取状态
                    state = self.ui_exporter.export_ui_state()

                    results = []

                    # 添加截图
                    if screenshot_b64:
                        results.append(ImageContent(
                            type="image",
                            data=screenshot_b64,
                            mimeType="image/png"
                        ))

                    # 添加状态
                    results.append(TextContent(
                        type="text",
                        text=json.dumps(state, ensure_ascii=False, indent=2)
                    ))

                    return results

                elif name == "get_app_status":
                    state = self.ui_exporter.export_ui_state()
                    return [TextContent(
                        type="text",
                        text=json.dumps(state, ensure_ascii=False, indent=2)
                    )]

                else:
                    return [TextContent(
                        type="text",
                        text=json.dumps({"error": f"Unknown tool: {name}"})
                    )]

            except Exception as e:
                logger.error(f"Tool call error: {e}")
                return [TextContent(
                    type="text",
                    text=json.dumps({"error": str(e)})
                )]

    def _setup_resources(self):
        """设置 MCP Resources"""

        @self.server.list_resources()
        async def list_resources():
            return [
                Resource(
                    uri="serial://ports",
                    name="Available Serial Ports",
                    mimeType="application/json",
                    description="List of available serial ports"
                ),
                Resource(
                    uri="app://status",
                    name="Application Status",
                    mimeType="application/json",
                    description="Current application status"
                )
            ]

        @self.server.read_resource()
        async def read_resource(uri):
            # mcp >= 1.0 传入 AnyUrl 对象，str() 兼容旧版字符串形式
            uri_str = str(uri)
            try:
                if uri_str == "serial://ports":
                    ports = self.ui_exporter.get_serial_ports()
                    return json.dumps({"ports": ports}, ensure_ascii=False)

                elif uri_str == "app://status":
                    state = self.ui_exporter.export_ui_state()
                    return json.dumps(state, ensure_ascii=False, indent=2)

                else:
                    return json.dumps({"error": f"Unknown resource: {uri_str}"})

            except Exception as e:
                logger.error(f"Resource read error: {e}")
                return json.dumps({"error": str(e)})

    def start(self):
        """启动 MCP Server（在独立线程）"""
        if self._running:
            logger.warning("MCP server already running")
            return

        self._running = True

        def run_server():
            """在线程中运行 asyncio 事件循环"""
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(self._serve())

        self._thread = threading.Thread(target=run_server, daemon=True)
        self._thread.start()
        logger.info("MCP server started")

    async def _serve(self):
        """运行 MCP Server"""
        async with stdio_server() as (read_stream, write_stream):
            await self.server.run(
                read_stream,
                write_stream,
                self.server.create_initialization_options()
            )

    def stop(self):
        """停止 MCP Server"""
        self._running = False
        if self._thread:
            self._thread.join(timeout=5)
        logger.info("MCP server stopped")
