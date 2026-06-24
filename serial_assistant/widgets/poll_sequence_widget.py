"""发送序列 — 轮询 + 参数化，每行独立布局（不用 QTableWidget）"""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFrame,
    QPushButton, QComboBox, QCheckBox, QLabel, QSpinBox, QLineEdit, QSizePolicy,
)


def default_poll_item(cmd: str = "") -> Dict[str, Any]:
    return {
        "enabled": True,
        "cmd": cmd,
        "var": "none",
        "start": 0,
        "step": 1,
        "end_mode": "none",
        "end_value": 100,
        "end_count": 10,
        "end_action": "hold",
        "list": "",
    }


def _parse_legacy_param(var: str, param: str, item: Dict[str, Any]) -> Dict[str, Any]:
    if var != "inc" or not param:
        return item
    if "," in param:
        parts = [p.strip() for p in param.split(",") if p.strip()]
        if parts:
            item["start"] = int(parts[0])
        if len(parts) > 1:
            item["step"] = int(parts[1])
    elif param.lstrip("-").isdigit():
        item["step"] = int(param)
    return item


def _normalize_items(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    if not items:
        return [default_poll_item()]
    copied = [dict(it) for it in items]
    with_cmd = [it for it in copied if str(it.get("cmd", "")).strip()]
    if with_cmd:
        return with_cmd
    return [copied[0]]


def migrate_poll_sequence(raw: list) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for x in raw or []:
        if isinstance(x, str):
            out.append(default_poll_item(x))
        elif isinstance(x, dict):
            var = str(x.get("var", "none"))
            item = default_poll_item(str(x.get("cmd", "")))
            item["enabled"] = bool(x.get("enabled", True))
            item["var"] = var
            item["start"] = int(x.get("start", 0))
            item["step"] = int(x.get("step", 1))
            item["end_mode"] = str(x.get("end_mode", "none"))
            item["end_value"] = int(x.get("end_value", 100))
            item["end_count"] = int(x.get("end_count", 10))
            item["end_action"] = str(x.get("end_action", "hold"))
            if var == "list":
                item["list"] = str(x.get("list", x.get("param", "")))
            else:
                item["list"] = str(x.get("list", ""))
            _parse_legacy_param(var, str(x.get("param", "")), item)
            if var == "inc" and item.get("list"):
                item["list"] = ""
            out.append(item)
    return _normalize_items(out)


class _PollRowWidget(QFrame):
    """单行：首行指令 + 次行参数（自增/列表时显示）"""

    changed = pyqtSignal()
    clicked_row = pyqtSignal(int)

    def __init__(self, row_index: int, item: Dict[str, Any], parent=None):
        super().__init__(parent)
        self._index = row_index
        self.setObjectName("poll_seq_row")
        self.setFrameShape(QFrame.StyledPanel)
        self.setCursor(Qt.PointingHandCursor)

        root = QVBoxLayout(self)
        root.setContentsMargins(8, 6, 8, 6)
        root.setSpacing(6)

        line1 = QHBoxLayout()
        line1.setSpacing(8)
        self.chk = QCheckBox("轮询")
        self.chk.setChecked(bool(item.get("enabled", True)))
        self.chk.toggled.connect(self._emit_changed)
        line1.addWidget(self.chk)

        self.cmd = QLineEdit(str(item.get("cmd", "")))
        self.cmd.setPlaceholderText("指令模板，如 C,1,{i}")
        self.cmd.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.cmd.textChanged.connect(self._emit_changed)
        line1.addWidget(self.cmd, stretch=1)

        line1.addWidget(QLabel("变化"))
        self.var = QComboBox()
        self.var.setFixedWidth(76)
        self.var.addItem("固定", "none")
        self.var.addItem("自增", "inc")
        self.var.addItem("列表", "list")
        idx = self.var.findData(str(item.get("var", "none")))
        self.var.setCurrentIndex(idx if idx >= 0 else 0)
        self.var.currentIndexChanged.connect(self._on_var_changed)
        line1.addWidget(self.var)
        root.addLayout(line1)

        self._params = QWidget()
        params = QHBoxLayout(self._params)
        params.setContentsMargins(0, 0, 0, 0)
        params.setSpacing(8)

        params.addWidget(QLabel("起"))
        self.start = QSpinBox()
        self.start.setRange(-999999, 999999)
        self.start.setValue(int(item.get("start", 0)))
        self.start.setFixedWidth(88)
        self.start.valueChanged.connect(self._emit_changed)
        params.addWidget(self.start)

        params.addWidget(QLabel("步"))
        self.step = QSpinBox()
        self.step.setRange(-999999, 999999)
        self.step.setValue(int(item.get("step", 1)))
        self.step.setFixedWidth(88)
        self.step.valueChanged.connect(self._emit_changed)
        params.addWidget(self.step)

        params.addWidget(QLabel("结束"))
        self.end_mode = QComboBox()
        self.end_mode.setFixedWidth(76)
        self.end_mode.addItem("无限", "none")
        self.end_mode.addItem("≤值", "max")
        self.end_mode.addItem("次数", "count")
        em = str(item.get("end_mode", "none"))
        ei = self.end_mode.findData(em)
        self.end_mode.setCurrentIndex(ei if ei >= 0 else 0)
        self.end_mode.currentIndexChanged.connect(self._on_end_mode_changed)
        params.addWidget(self.end_mode)

        params.addWidget(QLabel("限值"))
        limit_val = int(item.get("end_count" if em == "count" else "end_value", 100))
        self.limit = QSpinBox()
        self.limit.setRange(-999999, 999999)
        self.limit.setValue(limit_val)
        self.limit.setFixedWidth(88)
        self.limit.valueChanged.connect(self._emit_changed)
        params.addWidget(self.limit)

        params.addWidget(QLabel("到时"))
        self.action = QComboBox()
        self.action.setFixedWidth(76)
        self.action.addItem("保持", "hold")
        self.action.addItem("重置", "reset")
        self.action.addItem("停用", "disable")
        ai = self.action.findData(str(item.get("end_action", "hold")))
        self.action.setCurrentIndex(ai if ai >= 0 else 0)
        self.action.currentIndexChanged.connect(self._emit_changed)
        params.addWidget(self.action)
        params.addStretch()
        root.addWidget(self._params)

        self._list_row = QWidget()
        list_lay = QHBoxLayout(self._list_row)
        list_lay.setContentsMargins(0, 0, 0, 0)
        list_lay.setSpacing(8)
        list_lay.addWidget(QLabel("列表"))
        self.list_edit = QLineEdit()
        if str(item.get("var", "none")) == "list":
            self.list_edit.setText(str(item.get("list", "")))
        self.list_edit.setPlaceholderText("逗号分隔，如 1,2,3")
        self.list_edit.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.list_edit.textChanged.connect(self._emit_changed)
        list_lay.addWidget(self.list_edit, stretch=1)
        root.addWidget(self._list_row)

        self._refresh_mode_ui()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked_row.emit(self._index)
        super().mousePressEvent(event)

    def set_selected(self, on: bool):
        self.setProperty("selected", on)
        self.style().unpolish(self)
        self.style().polish(self)

    def set_row_index(self, index: int):
        self._index = index

    def _emit_changed(self, *_args):
        self.changed.emit()

    def _on_var_changed(self, *_args):
        self._refresh_mode_ui()
        self.changed.emit()

    def _on_end_mode_changed(self, *_args):
        mode = self.end_mode.currentData()
        self.limit.setSuffix("次" if mode == "count" else "")
        need = mode in ("max", "count")
        self.limit.setEnabled(need)
        self.changed.emit()

    def _refresh_mode_ui(self):
        var = self.var.currentData()
        inc = var == "inc"
        lst = var == "list"
        self._params.setVisible(inc)
        self._list_row.setVisible(lst)
        if inc:
            mode = self.end_mode.currentData()
            need = mode in ("max", "count")
            self.limit.setEnabled(need)
            self.limit.setSuffix("次" if mode == "count" else "")

    def to_dict(self) -> Dict[str, Any]:
        em = self.end_mode.currentData()
        d = {
            "enabled": self.chk.isChecked(),
            "cmd": self.cmd.text(),
            "var": self.var.currentData(),
            "start": self.start.value(),
            "step": self.step.value(),
            "end_mode": em,
            "end_action": self.action.currentData(),
            "list": self.list_edit.text().strip(),
        }
        if em == "count":
            d["end_count"] = self.limit.value()
            d["end_value"] = 100
        else:
            d["end_value"] = self.limit.value()
            d["end_count"] = 10
        return d


class PollSequenceWidget(QWidget):
    """发送序列列表"""

    changed = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._items: List[Dict[str, Any]] = []
        self._row_widgets: List[_PollRowWidget] = []
        self._counters: Dict[int, int] = {}
        self._list_indices: Dict[int, int] = {}
        self._last_values: Dict[int, str] = {}
        self._inc_counts: Dict[int, int] = {}
        self._disabled_rows: set[int] = set()
        self._selected_index = 0
        self._blocking = False
        self._fill_cb: Optional[Callable[[], str]] = None

        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        self._rows_host = QWidget()
        self._rows_host.setObjectName("poll_seq_list")
        self._rows_layout = QVBoxLayout(self._rows_host)
        self._rows_layout.setContentsMargins(0, 0, 0, 0)
        self._rows_layout.setSpacing(6)
        layout.addWidget(self._rows_host)

        row = QHBoxLayout()
        btn_add = QPushButton("+ 添加")
        btn_add.clicked.connect(lambda: self._insert_row())
        btn_del = QPushButton("− 删除")
        btn_del.clicked.connect(self._delete_rows)
        btn_up = QPushButton("↑")
        btn_up.setFixedWidth(32)
        btn_up.setToolTip("上移")
        btn_up.clicked.connect(lambda: self._move_row(-1))
        btn_dn = QPushButton("↓")
        btn_dn.setFixedWidth(32)
        btn_dn.setToolTip("下移")
        btn_dn.clicked.connect(lambda: self._move_row(1))
        btn_from = QPushButton("← 用输入框")
        btn_from.setToolTip("将发送框内容填入选中行模板")
        btn_from.clicked.connect(self._on_from_input)
        row.addWidget(btn_add)
        row.addWidget(btn_del)
        row.addWidget(btn_up)
        row.addWidget(btn_dn)
        row.addStretch()
        lbl = QLabel("用 ↑↓ 调整顺序；自增用 {i}/{v}；结束：无限/≤值/次数")
        lbl.setObjectName("status_hint")
        row.addWidget(lbl)
        row.addWidget(btn_from)
        layout.addLayout(row)

    def current_row(self) -> int:
        return self._selected_index

    def set_fill_from_input_callback(self, cb: Callable[[], str]):
        self._fill_cb = cb

    def _on_from_input(self):
        if not self._fill_cb:
            return
        text = self._fill_cb().strip()
        if not text:
            return
        r = self._selected_index
        if 0 <= r < len(self._items):
            self._items[r]["cmd"] = text
            self._render_rows()

    def _on_row_changed(self):
        if self._blocking:
            return
        self._sync_from_widgets()
        self.changed.emit()

    def _on_row_clicked(self, index: int):
        self._selected_index = index
        self._update_selection()

    def _update_selection(self):
        for i, w in enumerate(self._row_widgets):
            w.set_selected(i == self._selected_index)

    def _sync_from_widgets(self):
        for i, w in enumerate(self._row_widgets):
            if i < len(self._items):
                self._items[i] = w.to_dict()

    def _move_row(self, delta: int):
        r = self._selected_index
        dst = r + delta
        if r < 0 or dst < 0 or dst >= len(self._items):
            return
        self._items[r], self._items[dst] = self._items[dst], self._items[r]
        self._selected_index = dst
        self._render_rows()
        self.changed.emit()

    def _insert_row(self, item: Dict[str, Any] | None = None, index: int | None = None):
        item = dict(item or default_poll_item())
        if index is None:
            self._items.append(item)
            self._selected_index = len(self._items) - 1
        else:
            self._items.insert(index, item)
            self._selected_index = index
        self._render_rows()
        self.changed.emit()

    def _delete_rows(self):
        if not self._items:
            return
        r = self._selected_index
        if 0 <= r < len(self._items):
            self._items.pop(r)
        if not self._items:
            self._items.append(default_poll_item())
        self._selected_index = min(r, len(self._items) - 1)
        self._render_rows()
        self.changed.emit()

    def _render_rows(self):
        self._blocking = True
        while self._rows_layout.count():
            item = self._rows_layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()
        self._row_widgets.clear()

        for i, data in enumerate(self._items):
            rw = _PollRowWidget(i, data, self._rows_host)
            rw.changed.connect(self._on_row_changed)
            rw.clicked_row.connect(self._on_row_clicked)
            self._rows_layout.addWidget(rw)
            self._row_widgets.append(rw)

        self._rows_layout.addStretch()
        self._blocking = False
        self._selected_index = min(self._selected_index, max(0, len(self._items) - 1))
        self._update_selection()

    def set_items(self, items: List[Dict[str, Any]]):
        self._items = _normalize_items([dict(it) for it in items] if items else [])
        self._render_rows()

    def get_items(self) -> List[Dict[str, Any]]:
        self._sync_from_widgets()
        return [dict(it) for it in self._items]

    def items_for_persist(self) -> List[Dict[str, Any]]:
        return _normalize_items(self.get_items())

    def reset_runtime_state(self):
        self._counters.clear()
        self._list_indices.clear()
        self._last_values.clear()
        self._inc_counts.clear()
        self._disabled_rows.clear()

    def _apply_end_action(self, row_index: int, item: Dict[str, Any], cur: int):
        action = item.get("end_action", "hold")
        if action == "reset":
            self._counters.pop(row_index, None)
            self._inc_counts.pop(row_index, None)
            self._disabled_rows.discard(row_index)
        elif action == "disable":
            self._disabled_rows.add(row_index)
            self._last_values[row_index] = str(cur)
        else:
            self._last_values[row_index] = str(cur)

    def _inc_reached_end(self, row_index: int, item: Dict[str, Any], cur: int) -> bool:
        mode = item.get("end_mode", "none")
        step = int(item.get("step", 1))
        if mode == "max":
            limit = int(item.get("end_value", 0))
            if step >= 0:
                return cur >= limit
            return cur <= limit
        if mode == "count":
            n = self._inc_counts.get(row_index, 0)
            return n >= int(item.get("end_count", 1))
        return False

    def resolve_cmd(self, row_index: int, item: Dict[str, Any]) -> Optional[str]:
        if row_index in self._disabled_rows:
            action = item.get("end_action", "hold")
            if action == "disable":
                last = self._last_values.get(row_index)
                if last is not None:
                    cmd = item.get("cmd", "")
                    return cmd.replace("{i}", last).replace("{v}", last)
                return None
            return None

        cmd = item.get("cmd", "")
        var = item.get("var", "none")

        if var == "inc":
            start = int(item.get("start", 0))
            step = int(item.get("step", 1))
            cur = self._counters.get(row_index, start)

            if self._inc_reached_end(row_index, item, cur):
                self._apply_end_action(row_index, item, cur)
                if row_index in self._disabled_rows:
                    last = self._last_values.get(row_index, str(cur))
                    return cmd.replace("{i}", last).replace("{v}", last)
                if item.get("end_action") == "reset":
                    cur = self._counters.get(row_index, start)
                else:
                    return cmd.replace("{i}", str(cur)).replace("{v}", str(cur))

            self._counters[row_index] = cur + step
            self._inc_counts[row_index] = self._inc_counts.get(row_index, 0) + 1
            s = str(cur)
            resolved = cmd.replace("{i}", s).replace("{v}", s)

            if self._inc_reached_end(row_index, item, cur):
                self._apply_end_action(row_index, item, cur)
            return resolved

        if var == "list":
            vals = [v.strip() for v in str(item.get("list", "")).split(",") if v.strip()]
            if not vals:
                return cmd
            idx = self._list_indices.get(row_index, 0) % len(vals)
            self._list_indices[row_index] = idx + 1
            v = vals[idx]
            return cmd.replace("{v}", v).replace("{i}", v)

        return cmd

    def enabled_items_with_index(self) -> List[tuple[int, Dict[str, Any]]]:
        all_items = self.get_items()
        result = []
        for i, it in enumerate(all_items):
            if not it.get("enabled", True):
                continue
            if i in self._disabled_rows and it.get("end_action") == "disable":
                continue
            result.append((i, it))
        return result

    def row_skipped_in_poll(self, row_index: int, item: Dict[str, Any]) -> bool:
        return row_index in self._disabled_rows and item.get("end_action") == "disable"

    def send_once_row(self, row: int) -> Optional[str]:
        if row < 0 or row >= len(self._items):
            return None
        self._sync_from_widgets()
        item = self._items[row]
        return self.resolve_cmd(row, item)
