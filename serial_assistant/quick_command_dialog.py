"""快捷指令 / 协议模板发送对话框"""

from __future__ import annotations

from typing import Any, Dict, List

from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QFormLayout, QLineEdit, QLabel,
    QDialogButtonBox, QComboBox,
)

from .send_protocol import extract_template_fields, render_template


class QuickCommandDialog(QDialog):
    """选择快捷指令并填写模板字段后发送"""

    def __init__(self, commands: List[Dict[str, Any]], parent=None):
        super().__init__(parent)
        self.setWindowTitle("快捷指令")
        self.setMinimumWidth(360)
        self._commands = [c for c in commands if isinstance(c, dict)]
        self._field_edits: Dict[str, QLineEdit] = {}
        self._result_bytes = b""

        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.combo_cmd = QComboBox()
        for cmd in self._commands:
            self.combo_cmd.addItem(cmd.get("name", "未命名"), cmd)
        self.combo_cmd.currentIndexChanged.connect(self._rebuild_fields)
        form.addRow("指令:", self.combo_cmd)
        layout.addLayout(form)

        self.lbl_hint = QLabel("")
        self.lbl_hint.setWordWrap(True)
        self.lbl_hint.setStyleSheet("color:#888; font-size:11px;")
        layout.addWidget(self.lbl_hint)

        self._fields_box = QFormLayout()
        layout.addLayout(self._fields_box)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self._rebuild_fields()

    def _clear_fields(self):
        while self._fields_box.rowCount():
            self._fields_box.removeRow(0)
        self._field_edits.clear()

    def _rebuild_fields(self):
        self._clear_fields()
        cmd = self.combo_cmd.currentData() or {}
        template = cmd.get("template") or cmd.get("body", "")
        self.lbl_hint.setText(f"模板: {template}")
        defaults = cmd.get("defaults") or {}
        for name in extract_template_fields(template):
            edit = QLineEdit(str(defaults.get(name, "")))
            self._field_edits[name] = edit
            self._fields_box.addRow(name + ":", edit)

    def _on_accept(self):
        cmd = self.combo_cmd.currentData() or {}
        template = cmd.get("template") or cmd.get("body", "")
        mode = cmd.get("mode", "text")
        encoding = cmd.get("encoding", "UTF-8")
        use_escape = bool(cmd.get("use_escape", False))
        fields = {k: e.text() for k, e in self._field_edits.items()}
        self._result_bytes = render_template(
            template, mode, fields, encoding, use_escape
        )
        self.accept()

    def payload(self) -> bytes:
        return self._result_bytes
