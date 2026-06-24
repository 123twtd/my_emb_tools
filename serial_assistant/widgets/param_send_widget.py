"""参数化单次/循环发送面板"""

from __future__ import annotations

from PyQt5.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QLabel, QLineEdit,
    QComboBox, QSpinBox, QPushButton,
)


class ParamSendWidget(QWidget):
    """模板 + 固定/自增/列表 → 生成发送内容"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._counter = 0
        self._list_idx = 0

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        row1 = QHBoxLayout()
        row1.addWidget(QLabel("模板"))
        self.ed_template = QLineEdit()
        self.ed_template.setPlaceholderText("如 L,{v},100  用 {v} 或 {i} 作变量位")
        row1.addWidget(self.ed_template, stretch=1)
        layout.addLayout(row1)

        row2 = QHBoxLayout()
        row2.addWidget(QLabel("变化"))
        self.cb_mode = QComboBox()
        self.cb_mode.addItem("固定值", "fixed")
        self.cb_mode.addItem("自增", "inc")
        self.cb_mode.addItem("列表循环", "list")
        self.cb_mode.currentIndexChanged.connect(self._on_mode_changed)
        row2.addWidget(self.cb_mode)

        self.ed_fixed = QLineEdit("100")
        self.ed_fixed.setFixedWidth(80)
        row2.addWidget(self.ed_fixed)

        self.spin_start = QSpinBox()
        self.spin_start.setRange(-999999, 999999)
        self.spin_start.setPrefix("起 ")
        self.spin_start.setVisible(False)
        row2.addWidget(self.spin_start)

        self.spin_step = QSpinBox()
        self.spin_step.setRange(-999999, 999999)
        self.spin_step.setValue(1)
        self.spin_step.setPrefix("步 ")
        self.spin_step.setVisible(False)
        row2.addWidget(self.spin_step)

        self.ed_list = QLineEdit("1,2,3,4")
        self.ed_list.setPlaceholderText("1,2,3")
        self.ed_list.setVisible(False)
        row2.addWidget(self.ed_list, stretch=1)

        self.btn_reset = QPushButton("重置计数")
        self.btn_reset.setFixedHeight(24)
        self.btn_reset.clicked.connect(self.reset_counter)
        row2.addWidget(self.btn_reset)

        layout.addLayout(row2)
        self._on_mode_changed()

    def _on_mode_changed(self):
        mode = self.cb_mode.currentData()
        self.ed_fixed.setVisible(mode == "fixed")
        self.spin_start.setVisible(mode == "inc")
        self.spin_step.setVisible(mode == "inc")
        self.ed_list.setVisible(mode == "list")

    def reset_counter(self):
        self._counter = 0
        self._list_idx = 0
        self.spin_start.setValue(0)

    def next_payload(self) -> str:
        tpl = self.ed_template.text()
        mode = self.cb_mode.currentData()
        if mode == "fixed":
            val = self.ed_fixed.text()
            return tpl.replace("{v}", val).replace("{i}", val)
        if mode == "inc":
            val = self.spin_start.value() + self._counter * self.spin_step.value()
            self._counter += 1
            s = str(val)
            return tpl.replace("{v}", s).replace("{i}", s)
        vals = [x.strip() for x in self.ed_list.text().split(",") if x.strip()]
        if not vals:
            return tpl
        val = vals[self._list_idx % len(vals)]
        self._list_idx += 1
        return tpl.replace("{v}", val).replace("{i}", val)

    def to_dict(self) -> dict:
        return {
            "template": self.ed_template.text(),
            "mode": self.cb_mode.currentData(),
            "fixed": self.ed_fixed.text(),
            "start": self.spin_start.value(),
            "step": self.spin_step.value(),
            "list": self.ed_list.text(),
        }

    def load_dict(self, d: dict):
        if not d:
            return
        self.ed_template.setText(d.get("template", ""))
        mode = d.get("mode", "fixed")
        idx = self.cb_mode.findData(mode)
        if idx >= 0:
            self.cb_mode.setCurrentIndex(idx)
        self.ed_fixed.setText(str(d.get("fixed", "100")))
        self.spin_start.setValue(int(d.get("start", 0)))
        self.spin_step.setValue(int(d.get("step", 1)))
        self.ed_list.setText(str(d.get("list", "1,2,3,4")))
