"""轮询发送序列编辑"""

from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QLabel, QTextEdit, QDialogButtonBox, QCheckBox,
)


class SequenceSendDialog(QDialog):
    """多行指令，按顺序轮询发送"""

    def __init__(self, lines: str = "", parent=None):
        super().__init__(parent)
        self.setWindowTitle("轮询发送序列")
        self.setMinimumSize(440, 320)

        layout = QVBoxLayout(self)

        hint = QLabel(
            "每一行 = 轮询中的一条指令（在编辑框里按 Enter 换行即可分行）。\n"
            "发送时自动沿用发送栏的「新行」「转义」设置：\n"
            "  · 勾选「新行」→ 每条末尾自动加 \\r\\n\n"
            "  · 勾选「转义」→ 行内 \\r\\n、\\x41 等会变为真实字节"
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color:#888;font-size:11px;")
        layout.addWidget(hint)

        self.txt = QTextEdit()
        self.txt.setFontFamily("Consolas")
        self.txt.setPlainText(lines)
        self.txt.setPlaceholderText(
            "666,111,222\n"
            "AT+GMR\n"
            "AT\\r\\n"
        )
        layout.addWidget(self.txt)

        self.chk_skip_blank = QCheckBox("忽略空行")
        self.chk_skip_blank.setChecked(True)
        layout.addWidget(self.chk_skip_blank)

        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)

    def lines(self) -> list[str]:
        raw = self.txt.toPlainText().splitlines()
        if self.chk_skip_blank.isChecked():
            return [ln for ln in raw if ln.strip()]
        return raw
