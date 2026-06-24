"""接收解析实时显示面板 — 表格展示 + 1s 帧率"""

from __future__ import annotations

import time
from collections import deque
from typing import Deque, Dict, List

from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QFont
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QCheckBox,
    QPushButton, QTextEdit, QScrollArea, QFrame, QGridLayout,
)

from .rx_frame_parser import ParsedFrame, ParserConfig, RxFrameParser

_CELL_STYLE = (
    "border: 1px solid #3B4261; padding: 3px 6px; "
    "font-family: Consolas; font-size: 11px;"
)
_HEAD_STYLE = _CELL_STYLE + " color: #7AA2F7; font-weight: bold;"
_VAL_STYLE = _CELL_STYLE + " color: #98C379;"


class _ParserBlock(QFrame):
    def __init__(self, config: ParserConfig, parent=None):
        super().__init__(parent)
        self.config = config
        self.parser = RxFrameParser(config)
        self._history: Deque[str] = deque(maxlen=max(10, config.history_max))
        self._frame_times: Deque[float] = deque()
        self._last_frame: ParsedFrame | None = None

        self.setFrameShape(QFrame.StyledPanel)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 4, 6, 4)
        layout.setSpacing(4)

        head = QHBoxLayout()
        self.chk_enable = QCheckBox(config.name)
        self.chk_enable.setChecked(config.enabled)
        self.chk_enable.toggled.connect(self._on_enable_toggled)
        head.addWidget(self.chk_enable)

        self.lbl_rate = QLabel("暂无数据")
        self.lbl_rate.setStyleSheet("color:#565F89;font-size:11px;")
        head.addWidget(self.lbl_rate)

        self.btn_toggle = QPushButton("历史 ▼")
        self.btn_toggle.setFixedHeight(22)
        self.btn_toggle.clicked.connect(self._toggle_history)
        head.addWidget(self.btn_toggle)
        layout.addLayout(head)

        self._grid_host = QWidget()
        self._grid = QGridLayout(self._grid_host)
        self._grid.setContentsMargins(0, 0, 0, 0)
        self._grid.setSpacing(0)
        self._field_labels: Dict[str, QLabel] = {}
        layout.addWidget(self._grid_host)

        self.lbl_empty = QLabel("等待数据…")
        self.lbl_empty.setAlignment(Qt.AlignCenter)
        self.lbl_empty.setStyleSheet("color:#565F89;font-size:11px;")
        layout.addWidget(self.lbl_empty)

        self.txt_history = QTextEdit()
        self.txt_history.setReadOnly(True)
        self.txt_history.setFont(QFont("Consolas", 9))
        self.txt_history.setMaximumHeight(100)
        self.txt_history.setVisible(False)
        layout.addWidget(self.txt_history)

        self._apply_style()
        if self.config.field_names:
            self._rebuild_field_grid()
        else:
            self.lbl_empty.setVisible(True)
            self._grid_host.setVisible(False)

    def _rebuild_field_grid(self):
        while self._grid.count():
            item = self._grid.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._field_labels.clear()

        names = self.config.field_names
        if not names and self._last_frame:
            names = list(self._last_frame.fields.keys())
        if not names:
            self._grid_host.setVisible(False)
            return

        self._grid_host.setVisible(True)
        col = 0
        for name in names:
            h = QLabel(name + "：")
            h.setStyleSheet(_HEAD_STYLE)
            h.setAlignment(Qt.AlignCenter)
            self._grid.addWidget(h, 0, col)
            v = QLabel("—")
            v.setStyleSheet(_VAL_STYLE)
            v.setAlignment(Qt.AlignCenter)
            self._grid.addWidget(v, 1, col)
            self._field_labels[name] = v
            col += 1

    def _apply_style(self):
        if self.chk_enable.isChecked():
            self.setStyleSheet("QFrame { border: 1px solid #3B4261; border-radius: 4px; }")
            self.chk_enable.setStyleSheet("font-weight:bold; color:#7AA2F7;")
        else:
            self.setStyleSheet("QFrame { border: 1px dashed #414868; border-radius: 4px; }")
            self.chk_enable.setStyleSheet("font-weight:bold; color:#565F89;")

    def _on_enable_toggled(self, _on: bool):
        self.config.enabled = self.chk_enable.isChecked()
        self._apply_style()

    def is_enabled(self) -> bool:
        return self.chk_enable.isChecked()

    def tick_second(self):
        """每秒刷新帧率 / 无数据提示"""
        if not self.is_enabled():
            self.lbl_rate.setText("未启用")
            self.lbl_rate.setStyleSheet("color:#E06C75;font-size:11px;")
            return

        now = time.monotonic()
        while self._frame_times and now - self._frame_times[0] > 1.0:
            self._frame_times.popleft()

        if self._frame_times:
            fps = len(self._frame_times)
            self.lbl_rate.setText(f"近1s: {fps} 帧")
            self.lbl_rate.setStyleSheet("color:#98C379;font-size:11px;")
            self.lbl_empty.setVisible(False)
            self._grid_host.setVisible(bool(self._field_labels))
        else:
            self.lbl_rate.setText("近1s: 无数据")
            self.lbl_rate.setStyleSheet("color:#565F89;font-size:11px;")
            if self._last_frame is None:
                self.lbl_empty.setVisible(True)
                self._grid_host.setVisible(False)

    def feed(self, data: bytes) -> List[ParsedFrame]:
        if not self.is_enabled():
            return []
        frames = self.parser.feed(data)
        for fr in frames:
            self._on_frame(fr)
        return frames

    def _on_frame(self, frame: ParsedFrame):
        self._last_frame = frame
        now = time.monotonic()
        self._frame_times.append(now)

        if frame.fields.keys() != self._field_labels.keys():
            self.config.field_names = list(frame.fields.keys())
            self._rebuild_field_grid()

        for name, val in frame.fields.items():
            lbl = self._field_labels.get(name)
            if lbl:
                lbl.setText(str(val))

        self.lbl_empty.setVisible(False)
        self._grid_host.setVisible(True)

        ts = frame.timestamp.strftime("%H:%M:%S.%f")[:-3]
        cells = " | ".join(f"{k}={v}" for k, v in frame.fields.items())
        self._history.appendleft(f"[{ts}] {cells}")
        self.txt_history.setPlainText("\n".join(self._history))
        self.tick_second()

    def _toggle_history(self):
        vis = not self.txt_history.isVisible()
        self.txt_history.setVisible(vis)
        self.btn_toggle.setText("历史 ▲" if vis else "历史 ▼")

    def reset(self):
        self.parser.reset()
        self._history.clear()
        self._frame_times.clear()
        self._last_frame = None
        for lbl in self._field_labels.values():
            lbl.setText("—")
        self.lbl_empty.setVisible(True)
        self.lbl_rate.setText("暂无数据")


class RxParserPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._blocks: Dict[str, _ParserBlock] = {}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        head = QHBoxLayout()
        self.lbl_title = QLabel("指令解析")
        self.lbl_title.setStyleSheet("font-weight:bold; color:#BB9AF7;")
        head.addWidget(self.lbl_title)
        self.lbl_summary = QLabel("")
        self.lbl_summary.setStyleSheet("color:#565F89;font-size:11px;")
        head.addWidget(self.lbl_summary, stretch=1)
        layout.addLayout(head)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self._container = QWidget()
        self._container_layout = QVBoxLayout(self._container)
        self._container_layout.setContentsMargins(0, 0, 0, 0)
        self._container_layout.setSpacing(4)

        self._placeholder = QLabel("展开「指令解析」并添加规则")
        self._placeholder.setAlignment(Qt.AlignCenter)
        self._placeholder.setStyleSheet("color:#565F89; font-size:11px;")
        self._placeholder.setWordWrap(True)
        self._container_layout.addWidget(self._placeholder)
        self._container_layout.addStretch()

        self._scroll.setWidget(self._container)
        layout.addWidget(self._scroll, stretch=1)

        self._fps_timer = QTimer(self)
        self._fps_timer.setInterval(1000)
        self._fps_timer.timeout.connect(self._on_fps_tick)
        self._fps_timer.start()

    def _on_fps_tick(self):
        for block in self._blocks.values():
            block.tick_second()

    def set_parsers(self, configs: List[ParserConfig]):
        for block in self._blocks.values():
            self._container_layout.removeWidget(block)
            block.deleteLater()
        self._blocks.clear()

        for cfg in configs:
            block = _ParserBlock(cfg, self._container)
            self._blocks[cfg.id] = block
            idx = self._container_layout.count() - 1
            self._container_layout.insertWidget(idx, block)

        self._placeholder.setVisible(len(configs) == 0)
        self._update_summary()

    def _update_summary(self):
        total = len(self._blocks)
        active = sum(1 for b in self._blocks.values() if b.is_enabled())
        if total == 0:
            self.lbl_summary.setText("")
        elif active == 0:
            self.lbl_summary.setText(f"{total} 条规则，均未启用")
            self.lbl_summary.setStyleSheet("color:#E06C75;font-size:11px;")
        else:
            self.lbl_summary.setText(f"{active}/{total} 运行")
            self.lbl_summary.setStyleSheet("color:#98C379;font-size:11px;")

    def feed_all(self, data: bytes):
        for block in self._blocks.values():
            block.feed(data)

    def enabled_configs(self) -> List[ParserConfig]:
        out = []
        for block in self._blocks.values():
            c = block.config
            c.enabled = block.is_enabled()
            out.append(c)
        self._update_summary()
        return out

    def reset_all(self):
        for block in self._blocks.values():
            block.reset()
