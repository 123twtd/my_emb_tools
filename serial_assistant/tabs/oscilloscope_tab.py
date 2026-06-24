"""示波器 Tab - 实时多通道波形显示"""

from collections import deque

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QGroupBox, QLabel, QLineEdit, QPushButton, QCheckBox,
    QFrame, QColorDialog, QSizePolicy, QSplitter, QScrollArea, QSpinBox
)
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QColor, QDoubleValidator

import pyqtgraph as pg

from .base_tab import SerialTab
from .protocol_parser import FrameParser
from ..utils import parse_escape_sequences


# 预定义通道颜色（自动分配使用，如果超过则循环或随机）
CHANNEL_COLORS = [
    "#FF4444", "#44CC44", "#4488FF", "#FFCC00",
    "#FF44FF", "#00CCCC", "#FF8800", "#AA44FF",
    "#A3E4D7", "#F9E79F", "#F5CBA7", "#D2B4DE",
]

MAX_POINTS = 5000  # 每通道最大缓冲点数


class OscilloscopeTab(SerialTab):
    """示波器模式 Tab"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._parser = FrameParser()
        
        # 动态通道相关数据结构
        self._num_channels = 0
        self._data_buffers = []
        self._x_data = deque(maxlen=MAX_POINTS)
        self._sample_counts = []
        self._latest_values = []
        self._point_count = 0
        
        self._auto_detect = True
        
        self._is_paused = False
        self._curves = []
        self._channel_enabled = []
        self._channel_colors = []
        self._channel_names = []
        
        self._window_size = 500
        self._y_auto = True
        self._y_min = 0.0
        self._y_max = 100.0

        self._init_ui()
        self._start_update_timer()

    def _init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(4, 4, 4, 4)
        main_layout.setSpacing(4)

        # 引入 Splitter 来自由调整绘图区和控制区比例
        self._splitter = QSplitter(Qt.Vertical)
        main_layout.addWidget(self._splitter)

        # ── 绘图区 ──
        self._plot_widget = pg.PlotWidget()
        self._plot_widget.setBackground("default") # 根据主题自适应或使用透明
        self._plot_widget.showGrid(x=True, y=True, alpha=0.3)
        self._plot_widget.setLabel("bottom", "采样点")
        self._plot_widget.setLabel("left", "数值")
        self._plot_widget.addLegend()
        self._splitter.addWidget(self._plot_widget)

        # ── 底部控制区 ──
        control_panel = QWidget()
        control_layout = QVBoxLayout(control_panel)
        control_layout.setContentsMargins(0, 0, 0, 0)
        control_layout.setSpacing(4)

        # 协议配置栏
        proto_group = QGroupBox("协议配置")
        proto_layout = QHBoxLayout(proto_group)
        proto_layout.setContentsMargins(6, 14, 6, 6)

        proto_layout.addWidget(QLabel("帧头:"))
        self.ed_header = QLineEdit("#")
        self.ed_header.setFixedWidth(80)
        self.ed_header.editingFinished.connect(self._on_protocol_changed)
        proto_layout.addWidget(self.ed_header)

        proto_layout.addWidget(QLabel("分隔符:"))
        self.ed_delimiter = QLineEdit(",")
        self.ed_delimiter.setFixedWidth(80)
        self.ed_delimiter.editingFinished.connect(self._on_protocol_changed)
        proto_layout.addWidget(self.ed_delimiter)

        proto_layout.addWidget(QLabel("帧尾:"))
        self.ed_footer = QLineEdit("\\n")
        self.ed_footer.setFixedWidth(80)
        self.ed_footer.editingFinished.connect(self._on_protocol_changed)
        proto_layout.addWidget(self.ed_footer)

        line1 = QFrame()
        line1.setFrameShape(QFrame.VLine)
        line1.setFrameShadow(QFrame.Sunken)
        proto_layout.addWidget(line1)

        proto_layout.addWidget(QLabel("X窗口:"))
        self.ed_x_window = QLineEdit("500")
        self.ed_x_window.setFixedWidth(50)
        self.ed_x_window.editingFinished.connect(self._on_x_window_changed)
        proto_layout.addWidget(self.ed_x_window)

        proto_layout.addWidget(QLabel("Y范围:"))
        self.cb_y_auto = QCheckBox("自动")
        self.cb_y_auto.setChecked(True)
        self.cb_y_auto.stateChanged.connect(self._on_y_auto_changed)
        proto_layout.addWidget(self.cb_y_auto)

        self.ed_y_min = QLineEdit("0")
        self.ed_y_min.setFixedWidth(50)
        self.ed_y_min.setValidator(QDoubleValidator())
        self.ed_y_min.setEnabled(False)
        self.ed_y_min.editingFinished.connect(self._on_y_range_changed)
        proto_layout.addWidget(self.ed_y_min)

        self.ed_y_max = QLineEdit("100")
        self.ed_y_max.setFixedWidth(50)
        self.ed_y_max.setValidator(QDoubleValidator())
        self.ed_y_max.setEnabled(False)
        self.ed_y_max.editingFinished.connect(self._on_y_range_changed)
        proto_layout.addWidget(self.ed_y_max)

        proto_layout.addStretch()

        self.btn_pause = QPushButton("暂停")
        self.btn_pause.setFixedWidth(60)
        self.btn_pause.setCheckable(True)
        self.btn_pause.clicked.connect(self._on_pause_toggled)
        proto_layout.addWidget(self.btn_pause)

        self.btn_clear = QPushButton("清除波形")
        self.btn_clear.setFixedWidth(80)
        self.btn_clear.clicked.connect(self._on_clear)
        proto_layout.addWidget(self.btn_clear)

        control_layout.addWidget(proto_group)

        # 通道配置区 (滚动区域)
        channel_group = QGroupBox("通道配置")
        channel_outer_layout = QVBoxLayout(channel_group)
        channel_outer_layout.setContentsMargins(4, 14, 4, 4)

        mode_row = QHBoxLayout()
        self.cb_auto_detect = QCheckBox("自动识别数量")
        self.cb_auto_detect.setChecked(True)
        self.cb_auto_detect.stateChanged.connect(self._on_auto_detect_changed)
        mode_row.addWidget(self.cb_auto_detect)
        
        mode_row.addWidget(QLabel("手动通道数:"))
        self.spin_manual_channels = QSpinBox()
        self.spin_manual_channels.setRange(1, 64)
        self.spin_manual_channels.setValue(8)
        self.spin_manual_channels.setEnabled(False)
        self.spin_manual_channels.valueChanged.connect(self._on_manual_channels_changed)
        mode_row.addWidget(self.spin_manual_channels)
        mode_row.addStretch()
        channel_outer_layout.addLayout(mode_row)
        
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setStyleSheet("background-color: transparent;")
        
        self.channel_container = QWidget()
        self.channel_layout = QGridLayout(self.channel_container)
        self.channel_layout.setContentsMargins(0, 0, 0, 0)
        self.channel_layout.setHorizontalSpacing(10)
        self.channel_layout.setVerticalSpacing(4)
        
        # 表头
        headers = ["启用", "颜色", "名称", "最新数值", "采样点数", "字节长度"]
        for col, text in enumerate(headers):
            lbl = QLabel(text)
            lbl.setAlignment(Qt.AlignCenter)
            lbl.setStyleSheet("color: #888888; font-weight: bold;")
            self.channel_layout.addWidget(lbl, 0, col)
            
        self.channel_layout.setRowStretch(100, 1) # 把控件往上顶
        
        scroll.setWidget(self.channel_container)
        channel_outer_layout.addWidget(scroll)

        control_layout.addWidget(channel_group)
        self._splitter.addWidget(control_panel)

        # 设置 splitter 初始比例
        self._splitter.setSizes([400, 200])

        self._ch_checkboxes = []
        self._ch_color_btns = []
        self._ch_name_edits = []
        self._ch_val_labels = []
        self._ch_sample_labels = []
        self._ch_byte_labels = []

    def _add_channel(self, idx: int):
        """动态添加新通道 UI 和逻辑结构"""
        self._num_channels += 1
        
        self._data_buffers.append(deque(maxlen=MAX_POINTS))
        self._sample_counts.append(0)
        self._latest_values.append(0.0)
        self._channel_enabled.append(True)
        
        color_hex = CHANNEL_COLORS[idx % len(CHANNEL_COLORS)]
        color = QColor(color_hex)
        self._channel_colors.append(color)
        name = f"CH{idx + 1}"
        self._channel_names.append(name)
        
        # 添加绘图曲线
        pen = pg.mkPen(color=color, width=1.5)
        curve = self._plot_widget.plot([], [], name=name, pen=pen)
        self._curves.append(curve)
        
        # UI 行 (行号 idx + 1)
        row = idx + 1
        
        cb = QCheckBox()
        cb.setChecked(True)
        cb.stateChanged.connect(lambda state, i=idx: self._on_channel_toggled(i, state))
        self.channel_layout.addWidget(cb, row, 0, alignment=Qt.AlignCenter)
        self._ch_checkboxes.append(cb)

        color_btn = QPushButton()
        color_btn.setFixedSize(30, 20)
        color_btn.setStyleSheet(f"background-color: {color_hex}; border-radius: 3px;")
        color_btn.clicked.connect(lambda checked, i=idx: self._on_color_pick(i))
        self.channel_layout.addWidget(color_btn, row, 1, alignment=Qt.AlignCenter)
        self._ch_color_btns.append(color_btn)

        name_ed = QLineEdit(name)
        name_ed.setFixedWidth(60)
        name_ed.editingFinished.connect(lambda i=idx: self._on_name_changed(i))
        self.channel_layout.addWidget(name_ed, row, 2, alignment=Qt.AlignCenter)
        self._ch_name_edits.append(name_ed)

        val_lbl = QLabel("0.00")
        val_lbl.setAlignment(Qt.AlignCenter)
        val_lbl.setStyleSheet("font-family: Consolas, monospace; color: #1890FF;")
        self.channel_layout.addWidget(val_lbl, row, 3)
        self._ch_val_labels.append(val_lbl)

        sample_lbl = QLabel("0")
        sample_lbl.setAlignment(Qt.AlignCenter)
        self.channel_layout.addWidget(sample_lbl, row, 4)
        self._ch_sample_labels.append(sample_lbl)
        
        byte_lbl = QLabel("-")
        byte_lbl.setAlignment(Qt.AlignCenter)
        byte_lbl.setStyleSheet("color: #888888;")
        self.channel_layout.addWidget(byte_lbl, row, 5)
        self._ch_byte_labels.append(byte_lbl)
        
        # 更新弹簧行
        self.channel_layout.setRowStretch(row, 0)
        self.channel_layout.setRowStretch(row + 1, 1)

    def _start_update_timer(self):
        """启动 30FPS 绘图更新定时器"""
        self._update_timer = QTimer(self)
        self._update_timer.timeout.connect(self._update_plot)
        self._update_timer.start(33)  # ~30 FPS

    # ──────────────────── 数据接收 ────────────────────

    def on_data_received(self, data: bytes):
        frames = self._parser.feed(data)
        for values in frames:
            # 检测是否需要扩展通道
            if self._auto_detect:
                while len(values) > self._num_channels:
                    self._add_channel(self._num_channels)
            
            # 如果是手动模式且数据超过设定，截断数据
            if not self._auto_detect and len(values) > self._num_channels:
                values = values[:self._num_channels]
                
            self._point_count += 1
            self._x_data.append(self._point_count)

            for ch_idx, value in enumerate(values):
                self._data_buffers[ch_idx].append(value)
                self._sample_counts[ch_idx] += 1
                self._latest_values[ch_idx] = value
                
                # 更新字节大小（近似）
                if self._point_count % 10 == 0:  # 降低 UI 更新频率
                    val_str = str(value)
                    self._ch_byte_labels[ch_idx].setText(f"{len(val_str)} B")

    # ──────────────────── 绘图更新 ────────────────────

    def _update_plot(self):
        if self._is_paused:
            return

        x = list(self._x_data)
        for i in range(self._num_channels):
            if self._channel_enabled[i]:
                y = list(self._data_buffers[i])
                if len(x) != len(y):
                    min_len = min(len(x), len(y))
                    x_slice = x[-min_len:] if min_len > 0 else []
                    y_slice = y[-min_len:] if min_len > 0 else []
                else:
                    x_slice = x
                    y_slice = y
                self._curves[i].setData(x_slice, y_slice)
            else:
                self._curves[i].setData([], [])

            # 更新 UI 标签
            self._ch_sample_labels[i].setText(str(self._sample_counts[i]))
            self._ch_val_labels[i].setText(f"{self._latest_values[i]:.4g}")

        # 自动滚动 X 轴
        if x:
            window = min(self._window_size, len(x))
            self._plot_widget.setXRange(x[-1] - window, x[-1], padding=0)

        # Y 轴范围
        if not self._y_auto:
            self._plot_widget.setYRange(self._y_min, self._y_max)

    # ──────────────────── 控件事件 ────────────────────

    def _on_protocol_changed(self):
        header = parse_escape_sequences(self.ed_header.text())
        delimiter = parse_escape_sequences(self.ed_delimiter.text())
        footer = parse_escape_sequences(self.ed_footer.text())

        self._parser.header = header
        self._parser.delimiter = delimiter
        self._parser.footer = footer
        self._parser.reset()

    def _on_pause_toggled(self, checked: bool):
        self._is_paused = checked
        self.btn_pause.setText("继续" if checked else "暂停")

    def _on_clear(self):
        for buf in self._data_buffers:
            buf.clear()
        self._x_data.clear()
        for i in range(self._num_channels):
            self._sample_counts[i] = 0
        self._point_count = 0
        for curve in self._curves:
            curve.setData([], [])
        for lbl in self._ch_sample_labels:
            lbl.setText("0")
        for lbl in self._ch_val_labels:
            lbl.setText("0.00")

    def _on_channel_toggled(self, idx: int, state: int):
        enabled = (state == Qt.Checked)
        self._channel_enabled[idx] = enabled

        if enabled:
            pen = pg.mkPen(color=self._channel_colors[idx], width=1.5)
            self._curves[idx].setPen(pen)
            legend = self._plot_widget.getPlotItem().legend
            if legend is not None:
                try:
                    legend.addItem(self._curves[idx], self._channel_names[idx])
                except Exception:
                    pass
        else:
            pen = pg.mkPen(color="#555555", width=1.5)
            self._curves[idx].setPen(pen)
            self._curves[idx].setData([], [])
            legend = self._plot_widget.getPlotItem().legend
            if legend is not None:
                try:
                    legend.removeItem(self._curves[idx])
                except Exception:
                    pass

    def _on_color_pick(self, idx: int):
        color = QColorDialog.getColor(self._channel_colors[idx], self, "选择通道颜色")
        if color.isValid():
            self._channel_colors[idx] = color
            self._ch_color_btns[idx].setStyleSheet(
                f"background-color: {color.name()}; border-radius: 3px;"
            )
            if self._channel_enabled[idx]:
                pen = pg.mkPen(color=color, width=1.5)
                self._curves[idx].setPen(pen)

    def _on_name_changed(self, idx: int):
        name = self._ch_name_edits[idx].text().strip()
        if name:
            self._channel_names[idx] = name
            self._curves[idx].setName(name)

    def _on_x_window_changed(self):
        try:
            val = int(self.ed_x_window.text())
            if val > 0:
                self._window_size = val
        except ValueError:
            pass

    def _on_y_auto_changed(self, state):
        self._y_auto = (state == Qt.Checked)
        self.ed_y_min.setEnabled(not self._y_auto)
        self.ed_y_max.setEnabled(not self._y_auto)
        if self._y_auto:
            self._plot_widget.enableAutoRange(axis='y')

    def _on_y_range_changed(self):
        try:
            ymin = float(self.ed_y_min.text())
            ymax = float(self.ed_y_max.text())
            if ymin < ymax:
                self._y_min = ymin
                self._y_max = ymax
                if not self._y_auto:
                    self._plot_widget.disableAutoRange(axis='y')
                    self._plot_widget.setYRange(ymin, ymax)
        except ValueError:
            pass

    def _on_auto_detect_changed(self, state):
        self._auto_detect = (state == Qt.Checked)
        self.spin_manual_channels.setEnabled(not self._auto_detect)
        if not self._auto_detect:
            # 应用当前的手动数量
            self._on_manual_channels_changed(self.spin_manual_channels.value())

    def _on_manual_channels_changed(self, target_count: int):
        if self._auto_detect:
            return
            
        while self._num_channels < target_count:
            self._add_channel(self._num_channels)
            
        # 如果减少通道数，只需停用多余的曲线，实际数据可以保留以备后续恢复
        # 为了简单处理，我们将超出的通道从UI中隐藏（由于没有专门删除行，只禁用它们）
        for i in range(self._num_channels):
            if i < target_count:
                if not self._channel_enabled[i]:
                    self._ch_checkboxes[i].setChecked(True)
            else:
                if self._channel_enabled[i]:
                    self._ch_checkboxes[i].setChecked(False)

    # ──────────────────── 生命周期 ────────────────────

    def on_port_toggled(self, is_open: bool):
        pass  # 示波器不需要特别处理

    def reset_state(self):
        self._on_clear()
