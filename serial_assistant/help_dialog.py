"""帮助 / 更新日志 / 功能路线图"""

from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QTabWidget, QTextBrowser, QPushButton,
)


HELP_USAGE = """
<h3>基础收发</h3>
<ul>
<li><b>文本 / HEX</b>：切换显示与发送格式。</li>
<li><b>转义</b>：勾选后，发送框里的 <code>\\r</code> <code>\\n</code> <code>\\t</code> <code>\\x41</code>
会变为真实字节，而不是两个字符。例：输入 <code>AT\\r\\n</code> 会发送 AT+回车换行。</li>
<li><b>发送新行</b>：在内容末尾自动追加 \\r\\n 等。</li>
<li><b>定时发送</b>：按间隔重复发送当前内容。</li>
<li><b>发送序列</b>：表格统一管理固定/自增/列表指令；勾选参与轮询，拖动行号排序。</li>
<li>自增可设<b>起始、步长、结束条件</b>（无限/≤值/次数）及<b>结束时</b>（保持/重置/停用）。</li>
<li><b>Ctrl+Enter</b>：发送；Enter 仍为换行。可在「设置→发送」录制按键修改。</li>
<li>发送历史会保存到配置文件，重启后仍可从「历史」下拉选用。</li>
</ul>

<h3>界面布局</h3>
<ul>
<li><b>常用</b>在顶栏：收发模式、按行、时间戳、自动滚动、发送。</li>
<li><b>接收过滤</b>常显于接收区上方；过滤栏右侧可勾选<b>指令解析</b>并管理规则。</li>
<li><b>发送序列</b>在发送区下方折叠区，含轮询与参数化表格。</li>
<li><b>自动滚动</b>：勾选时新数据滚到最新；取消可冻结画面查看历史（数据仍会继续显示）。</li>
</ul>

<h3>指令解析（右侧面板）</h3>
<p>点击「管理解析」配置帧头、帧尾、分隔符、整帧定长、字段名等。
可同时启用多条规则，实时显示最新一帧，展开可查看历史。</p>
<p>示例：帧头 <code>L</code>，分隔符 <code>,</code>，字段名 <code>id,value</code> ——
数据 <code>L1,23.5L2,40</code> 会解析为两帧。</p>
"""

HELP_DONE = """
<h3>已实现</h3>
<ul>
<li>UART / UDP 双通道</li>
<li>收发 HEX/文本、转义、定时发送、轮询发送</li>
<li>接收时间戳、按行显示、自动滚动、导出、落盘、上限截断</li>
<li>轮询序列表格、参数化发送（固定/自增/列表）</li>
<li>发送历史（去重）、快捷键录制</li>
<li>多路接收帧解析 + 命名字段</li>
<li>接收关键字过滤/高亮</li>
<li>示波器 / 图传 / ArUco 等扩展 Tab</li>
<li>网络 API / WebSocket / TCP / MCP</li>
<li>自定义波特率（下拉可编辑）</li>
</ul>
"""

HELP_PLANNED = """
<h3>计划中 / 暂未开放</h3>
<ul>
<li><b>DTR / RTS 控制线</b> — Arduino/ESP 复位与下载（界面已隐藏，后续可能加入）</li>
<li><b>快捷发送 JSON 模板编辑器</b> — 改为可视化「指令解析」配置</li>
<li><b>Modbus 等自动 CRC</b> — 发送模板自动计算校验</li>
<li><b>YMODEM 等文件传输协议</b> — 与「导出接收区」不同，需专用协议</li>
<li><b>更复杂的二进制位域解析</b> — 按 bit 定义字段</li>
</ul>
"""

CHANGELOG = """
<h3>更新日志</h3>
<p><b>V1.0</b></p>
<ul>
<li>插件化 Tab、PyInstaller 打包</li>
<li>基础收发增强：时间戳、落盘、自动滚动、历史、转义</li>
<li>接收多路帧解析面板</li>
<li>轮询序列表格、参数化发送、接收过滤常显</li>
<li>帮助与路线图窗口</li>
</ul>
"""


class HelpDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("帮助与更新")
        self.setMinimumSize(520, 420)

        layout = QVBoxLayout(self)
        tabs = QTabWidget()

        for title, html in [
            ("使用说明", HELP_USAGE),
            ("已实现", HELP_DONE),
            ("计划中", HELP_PLANNED),
            ("更新日志", CHANGELOG),
        ]:
            browser = QTextBrowser()
            browser.setOpenExternalLinks(True)
            browser.setHtml(html)
            tabs.addTab(browser, title)

        layout.addWidget(tabs)
        btn = QPushButton("关闭")
        btn.clicked.connect(self.accept)
        layout.addWidget(btn)
