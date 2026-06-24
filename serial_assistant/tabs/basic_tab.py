"""基础串口 Tab - 迁移自原 MainWindow 的 HEX/文本收发功能，新增 Splitter 布局和内嵌工具栏"""

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QSplitter,
    QLabel, QComboBox, QPushButton, QTextEdit, QCheckBox
)
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QFont

from .base_tab import SerialTab
from ..utils import bytes_to_hex, bytes_to_text, text_to_bytes, hex_to_bytes


class BasicSerialTab(SerialTab):
    """基础串口收发 Tab"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._recv_buffer = bytearray()
        self._rx_count = 0
        self._tx_count = 0
        self._init_ui()

    def _init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        
        splitter = QSplitter(Qt.Vertical)
        
        # ── 接收区 ──
        recv_widget = QWidget()
        recv_layout = QVBoxLayout(recv_widget)
        recv_layout.setContentsMargins(4, 4, 4, 4)
        recv_layout.setSpacing(4)
        
        # 接收工具栏
        rx_toolbar = QHBoxLayout()
        rx_label = QLabel("接收")
        rx_label.setStyleSheet("font-weight: bold; color: #7AA2F7;")
        rx_toolbar.addWidget(rx_label)
        
        self.cb_recv_mode = QComboBox()
        self.cb_recv_mode.addItems(["文本模式", "HEX模式"])
        self.cb_recv_mode.currentTextChanged.connect(self._on_rx_mode_changed)
        rx_toolbar.addWidget(self.cb_recv_mode)
        
        self.cb_recv_encoding = QComboBox()
        self.cb_recv_encoding.addItems(["GBK", "UTF-8"])
        rx_toolbar.addWidget(self.cb_recv_encoding)
        
        self.chk_auto_scroll = QCheckBox("自动滚动")
        self.chk_auto_scroll.setChecked(True)
        rx_toolbar.addWidget(self.chk_auto_scroll)
        
        rx_toolbar.addStretch()
        
        self.lbl_rx_count = QLabel("Rx: 0")
        self.lbl_rx_count.setStyleSheet("color: #565F89;")
        rx_toolbar.addWidget(self.lbl_rx_count)
        
        btn_clear_recv = QPushButton("清空")
        btn_clear_recv.setFixedHeight(24)
        btn_clear_recv.clicked.connect(self._clear_rx)
        rx_toolbar.addWidget(btn_clear_recv)
        
        recv_layout.addLayout(rx_toolbar)
        
        self.txt_receive = QTextEdit()
        self.txt_receive.setReadOnly(True)
        self.txt_receive.setFont(QFont("Consolas", 10))
        recv_layout.addWidget(self.txt_receive)
        
        splitter.addWidget(recv_widget)
        
        # ── 发送区 ──
        send_widget = QWidget()
        send_layout = QVBoxLayout(send_widget)
        send_layout.setContentsMargins(4, 4, 4, 4)
        send_layout.setSpacing(4)
        
        # 发送工具栏
        tx_toolbar = QHBoxLayout()
        tx_label = QLabel("发送")
        tx_label.setStyleSheet("font-weight: bold; color: #98C379;")
        tx_toolbar.addWidget(tx_label)
        
        self.cb_send_mode = QComboBox()
        self.cb_send_mode.addItems(["文本模式", "HEX模式"])
        self.cb_send_mode.currentTextChanged.connect(self._on_tx_mode_changed)
        tx_toolbar.addWidget(self.cb_send_mode)
        
        self.cb_send_encoding = QComboBox()
        self.cb_send_encoding.addItems(["GBK", "UTF-8"])
        tx_toolbar.addWidget(self.cb_send_encoding)
        
        tx_toolbar.addStretch()
        
        self.lbl_tx_count = QLabel("Tx: 0")
        self.lbl_tx_count.setStyleSheet("color: #565F89;")
        tx_toolbar.addWidget(self.lbl_tx_count)
        
        btn_clear_send = QPushButton("清空")
        btn_clear_send.setFixedHeight(24)
        btn_clear_send.clicked.connect(self._clear_tx)
        tx_toolbar.addWidget(btn_clear_send)
        
        self.btn_send = QPushButton("发送")
        self.btn_send.setFixedHeight(24)
        self.btn_send.setStyleSheet("background-color: #1A3A28; color: #98C379;")
        self.btn_send.setEnabled(False)
        self.btn_send.clicked.connect(self._on_send)
        tx_toolbar.addWidget(self.btn_send)
        
        send_layout.addLayout(tx_toolbar)
        
        self.txt_send = QTextEdit()
        self.txt_send.setFont(QFont("Consolas", 10))
        send_layout.addWidget(self.txt_send)
        
        splitter.addWidget(send_widget)
        
        # 初始比例 7:3
        splitter.setSizes([700, 300])
        main_layout.addWidget(splitter)

    # ──────────────────── 交互逻辑 ────────────────────

    def _on_rx_mode_changed(self, mode: str):
        self.cb_recv_encoding.setEnabled(mode == "文本模式")

    def _on_tx_mode_changed(self, mode: str):
        self.cb_send_encoding.setEnabled(mode == "文本模式")

    def _clear_rx(self):
        self.txt_receive.clear()
        self._rx_count = 0
        self.lbl_rx_count.setText("Rx: 0")

    def _clear_tx(self):
        self.txt_send.clear()
        self._tx_count = 0
        self.lbl_tx_count.setText("Tx: 0")

    # ──────────────────── 数据收发 ────────────────────

    def on_data_received(self, data: bytes):
        self._rx_count += len(data)
        self.lbl_rx_count.setText(f"Rx: {self._rx_count}")
        
        if self.cb_recv_mode.currentText() == "HEX模式":
            self.txt_receive.insertPlainText(bytes_to_hex(data))
        else:
            encoding = self.cb_recv_encoding.currentText()
            text = bytes_to_text(data, encoding, self._recv_buffer)
            if text:
                self.txt_receive.insertPlainText(text)
                
        if self.chk_auto_scroll.isChecked():
            sb = self.txt_receive.verticalScrollBar()
            sb.setValue(sb.maximum())

    def _on_send(self):
        # 兼容新的 is_open() 方法以及老的 is_open 属性
        is_open = False
        if self._serial_worker:
            if callable(self._serial_worker.is_open):
                is_open = self._serial_worker.is_open()
            else:
                is_open = self._serial_worker.is_open
                
        if not is_open:
            return

        text = self.txt_send.toPlainText()
        if not text:
            return

        if self.cb_send_mode.currentText() == "HEX模式":
            data = hex_to_bytes(text)
        else:
            encoding = self.cb_send_encoding.currentText()
            data = text_to_bytes(text, encoding)

        if data:
            # 兼容新的 send_data() 和老的 send()
            if hasattr(self._serial_worker, "send_data"):
                self._serial_worker.send_data(data)
            else:
                self._serial_worker.send(data)
            self._tx_count += len(data)
            self.lbl_tx_count.setText(f"Tx: {self._tx_count}")

    def on_port_toggled(self, is_open: bool):
        self.btn_send.setEnabled(is_open)

    def reset_state(self):
        self._recv_buffer.clear()
