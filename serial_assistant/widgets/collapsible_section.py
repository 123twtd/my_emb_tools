"""可折叠区域 — 用于非常用功能收纳在底部"""

from PyQt5.QtCore import pyqtSignal
from PyQt5.QtWidgets import QWidget, QVBoxLayout, QPushButton, QSizePolicy


class CollapsibleSection(QWidget):
    """标题按钮 + 可隐藏内容区，默认折叠"""

    toggled = pyqtSignal(bool)

    def __init__(self, title: str, collapsed: bool = True, parent=None):
        super().__init__(parent)
        self._title = title
        self._collapsed = collapsed

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 2, 0, 2)
        layout.setSpacing(2)

        self._btn = QPushButton(self._label(collapsed))
        self._btn.setObjectName("collapsible_header")
        self._btn.setFlat(True)
        self._btn.clicked.connect(self._on_click)
        layout.addWidget(self._btn)

        self._body = QWidget()
        self._body.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
        self._body_layout = QVBoxLayout(self._body)
        self._body_layout.setContentsMargins(12, 0, 0, 4)
        self._body_layout.setSpacing(4)
        self._body.setVisible(not collapsed)
        self._body.setMaximumHeight(0 if collapsed else 16777215)
        layout.addWidget(self._body)

    def body_layout(self) -> QVBoxLayout:
        return self._body_layout

    def is_collapsed(self) -> bool:
        return self._collapsed

    def set_collapsed(self, collapsed: bool):
        if collapsed == self._collapsed:
            return
        self._collapsed = collapsed
        self._body.setVisible(not collapsed)
        self._body.setMaximumHeight(0 if collapsed else 16777215)
        self._btn.setText(self._label(collapsed))
        self.updateGeometry()
        self.toggled.emit(not collapsed)

    def _label(self, collapsed: bool) -> str:
        arrow = "▸" if collapsed else "▾"
        return f"{arrow}  {self._title}"

    def _on_click(self):
        self.set_collapsed(not self._collapsed)
