"""ArUco 定位参数设置对话框"""

from __future__ import annotations

import copy
import os
from typing import Dict, List, Optional, Tuple

import yaml
from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox,
    QFormLayout, QGroupBox, QHBoxLayout, QLabel, QMessageBox,
    QPushButton, QRadioButton, QSpinBox, QTabWidget, QTableWidget,
    QTableWidgetItem, QVBoxLayout, QWidget, QHeaderView,
)

from aruco_loc.undistort_profiles import (
    DEFAULT_PROFILE_ID,
    migrate_undistort_section,
    list_profiles,
    profile_has_calib,
    delete_profile,
    restore_defaults,
    resolve_profile,
)

from app_paths import app_root, config_path

_PROJECT_ROOT = app_root()
_DEFAULT_CONFIG = config_path("aruco_config.yaml")

try:
    import cv2
    _DICT_NAMES = sorted(
        n for n in dir(cv2.aruco)
        if n.startswith("DICT_") and n.upper() == n
    )
except Exception:
    _DICT_NAMES = ["DICT_4X4_50", "DICT_5X5_100", "DICT_6X6_250"]


class ArucoSettingsDialog(QDialog):
    """编辑 config/aruco_config.yaml 中的标定与去畸变参数"""

    def __init__(
        self,
        config_path: str = _DEFAULT_CONFIG,
        parent=None,
        camera_index: Optional[int] = None,
        camera_uid: Optional[str] = None,
        camera_name: Optional[str] = None,
        on_calibration_saved: Optional[callable] = None,
    ):
        super().__init__(parent)
        self._path = config_path
        self._camera_index = camera_index if camera_index is not None else 0
        self._camera_uid = camera_uid
        self._camera_name = camera_name
        self._on_calibration_saved = on_calibration_saved

        self.setWindowTitle("ArUco 定位配置")
        self.setMinimumWidth(620)

        with open(self._path, "r", encoding="utf-8") as f:
            self._data: Dict = yaml.safe_load(f) or {}

        root = QVBoxLayout(self)
        tabs = QTabWidget()
        root.addWidget(tabs)
        tabs.addTab(self._build_detect_tab(), "检测与场地")
        tabs.addTab(self._build_undistort_tab(), "镜头去畸变")

        hint = QLabel(f"配置文件: {self._path}")
        hint.setStyleSheet("color:#888; font-size:11px;")
        root.addWidget(hint)

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._on_save)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

        self._load_fields()

    def _build_detect_tab(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)

        form = QFormLayout()
        self.combo_dict = QComboBox()
        for name in _DICT_NAMES:
            self.combo_dict.addItem(name, name)
        form.addRow("ArUco 字典:", self.combo_dict)

        self.spin_vehicle = QSpinBox()
        self.spin_vehicle.setRange(0, 1023)
        form.addRow("车辆标记 ID:", self.spin_vehicle)

        self.spin_min_markers = QSpinBox()
        self.spin_min_markers.setRange(3, 16)
        form.addRow("标定最少标记数:", self.spin_min_markers)

        self.spin_marker_m = QDoubleSpinBox()
        self.spin_marker_m.setRange(0.001, 1.0)
        self.spin_marker_m.setDecimals(4)
        self.spin_marker_m.setSuffix(" m")
        form.addRow("标记边长:", self.spin_marker_m)
        layout.addLayout(form)

        grp = QGroupBox("场地标记世界坐标 (mm)")
        gl = QVBoxLayout(grp)
        self.table_world = QTableWidget(0, 3)
        self.table_world.setHorizontalHeaderLabels(["ID", "X (mm)", "Y (mm)"])
        self.table_world.horizontalHeader().setStretchLastSection(True)
        gl.addWidget(self.table_world)

        row = QHBoxLayout()
        btn_add = QPushButton("添加行")
        btn_add.clicked.connect(self._add_world_row)
        btn_del = QPushButton("删除选中")
        btn_del.clicked.connect(self._del_world_row)
        row.addWidget(btn_add)
        row.addWidget(btn_del)
        row.addStretch()
        gl.addLayout(row)
        layout.addWidget(grp)
        return w

    def _build_undistort_tab(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)

        self.chk_undistort = QCheckBox("启用镜头去畸变")
        layout.addWidget(self.chk_undistort)

        cam_txt = (
            f"当前 Tab 摄像头: #{self._camera_uid} {self._camera_name}"
            if self._camera_uid is not None
            else "当前 Tab 未选择摄像头（标定向导将使用索引 0）"
        )
        self.lbl_current_camera = QLabel(cam_txt)
        self.lbl_current_camera.setStyleSheet("color:#AAA; font-size:11px;")
        layout.addWidget(self.lbl_current_camera)

        self.lbl_resolve_hint = QLabel("")
        self.lbl_resolve_hint.setWordWrap(True)
        self.lbl_resolve_hint.setStyleSheet("color:#CCAA00; font-size:12px;")
        layout.addWidget(self.lbl_resolve_hint)

        mode_grp = QGroupBox("参数加载方式")
        mode_layout = QVBoxLayout(mode_grp)
        self.radio_auto = QRadioButton("自动 — 按摄像头绑定匹配配置，无匹配则用默认")
        self.radio_manual = QRadioButton("手动 — 始终使用下方所选配置")
        self.radio_auto.toggled.connect(self._refresh_resolve_hint)
        self.radio_manual.toggled.connect(self._refresh_resolve_hint)
        mode_layout.addWidget(self.radio_auto)
        mode_layout.addWidget(self.radio_manual)
        manual_row = QHBoxLayout()
        manual_row.addWidget(QLabel("手动选择:"))
        self.combo_manual_profile = QComboBox()
        self.combo_manual_profile.currentIndexChanged.connect(self._refresh_resolve_hint)
        manual_row.addWidget(self.combo_manual_profile, stretch=1)
        mode_layout.addLayout(manual_row)
        layout.addWidget(mode_grp)

        prof_grp = QGroupBox("已保存的配置")
        prof_layout = QVBoxLayout(prof_grp)
        self.table_profiles = QTableWidget(0, 4)
        self.table_profiles.setHorizontalHeaderLabels(
            ["名称", "绑定摄像头", "RMS", "NPZ"]
        )
        self.table_profiles.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.Stretch
        )
        self.table_profiles.setSelectionBehavior(QTableWidget.SelectRows)
        self.table_profiles.setSelectionMode(QTableWidget.SingleSelection)
        self.table_profiles.itemSelectionChanged.connect(self._on_profile_selected)
        prof_layout.addWidget(self.table_profiles)

        prof_btn_row = QHBoxLayout()
        self.btn_wizard = QPushButton("镜头标定向导…")
        self.btn_wizard.setToolTip("棋盘格采集 → 命名 → 可选绑定当前摄像头")
        self.btn_wizard.clicked.connect(self._open_calib_wizard)
        prof_btn_row.addWidget(self.btn_wizard)
        self.btn_del_profile = QPushButton("删除选中配置")
        self.btn_del_profile.clicked.connect(self._on_delete_profile)
        prof_btn_row.addWidget(self.btn_del_profile)
        self.btn_bind_profile = QPushButton("绑定选中→当前摄像头")
        self.btn_bind_profile.clicked.connect(self._on_bind_profile)
        prof_btn_row.addWidget(self.btn_bind_profile)
        self.btn_unbind_profile = QPushButton("解除选中绑定")
        self.btn_unbind_profile.clicked.connect(self._on_unbind_profile)
        prof_btn_row.addWidget(self.btn_unbind_profile)
        self.btn_restore = QPushButton("恢复全部默认")
        self.btn_restore.clicked.connect(self._on_restore_defaults)
        prof_btn_row.addWidget(self.btn_restore)
        prof_btn_row.addStretch()
        prof_layout.addLayout(prof_btn_row)
        layout.addWidget(prof_grp)

        detail_grp = QGroupBox("选中配置详情")
        detail_layout = QVBoxLayout(detail_grp)
        self.lbl_profile_detail = QLabel("—")
        self.lbl_profile_detail.setWordWrap(True)
        self.lbl_profile_detail.setStyleSheet("color:#CCC; font-size:11px;")
        detail_layout.addWidget(self.lbl_profile_detail)

        grid = QFormLayout()
        labels = ["fx", "fy", "cx", "cy"]
        self._intrinsic_spins: Dict[str, QDoubleSpinBox] = {}
        for name in labels:
            sp = QDoubleSpinBox()
            sp.setRange(0, 20000)
            sp.setDecimals(2)
            sp.setReadOnly(True)
            self._intrinsic_spins[name] = sp
            grid.addRow(name + ":", sp)
        detail_layout.addLayout(grid)

        dist_row = QHBoxLayout()
        dist_labels = ["k1:", "k2:", "p1:", "p2:", "k3:"]
        self._dist_spins: List[QDoubleSpinBox] = []
        for i in range(5):
            dist_row.addWidget(QLabel(dist_labels[i]))
            sp = QDoubleSpinBox()
            sp.setRange(-10, 10)
            sp.setDecimals(6)
            sp.setReadOnly(True)
            self._dist_spins.append(sp)
            dist_row.addWidget(sp)
        detail_layout.addLayout(dist_row)
        layout.addWidget(detail_grp)

        note = QLabel(
            "在「镜头标定向导」中命名并保存配置；可选绑定到当前摄像头。\n"
            "切换摄像头时，自动模式会按绑定加载对应配置并提示来源。"
        )
        note.setWordWrap(True)
        note.setStyleSheet("color:#888; font-size:11px;")
        layout.addWidget(note)
        return w

    def _find_aruco_tab(self):
        w = self.parent()
        while w is not None:
            if hasattr(w, "release_camera_exclusive"):
                return w
            w = w.parent()
        return None

    def _release_camera_before_wizard(self):
        import time
        tab = self._find_aruco_tab()
        if tab is not None and hasattr(tab, "release_camera_exclusive"):
            tab.release_camera_exclusive()
        elif tab is not None:
            vs = getattr(tab, "_video_service", None)
            if vs is not None:
                vs.stop_capture()
            time.sleep(0.45)

    def _refresh_resolve_hint(self):
        ud = migrate_undistort_section(self._data.get("undistort"))
        if self.radio_manual.isChecked():
            pid = self.combo_manual_profile.currentData() or DEFAULT_PROFILE_ID
            prof = (ud.get("profiles") or {}).get(pid, {})
            name = prof.get("name") or pid
            self.lbl_resolve_hint.setText(f"手动模式 — 将使用【{name}】")
            return
        pid, prof, hint = resolve_profile(
            ud, _PROJECT_ROOT, self._camera_uid, self._camera_name
        )
        name = prof.get("name") or pid
        has = profile_has_calib(_PROJECT_ROOT, prof)
        calib = "已标定" if has else "无标定"
        self.lbl_resolve_hint.setText(
            f"自动模式 — 当前摄像头将加载: {hint} | 【{name}】{calib}"
        )

    def _selected_profile_id(self) -> Optional[str]:
        row = self.table_profiles.currentRow()
        if row < 0:
            return None
        item = self.table_profiles.item(row, 0)
        return item.data(Qt.UserRole) if item else None

    def _on_bind_profile(self):
        pid = self._selected_profile_id()
        if not pid:
            QMessageBox.information(self, "提示", "请先选中一个配置")
            return
        if pid == DEFAULT_PROFILE_ID:
            QMessageBox.information(self, "提示", "默认配置无需绑定，请使用自定义标定配置")
            return
        if self._camera_uid is None:
            QMessageBox.warning(self, "无法绑定", "请先在主界面扫描并选择摄像头")
            return
        ud = migrate_undistort_section(self._data.get("undistort"))
        prof = (ud.get("profiles") or {}).get(pid)
        if not prof:
            return
        prof["bind_camera_uid"] = str(self._camera_uid)
        prof["bind_camera_name"] = self._camera_name or None
        self._data["undistort"] = ud
        self._load_fields()
        self._refresh_resolve_hint()

    def _on_unbind_profile(self):
        pid = self._selected_profile_id()
        if not pid:
            QMessageBox.information(self, "提示", "请先选中一个配置")
            return
        ud = migrate_undistort_section(self._data.get("undistort"))
        prof = (ud.get("profiles") or {}).get(pid)
        if not prof:
            return
        prof["bind_camera_uid"] = None
        prof["bind_camera_name"] = None
        self._data["undistort"] = ud
        self._load_fields()
        self._refresh_resolve_hint()

    def _open_calib_wizard(self):
        from .camera_calib_wizard import CameraCalibWizard
        self._release_camera_before_wizard()
        wiz = None
        try:
            wiz = CameraCalibWizard(
                camera_index=self._camera_index,
                camera_uid=self._camera_uid,
                camera_name=self._camera_name,
                parent=self,
            )
            wiz.calibration_saved.connect(self._on_wizard_saved)
            wiz.exec_()
        except Exception as e:
            QMessageBox.warning(self, "无法启动", str(e))
        finally:
            if wiz is not None:
                wiz._shutdown_capture()

    def _on_wizard_saved(self):
        with open(self._path, "r", encoding="utf-8") as f:
            self._data = yaml.safe_load(f) or {}
        self._load_fields()
        if self._on_calibration_saved:
            self._on_calibration_saved()

    def _on_restore_defaults(self):
        reply = QMessageBox.question(
            self, "恢复默认",
            "将删除所有自定义标定 NPZ 并重置为出厂默认，是否继续？",
            QMessageBox.Yes | QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return
        self._data["undistort"] = restore_defaults(
            self._data.get("undistort"), _PROJECT_ROOT
        )
        try:
            with open(self._path, "w", encoding="utf-8") as f:
                yaml.safe_dump(self._data, f, allow_unicode=True, sort_keys=False)
        except Exception as e:
            QMessageBox.warning(self, "保存失败", str(e))
            return
        self._load_fields()
        if self._on_calibration_saved:
            self._on_calibration_saved()
        QMessageBox.information(self, "已恢复", "已恢复默认配置。")

    def _on_delete_profile(self):
        row = self.table_profiles.currentRow()
        if row < 0:
            QMessageBox.information(self, "提示", "请先选中要删除的配置")
            return
        pid_item = self.table_profiles.item(row, 0)
        if pid_item is None:
            return
        pid = pid_item.data(Qt.UserRole)
        if pid == DEFAULT_PROFILE_ID:
            QMessageBox.warning(self, "无法删除", "默认配置不可删除")
            return
        name = pid_item.text()
        reply = QMessageBox.question(
            self, "删除配置",
            f"确定删除配置「{name}」及其 NPZ 文件？",
            QMessageBox.Yes | QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return
        try:
            self._data["undistort"] = delete_profile(
                self._data.get("undistort"), _PROJECT_ROOT, pid
            )
            with open(self._path, "w", encoding="utf-8") as f:
                yaml.safe_dump(self._data, f, allow_unicode=True, sort_keys=False)
            self._load_fields()
            if self._on_calibration_saved:
                self._on_calibration_saved()
        except Exception as e:
            QMessageBox.warning(self, "删除失败", str(e))

    def _add_world_row(self):
        r = self.table_world.rowCount()
        self.table_world.insertRow(r)
        self.table_world.setItem(r, 0, QTableWidgetItem("0"))
        self.table_world.setItem(r, 1, QTableWidgetItem("0"))
        self.table_world.setItem(r, 2, QTableWidgetItem("0"))

    def _del_world_row(self):
        r = self.table_world.currentRow()
        if r >= 0:
            self.table_world.removeRow(r)

    def _refresh_profile_table(self, ud: Dict):
        self.table_profiles.setRowCount(0)
        self.combo_manual_profile.clear()
        for pid, prof in list_profiles(ud):
            name = prof.get("name") or pid
            bind = prof.get("bind_camera_name") or prof.get("bind_camera_uid") or "—"
            rms = prof.get("rms")
            rms_txt = f"{rms:.4f}" if isinstance(rms, (int, float)) else "—"
            npz = prof.get("npz_path") or "—"
            has = profile_has_calib(_PROJECT_ROOT, prof)
            npz_txt = "有" if has else "无"

            r = self.table_profiles.rowCount()
            self.table_profiles.insertRow(r)
            name_item = QTableWidgetItem(name)
            name_item.setData(Qt.UserRole, pid)
            self.table_profiles.setItem(r, 0, name_item)
            self.table_profiles.setItem(r, 1, QTableWidgetItem(str(bind)))
            self.table_profiles.setItem(r, 2, QTableWidgetItem(rms_txt))
            self.table_profiles.setItem(r, 3, QTableWidgetItem(npz_txt))

            self.combo_manual_profile.addItem(name, pid)

    def _on_profile_selected(self):
        row = self.table_profiles.currentRow()
        if row < 0:
            return
        item = self.table_profiles.item(row, 0)
        if item is None:
            return
        pid = item.data(Qt.UserRole)
        ud = migrate_undistort_section(self._data.get("undistort"))
        prof = (ud.get("profiles") or {}).get(pid, {})
        self._show_profile_detail(pid, prof)

    def _show_profile_detail(self, pid: str, prof: Dict):
        name = prof.get("name") or pid
        bind = prof.get("bind_camera_name") or prof.get("bind_camera_uid")
        bind_txt = f"绑定: {bind}" if bind else "未绑定"
        has = profile_has_calib(_PROJECT_ROOT, prof)
        self.lbl_profile_detail.setText(
            f"ID: {pid} | {name} | {bind_txt} | "
            f"{'已标定' if has else '无有效标定'}"
        )
        mat = prof.get("camera_matrix") or [[800, 0, 320], [0, 800, 240], [0, 0, 1]]
        dist = prof.get("dist_coeffs") or [0, 0, 0, 0, 0]
        self._intrinsic_spins["fx"].setValue(float(mat[0][0]))
        self._intrinsic_spins["fy"].setValue(float(mat[1][1]))
        self._intrinsic_spins["cx"].setValue(float(mat[0][2]))
        self._intrinsic_spins["cy"].setValue(float(mat[1][2]))
        dist_list = list(dist) if hasattr(dist, "__iter__") else [0, 0, 0, 0, 0]
        for i, sp in enumerate(self._dist_spins):
            sp.setValue(float(dist_list[i]) if i < len(dist_list) else 0.0)

    def _load_fields(self):
        d = self._data
        aruco = d.get("aruco", {}) or {}
        idx = self.combo_dict.findData(aruco.get("dict_type", "DICT_4X4_50"))
        if idx >= 0:
            self.combo_dict.setCurrentIndex(idx)
        self.spin_marker_m.setValue(float(aruco.get("marker_size", 0.05)))
        self.spin_vehicle.setValue(int(d.get("vehicle_id", 0)))
        self.spin_min_markers.setValue(int(d.get("min_marker_count", 4)))

        wc = d.get("world_coordinates", {}) or {}
        self.table_world.setRowCount(0)
        for mid in sorted(wc.keys(), key=lambda x: int(x)):
            coords = wc[mid]
            r = self.table_world.rowCount()
            self.table_world.insertRow(r)
            self.table_world.setItem(r, 0, QTableWidgetItem(str(int(mid))))
            self.table_world.setItem(r, 1, QTableWidgetItem(str(float(coords[0]))))
            self.table_world.setItem(r, 2, QTableWidgetItem(str(float(coords[1]))))

        ud = migrate_undistort_section(d.get("undistort"))
        self._data["undistort"] = ud
        self.chk_undistort.setChecked(bool(ud.get("enabled", False)))
        use_mode = ud.get("use_mode", "auto")
        self.radio_auto.setChecked(use_mode != "manual")
        self.radio_manual.setChecked(use_mode == "manual")
        self._refresh_profile_table(ud)
        manual_pid = ud.get("manual_profile_id") or DEFAULT_PROFILE_ID
        midx = self.combo_manual_profile.findData(manual_pid)
        if midx >= 0:
            self.combo_manual_profile.setCurrentIndex(midx)
        if self.table_profiles.rowCount() > 0:
            self.table_profiles.selectRow(0)
            self._on_profile_selected()
        self._refresh_resolve_hint()

    def _collect_data(self) -> Dict:
        out = copy.deepcopy(self._data)
        out.setdefault("aruco", {})
        out["aruco"]["dict_type"] = self.combo_dict.currentData()
        out["aruco"]["marker_size"] = float(self.spin_marker_m.value())
        out["vehicle_id"] = int(self.spin_vehicle.value())
        out["min_marker_count"] = int(self.spin_min_markers.value())

        wc = {}
        for r in range(self.table_world.rowCount()):
            try:
                mid = int(self.table_world.item(r, 0).text())
                x = float(self.table_world.item(r, 1).text())
                y = float(self.table_world.item(r, 2).text())
                wc[mid] = [x, y]
            except Exception:
                continue
        out["world_coordinates"] = wc

        ud = migrate_undistort_section(out.get("undistort"))
        ud["enabled"] = self.chk_undistort.isChecked()
        ud["use_mode"] = "manual" if self.radio_manual.isChecked() else "auto"
        ud["manual_profile_id"] = (
            self.combo_manual_profile.currentData() or DEFAULT_PROFILE_ID
        )
        out["undistort"] = ud
        return out

    def _on_save(self):
        try:
            data = self._collect_data()
            with open(self._path, "w", encoding="utf-8") as f:
                yaml.safe_dump(data, f, allow_unicode=True, sort_keys=False)
            self._data = data
            self.accept()
        except Exception as e:
            QMessageBox.warning(self, "保存失败", str(e))

    def get_data(self) -> Dict:
        return copy.deepcopy(self._data)
