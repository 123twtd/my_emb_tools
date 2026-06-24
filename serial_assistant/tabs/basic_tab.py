"""基础串口 Tab"""

from __future__ import annotations

import json
from collections import deque
from datetime import datetime
from typing import Any, Deque, Dict, List, Optional

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QSplitter,
    QLabel, QComboBox, QPushButton, QTextEdit, QCheckBox, QSpinBox,
    QFileDialog, QMessageBox, QLineEdit, QFrame, QScrollArea, QSizePolicy,
)
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QFont, QKeySequence, QTextCursor, QTextCharFormat, QColor
from PyQt5.QtWidgets import QShortcut

from app_paths import config_path
from .base_tab import SerialTab
from ..parser_config_dialog import ParserManagerDialog
from ..rx_frame_parser import ParserConfig
from ..rx_parser_panel import RxParserPanel
from ..widgets.collapsible_section import CollapsibleSection
from ..widgets.poll_sequence_widget import PollSequenceWidget, migrate_poll_sequence
from ..utils import (
    bytes_to_hex, bytes_to_text, text_to_bytes, hex_to_bytes,
    parse_escape_sequences,
)

_CONFIG_PATH = config_path("app.json")


class BasicSerialTab(SerialTab):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._recv_buffer = bytearray()
        self._line_byte_buf = bytearray()
        self._rx_count = 0
        self._tx_count = 0
        self._auto_scroll = True
        self._max_recv_bytes = 1_048_576
        self._max_recv_lines = 0
        self._send_history_max = 20
        self._send_history: Deque[Dict[str, str]] = deque(maxlen=20)
        self._log_file_path = ""
        self._rx_display_buf = ""
        self._send_shortcut: Optional[QShortcut] = None
        self._parser_configs: List[ParserConfig] = []
        self._poll_items: List[Dict[str, Any]] = []
        self._poll_index = 0
        self._rx_splitter: Optional[QSplitter] = None
        self._main_splitter: Optional[QSplitter] = None
        self._send_splitter: Optional[QSplitter] = None

        self._periodic_timer = QTimer(self)
        self._periodic_timer.timeout.connect(self._on_periodic_send)
        self._poll_timer = QTimer(self)
        self._poll_timer.timeout.connect(self._on_poll_send)
        self._line_flush_timer = QTimer(self)
        self._line_flush_timer.setSingleShot(True)
        self._line_flush_timer.setInterval(80)
        self._line_flush_timer.timeout.connect(self._flush_partial_line)
        self._init_ui()

    def _init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)

        splitter = QSplitter(Qt.Vertical)
        self._main_splitter = splitter

        # ══════════════ 接收区 ══════════════
        recv_widget = QWidget()
        recv_layout = QVBoxLayout(recv_widget)
        recv_layout.setContentsMargins(8, 8, 8, 6)
        recv_layout.setSpacing(8)

        rx_row = QHBoxLayout()
        rx_row.setSpacing(10)
        rx_label = QLabel("接收")
        rx_label.setStyleSheet("font-weight: bold; color: #7AA2F7;")
        rx_row.addWidget(rx_label)

        self.cb_recv_mode = QComboBox()
        self.cb_recv_mode.addItems(["文本模式", "HEX模式"])
        self.cb_recv_mode.currentTextChanged.connect(self._on_rx_mode_changed)
        rx_row.addWidget(self.cb_recv_mode)

        self.cb_recv_encoding = QComboBox()
        self.cb_recv_encoding.addItems(["GBK", "UTF-8"])
        rx_row.addWidget(self.cb_recv_encoding)

        self.chk_line_mode = QCheckBox("按行")
        self.chk_line_mode.setChecked(False)
        self.chk_line_mode.setToolTip("遇到 \\r\\n 时换行；无换行仍显示（短延迟合并）")
        self.chk_line_mode.toggled.connect(self._update_rx_status_label)
        rx_row.addWidget(self.chk_line_mode)

        self.chk_rx_timestamp = QCheckBox("时间戳")
        self.chk_rx_timestamp.setToolTip("在每条显示内容前加 [HH:MM:SS.mmm]")
        self.chk_rx_timestamp.toggled.connect(self._update_rx_status_label)
        rx_row.addWidget(self.chk_rx_timestamp)

        self.chk_auto_scroll = QCheckBox("自动滚动")
        self.chk_auto_scroll.setChecked(True)
        self.chk_auto_scroll.setToolTip("勾选时新数据自动滚到最新；取消可冻结画面查看历史")
        self.chk_auto_scroll.toggled.connect(self._on_auto_scroll_toggled)
        rx_row.addWidget(self.chk_auto_scroll)

        rx_row.addStretch()

        self.lbl_rx_count = QLabel("Rx: 0")
        self.lbl_rx_count.setStyleSheet("color: #565F89;")
        rx_row.addWidget(self.lbl_rx_count)

        btn_export = QPushButton("导出")
        btn_export.setFixedHeight(26)
        btn_export.clicked.connect(self._export_receive)
        rx_row.addWidget(btn_export)

        btn_clear_recv = QPushButton("清空")
        btn_clear_recv.setFixedHeight(26)
        btn_clear_recv.clicked.connect(self._clear_rx)
        rx_row.addWidget(btn_clear_recv)

        recv_layout.addLayout(rx_row)

        # 过滤栏 — 常显于接收区上方
        filter_bar = QFrame()
        filter_bar.setObjectName("rxFilterBar")
        fl = QHBoxLayout(filter_bar)
        fl.setContentsMargins(10, 6, 10, 6)
        fl.setSpacing(10)
        fl.addWidget(QLabel("过滤"))
        self.chk_filter_enable = QCheckBox("启用")
        self.chk_filter_enable.toggled.connect(self._on_filter_enable_changed)
        fl.addWidget(self.chk_filter_enable)
        fl.addWidget(QLabel("关键字"))
        self.ed_filter = QLineEdit()
        self.ed_filter.setPlaceholderText("输入关键字")
        self.ed_filter.setEnabled(False)
        self.ed_filter.textChanged.connect(self._update_rx_status_label)
        fl.addWidget(self.ed_filter, stretch=1)
        fl.addWidget(QLabel("方式"))
        self.cb_filter_mode = QComboBox()
        self.cb_filter_mode.addItem("仅含关键字", "only")
        self.cb_filter_mode.addItem("高亮关键字", "highlight")
        self.cb_filter_mode.setFixedWidth(120)
        self.cb_filter_mode.setEnabled(False)
        self.cb_filter_mode.currentIndexChanged.connect(self._update_rx_status_label)
        fl.addWidget(self.cb_filter_mode)
        self.chk_auto_log = QCheckBox("持续落盘")
        self.chk_auto_log.toggled.connect(self._on_auto_log_toggled)
        fl.addWidget(self.chk_auto_log)

        fl.addWidget(self._vline())
        self.chk_parser = QCheckBox("指令解析")
        self.chk_parser.setToolTip("显示右侧解析面板")
        self.chk_parser.toggled.connect(self._on_parser_checkbox)
        fl.addWidget(self.chk_parser)
        self.btn_manage_parser = QPushButton("管理…")
        self.btn_manage_parser.setFixedHeight(24)
        self.btn_manage_parser.setToolTip("配置接收帧解析规则")
        self.btn_manage_parser.clicked.connect(self._on_manage_parsers)
        fl.addWidget(self.btn_manage_parser)

        recv_layout.addWidget(filter_bar)

        self.lbl_rx_status = QLabel("")
        self.lbl_rx_status.setObjectName("status_hint")
        recv_layout.addWidget(self.lbl_rx_status)

        self._rx_splitter = QSplitter(Qt.Horizontal)
        self.txt_receive = QTextEdit()
        self.txt_receive.setReadOnly(True)
        self.txt_receive.setFont(QFont("Consolas", 10))
        self.txt_receive.setTextInteractionFlags(Qt.NoTextInteraction)
        self.txt_receive.setFocusPolicy(Qt.NoFocus)
        self.txt_receive.setContextMenuPolicy(Qt.NoContextMenu)
        self._rx_splitter.addWidget(self.txt_receive)

        self.parser_panel = RxParserPanel()
        self.parser_panel.setMinimumWidth(180)
        self._rx_splitter.addWidget(self.parser_panel)
        self._parser_expanded = False
        self._set_parser_panel_visible(False)

        recv_layout.addWidget(self._rx_splitter, stretch=1)

        splitter.addWidget(recv_widget)

        # ══════════════ 发送区 ══════════════
        send_widget = QWidget()
        send_layout = QVBoxLayout(send_widget)
        send_layout.setContentsMargins(8, 8, 8, 6)
        send_layout.setSpacing(6)

        send_splitter = QSplitter(Qt.Vertical)
        self._send_splitter = send_splitter
        send_splitter.setChildrenCollapsible(False)
        send_splitter.setHandleWidth(8)

        send_core = QWidget()
        send_core_layout = QVBoxLayout(send_core)
        send_core_layout.setContentsMargins(0, 0, 0, 0)
        send_core_layout.setSpacing(6)

        tx_row = QHBoxLayout()
        tx_row.setSpacing(10)
        tx_label = QLabel("发送")
        tx_label.setStyleSheet("font-weight: bold; color: #98C379;")
        tx_row.addWidget(tx_label)

        self.cb_send_mode = QComboBox()
        self.cb_send_mode.addItems(["文本模式", "HEX模式"])
        self.cb_send_mode.currentTextChanged.connect(self._on_tx_mode_changed)
        tx_row.addWidget(self.cb_send_mode)

        self.cb_send_encoding = QComboBox()
        self.cb_send_encoding.addItems(["GBK", "UTF-8"])
        tx_row.addWidget(self.cb_send_encoding)

        self.chk_append_newline = QCheckBox("新行")
        self.chk_append_newline.setChecked(True)
        tx_row.addWidget(self.chk_append_newline)

        self.cb_newline = QComboBox()
        self.cb_newline.addItem("\\r\\n", b"\r\n")
        self.cb_newline.addItem("\\n", b"\n")
        self.cb_newline.addItem("\\r", b"\r")
        self.cb_newline.setFixedWidth(68)
        tx_row.addWidget(self.cb_newline)

        self.chk_periodic = QCheckBox("定时")
        self.chk_periodic.setToolTip("按间隔重复发送下方输入框内容")
        self.chk_periodic.toggled.connect(self._on_periodic_toggled)
        tx_row.addWidget(self.chk_periodic)

        self.spin_period_ms = QSpinBox()
        self.spin_period_ms.setRange(10, 600000)
        self.spin_period_ms.setValue(1000)
        self.spin_period_ms.setSuffix(" ms")
        self.spin_period_ms.setFixedWidth(92)
        self.spin_period_ms.valueChanged.connect(self._on_period_changed)
        tx_row.addWidget(self.spin_period_ms)

        self.chk_escape = QCheckBox("转义")
        self.chk_escape.setToolTip("发送 \\r \\n \\xNN 等转义序列")
        tx_row.addWidget(self.chk_escape)

        tx_row.addStretch()

        self.lbl_tx_count = QLabel("Tx: 0")
        tx_row.addWidget(self.lbl_tx_count)

        btn_clear_send = QPushButton("清空")
        btn_clear_send.setFixedHeight(26)
        btn_clear_send.clicked.connect(self._clear_tx)
        tx_row.addWidget(btn_clear_send)

        self.btn_send = QPushButton("发送")
        self.btn_send.setObjectName("btn_send_primary")
        self.btn_send.setFixedHeight(26)
        self.btn_send.setEnabled(False)
        self.btn_send.clicked.connect(self._on_send)
        tx_row.addWidget(self.btn_send)

        send_core_layout.addLayout(tx_row)

        self.txt_send = QTextEdit()
        self.txt_send.setFont(QFont("Consolas", 10))
        self.txt_send.setMinimumHeight(72)
        self.txt_send.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        send_core_layout.addWidget(self.txt_send, stretch=1)

        hist_row = QHBoxLayout()
        hist_row.addWidget(QLabel("历史"))
        self.combo_history = QComboBox()
        self.combo_history.activated.connect(self._on_history_selected)
        hist_row.addWidget(self.combo_history, stretch=1)
        send_core_layout.addLayout(hist_row)

        send_splitter.addWidget(send_core)

        # 发送扩展区（参数化 / 轮询）— 可滚动，避免撑破窗口
        send_extras = QWidget()
        extras_layout = QVBoxLayout(send_extras)
        extras_layout.setContentsMargins(0, 0, 0, 0)
        extras_layout.setSpacing(4)

        self._sec_tx_adv = CollapsibleSection("发送序列", collapsed=True)
        self._sec_tx_adv.toggled.connect(self._on_send_extras_toggled)
        adv = self._sec_tx_adv.body_layout()

        row_poll = QHBoxLayout()
        row_poll.setSpacing(10)
        self.chk_poll = QCheckBox("启用轮询")
        self.chk_poll.setToolTip("按间隔依次发送表中勾选的指令；可拖动行号调整顺序")
        self.chk_poll.toggled.connect(self._on_poll_toggled)
        row_poll.addWidget(self.chk_poll)
        row_poll.addWidget(QLabel("间隔"))
        self.spin_poll_ms = QSpinBox()
        self.spin_poll_ms.setRange(10, 600000)
        self.spin_poll_ms.setValue(100)
        self.spin_poll_ms.setSuffix(" ms")
        self.spin_poll_ms.setFixedWidth(92)
        self.spin_poll_ms.setToolTip("轮询每条指令之间的等待时间")
        self.spin_poll_ms.valueChanged.connect(self._on_poll_period_changed)
        row_poll.addWidget(self.spin_poll_ms)
        self.btn_send_once_row = QPushButton("发选中行")
        self.btn_send_once_row.setFixedHeight(26)
        self.btn_send_once_row.setToolTip("对表格当前选中行发送一次（含自增/列表逻辑）")
        self.btn_send_once_row.clicked.connect(self._on_send_selected_row)
        row_poll.addWidget(self.btn_send_once_row)
        self.lbl_poll_status = QLabel("")
        self.lbl_poll_status.setObjectName("status_hint")
        row_poll.addWidget(self.lbl_poll_status, stretch=1)
        adv.addLayout(row_poll)

        self.poll_table = PollSequenceWidget()
        self.poll_table.changed.connect(self._on_poll_table_changed)
        self.poll_table.set_fill_from_input_callback(
            lambda: self.txt_send.toPlainText()
        )
        adv.addWidget(self.poll_table, stretch=1)

        extras_layout.addWidget(self._sec_tx_adv)

        extras_scroll = QScrollArea()
        extras_scroll.setWidgetResizable(True)
        extras_scroll.setFrameShape(QFrame.NoFrame)
        extras_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        extras_scroll.setWidget(send_extras)
        extras_scroll.setMinimumHeight(0)
        send_splitter.addWidget(extras_scroll)

        send_splitter.setStretchFactor(0, 1)
        send_splitter.setStretchFactor(1, 0)
        send_splitter.setSizes([180, 100])

        send_layout.addWidget(send_splitter, stretch=1)

        splitter.addWidget(send_widget)
        splitter.setChildrenCollapsible(False)
        splitter.setHandleWidth(8)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
        splitter.setSizes([520, 280])
        main_layout.addWidget(splitter)

        self._bind_send_shortcut("Ctrl+Return")
        self._refresh_poll_status()
        self._update_rx_status_label()
        self._on_send_extras_toggled(False)

    def _vline(self) -> QFrame:
        line = QFrame()
        line.setFrameShape(QFrame.VLine)
        line.setFrameShadow(QFrame.Sunken)
        line.setFixedWidth(1)
        return line

    def _set_parser_panel_visible(self, visible: bool):
        self._parser_expanded = visible
        if not self._rx_splitter:
            return
        if visible:
            self.parser_panel.show()
            self.parser_panel.setMinimumWidth(180)
            self._rx_splitter.setSizes([820, 220])
        else:
            self._rx_splitter.setSizes([10000, 0])

    def _on_send_extras_toggled(self, expanded: bool):
        if not self._send_splitter:
            return
        if expanded:
            self._send_splitter.setSizes([280, 140])
            if self._main_splitter:
                self._main_splitter.setSizes([540, 260])
        else:
            self._send_splitter.setSizes([1, 0])

    def _on_parser_checkbox(self, on: bool):
        self._set_parser_panel_visible(on)
        self._save_ui_prefs(parser_panel=on)

    def _save_ui_prefs(self, parser_panel: bool | None = None):
        try:
            with open(_CONFIG_PATH, "r", encoding="utf-8") as f:
                cfg = json.load(f)
        except (OSError, json.JSONDecodeError):
            cfg = {}
        s = cfg.setdefault("settings", {})
        if parser_panel is not None:
            s["parser_panel_visible"] = parser_panel
        try:
            with open(_CONFIG_PATH, "w", encoding="utf-8") as f:
                json.dump(cfg, f, ensure_ascii=False, indent=2)
        except OSError:
            pass

    def _refresh_poll_status(self):
        items = self.poll_table.get_items()
        configured = [it for it in items if str(it.get("cmd", "")).strip()]
        n = len(configured)
        enabled = sum(1 for it in configured if it.get("enabled", True))
        ms = self.spin_poll_ms.value()
        if self.chk_poll.isChecked() and enabled:
            self.lbl_poll_status.setText(f"{enabled}/{n} 条 · 每 {ms} ms 发一条")
        elif n:
            self.lbl_poll_status.setText(f"{enabled}/{n} 条已配置 · 间隔 {ms} ms")
        else:
            self.lbl_poll_status.setText("在表格中添加指令")

    def _on_poll_table_changed(self):
        self._poll_items = self.poll_table.get_items()
        self._save_poll_sequence()
        self._refresh_poll_status()
        self._sync_timers()

    def _on_filter_enable_changed(self, enabled: bool):
        self.ed_filter.setEnabled(enabled)
        self.cb_filter_mode.setEnabled(enabled)
        self._update_rx_status_label()

    def _filter_active(self) -> bool:
        return self.chk_filter_enable.isChecked() and bool(self.ed_filter.text().strip())

    def _update_rx_status_label(self):
        parts = []
        if self.chk_line_mode.isChecked():
            parts.append("按行(遇换行)")
        else:
            parts.append("流式")
        if self.chk_rx_timestamp.isChecked():
            parts.append("时间戳")
        if self._filter_active():
            kw = self.ed_filter.text().strip()
            mode = self.cb_filter_mode.currentData()
            parts.append(f"过滤:{kw}" if mode == "only" else f"高亮:{kw}")
        if not self._auto_scroll:
            parts.append("滚动已关")
        self.lbl_rx_status.setText(" · ".join(parts) if parts else "")

    def _need_line_split(self) -> bool:
        if self.chk_line_mode.isChecked():
            return True
        return self._filter_active() and self.cb_filter_mode.currentData() == "only"

    def apply_app_settings(self, app_config: dict):
        settings = app_config.get("settings", {})
        self._max_recv_bytes = int(settings.get("max_recv_bytes", 1_048_576))
        self._max_recv_lines = int(settings.get("max_recv_lines", 0))
        self._send_history_max = max(1, int(settings.get("send_history_max", 20)))
        raw_hist = settings.get("send_history", []) or []
        self._send_history = deque(maxlen=self._send_history_max)
        for h in reversed(raw_hist):
            if isinstance(h, dict) and h.get("text"):
                self._send_history.appendleft({
                    "text": str(h["text"]),
                    "time": str(h.get("time", "")),
                })
        self._refresh_history_combo()
        self._log_file_path = settings.get("recv_log_path", "") or ""
        self._poll_items = migrate_poll_sequence(settings.get("poll_sequence", []))
        self.poll_table.set_items(self._poll_items)

        self._load_parsers(app_config.get("rx_parsers", []))
        self._bind_send_shortcut(settings.get("send_shortcut", "Ctrl+Return"))
        poll_ms = int(settings.get("poll_interval_ms", 100))
        self.spin_poll_ms.setValue(poll_ms)
        parser_on = bool(settings.get("parser_panel_visible", False))
        self.chk_parser.blockSignals(True)
        self.chk_parser.setChecked(parser_on)
        self.chk_parser.blockSignals(False)
        self._set_parser_panel_visible(parser_on)
        self._refresh_poll_status()

    # ── 解析配置 ──

    def _load_parsers(self, data: list):
        configs = []
        for item in data:
            if isinstance(item, dict):
                configs.append(ParserConfig.from_dict(item))
        self._parser_configs = configs
        self.parser_panel.set_parsers(configs)

    def _save_parsers(self):
        configs = self.parser_panel.enabled_configs()
        self._parser_configs = configs
        try:
            with open(_CONFIG_PATH, "r", encoding="utf-8") as f:
                cfg = json.load(f)
        except (OSError, json.JSONDecodeError):
            cfg = {}
        cfg["rx_parsers"] = [c.to_dict() for c in configs]
        try:
            with open(_CONFIG_PATH, "w", encoding="utf-8") as f:
                json.dump(cfg, f, ensure_ascii=False, indent=2)
        except OSError:
            pass

    def _bind_send_shortcut(self, seq: str):
        if self._send_shortcut:
            self._send_shortcut.deleteLater()
            self._send_shortcut = None
        self._send_shortcut = QShortcut(QKeySequence(seq), self.txt_send)
        self._send_shortcut.setContext(Qt.WidgetWithChildrenShortcut)
        self._send_shortcut.activated.connect(self._on_send)

    # ── 交互 ──

    def _on_manage_parsers(self):
        dlg = ParserManagerDialog(self._parser_configs, self)
        if dlg.exec_() != dlg.Accepted:
            return
        self._parser_configs = dlg.parsers()
        self.parser_panel.set_parsers(self._parser_configs)
        self._save_parsers()
        active = sum(1 for p in self._parser_configs if p.enabled)
        if active > 0:
            self.chk_parser.blockSignals(True)
            self.chk_parser.setChecked(True)
            self.chk_parser.blockSignals(False)
            self._set_parser_panel_visible(True)
            self._save_ui_prefs(parser_panel=True)
        elif self._parser_configs and active == 0:
            QMessageBox.information(
                self, "提示",
                "规则已保存。请在右侧勾选规则名称以启用，\n"
                "或编辑规则时勾选「保存后立即启用」。"
            )

    def _save_poll_sequence(self):
        self._poll_items = self.poll_table.items_for_persist()
        try:
            with open(_CONFIG_PATH, "r", encoding="utf-8") as f:
                cfg = json.load(f)
        except (OSError, json.JSONDecodeError):
            cfg = {}
        s = cfg.setdefault("settings", {})
        s["poll_sequence"] = self._poll_items
        s["poll_interval_ms"] = self.spin_poll_ms.value()
        try:
            with open(_CONFIG_PATH, "w", encoding="utf-8") as f:
                json.dump(cfg, f, ensure_ascii=False, indent=2)
        except OSError:
            pass

    def _save_send_history(self):
        try:
            with open(_CONFIG_PATH, "r", encoding="utf-8") as f:
                cfg = json.load(f)
        except (OSError, json.JSONDecodeError):
            cfg = {}
        cfg.setdefault("settings", {})["send_history"] = list(self._send_history)
        try:
            with open(_CONFIG_PATH, "w", encoding="utf-8") as f:
                json.dump(cfg, f, ensure_ascii=False, indent=2)
        except OSError:
            pass

    def _on_send_selected_row(self):
        row = self.poll_table.current_row()
        if row < 0:
            QMessageBox.information(self, "提示", "请先在表格中选中一行")
            return
        line = self.poll_table.send_once_row(row)
        if not line:
            return
        data = self._build_line_send_bytes(line)
        self._do_send(data, record_history=True, history_text=line)

    def _on_rx_mode_changed(self, mode: str):
        self.cb_recv_encoding.setEnabled(mode == "文本模式")
        self._line_byte_buf.clear()

    def _on_tx_mode_changed(self, mode: str):
        self.cb_send_encoding.setEnabled(mode == "文本模式")

    def _on_auto_scroll_toggled(self, on: bool):
        self._auto_scroll = on
        self._update_rx_status_label()
        if on:
            sb = self.txt_receive.verticalScrollBar()
            sb.setValue(sb.maximum())

    def _on_auto_log_toggled(self, enabled: bool):
        if not enabled:
            return
        if not self._log_file_path:
            path, _ = QFileDialog.getSaveFileName(
                self, "选择接收日志文件", "", "日志 (*.log);;文本 (*.txt)"
            )
            if not path:
                self.chk_auto_log.blockSignals(True)
                self.chk_auto_log.setChecked(False)
                self.chk_auto_log.blockSignals(False)
                return
            self._log_file_path = path

    def _on_history_selected(self, _index: int):
        item = self.combo_history.currentData()
        if item:
            self.txt_send.setPlainText(item)

    def _on_periodic_toggled(self, on: bool):
        if on:
            self.chk_poll.blockSignals(True)
            self.chk_poll.setChecked(False)
            self.chk_poll.blockSignals(False)
        self._sync_timers()

    def _on_poll_toggled(self, on: bool):
        if on:
            self.chk_periodic.blockSignals(True)
            self.chk_periodic.setChecked(False)
            self.chk_periodic.blockSignals(False)
            self.poll_table.reset_runtime_state()
            self._poll_index = 0
        self._sync_timers()

    def _on_period_changed(self, ms: int):
        if self._periodic_timer.isActive():
            self._periodic_timer.start(ms)

    def _on_poll_period_changed(self, ms: int):
        self._refresh_poll_status()
        if self._poll_timer.isActive():
            self._poll_timer.start(ms)
        self._save_poll_sequence()

    def _clear_rx(self):
        self._rx_display_buf = ""
        self.txt_receive.clear()
        self._rx_count = 0
        self._recv_buffer.clear()
        self._line_byte_buf.clear()
        self.lbl_rx_count.setText("Rx: 0")
        self.parser_panel.reset_all()

    def _clear_tx(self):
        self.txt_send.clear()
        self._tx_count = 0
        self.lbl_tx_count.setText("Tx: 0")

    def _export_receive(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "导出接收内容", "", "文本 (*.txt);;日志 (*.log)"
        )
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(self._rx_display_buf or self.txt_receive.toPlainText())
            QMessageBox.information(self, "导出成功", f"已保存到:\n{path}")
        except OSError as e:
            QMessageBox.warning(self, "导出失败", str(e))

    def _timestamp_prefix(self) -> str:
        now = datetime.now()
        return f"[{now.strftime('%H:%M:%S')}.{now.microsecond // 1000:03d}] "

    def _passes_line_filter(self, text: str) -> bool:
        if not self._filter_active():
            return True
        if self.cb_filter_mode.currentData() != "only":
            return True
        return self.ed_filter.text().strip() in text

    def _should_highlight(self) -> bool:
        return self._filter_active() and self.cb_filter_mode.currentData() == "highlight"

    def _append_receive_text(self, text: str):
        if not text:
            return

        te = self.txt_receive
        sb = te.verticalScrollBar()
        was_at_bottom = sb.value() >= max(0, sb.maximum() - 4)

        if self.chk_rx_timestamp.isChecked():
            text = self._timestamp_prefix() + text

        self._rx_display_buf += text
        trimmed = self._trim_rx_buffer()
        if trimmed:
            te.setPlainText(self._rx_display_buf)
        else:
            self._insert_receive_at_end(te, text)

        if self._auto_scroll and was_at_bottom:
            sb.setValue(sb.maximum())

    def _emit_rx_text(self, text: str, for_display: bool = True):
        """统一出口：先落盘完整行，再按过滤规则显示"""
        if not text:
            return
        self._append_to_log_file(text)
        if not for_display:
            return
        if not self._passes_line_filter(text):
            return
        self._append_receive_text(text)

    def _insert_receive_at_end(self, te: QTextEdit, text: str):
        cursor = te.textCursor()
        cursor.movePosition(QTextCursor.End)
        kw = self.ed_filter.text().strip()
        if kw and self._should_highlight() and kw in text:
            fmt_norm = QTextCharFormat()
            fmt_hi = QTextCharFormat()
            fmt_hi.setForeground(QColor("#E0AF68"))
            fmt_hi.setFontWeight(QFont.Bold)
            parts = text.split(kw)
            for i, part in enumerate(parts):
                if part:
                    cursor.insertText(part, fmt_norm)
                if i < len(parts) - 1:
                    cursor.insertText(kw, fmt_hi)
        else:
            cursor.insertText(text)
        cursor.movePosition(QTextCursor.End)
        te.setTextCursor(cursor)

    def _trim_rx_buffer(self) -> bool:
        """截断内部缓冲；若内容有变返回 True（需整页刷新）"""
        changed = False
        if self._max_recv_lines > 0:
            lines = self._rx_display_buf.splitlines(keepends=True)
            if len(lines) > self._max_recv_lines:
                self._rx_display_buf = "".join(lines[-self._max_recv_lines:])
                changed = True
        if self._max_recv_bytes > 0:
            enc = self._rx_display_buf.encode("utf-8")
            if len(enc) > self._max_recv_bytes:
                self._rx_display_buf = enc[-self._max_recv_bytes:].decode("utf-8", errors="ignore")
                changed = True
        return changed

    def _append_to_log_file(self, text: str):
        if not self.chk_auto_log.isChecked() or not self._log_file_path:
            return
        if self.chk_rx_timestamp.isChecked() and text and not text.startswith("["):
            text = self._timestamp_prefix() + text
        try:
            with open(self._log_file_path, "a", encoding="utf-8") as f:
                f.write(text)
        except OSError:
            pass

    def _split_lines_bytes(self, data: bytes) -> List[bytes]:
        self._line_byte_buf.extend(data)
        lines: List[bytes] = []
        buf = self._line_byte_buf
        i = 0
        while i < len(buf):
            if buf[i] == 0x0D:
                if i + 1 < len(buf) and buf[i + 1] == 0x0A:
                    lines.append(bytes(buf[:i]))
                    del buf[:i + 2]
                    i = 0
                    continue
                lines.append(bytes(buf[:i]))
                del buf[:i + 1]
                i = 0
                continue
            if buf[i] == 0x0A:
                lines.append(bytes(buf[:i]))
                del buf[:i + 1]
                i = 0
                continue
            i += 1
        return lines

    def _format_rx_chunk(self, data: bytes, is_line: bool) -> str:
        hex_mode = self.cb_recv_mode.currentText() == "HEX模式"
        if hex_mode:
            body = bytes_to_hex(data)
            if is_line and not body.endswith("\n"):
                body += "\n"
            return body
        encoding = self.cb_recv_encoding.currentText()
        if is_line:
            text = data.decode(encoding, errors="replace")
            if not text.endswith("\n"):
                text += "\n"
            return text
        return bytes_to_text(data, encoding, self._recv_buffer)

    def _flush_partial_line(self):
        """无换行的残留内容，短延迟后仍显示一行"""
        if not self._line_byte_buf:
            return
        chunk = bytes(self._line_byte_buf)
        self._line_byte_buf.clear()
        self._emit_rx_text(self._format_rx_chunk(chunk, is_line=True))

    def _dispatch_rx(self, data: bytes):
        if self._need_line_split():
            lines = self._split_lines_bytes(data)
            for line in lines:
                self._emit_rx_text(self._format_rx_chunk(line, is_line=True))
            if self.chk_line_mode.isChecked() and self._line_byte_buf:
                self._line_flush_timer.start(80)
        else:
            text = self._format_rx_chunk(data, is_line=False)
            if text:
                self._emit_rx_text(text)

    def on_data_received(self, data: bytes):
        self._rx_count += len(data)
        self.lbl_rx_count.setText(f"Rx: {self._rx_count}")

        self.parser_panel.feed_all(data)
        self._dispatch_rx(data)

    def _is_port_open(self) -> bool:
        if not self._serial_worker:
            return False
        if callable(self._serial_worker.is_open):
            return self._serial_worker.is_open()
        return bool(self._serial_worker.is_open)

    def _newline_suffix(self) -> bytes:
        if not self.chk_append_newline.isChecked():
            return b""
        return bytes(self.cb_newline.currentData() or b"\r\n")

    def _text_to_send_bytes(self, text: str) -> bytes:
        use_escape = self.chk_escape.isChecked()
        if self.cb_send_mode.currentText() == "HEX模式":
            return parse_escape_sequences(text) if use_escape else hex_to_bytes(text)
        encoding = self.cb_send_encoding.currentText()
        return parse_escape_sequences(text) if use_escape else text_to_bytes(text, encoding)

    def _build_line_send_bytes(self, text: str) -> bytes:
        """单条文本 → 字节（含转义 + 顶栏「新行」后缀，与手动发送一致）"""
        if not text:
            return b""
        data = self._text_to_send_bytes(text)
        suffix = self._newline_suffix()
        return data + suffix if suffix else data

    def _build_send_bytes(self) -> bytes:
        return self._build_line_send_bytes(self.txt_send.toPlainText())

    def _push_history(self, text: str):
        if not text:
            return
        for i, item in enumerate(self._send_history):
            if item["text"] == text:
                self._send_history.remove(item)
                break
        self._send_history.appendleft({
            "text": text,
            "time": datetime.now().strftime("%H:%M:%S"),
        })
        self._refresh_history_combo()
        self._save_send_history()

    def _refresh_history_combo(self):
        self.combo_history.blockSignals(True)
        self.combo_history.clear()
        for item in self._send_history:
            label = f"{item['time']}  {item['text'][:48]}"
            self.combo_history.addItem(label, item["text"])
        self.combo_history.blockSignals(False)

    def _do_send(self, data: bytes, record_history: bool = True, history_text: str = "") -> bool:
        if not data or not self._is_port_open():
            return False
        if hasattr(self._serial_worker, "send_data"):
            self._serial_worker.send_data(data)
        else:
            self._serial_worker.send(data)
        self._tx_count += len(data)
        self.lbl_tx_count.setText(f"Tx: {self._tx_count}")
        if record_history:
            preview = history_text or self.txt_send.toPlainText().strip()
            if preview:
                self._push_history(preview)
        return True

    def _sync_timers(self):
        pms = self.spin_period_ms.value()
        poll_ms = self.spin_poll_ms.value()
        if self.chk_periodic.isChecked() and self._is_port_open():
            self._periodic_timer.start(pms)
        else:
            self._periodic_timer.stop()
        enabled = self.poll_table.enabled_items_with_index()
        if self.chk_poll.isChecked() and self._is_port_open() and enabled:
            self._poll_timer.start(poll_ms)
        else:
            self._poll_timer.stop()
        self._refresh_poll_status()

    def _on_periodic_send(self):
        self._do_send(self._build_send_bytes())

    def _on_poll_send(self):
        enabled = self.poll_table.enabled_items_with_index()
        if not enabled:
            return
        n = len(enabled)
        for _ in range(n):
            idx = self._poll_index % n
            row_i, item = enabled[idx]
            self._poll_index += 1
            if self.poll_table.row_skipped_in_poll(row_i, item):
                continue
            line = self.poll_table.resolve_cmd(row_i, item)
            if line:
                data = self._build_line_send_bytes(line)
                self._do_send(data, record_history=True, history_text=line)
                return

    def _on_send(self):
        self._do_send(self._build_send_bytes())

    def on_port_toggled(self, is_open: bool):
        self.btn_send.setEnabled(is_open)
        self._sync_timers()

    def reset_state(self):
        self._recv_buffer.clear()
        self._line_byte_buf.clear()
        self._periodic_timer.stop()
        self._poll_timer.stop()

    def cleanup(self):
        self._periodic_timer.stop()
        self._poll_timer.stop()
        self._save_send_history()
        self._save_poll_sequence()
