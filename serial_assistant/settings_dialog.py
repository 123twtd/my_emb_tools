"""设置对话框 - 非常用配置集中管理

成熟软件的分层设计：
- 常用配置（串口参数、打开/关闭）保留在主界面
- 非常用配置（端口号、广播模式等）集中在本对话框
"""

import copy
import json
import logging
import os

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QGridLayout,
    QTabWidget, QWidget, QGroupBox, QLabel,
    QCheckBox, QLineEdit, QSpinBox, QComboBox,
    QPushButton, QDialogButtonBox, QMessageBox,
    QRadioButton, QButtonGroup, QFrame,
)

logger = logging.getLogger(__name__)

from .widgets.key_sequence_capture import KeySequenceCaptureWidget, DEFAULT_SEND_SHORTCUT

# 配置文件路径（以本文件为基准）
from app_paths import config_path

_CONFIG_PATH = config_path("app.json")


class SettingsDialog(QDialog):
    """应用设置对话框

    读取 app.json，以分 Tab 的方式呈现非常用配置。
    点击"保存"后写回文件并通知调用方。
    """

    def __init__(self, config: dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle("设置")
        self.setMinimumSize(480, 380)
        self.setModal(True)

        # 深拷贝，避免用户取消时污染原始配置
        self._cfg = copy.deepcopy(config)

        self._init_ui()
        self._load_values()

    # ── UI 构建 ────────────────────────────────────────

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        layout.setContentsMargins(12, 12, 12, 12)

        self._tabs = QTabWidget()
        self._tabs.addTab(self._build_network_tab(),     "网络服务")
        self._tabs.addTab(self._build_display_tab(),     "显示与行为")
        self._tabs.addTab(self._build_send_tab(),        "发送")
        self._tabs.addTab(self._build_serial_tab(),      "串口默认值")
        layout.addWidget(self._tabs, stretch=1)

        # 底部按钮
        btn_box = QDialogButtonBox(
            QDialogButtonBox.Save | QDialogButtonBox.Cancel
        )
        btn_box.button(QDialogButtonBox.Save).setText("保存")
        btn_box.button(QDialogButtonBox.Cancel).setText("取消")
        btn_box.accepted.connect(self._on_save)
        btn_box.rejected.connect(self.reject)
        layout.addWidget(btn_box)

    # ── 网络服务 Tab ───────────────────────────────────

    def _build_network_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        note = QLabel(
            "⚠ 端口号修改后，需重启对应服务才能生效。\n"
            "局域网访问：API / TCP 监听地址填 0.0.0.0（允许其他设备连接）。"
        )
        note.setStyleSheet("color: #CCAA00; font-size: 11px;")
        layout.addWidget(note)

        SERVICE_DEFS = [
            ("API 服务",   "api_server",       "0.0.0.0", 8000),
            ("WebSocket",  "websocket_server", "127.0.0.1", 8001),
            ("TCP 服务",   "tcp_server",       "0.0.0.0",   9999),
        ]

        self._net_enabled = {}
        self._net_host    = {}
        self._net_port    = {}

        for label, cfg_key, def_host, def_port in SERVICE_DEFS:
            group = QGroupBox(label)
            grid  = QGridLayout(group)
            grid.setContentsMargins(8, 14, 8, 8)
            grid.setHorizontalSpacing(8)
            grid.setVerticalSpacing(4)

            cb_enabled = QCheckBox("启用")
            grid.addWidget(cb_enabled, 0, 0, 1, 2)
            self._net_enabled[cfg_key] = cb_enabled

            grid.addWidget(QLabel("监听地址:"), 1, 0)
            ed_host = QLineEdit(def_host)
            ed_host.setPlaceholderText(def_host)
            grid.addWidget(ed_host, 1, 1)
            self._net_host[cfg_key] = ed_host

            grid.addWidget(QLabel("端口:"), 2, 0)
            sp_port = QSpinBox()
            sp_port.setRange(1024, 65535)
            sp_port.setValue(def_port)
            grid.addWidget(sp_port, 2, 1)
            self._net_port[cfg_key] = sp_port

            layout.addWidget(group)

        layout.addStretch(1)
        return widget

    # ── 显示与行为 Tab ─────────────────────────────────

    def _build_display_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(10)

        # 串口数据分发模式
        group_data = QGroupBox("串口数据分发")
        vl = QVBoxLayout(group_data)
        vl.setContentsMargins(8, 14, 8, 8)

        desc = QLabel(
            "控制收到的串口数据发给哪些 Tab。\n"
            "「仅当前 Tab」节省 CPU；「广播到所有 Tab」保证示波器等后台 Tab 不丢数据。"
        )
        desc.setWordWrap(True)
        desc.setStyleSheet("color: #888; font-size: 11px;")
        vl.addWidget(desc)

        self._rb_active = QRadioButton("仅发送给当前活动 Tab（推荐，低 CPU 占用）")
        self._rb_all    = QRadioButton("广播到所有已加载的 Tab（示波器后台不丢数据）")
        self._rb_group  = QButtonGroup(self)
        self._rb_group.addButton(self._rb_active, 0)
        self._rb_group.addButton(self._rb_all,    1)
        self._rb_active.setChecked(True)
        vl.addWidget(self._rb_active)
        vl.addWidget(self._rb_all)
        layout.addWidget(group_data)

        # 接收区行为
        group_recv = QGroupBox("接收区")
        gl = QGridLayout(group_recv)
        gl.setContentsMargins(8, 14, 8, 8)

        self._cb_auto_scroll = QCheckBox("新数据到来时自动滚动到底部")
        self._cb_auto_scroll.setChecked(True)
        gl.addWidget(self._cb_auto_scroll, 0, 0)

        gl.addWidget(QLabel("最大显示行数 (0=不限):"), 1, 0)
        self._sp_max_lines = QSpinBox()
        self._sp_max_lines.setRange(0, 100000)
        self._sp_max_lines.setValue(0)
        self._sp_max_lines.setSuffix(" 行")
        gl.addWidget(self._sp_max_lines, 1, 1)

        gl.addWidget(QLabel("接收区上限 (字节):"), 2, 0)
        self._sp_max_bytes = QSpinBox()
        self._sp_max_bytes.setRange(0, 100_000_000)
        self._sp_max_bytes.setSingleStep(65536)
        self._sp_max_bytes.setValue(1048576)
        self._sp_max_bytes.setSuffix(" B")
        self._sp_max_bytes.setToolTip("0=不限；超出后删除最旧内容，防止长时间抓包卡死")
        gl.addWidget(self._sp_max_bytes, 2, 1)

        layout.addWidget(group_recv)
        layout.addStretch(1)
        return widget

    # ── 发送 Tab ───────────────────────────────────────

    def _build_send_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(10)

        group = QGroupBox("发送行为")
        grid = QGridLayout(group)
        grid.setContentsMargins(8, 14, 8, 8)

        grid.addWidget(QLabel("发送快捷键:"), 0, 0)
        self._key_capture = KeySequenceCaptureWidget(DEFAULT_SEND_SHORTCUT)
        grid.addWidget(self._key_capture, 0, 1)

        grid.addWidget(QLabel("发送历史条数:"), 1, 0)
        self._sp_history_max = QSpinBox()
        self._sp_history_max.setRange(5, 500)
        self._sp_history_max.setValue(20)
        grid.addWidget(self._sp_history_max, 1, 1)

        grid.addWidget(QLabel("接收落盘路径:"), 2, 0)
        self._ed_log_path = QLineEdit()
        self._ed_log_path.setPlaceholderText("留空则在勾选「接收落盘」时选择文件")
        grid.addWidget(self._ed_log_path, 2, 1)

        layout.addWidget(group)
        layout.addStretch(1)
        return widget

    # ── 串口默认值 Tab ─────────────────────────────────

    def _build_serial_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        group = QGroupBox("启动时的默认参数")
        grid  = QGridLayout(group)
        grid.setContentsMargins(8, 14, 8, 8)
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(6)

        grid.addWidget(QLabel("默认波特率:"), 0, 0)
        self._cb_def_baud = QComboBox()
        self._cb_def_baud.addItems(["4800", "9600", "19200", "38400", "57600",
                                    "115200", "230400", "460800", "921600"])
        self._cb_def_baud.setCurrentText("9600")
        grid.addWidget(self._cb_def_baud, 0, 1)

        grid.addWidget(QLabel("默认数据位:"), 1, 0)
        self._cb_def_data = QComboBox()
        self._cb_def_data.addItems(["5", "6", "7", "8"])
        self._cb_def_data.setCurrentText("8")
        grid.addWidget(self._cb_def_data, 1, 1)

        grid.addWidget(QLabel("默认停止位:"), 2, 0)
        self._cb_def_stop = QComboBox()
        self._cb_def_stop.addItems(["1", "1.5", "2"])
        self._cb_def_stop.setCurrentText("1")
        grid.addWidget(self._cb_def_stop, 2, 1)

        grid.addWidget(QLabel("默认校验位:"), 3, 0)
        self._cb_def_parity = QComboBox()
        self._cb_def_parity.addItems(["无", "奇", "偶"])
        self._cb_def_parity.setCurrentText("无")
        grid.addWidget(self._cb_def_parity, 3, 1)

        layout.addWidget(group)
        layout.addStretch(1)
        return widget

    # ── 值加载 / 保存 ──────────────────────────────────

    def _load_values(self):
        """从 self._cfg 填充控件"""
        net_cfg = self._cfg.get("network", {})

        for cfg_key in ("api_server", "websocket_server", "tcp_server"):
            svc = net_cfg.get(cfg_key, {})
            self._net_enabled[cfg_key].setChecked(svc.get("enabled", False))
            self._net_host[cfg_key].setText(str(svc.get("host", "")))
            port = svc.get("port")
            if port:
                self._net_port[cfg_key].setValue(int(port))

        settings = self._cfg.get("settings", {})
        mode = settings.get("data_broadcast_mode", "active_tab")
        if mode == "all_tabs":
            self._rb_all.setChecked(True)
        else:
            self._rb_active.setChecked(True)

        self._cb_auto_scroll.setChecked(settings.get("auto_scroll", True))
        self._sp_max_lines.setValue(settings.get("max_recv_lines", 0))
        self._sp_max_bytes.setValue(settings.get("max_recv_bytes", 1048576))

        self._key_capture.set_sequence(settings.get("send_shortcut", DEFAULT_SEND_SHORTCUT))
        self._sp_history_max.setValue(settings.get("send_history_max", 20))
        self._ed_log_path.setText(settings.get("recv_log_path", "") or "")

        serial_defaults = self._cfg.get("serial_defaults", {})
        self._cb_def_baud.setCurrentText(str(serial_defaults.get("baudrate", "9600")))
        self._cb_def_data.setCurrentText(str(serial_defaults.get("databits", "8")))
        self._cb_def_stop.setCurrentText(str(serial_defaults.get("stopbits", "1")))
        self._cb_def_parity.setCurrentText(serial_defaults.get("parity", "无"))

    def _collect_values(self):
        """将控件值写回 self._cfg，失败返回 False"""
        net_cfg = self._cfg.setdefault("network", {})

        for cfg_key in ("api_server", "websocket_server", "tcp_server"):
            svc = net_cfg.setdefault(cfg_key, {})
            svc["enabled"] = self._net_enabled[cfg_key].isChecked()
            svc["host"]    = self._net_host[cfg_key].text().strip() or svc.get("host", "127.0.0.1")
            svc["port"]    = self._net_port[cfg_key].value()

        settings = self._cfg.setdefault("settings", {})
        settings["data_broadcast_mode"] = (
            "all_tabs" if self._rb_all.isChecked() else "active_tab"
        )
        settings["auto_scroll"]     = self._cb_auto_scroll.isChecked()
        settings["max_recv_lines"]  = self._sp_max_lines.value()
        settings["max_recv_bytes"] = self._sp_max_bytes.value()
        settings["send_shortcut"]   = self._key_capture.sequence()
        settings["send_history_max"] = self._sp_history_max.value()
        settings["recv_log_path"]   = self._ed_log_path.text().strip()

        serial_defaults = self._cfg.setdefault("serial_defaults", {})
        serial_defaults["baudrate"] = self._cb_def_baud.currentText()
        serial_defaults["databits"] = self._cb_def_data.currentText()
        serial_defaults["stopbits"] = self._cb_def_stop.currentText()
        serial_defaults["parity"]   = self._cb_def_parity.currentText()
        return True

    def _on_save(self):
        """保存配置到 app.json 并关闭对话框"""
        if self._collect_values() is False:
            return
        try:
            with open(_CONFIG_PATH, "w", encoding="utf-8") as f:
                json.dump(self._cfg, f, ensure_ascii=False, indent=2)
            logger.info(f"Settings saved to {_CONFIG_PATH}")
        except Exception as e:
            QMessageBox.warning(self, "保存失败", f"写入配置文件失败:\n{e}")
            return
        self.accept()

    def get_config(self) -> dict:
        """返回（可能已修改的）配置字典"""
        return self._cfg
