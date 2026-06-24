"""按键录制控件 — 用于设置发送快捷键"""

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QKeySequence
from PyQt5.QtWidgets import QWidget, QHBoxLayout, QLineEdit, QPushButton


DEFAULT_SEND_SHORTCUT = "Ctrl+Return"


class KeySequenceCaptureWidget(QWidget):
    """显示当前快捷键，支持录制与恢复默认"""

    sequence_changed = pyqtSignal(str)

    def __init__(self, default: str = DEFAULT_SEND_SHORTCUT, parent=None):
        super().__init__(parent)
        self._default = default
        self._recording = False

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self._edit = QLineEdit()
        self._edit.setReadOnly(True)
        self._edit.setPlaceholderText("点击「录制按键」后按下组合键")
        layout.addWidget(self._edit, stretch=1)

        self._btn_record = QPushButton("录制按键")
        self._btn_record.setCheckable(True)
        self._btn_record.clicked.connect(self._toggle_record)
        layout.addWidget(self._btn_record)

        self._btn_reset = QPushButton("恢复默认")
        self._btn_reset.clicked.connect(self._restore_default)
        layout.addWidget(self._btn_reset)

        self.set_sequence(default)

    def set_sequence(self, seq: str):
        text = seq.strip() or self._default
        self._edit.setText(text)
        self.sequence_changed.emit(text)

    def sequence(self) -> str:
        return self._edit.text().strip() or self._default

    def _restore_default(self):
        self._stop_record()
        self.set_sequence(self._default)

    def _toggle_record(self, checked: bool):
        if checked:
            self._recording = True
            self._btn_record.setText("按下组合键…")
            self._edit.setText("")
            self._edit.setPlaceholderText("正在录制，按 Esc 取消")
            self.grabKeyboard()
        else:
            self._stop_record()

    def _stop_record(self):
        self._recording = False
        self._btn_record.setChecked(False)
        self._btn_record.setText("录制按键")
        self._edit.setPlaceholderText("点击「录制按键」后按下组合键")
        self.releaseKeyboard()

    def keyPressEvent(self, event):
        if not self._recording:
            super().keyPressEvent(event)
            return

        if event.key() == Qt.Key_Escape:
            self._stop_record()
            self.set_sequence(self.sequence() or self._default)
            return

        key = event.key()
        if key in (Qt.Key_Control, Qt.Key_Shift, Qt.Key_Alt, Qt.Key_Meta):
            return

        mods = event.modifiers()
        seq = QKeySequence(mods | key)
        text = seq.toString(QKeySequence.NativeText)
        if not text:
            text = seq.toString()
        self._stop_record()
        self.set_sequence(text)
        event.accept()
