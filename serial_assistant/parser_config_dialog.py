"""接收解析器配置对话框"""

from __future__ import annotations

import uuid
from typing import Callable, List, Optional

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, QLineEdit,
    QPushButton, QListWidget, QListWidgetItem, QSpinBox, QComboBox,
    QCheckBox, QDialogButtonBox, QMessageBox, QLabel, QGroupBox,
)

from .rx_frame_parser import ParserConfig


class ParserEditDialog(QDialog):
    """编辑单条解析规则"""

    def __init__(self, config: Optional[ParserConfig] = None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("解析规则")
        self.setMinimumWidth(420)
        self._cfg = config or ParserConfig(id=str(uuid.uuid4())[:8], name="新规则")

        layout = QVBoxLayout(self)
        form = QFormLayout()

        self.ed_name = QLineEdit(self._cfg.name)
        form.addRow("名称:", self.ed_name)

        self.ed_header = QLineEdit(self._cfg.header)
        self.ed_header.setPlaceholderText("如 L 或 \\xAA\\x55，留空=无")
        form.addRow("帧头:", self.ed_header)

        self.ed_footer = QLineEdit(self._cfg.footer)
        self.ed_footer.setPlaceholderText("如 \\n，留空=无")
        form.addRow("帧尾:", self.ed_footer)

        self.ed_delimiter = QLineEdit(self._cfg.delimiter)
        self.ed_delimiter.setPlaceholderText("如 , 或 |，留空=不按分隔符切帧")
        form.addRow("分隔符:", self.ed_delimiter)

        self.cb_encoding = QComboBox()
        self.cb_encoding.addItems(["utf-8", "gbk", "ascii"])
        self.cb_encoding.setCurrentText(self._cfg.encoding)
        form.addRow("编码:", self.cb_encoding)

        self.sp_frame_len = QSpinBox()
        self.sp_frame_len.setRange(0, 65535)
        self.sp_frame_len.setValue(self._cfg.frame_length)
        self.sp_frame_len.setToolTip("0=不定长；>0 时按整帧固定字节数（有帧头则从帧头后计）")
        form.addRow("整帧定长:", self.sp_frame_len)

        hint_len = QLabel("0=自动识别帧界；仅在有固定字节数协议时填写")
        hint_len.setStyleSheet("color:#888;font-size:10px;")
        form.addRow("", hint_len)

        self.cb_split = QComboBox()
        self.cb_split.addItem("按分隔符拆字段", "delimiter")
        self.cb_split.addItem("按固定字节宽拆字段", "fixed_width")
        idx = self.cb_split.findData(self._cfg.split_mode)
        self.cb_split.setCurrentIndex(idx if idx >= 0 else 0)
        form.addRow("字段拆分:", self.cb_split)

        self.ed_field_names = QLineEdit(",".join(self._cfg.field_names))
        self.ed_field_names.setPlaceholderText("逗号分隔，如 id,value,status")
        form.addRow("字段名:", self.ed_field_names)

        self.ed_field_widths = QLineEdit(
            ",".join(str(w) for w in self._cfg.field_widths)
        )
        self.ed_field_widths.setPlaceholderText("定宽模式：如 2,4,1（字节）")
        form.addRow("字段定宽:", self.ed_field_widths)

        self.sp_history = QSpinBox()
        self.sp_history.setRange(10, 5000)
        self.sp_history.setValue(self._cfg.history_max)
        form.addRow("历史条数:", self.sp_history)

        self.chk_enabled = QCheckBox("保存后立即启用")
        self.chk_enabled.setChecked(self._cfg.enabled)
        form.addRow("", self.chk_enabled)

        layout.addLayout(form)

        hint = QLabel(
            "帧边界：帧头+帧尾 / 仅帧头(下一帧头结束) / 仅帧尾 / 整帧定长 / 分隔符切帧。\n"
            "字段：帧内再用分隔符或定宽拆成命名项。转义：\\r \\n \\t \\xNN"
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color:#888;font-size:11px;")
        layout.addWidget(hint)

        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.accepted.connect(self._on_ok)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)

    def _on_ok(self):
        if not self.ed_name.text().strip():
            QMessageBox.warning(self, "提示", "请填写名称")
            return
        self.accept()

    def result_config(self) -> ParserConfig:
        names = [n.strip() for n in self.ed_field_names.text().split(",") if n.strip()]
        widths = []
        for p in self.ed_field_widths.text().split(","):
            p = p.strip()
            if p.isdigit():
                widths.append(int(p))
        return ParserConfig(
            id=self._cfg.id,
            name=self.ed_name.text().strip(),
            enabled=self.chk_enabled.isChecked(),
            header=self.ed_header.text(),
            footer=self.ed_footer.text(),
            delimiter=self.ed_delimiter.text(),
            encoding=self.cb_encoding.currentText(),
            frame_length=self.sp_frame_len.value(),
            split_mode=self.cb_split.currentData(),
            field_names=names,
            field_widths=widths,
            history_max=self.sp_history.value(),
        )


class ParserManagerDialog(QDialog):
    """管理多条解析规则"""

    def __init__(self, parsers: List[ParserConfig], parent=None):
        super().__init__(parent)
        self.setWindowTitle("接收解析规则")
        self.setMinimumSize(480, 360)
        self._parsers = [ParserConfig.from_dict(p.to_dict()) if isinstance(p, ParserConfig)
                         else ParserConfig.from_dict(p) for p in parsers]

        layout = QVBoxLayout(self)
        self.list = QListWidget()
        self._refresh_list()
        layout.addWidget(self.list)

        row = QHBoxLayout()
        for label, slot in [
            ("添加", self._add), ("编辑", self._edit), ("删除", self._delete),
            ("复制", self._duplicate),
        ]:
            btn = QPushButton(label)
            btn.clicked.connect(slot)
            row.addWidget(btn)
        row.addStretch()
        layout.addLayout(row)

        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)

    def _refresh_list(self):
        self.list.clear()
        for p in self._parsers:
            flag = "✓" if p.enabled else "○"
            item = QListWidgetItem(f"{flag} {p.name}")
            item.setData(Qt.UserRole, p.id)
            self.list.addItem(item)

    def _current(self) -> Optional[ParserConfig]:
        item = self.list.currentItem()
        if not item:
            return None
        pid = item.data(Qt.UserRole)
        for p in self._parsers:
            if p.id == pid:
                return p
        return None

    def _add(self):
        base = ParserConfig(id=str(uuid.uuid4())[:8], name="新规则", enabled=True)
        dlg = ParserEditDialog(base, parent=self)
        if dlg.exec_() == dlg.Accepted:
            self._parsers.append(dlg.result_config())
            self._refresh_list()

    def _edit(self):
        cur = self._current()
        if not cur:
            return
        dlg = ParserEditDialog(cur, parent=self)
        if dlg.exec_() == dlg.Accepted:
            new_cfg = dlg.result_config()
            for i, p in enumerate(self._parsers):
                if p.id == cur.id:
                    self._parsers[i] = new_cfg
                    break
            self._refresh_list()

    def _delete(self):
        cur = self._current()
        if not cur:
            return
        self._parsers = [p for p in self._parsers if p.id != cur.id]
        self._refresh_list()

    def _duplicate(self):
        cur = self._current()
        if not cur:
            return
        d = cur.to_dict()
        d["id"] = str(uuid.uuid4())[:8]
        d["name"] = cur.name + " (副本)"
        self._parsers.append(ParserConfig.from_dict(d))
        self._refresh_list()

    def parsers(self) -> List[ParserConfig]:
        return self._parsers
