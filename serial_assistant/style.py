"""应用主题 - LED 颜色常量与 QSS 暗色样式表"""

# ── LED 指示灯颜色 ──────────────────────────────
LED_ON   = "#44CC44"   # 服务运行中（绿）
LED_OFF  = "#555577"   # 服务已停止（暗蓝灰）
LED_ERR  = "#CC4444"   # 服务出错（红）
LED_WARN = "#CCAA00"   # 警告/连接中（黄）

# ── Tokyo Night 暗色主题 ──────────────────────────
DARK_STYLESHEET = """
/* ── 全局基础 ── */
* {
    font-family: "Segoe UI", "Microsoft YaHei UI", "SimHei", sans-serif;
    font-size: 12px;
    outline: none;
}

QMainWindow {
    background-color: #1A1B26;
}

QWidget {
    background-color: #1A1B26;
    color: #C0CAF5;
}

QLabel, QCheckBox, QRadioButton {
    background-color: transparent;
}

/* ── 分组框 ── */
QGroupBox {
    background-color: #1E2030;
    border: 1px solid #2F354A;
    border-radius: 8px;
    margin-top: 10px;
    padding-top: 4px;
    font-weight: bold;
    color: #7AA2F7;
}
QGroupBox::title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    padding: 0 8px;
    left: 10px;
}

/* ── 标签 ── */
QLabel {
    color: #A9B1D6;
    background-color: transparent;
}

/* ── 下拉框 ── */
QComboBox {
    background-color: #24283B;
    border: 1px solid #2F354A;
    border-radius: 5px;
    padding: 2px 8px;
    color: #C0CAF5;
    min-height: 24px;
    selection-background-color: #364A82;
}
QComboBox:hover  { border-color: #7AA2F7; }
QComboBox:disabled { color: #565F89; border-color: #1E2030; background-color: #1E2030; }
QComboBox::drop-down {
    border: none;
    width: 20px;
    background-color: #364A82;
    border-top-right-radius: 4px;
    border-bottom-right-radius: 4px;
}
QComboBox::drop-down:hover { background-color: #3D59A1; }
QComboBox QAbstractItemView {
    background-color: #1E2030;
    border: 1px solid #2F354A;
    border-radius: 5px;
    color: #C0CAF5;
    selection-background-color: #364A82;
}

/* ── 输入框 ── */
QLineEdit {
    background-color: #24283B;
    border: 1px solid #2F354A;
    border-radius: 5px;
    padding: 2px 8px;
    color: #C0CAF5;
    min-height: 24px;
}
QLineEdit:hover  { border-color: #7AA2F7; }
QLineEdit:focus  { border-color: #7AA2F7; background-color: #1E2030; }
QLineEdit:disabled { color: #565F89; background-color: #1A1B26; }
QLineEdit[readOnly="true"] { background-color: #1E2030; color: #565F89; }

/* ── 文本编辑区 ── */
QTextEdit {
    background-color: #24283B;
    border: 1px solid #2F354A;
    border-radius: 6px;
    padding: 4px;
    color: #C0CAF5;
}
QTextEdit:focus { border-color: #7AA2F7; }

/* ── 通用按钮 ── */
QPushButton {
    background-color: #364A82;
    color: #C0CAF5;
    border: 1px solid #3B4261;
    border-radius: 6px;
    padding: 4px 14px;
    min-height: 26px;
}
QPushButton:hover   { background-color: #3D59A1; border-color: #7AA2F7; }
QPushButton:pressed { background-color: #2A3F7E; }
QPushButton:disabled { background-color: #24283B; color: #565F89; border-color: #2F354A; }
QPushButton:checked  { background-color: #BB9AF7; color: #1A1B26; border-color: #BB9AF7; }

/* ── Tab 组件 ── */
QTabWidget::pane {
    border: 1px solid #2F354A;
    border-radius: 8px;
    background-color: #1E2030;
    top: -1px;
}
QTabBar::tab {
    background-color: #24283B;
    color: #A9B1D6;
    border: 1px solid #2F354A;
    border-bottom: none;
    border-radius: 5px 5px 0 0;
    padding: 6px 18px;
    margin-right: 2px;
}
QTabBar::tab:selected {
    background-color: #1E2030;
    color: #7AA2F7;
    border-bottom: 2px solid #7AA2F7;
}
QTabBar::tab:hover:!selected {
    background-color: #1E2030;
    color: #C0CAF5;
}

/* ── 滚动条 ── */
QScrollBar:vertical {
    background-color: #1E2030;
    width: 8px;
    border-radius: 4px;
}
QScrollBar::handle:vertical {
    background-color: #3B4261;
    border-radius: 4px;
    min-height: 24px;
}
QScrollBar::handle:vertical:hover { background-color: #565F89; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }

QScrollBar:horizontal {
    background-color: #1E2030;
    height: 8px;
    border-radius: 4px;
}
QScrollBar::handle:horizontal {
    background-color: #3B4261;
    border-radius: 4px;
    min-width: 24px;
}
QScrollBar::handle:horizontal:hover { background-color: #565F89; }
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0; }

/* ── 复选框 ── */
QCheckBox { color: #A9B1D6; spacing: 6px; }
QCheckBox::indicator {
    width: 14px; height: 14px;
    border-radius: 3px;
    border: 1px solid #3B4261;
    background-color: #24283B;
}
QCheckBox::indicator:checked { background-color: #7AA2F7; border-color: #7AA2F7; }
QCheckBox::indicator:hover   { border-color: #7AA2F7; }
QCheckBox:disabled { color: #565F89; }

/* ── 进度条 ── */
QProgressBar {
    background-color: #24283B;
    border: 1px solid #2F354A;
    border-radius: 5px;
    text-align: center;
    color: #C0CAF5;
    min-height: 18px;
}
QProgressBar::chunk { background-color: #7AA2F7; border-radius: 4px; }

/* ── 消息框 ── */
QMessageBox { background-color: #1E2030; }
QMessageBox QPushButton { min-width: 70px; }

/* ── 对话框 ── */
QDialog { background-color: #1A1B26; }
QDialogButtonBox QPushButton { min-width: 80px; }

/* ── 分隔线 ── */
QFrame[frameShape="4"], QFrame[frameShape="5"] { color: #2F354A; }

/* ── 工具提示 ── */
QToolTip {
    background-color: #24283B;
    color: #C0CAF5;
    border: 1px solid #3B4261;
    border-radius: 4px;
    padding: 4px 8px;
}

/* ── SpinBox ── */
QSpinBox, QDoubleSpinBox {
    background-color: #24283B;
    border: 1px solid #2F354A;
    border-radius: 5px;
    padding: 2px 6px;
    color: #C0CAF5;
    min-height: 24px;
}
QSpinBox:hover, QDoubleSpinBox:hover { border-color: #7AA2F7; }
QSpinBox::up-button, QDoubleSpinBox::up-button,
QSpinBox::down-button, QDoubleSpinBox::down-button {
    background-color: #2F354A;
    border: none;
    border-radius: 3px;
    width: 14px;
}

/* ── RadioButton ── */
QRadioButton { color: #A9B1D6; spacing: 6px; }
QRadioButton::indicator {
    width: 14px; height: 14px;
    border-radius: 7px;
    border: 1px solid #3B4261;
    background-color: #24283B;
}
QRadioButton::indicator:checked { background-color: #7AA2F7; border-color: #7AA2F7; }

/* ── 颜色选择对话框 ── */
QColorDialog { background-color: #1E2030; }

/* ── Splitter ── */
QSplitter::handle {
    background-color: #1A1B26;
}
QSplitter::handle:horizontal {
    width: 4px;
}
QSplitter::handle:vertical {
    height: 4px;
}
QSplitter::handle:hover {
    background-color: #364A82;
}

/* ── 服务卡片 (QFrame#service_card) ── */
QFrame#service_card {
    background-color: #24283B;
    border: 1px solid #2F354A;
    border-radius: 6px;
}
QFrame#service_card:hover {
    border-color: #364A82;
}

/* ── 右上角工具栏按钮 ── */
QPushButton#theme_toggle, QPushButton#settings_btn {
    background-color: #24283B;
    color: #A9B1D6;
    border: 1px solid #2F354A;
    border-radius: 12px;
    padding: 2px 12px;
    font-weight: bold;
    min-height: 24px;
}
QPushButton#theme_toggle:hover, QPushButton#settings_btn:hover {
    background-color: #2A2E44;
    border-color: #364A82;
    color: #C0CAF5;
}
QPushButton#theme_toggle:checked {
    background-color: #364A82;
    color: #FFFFFF;
    border-color: #7AA2F7;
}
"""

# ── Light 主题 ──────────────────────────
LIGHT_STYLESHEET = """
/* ── 全局基础 ── */
* {
    font-family: "Segoe UI", "Microsoft YaHei UI", "SimHei", sans-serif;
    font-size: 12px;
    outline: none;
}

QMainWindow {
    background-color: #FFFFFF;
}

QWidget {
    background-color: #FFFFFF;
    color: #202124;
}

QLabel, QCheckBox, QRadioButton {
    background-color: transparent;
}

/* ── 分组框 ── */
QGroupBox {
    background-color: #F8F9FA;
    border: 1px solid #E0E0E0;
    border-radius: 8px;
    margin-top: 15px;
    padding-top: 15px;
    font-weight: bold;
    color: #1A73E8;
}
QGroupBox::title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    padding: 0 5px;
    left: 10px;
}

/* ── 标签 ── */
QLabel {
    color: #555555;
    background-color: transparent;
}

/* ── 下拉框 ── */
QComboBox {
    background-color: #FFFFFF;
    border: 1px solid #D9D9D9;
    border-radius: 5px;
    padding: 2px 8px;
    color: #333333;
    min-height: 24px;
    selection-background-color: #E6F7FF;
    selection-color: #1890FF;
}
QComboBox:hover  { border-color: #1890FF; }
QComboBox:disabled { color: #BFBFBF; border-color: #F0F2F5; background-color: #F0F2F5; }
QComboBox::drop-down {
    border: none;
    width: 20px;
    background-color: #E6F7FF;
    border-top-right-radius: 4px;
    border-bottom-right-radius: 4px;
}
QComboBox::drop-down:hover { background-color: #BAE7FF; }
QComboBox QAbstractItemView {
    background-color: #FFFFFF;
    border: 1px solid #D9D9D9;
    border-radius: 5px;
    color: #333333;
    selection-background-color: #E6F7FF;
    selection-color: #1890FF;
}

/* ── 输入框 ── */
QLineEdit {
    background-color: #FFFFFF;
    border: 1px solid #D9D9D9;
    border-radius: 5px;
    padding: 2px 8px;
    color: #333333;
    min-height: 24px;
}
QLineEdit:hover  { border-color: #1890FF; }
QLineEdit:focus  { border-color: #1890FF; background-color: #FFFFFF; }
QLineEdit:disabled { color: #BFBFBF; background-color: #F5F5F5; }
QLineEdit[readOnly="true"] { background-color: #F5F5F5; color: #888888; }

/* ── 文本编辑区 ── */
QTextEdit {
    background-color: #FFFFFF;
    border: 1px solid #D9D9D9;
    border-radius: 6px;
    padding: 4px;
    color: #333333;
}
QTextEdit:focus { border-color: #1890FF; }

/* ── 通用按钮 ── */
QPushButton {
    background-color: #FFFFFF;
    color: #333333;
    border: 1px solid #D9D9D9;
    border-radius: 6px;
    padding: 4px 14px;
    min-height: 26px;
}
QPushButton:hover   { border-color: #1890FF; color: #1890FF; }
QPushButton:pressed { background-color: #F0F2F5; }
QPushButton:disabled { background-color: #F5F5F5; color: #BFBFBF; border-color: #D9D9D9; }
QPushButton:checked  { background-color: #1890FF; color: #FFFFFF; border-color: #1890FF; }

/* ── Tab 组件 ── */
QTabWidget::pane {
    border: 1px solid #D9D9D9;
    border-radius: 8px;
    background-color: #FFFFFF;
    top: -1px;
}
QTabBar::tab {
    background-color: #FAFAFA;
    color: #555555;
    border: 1px solid #D9D9D9;
    border-bottom: none;
    border-radius: 5px 5px 0 0;
    padding: 6px 18px;
    margin-right: 2px;
}
QTabBar::tab:selected {
    background-color: #FFFFFF;
    color: #1890FF;
    border-bottom: 2px solid #1890FF;
}
QTabBar::tab:hover:!selected {
    background-color: #F0F2F5;
    color: #333333;
}

/* ── 滚动条 ── */
QScrollBar:vertical {
    background-color: #F0F2F5;
    width: 8px;
    border-radius: 4px;
}
QScrollBar::handle:vertical {
    background-color: #BFBFBF;
    border-radius: 4px;
    min-height: 24px;
}
QScrollBar::handle:vertical:hover { background-color: #8C8C8C; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }

QScrollBar:horizontal {
    background-color: #F0F2F5;
    height: 8px;
    border-radius: 4px;
}
QScrollBar::handle:horizontal {
    background-color: #BFBFBF;
    border-radius: 4px;
    min-width: 24px;
}
QScrollBar::handle:horizontal:hover { background-color: #8C8C8C; }
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0; }

/* ── 复选框 ── */
QCheckBox { color: #333333; spacing: 6px; }
QCheckBox::indicator {
    width: 14px; height: 14px;
    border-radius: 3px;
    border: 1px solid #D9D9D9;
    background-color: #FFFFFF;
}
QCheckBox::indicator:checked { background-color: #1890FF; border-color: #1890FF; }
QCheckBox::indicator:hover   { border-color: #1890FF; }
QCheckBox:disabled { color: #BFBFBF; }

/* ── 进度条 ── */
QProgressBar {
    background-color: #F5F5F5;
    border: 1px solid #D9D9D9;
    border-radius: 5px;
    text-align: center;
    color: #333333;
    min-height: 18px;
}
QProgressBar::chunk { background-color: #1890FF; border-radius: 4px; }

/* ── 消息框 ── */
QMessageBox { background-color: #FFFFFF; }
QMessageBox QPushButton { min-width: 70px; }

/* ── 对话框 ── */
QDialog { background-color: #F0F2F5; }
QDialogButtonBox QPushButton { min-width: 80px; }

/* ── 分隔线 ── */
QFrame[frameShape="4"], QFrame[frameShape="5"] { color: #D9D9D9; }

/* ── 工具提示 ── */
QToolTip {
    background-color: #FFFFFF;
    color: #333333;
    border: 1px solid #D9D9D9;
    border-radius: 4px;
    padding: 4px 8px;
}

/* ── SpinBox ── */
QSpinBox, QDoubleSpinBox {
    background-color: #FFFFFF;
    border: 1px solid #D9D9D9;
    border-radius: 5px;
    padding: 2px 6px;
    color: #333333;
    min-height: 24px;
}
QSpinBox:hover, QDoubleSpinBox:hover { border-color: #1890FF; }
QSpinBox::up-button, QDoubleSpinBox::up-button,
QSpinBox::down-button, QDoubleSpinBox::down-button {
    background-color: #F0F2F5;
    border: none;
    border-radius: 3px;
    width: 14px;
}

/* ── RadioButton ── */
QRadioButton { color: #333333; spacing: 6px; }
QRadioButton::indicator {
    width: 14px; height: 14px;
    border-radius: 7px;
    border: 1px solid #D9D9D9;
    background-color: #FFFFFF;
}
QRadioButton::indicator:checked { background-color: #1890FF; border-color: #1890FF; }

/* ── 颜色选择对话框 ── */
QColorDialog { background-color: #FFFFFF; }

/* ── Splitter ── */
QSplitter::handle {
    background-color: #F0F2F5;
}
QSplitter::handle:horizontal {
    width: 4px;
}
QSplitter::handle:vertical {
    height: 4px;
}
QSplitter::handle:hover {
    background-color: #D2E3FC;
}

/* ── 服务卡片 (QFrame#service_card) ── */
QFrame#service_card {
    background-color: #F8F9FA;
    border: 1px solid #E0E0E0;
    border-radius: 6px;
}
QFrame#service_card:hover {
    border-color: #1A73E8;
    background-color: #F1F3F4;
}

/* ── 右上角工具栏按钮 ── */
QPushButton#theme_toggle, QPushButton#settings_btn {
    background-color: #FFFFFF;
    color: #5F6368;
    border: 1px solid #DADCE0;
    border-radius: 12px;
    padding: 2px 12px;
    font-weight: bold;
    min-height: 24px;
}
QPushButton#theme_toggle:hover, QPushButton#settings_btn:hover {
    background-color: #F1F3F4;
    color: #202124;
}
QPushButton#theme_toggle:checked {
    background-color: #E8F0FE;
    color: #1A73E8;
    border-color: #1A73E8;
}
"""

