"""主窗口模块 - 串口助手 V3.0 插件化架构 + 网络服务 + 设置对话框"""

import os
import json
import logging
import importlib

from PyQt5.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QGroupBox, QLabel, QComboBox, QPushButton, QLineEdit, QSpinBox, QCheckBox,
    QMessageBox, QTabWidget, QSizePolicy, QFrame, QStackedWidget, QSplitter
)
from PyQt5.QtCore import Qt, QThread, QTimer
from PyQt5.QtGui import QFont

from .serial_core import SerialWorker, get_available_ports
from .channel.udp_channel import UdpWorker
from .tabs.base_tab import SerialTab
from .tabs.lazy_tab import LazyTabWrapper
from serial_assistant.style import DARK_STYLESHEET, LIGHT_STYLESHEET
from .service_manager import ServiceManager
from .settings_dialog import SettingsDialog
from .style import LED_ON, LED_OFF, LED_ERR
from app_paths import config_path as _app_config_path

logger = logging.getLogger(__name__)


def _config_path(filename: str) -> str:
    """获取 config/ 目录下配置文件的绝对路径"""
    return _app_config_path(filename)


# ── 服务面板描述表（有序，用于数据驱动 UI 构建）──────────────────
_SERVICE_ROWS = [
    {"key": "api", "label": "API 服务",  "cfg_key": "api_server",       "default_port": 8000, "tooltip": "提供 HTTP 接口，供外部程序/脚本发送串口指令"},
    {"key": "ws",  "label": "WebSocket", "cfg_key": "websocket_server", "default_port": 8001, "tooltip": "允许网页或其他客户端实时双向收发串口数据"},
    {"key": "tcp", "label": "TCP 服务",  "cfg_key": "tcp_server",       "default_port": 9999, "tooltip": "将串口透传到网络，支持多个 TCP 客户端直接连接"},
    {"key": "mcp", "label": "MCP 桥接",  "cfg_key": None,               "default_port": None, "tooltip": "Model Context Protocol 接口，供 AI 助手直接接管串口读写"},
]


class MainWindow(QMainWindow):
    """串口助手主窗口 - 插件化 Tab 容器"""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("串口助手 V1.0")
        self.resize(1280, 800)
        self.setMinimumSize(1040, 700)

        # ── 通道工作对象和读取线程 ──
        self._serial_worker = SerialWorker()
        self._serial_thread = QThread()
        self._serial_worker.moveToThread(self._serial_thread)
        self._serial_thread.started.connect(self._serial_worker.read_loop)

        self._udp_worker = UdpWorker()
        self._udp_thread = QThread()
        self._udp_worker.moveToThread(self._udp_thread)
        self._udp_thread.started.connect(self._udp_worker.read_loop)

        for w in (self._serial_worker, self._udp_worker):
            w.data_received.connect(self._on_data_received)
            w.error_occurred.connect(self._on_channel_error)
            w.closed_unexpected.connect(self._on_port_unplugged)

        # 兼容旧引用
        self._worker = self._serial_worker
        self._thread = self._serial_thread

        # ── 应用配置 ──
        self._app_config: dict = {}
        self._is_light_theme = False
        self._load_app_config()
        self._broadcast_all: bool = (
            self._app_config.get("settings", {})
                            .get("data_broadcast_mode", "active_tab") == "all_tabs"
        )

        # ── 服务管理器 ──
        self._svc = ServiceManager(self)
        self._svc.set_callbacks(
            get_ports=get_available_ports,
            send_data=self._api_send_data,
            get_status=self._get_app_status,
            get_main_window=lambda: self,
        )
        self._svc.state_changed.connect(self._on_service_state_changed)
        self._svc.error_occurred.connect(self._on_service_error)
        self._svc.tcp_client_count_changed.connect(self._on_tcp_count_changed)
        self._svc.tcp_data_received.connect(self._on_tcp_data_received)

        # ── Tab 实例字典 {tab_id: instance} ──
        self._tab_instances: dict = {}

        # ── LED / 按钮引用（数据驱动构建时填充）──
        self._service_leds:  dict = {}
        self._service_btns:  dict = {}
        self._service_ports: dict = {}

        # ── 构建 UI ──
        self._init_ui()
        self.setStyleSheet(DARK_STYLESHEET)
        self._update_ui_state(is_open=False)

        # ── 延迟初始化（避免阻塞启动帧渲染）──
        QTimer.singleShot(100, self._load_tabs_lazy)
        QTimer.singleShot(300, self._init_network_services)
        QTimer.singleShot(400, self._init_mcp_services)

    # ══════════════════ 配置加载 ══════════════════════════════════

    def _load_app_config(self):
        config_file = _config_path("app.json")
        if os.path.exists(config_file):
            try:
                with open(config_file, "r", encoding="utf-8") as f:
                    self._app_config = json.load(f)
                logger.info(f"Loaded app config from {config_file}")
            except Exception as e:
                logger.error(f"Failed to load app config: {e}")
                self._app_config = {}
        else:
            logger.warning("App config not found, using defaults")

    def _get_network_config(self, cfg_key: str) -> dict:
        defaults = {
            "api_server":       {"enabled": False, "host": "127.0.0.1", "port": 8000},
            "websocket_server": {"enabled": False, "host": "127.0.0.1", "port": 8001},
            "tcp_server":       {"enabled": False, "host": "0.0.0.0",   "port": 9999},
        }
        return self._app_config.get("network", {}).get(cfg_key, defaults.get(cfg_key, {}))

    # ══════════════════ UI 构建 ═══════════════════════════════════

    def _init_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QHBoxLayout(central)
        main_layout.setContentsMargins(8, 8, 8, 8)
        main_layout.setSpacing(8)

        main_splitter = QSplitter(Qt.Horizontal)
        main_splitter.setChildrenCollapsible(False)
        main_splitter.setHandleWidth(8)
        main_layout.addWidget(main_splitter)

        # ── 左侧：Tab 容器 ──
        self._tab_widget = QTabWidget()
        
        # ── 右上角工具栏 (主题、设置) ──
        corner_widget = QWidget()
        corner_layout = QHBoxLayout(corner_widget)
        corner_layout.setContentsMargins(0, 0, 5, 0)
        corner_layout.setSpacing(8)

        self.btn_theme = QPushButton("🌙 夜间")
        self.btn_theme.setObjectName("theme_toggle")
        self.btn_theme.setCheckable(True)
        self.btn_theme.setChecked(False)  # 默认深色
        self.btn_theme.setCursor(Qt.PointingHandCursor)
        self.btn_theme.clicked.connect(self._toggle_theme)
        
        btn_settings = QPushButton("⚙ 设置")
        btn_settings.setObjectName("settings_btn")
        btn_settings.setCursor(Qt.PointingHandCursor)
        btn_settings.clicked.connect(self._on_open_settings)

        btn_help = QPushButton("? 帮助")
        btn_help.setObjectName("help_btn")
        btn_help.setCursor(Qt.PointingHandCursor)
        btn_help.setToolTip("使用说明、功能列表与更新日志")
        btn_help.clicked.connect(self._on_open_help)

        corner_layout.addWidget(self.btn_theme)
        corner_layout.addWidget(btn_help)
        corner_layout.addWidget(btn_settings)
        
        self._tab_widget.setCornerWidget(corner_widget, Qt.TopRightCorner)
        
        main_splitter.addWidget(self._tab_widget)

        # ── 右侧：控制面板 ──
        right_widget = QWidget()
        right_widget.setMinimumWidth(220)
        right_widget.setMaximumWidth(300)
        right_widget.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)
        right_layout = QVBoxLayout(right_widget)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(8)
        right_layout.addWidget(self._build_serial_config_group())
        right_layout.addWidget(self._build_services_group())
        right_layout.addStretch(1)

        main_splitter.addWidget(right_widget)
        main_splitter.setStretchFactor(0, 1)
        main_splitter.setStretchFactor(1, 0)
        main_splitter.setSizes([1020, 260])

    def _build_serial_config_group(self) -> QGroupBox:
        """通道配置面板"""
        group = QGroupBox("通道配置")
        main_layout = QVBoxLayout(group)
        main_layout.setContentsMargins(8, 18, 8, 8)
        main_layout.setSpacing(8)

        def label(text):
            l = QLabel(text)
            l.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            return l

        # 通道类型选择
        type_row = QHBoxLayout()
        type_row.addWidget(label("通道类型"))
        self.cb_channel_type = QComboBox()
        self.cb_channel_type.addItems(["UART 串口", "UDP 网络"])
        self.cb_channel_type.currentIndexChanged.connect(self._on_channel_type_changed)
        type_row.addWidget(self.cb_channel_type, stretch=1)
        main_layout.addLayout(type_row)

        self.stack_channel = QStackedWidget()

        # --- UART Page ---
        uart_page = QWidget()
        grid = QGridLayout(uart_page)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(5)

        # 串口号行（含刷新按钮）
        grid.addWidget(label("串口号"), 0, 0)
        port_row = QHBoxLayout()
        port_row.setSpacing(4)
        port_row.setContentsMargins(0, 0, 0, 0)
        self.cb_port = QComboBox()
        self.cb_port.setEditable(False)
        port_row.addWidget(self.cb_port, stretch=1)
        btn_refresh = QPushButton("刷新")
        btn_refresh.setFixedSize(55, 26)
        btn_refresh.setToolTip("刷新串口列表")
        btn_refresh.clicked.connect(self._refresh_ports)
        port_row.addWidget(btn_refresh)
        port_container = QWidget()
        port_container.setLayout(port_row)
        grid.addWidget(port_container, 0, 1)

        grid.addWidget(label("波特率"), 1, 0)
        self.cb_baudrate = QComboBox()
        # 从配置读取默认值
        default_baud = (self._app_config.get("serial_defaults", {})
                                        .get("baudrate", "9600"))
        self.cb_baudrate.addItems(["4800", "9600", "19200", "38400",
                                   "57600", "115200", "230400", "460800", "921600"])
        self.cb_baudrate.setEditable(True)
        self.cb_baudrate.setCurrentText(default_baud)
        grid.addWidget(self.cb_baudrate, 1, 1)

        grid.addWidget(label("数据位"), 2, 0)
        self.cb_databits = QComboBox()
        self.cb_databits.addItems(["5", "6", "7", "8"])
        self.cb_databits.setCurrentText(
            self._app_config.get("serial_defaults", {}).get("databits", "8"))
        grid.addWidget(self.cb_databits, 2, 1)

        grid.addWidget(label("停止位"), 3, 0)
        self.cb_stopbits = QComboBox()
        self.cb_stopbits.addItems(["1", "1.5", "2"])
        self.cb_stopbits.setCurrentText(
            self._app_config.get("serial_defaults", {}).get("stopbits", "1"))
        grid.addWidget(self.cb_stopbits, 3, 1)

        grid.addWidget(label("校验位"), 4, 0)
        self.cb_parity = QComboBox()
        self.cb_parity.addItems(["无", "奇", "偶"])
        self.cb_parity.setCurrentText(
            self._app_config.get("serial_defaults", {}).get("parity", "无"))
        grid.addWidget(self.cb_parity, 4, 1)
        
        self.stack_channel.addWidget(uart_page)

        # --- UDP Page ---
        udp_page = QWidget()
        udp_grid = QGridLayout(udp_page)
        udp_grid.setContentsMargins(0, 0, 0, 0)
        udp_grid.setHorizontalSpacing(8)
        udp_grid.setVerticalSpacing(5)

        udp_defaults = self._app_config.get("udp_defaults", {})

        def udp_label(text):
            l = QLabel(text)
            l.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            return l

        udp_grid.addWidget(udp_label("本地地址"), 0, 0)
        self.edit_udp_local_host = QLineEdit(
            udp_defaults.get("local_host", "0.0.0.0"))
        udp_grid.addWidget(self.edit_udp_local_host, 0, 1)

        udp_grid.addWidget(udp_label("本地端口"), 1, 0)
        self.spin_udp_local_port = QSpinBox()
        self.spin_udp_local_port.setRange(1, 65535)
        self.spin_udp_local_port.setValue(int(udp_defaults.get("local_port", 8888)))
        udp_grid.addWidget(self.spin_udp_local_port, 1, 1)

        udp_grid.addWidget(udp_label("远端地址"), 2, 0)
        self.edit_udp_remote_host = QLineEdit(
            udp_defaults.get("remote_host", "127.0.0.1"))
        udp_grid.addWidget(self.edit_udp_remote_host, 2, 1)

        udp_grid.addWidget(udp_label("远端端口"), 3, 0)
        self.spin_udp_remote_port = QSpinBox()
        self.spin_udp_remote_port.setRange(0, 65535)
        self.spin_udp_remote_port.setValue(int(udp_defaults.get("remote_port", 8889)))
        udp_grid.addWidget(self.spin_udp_remote_port, 3, 1)

        self.chk_udp_reply_last = QCheckBox("无固定远端时回包到最近对端")
        self.chk_udp_reply_last.setChecked(
            bool(udp_defaults.get("reply_to_last", True)))
        udp_grid.addWidget(self.chk_udp_reply_last, 4, 0, 1, 2)

        self.stack_channel.addWidget(udp_page)

        main_layout.addWidget(self.stack_channel)

        # 打开按钮
        self.btn_open = QPushButton("打开通道")
        self.btn_open.setObjectName("btn_open_port")
        self.btn_open.setMinimumHeight(30)
        self.btn_open.clicked.connect(self._on_toggle_port)
        main_layout.addWidget(self.btn_open)

        return group

    def _build_services_group(self) -> QGroupBox:
        """网络服务控制面板（数据驱动生成各行）"""
        group = QGroupBox("网络服务")
        layout = QVBoxLayout(group)
        layout.setContentsMargins(8, 18, 8, 8)
        layout.setSpacing(4)

        for row_def in _SERVICE_ROWS:
            key      = row_def["key"]
            label    = row_def["label"]
            cfg_key  = row_def["cfg_key"]
            def_port = row_def["default_port"]
            tooltip  = row_def["tooltip"]

            card = QFrame()
            card.setObjectName("service_card")
            card.setToolTip(tooltip)
            row = QHBoxLayout(card)
            row.setContentsMargins(6, 4, 6, 4)
            row.setSpacing(4)

            # LED 指示灯
            led = QLabel("●")
            led.setStyleSheet(f"color: {LED_OFF};")
            led.setFixedWidth(14)
            row.addWidget(led)
            self._service_leds[key] = led

            # 标签
            lbl = QLabel(label)
            lbl.setFixedWidth(65)
            row.addWidget(lbl)

            # 端口 / 监听地址标签（MCP 无端口号）
            if def_port is not None:
                svc_cfg = self._get_network_config(cfg_key) if cfg_key else {}
                host_val = svc_cfg.get("host", "127.0.0.1")
                port_val = svc_cfg.get("port", def_port)
                from network.utils import format_service_bind_label
                bind_text = format_service_bind_label(host_val, port_val)
                port_lbl = QLabel(bind_text)
                port_lbl.setStyleSheet("color: #565F89; font-size: 10px;")
                port_lbl.setMinimumWidth(88)
                row.addWidget(port_lbl)
                self._service_ports[key] = port_lbl
            else:
                row.addSpacing(44)

            row.addStretch(1)

            # 启停按钮
            btn_text = "激活" if key == "mcp" else "启动"
            btn = QPushButton(btn_text)
            btn.setFixedWidth(54)
            btn.setFixedHeight(22)
            btn.setEnabled(False)
            btn.clicked.connect(lambda checked, k=key: self._svc.toggle(k))
            row.addWidget(btn)
            self._service_btns[key] = btn

            layout.addWidget(card)

            # TCP 专属：客户端数量显示
            if key == "tcp":
                self._tcp_client_label = QLabel("  客户端: 0")
                self._tcp_client_label.setStyleSheet(
                    "color: #565F89; font-size: 11px; padding-left: 16px;"
                )
                layout.addWidget(self._tcp_client_label)

        return group

    # ══════════════════ Tab 懒加载 ════════════════════════════════

    def _load_tabs_lazy(self):
        """懒加载 Tab：仅第一个立即创建，其余用占位符延迟加载"""
        config_file = _config_path("tabs.json")
        if not os.path.exists(config_file):
            logger.warning(f"Config file {config_file} not found, using defaults")
            self._load_default_tabs()
            self._on_all_tabs_loaded()
            return

        try:
            with open(config_file, "r", encoding="utf-8") as f:
                config = json.load(f)
        except Exception as e:
            logger.error(f"Failed to load tabs config: {e}")
            self._load_default_tabs()
            self._on_all_tabs_loaded()
            return

        tabs_config = config.get("tabs", [])
        if not tabs_config:
            self._load_default_tabs()
            self._on_all_tabs_loaded()
            return

        tabs_config.sort(key=lambda x: x.get("order", 999))
        self._load_failures = []
        self._tab_widget.currentChanged.connect(self._on_tab_changed)

        first_loaded = False
        for tab_cfg in tabs_config:
            tab_id     = tab_cfg.get("tab_id")
            title      = tab_cfg.get("title", tab_id)
            module_name= tab_cfg.get("module")
            class_name = tab_cfg.get("class")
            enabled    = tab_cfg.get("enabled", True)

            if not enabled or not all([tab_id, module_name, class_name]):
                continue

            if not first_loaded:
                try:
                    module    = importlib.import_module(module_name)
                    tab_class = getattr(module, class_name, None)
                    if tab_class is None:
                        raise AttributeError(
                            f"Class {class_name} not found in {module_name}"
                        )
                    instance = tab_class()
                    self._tab_instances[tab_id] = instance
                    self._tab_widget.addTab(instance, title)
                    first_loaded = True
                    logger.info(f"Loaded first tab immediately: {tab_id}")
                except Exception as e:
                    logger.error(f"Failed to load first tab {tab_id}: {e}", exc_info=True)
                    self._load_failures.append(
                        {"tab_id": tab_id, "title": title, "error": str(e)}
                    )
                    wrapper = LazyTabWrapper(module_name, class_name, title)
                    self._tab_instances[tab_id] = wrapper
                    self._tab_widget.addTab(wrapper, title)
                    first_loaded = True
            else:
                wrapper = LazyTabWrapper(module_name, class_name, title)
                self._tab_instances[tab_id] = wrapper
                self._tab_widget.addTab(wrapper, title)

        for tab_instance in self._tab_instances.values():
            if hasattr(tab_instance, "set_serial_worker"):
                tab_instance.set_serial_worker(self._active_worker())

        self._apply_settings_to_tabs()
        self._wire_camera_broadcaster()
        self._on_all_tabs_loaded()

    def _on_tab_changed(self, index: int):
        """Tab 切换：触发懒加载"""
        if index < 0:
            return
        tab = self._tab_widget.widget(index)
        if isinstance(tab, LazyTabWrapper) and not tab.is_loaded:
            tab.ensure_loaded()

    def _toggle_theme(self):
        self._is_light_theme = not self._is_light_theme
        if self._is_light_theme:
            self.setStyleSheet(LIGHT_STYLESHEET)
            self.btn_theme.setText("🌞 白天")
            self.btn_theme.setChecked(True)
        else:
            self.setStyleSheet(DARK_STYLESHEET)
            self.btn_theme.setText("🌙 夜间")
            self.btn_theme.setChecked(False)

    def _on_all_tabs_loaded(self):
        failures = getattr(self, "_load_failures", [])
        if failures:
            msg_lines = ["以下功能模块因缺少依赖无法加载：\n"]
            for f in failures:
                msg_lines.append(f"  • {f['title']} — {f['error']}")
            msg_lines.append("\n请安装缺少的依赖后重启应用：")
            msg_lines.append("  pip install pyqtgraph numpy Pillow")
            QMessageBox.warning(self, "模块加载失败", "\n".join(msg_lines))
        QTimer.singleShot(100, self._auto_start_services)

    def _load_default_tabs(self):
        """降级方案：直接导入内置 Tab"""
        self._tab_widget.currentChanged.connect(self._on_tab_changed)
        failures = []
        try:
            from .tabs.basic_tab import BasicSerialTab
            self._tab_instances["basic_serial"] = BasicSerialTab()
            self._tab_widget.addTab(self._tab_instances["basic_serial"], "基础串口")
            self._apply_settings_to_tabs()
        except Exception as e:
            logger.error(f"Failed to load BasicSerialTab: {e}")
            failures.append(("基础串口", str(e)))

        for tab_id, module, cls, title in [
            ("oscilloscope",   "serial_assistant.tabs.oscilloscope_tab", "OscilloscopeTab", "示波器"),
            ("image_transfer", "serial_assistant.tabs.image_tab",        "ImageTab",        "图传(Beta)"),
        ]:
            wrapper = LazyTabWrapper(module, cls, title)
            self._tab_instances[tab_id] = wrapper
            self._tab_widget.addTab(wrapper, title)

        if failures:
            msg = "\n".join(f"  • {n}: {e}" for n, e in failures)
            QMessageBox.warning(self, "警告", f"以下模块加载失败：\n{msg}")

    # ══════════════════ 服务初始化 ════════════════════════════════

    def _init_network_services(self):
        """延迟导入重型依赖并初始化 API / WS / TCP"""
        network_cfg = self._app_config.get("network", {})
        ok = self._svc.init_network(network_cfg)
        if ok:
            # 启用服务按钮
            for key in ("api", "ws", "tcp"):
                btn = self._service_btns.get(key)
                if btn:
                    btn.setEnabled(True)
            self._refresh_service_bind_labels()
            self._wire_camera_broadcaster()
        else:
            logger.info("Network services not available")

    def _refresh_service_bind_labels(self):
        """根据 app.json 刷新服务面板的 host:port 显示"""
        from network.utils import format_service_bind_label
        for row_def in _SERVICE_ROWS:
            key = row_def["key"]
            cfg_key = row_def["cfg_key"]
            if not cfg_key:
                continue
            lbl = self._service_ports.get(key)
            if not lbl:
                continue
            cfg = self._get_network_config(cfg_key)
            host = cfg.get("host", "127.0.0.1")
            port = self._svc.get_network_port(key) or cfg.get("port", row_def["default_port"])
            lbl.setText(format_service_bind_label(host, port))

    def _get_api_access_bases(self) -> list:
        """根据 API 监听配置生成可访问的 URL 前缀（含局域网地址）"""
        from network.utils import api_access_bases
        cfg = self._get_network_config("api_server")
        host = cfg.get("host", "127.0.0.1")
        port = self._svc.get_network_port("api") or cfg.get("port", 8000)
        return api_access_bases(host, port)

    def _wire_camera_broadcaster(self):
        """将摄像头广播服务注入支持图传的 Tab"""
        cam = self._svc.get_camera_broadcaster()
        if cam is None:
            return
        cfg = self._get_network_config("api_server")
        api_port = self._svc.get_network_port("api") or cfg.get("port", 8000)
        api_host = cfg.get("host", "127.0.0.1")
        for tab_instance in self._tab_instances.values():
            if hasattr(tab_instance, "set_camera_broadcaster"):
                tab_instance.set_camera_broadcaster(
                    cam, api_host, api_port, self._get_api_access_bases
                )

    def _refresh_api_urls_in_tabs(self):
        """设置或 API 服务变更后，刷新图传页中的访问地址"""
        self._wire_camera_broadcaster()
        for tab_instance in self._tab_instances.values():
            loaded = getattr(tab_instance, "_loaded_tab", None)
            target = loaded if loaded is not None else tab_instance
            if hasattr(target, "_sync_stream_ui"):
                try:
                    target._sync_stream_ui()
                except Exception:
                    pass

    def _init_mcp_services(self):
        """延迟导入并初始化 MCP 桥接"""
        ok = self._svc.init_mcp()
        if ok:
            btn = self._service_btns.get("mcp")
            if btn:
                btn.setEnabled(True)
        else:
            logger.info("MCP services not available")

    def _auto_start_services(self):
        """根据 app.json enabled 字段自动启动服务"""
        network_cfg = self._app_config.get("network", {})
        self._svc.auto_start(network_cfg)

    # ══════════════════ 服务信号响应 ═════════════════════════════

    def _on_service_state_changed(self, key: str, is_running: bool):
        """更新 LED 颜色和按钮文字"""
        led = self._service_leds.get(key)
        btn = self._service_btns.get(key)

        if led:
            led.setStyleSheet(f"color: {LED_ON if is_running else LED_OFF};")

        if btn:
            if key == "mcp":
                btn.setText("停用" if is_running else "激活")
            else:
                btn.setText("停止" if is_running else "启动")

        if key == "api":
            self._refresh_api_urls_in_tabs()

    def _on_service_error(self, key: str, error_msg: str):
        """服务启动失败：LED 变红 + 对话框提示"""
        led = self._service_leds.get(key)
        if led:
            led.setStyleSheet(f"color: {LED_ERR};")
        QMessageBox.warning(self, "服务错误", f"【{key.upper()}】启动失败：\n{error_msg}")

    def _on_tcp_count_changed(self, count: int):
        self._tcp_client_label.setText(f"  客户端: {count}")

    # ══════════════════ 设置对话框 ════════════════════════════════

    def _on_open_help(self):
        from .help_dialog import HelpDialog
        HelpDialog(self).exec_()

    def _on_open_settings(self):
        dlg = SettingsDialog(self._app_config, parent=self)
        if dlg.exec_() == SettingsDialog.Accepted:
            new_cfg = dlg.get_config()
            self._app_config = new_cfg
            # 实时生效：广播模式
            self._broadcast_all = (
                new_cfg.get("settings", {})
                        .get("data_broadcast_mode", "active_tab") == "all_tabs"
            )
            self._refresh_service_bind_labels()
            self._refresh_api_urls_in_tabs()
            self._apply_settings_to_tabs()
            logger.info("Settings updated")

    def _apply_settings_to_tabs(self):
        for tab in self._tab_instances.values():
            if hasattr(tab, "apply_app_settings"):
                tab.apply_app_settings(self._app_config)
            elif getattr(tab, "is_loaded", False) and getattr(tab, "_loaded_tab", None):
                inst = tab._loaded_tab
                if hasattr(inst, "apply_app_settings"):
                    inst.apply_app_settings(self._app_config)

    # ══════════════════ 事件处理 ══════════════════════════════════

    def showEvent(self, event):
        super().showEvent(event)
        self._refresh_ports()

    def _is_udp_channel(self) -> bool:
        return self.cb_channel_type.currentIndex() == 1

    def _active_worker(self):
        return self._udp_worker if self._is_udp_channel() else self._serial_worker

    def _active_thread(self) -> QThread:
        return self._udp_thread if self._is_udp_channel() else self._serial_thread

    def _on_channel_type_changed(self, idx: int):
        self.stack_channel.setCurrentIndex(idx)
        self._wire_workers_to_tabs()

    def _wire_workers_to_tabs(self):
        worker = self._active_worker()
        for tab_instance in self._tab_instances.values():
            if hasattr(tab_instance, "set_serial_worker"):
                tab_instance.set_serial_worker(worker)

    def _refresh_ports(self):
        current = self.cb_port.currentText()
        self.cb_port.clear()
        ports = get_available_ports()
        self.cb_port.addItems(ports)
        if current in ports:
            self.cb_port.setCurrentText(current)

    def _on_toggle_port(self):
        if self._active_worker().is_open():
            self._close_port()
        else:
            self._open_port()

    def _open_port(self):
        if self._is_udp_channel():
            success = self._udp_worker.open_channel(
                local_host=self.edit_udp_local_host.text().strip() or "0.0.0.0",
                local_port=int(self.spin_udp_local_port.value()),
                remote_host=self.edit_udp_remote_host.text().strip(),
                remote_port=int(self.spin_udp_remote_port.value()),
                reply_to_last=self.chk_udp_reply_last.isChecked(),
            )
        else:
            port = self.cb_port.currentText()
            if not port:
                QMessageBox.warning(self, "提示", "请先选择串口")
                return
            try:
                baud = int(self.cb_baudrate.currentText().strip())
            except ValueError:
                QMessageBox.warning(self, "提示", "波特率必须是整数")
                return
            success = self._serial_worker.open_channel(
                port=port,
                baudrate=baud,
                data_bits=int(self.cb_databits.currentText()),
                stop_bits=float(self.cb_stopbits.currentText()),
                parity=self.cb_parity.currentText(),
            )
        if success:
            self._active_thread().start()
            self._update_ui_state(is_open=True)
            self._notify_tabs(is_open=True)

    def _close_port(self):
        worker = self._active_worker()
        thread = self._active_thread()
        worker.close_channel()
        thread.quit()
        if not thread.wait(2000):
            logger.warning("Channel read thread did not finish in 2s")
        self._update_ui_state(is_open=False)
        self._notify_tabs(is_open=False)
        self._reset_all_tabs()

    def _on_data_received(self, data: bytes):
        """串口数据分发：发给 Tab + 网络广播"""
        # 1. 分发给 Tab（按设置的广播模式）
        if self._broadcast_all:
            for tab_instance in self._tab_instances.values():
                if hasattr(tab_instance, "on_data_received"):
                    tab_instance.on_data_received(data)
        else:
            tab = self._tab_widget.currentWidget()
            if isinstance(tab, SerialTab):
                tab.on_data_received(data)

        # 2. 广播到网络（WebSocket + TCP）
        self._svc.broadcast_serial_data(data)

    def _on_channel_error(self, message: str):
        if not getattr(self, "_error_shown", False):
            self._error_shown = True
            QMessageBox.warning(self, "通道错误", message)
            self._error_shown = False

    def _on_serial_error(self, message: str):
        self._on_channel_error(message)

    def _on_port_unplugged(self):
        self._close_port()

    def _on_tcp_data_received(self, data: bytes):
        """TCP 客户端发来的数据 → 转发到当前通道"""
        if self._active_worker().is_open():
            self._active_worker().send_data(data)

    def _notify_tabs(self, is_open: bool):
        for tab_instance in self._tab_instances.values():
            if hasattr(tab_instance, "on_port_toggled"):
                tab_instance.on_port_toggled(is_open)

    def _reset_all_tabs(self):
        for tab_instance in self._tab_instances.values():
            if hasattr(tab_instance, "reset_state"):
                tab_instance.reset_state()

    def _update_ui_state(self, is_open: bool):
        if is_open:
            self.btn_open.setText("关闭通道")
            self.btn_open.setStyleSheet(
                "background-color: #4A1C1C; color: #E06C75;"
                "border: 1px solid #E06C75; border-radius: 6px;"
                "font-weight: bold;"
            )
        else:
            self.btn_open.setText("打开通道")
            self.btn_open.setStyleSheet(
                "background-color: #1A3A28; color: #98C379;"
                "border: 1px solid #98C379; border-radius: 6px;"
                "font-weight: bold;"
            )
        for cb in (self.cb_channel_type, self.cb_port, self.cb_baudrate, self.cb_databits,
                   self.cb_stopbits, self.cb_parity,
                   self.edit_udp_local_host, self.spin_udp_local_port,
                   self.edit_udp_remote_host, self.spin_udp_remote_port,
                   self.chk_udp_reply_last):
            cb.setEnabled(not is_open)

    # ══════════════════ API 回调 ══════════════════════════════════

    def _api_send_data(self, port: str, data: str, mode: str) -> bool:
        if not self._active_worker().is_open():
            return False
        try:
            raw = (bytes.fromhex(data.replace(" ", ""))
                   if mode == "hex" else data.encode("utf-8"))
            self._active_worker().send_data(raw)
            return True
        except Exception:
            return False

    def _get_app_status(self) -> dict:
        return {
            "version":     "3.0",
            "serial_open": self._active_worker().is_open(),
            "channel":     "udp" if self._is_udp_channel() else "uart",
            "active_tab":  self._tab_widget.tabText(self._tab_widget.currentIndex()),
            "tab_count":   self._tab_widget.count(),
            "services":    self._svc.export_status(),
        }

    # ══════════════════ 窗口关闭 ══════════════════════════════════

    def closeEvent(self, event):
        if self._serial_worker.is_open():
            self.cb_channel_type.setCurrentIndex(0)
            self._close_port()
        elif self._udp_worker.is_open():
            self.cb_channel_type.setCurrentIndex(1)
            self._close_port()

        # 停止所有网络服务（ServiceManager 内部处理顺序）
        self._svc.stop_all()

        # 清理 Tab 资源
        for tab_instance in self._tab_instances.values():
            if hasattr(tab_instance, "cleanup"):
                try:
                    tab_instance.cleanup()
                except Exception:
                    pass

        event.accept()
