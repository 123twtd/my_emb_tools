"""ArUco 定位 Tab - 标记检测、坐标标定、UDP 位姿广播"""

from __future__ import annotations

import logging
import math
import os
import socket
import sys
import time
from typing import Optional, Tuple

import yaml
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QImage, QPixmap
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QGroupBox,
    QLabel, QPushButton, QSpinBox, QDoubleSpinBox, QLineEdit,
    QCheckBox, QMessageBox, QSplitter, QComboBox, QProgressBar,
)

from .base_tab import SerialTab
from .camera_scan_worker import CameraScanWorker

logger = logging.getLogger(__name__)

_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)
_ARUCO_CONFIG = os.path.join(_PROJECT_ROOT, "config", "aruco_config.yaml")

CV2_AVAILABLE = False
_ARUCO_AVAILABLE = False
_ARUCO_IMPORT_ERROR = ""

try:
    import cv2
    import numpy as np
    CV2_AVAILABLE = True
except ImportError as e:
    cv2 = None  # type: ignore
    np = None  # type: ignore
    _ARUCO_IMPORT_ERROR = f"opencv-python 未安装: {e}"

if CV2_AVAILABLE:
    try:
        from aruco_loc.aruco_core.config_loader import (
            load_config_from_yaml, set_config_instance,
        )
        from aruco_loc.aruco_core import ArUcoDetector, CoordinateTransformer
        from aruco_loc.pos_udp import build_payload, parse_targets, send_to_targets
        from aruco_loc.undistort import LensUndistort
        from aruco_loc.undistort_profiles import (
            migrate_undistort_section,
            resolve_profile,
            load_profile_into_undistort_dict,
        )
        _ARUCO_AVAILABLE = True
    except Exception as e:
        _ARUCO_IMPORT_ERROR = str(e)
        logger.warning("ArUco modules unavailable: %s", e)


class ArucoTab(SerialTab):
    """ArUco 视觉定位：摄像头采集 → 标定 → 车辆位姿 → UDP 广播"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._detector = None
        self._transformer = None
        self._undistort = LensUndistort() if _ARUCO_AVAILABLE else None
        self._video_service = None
        self._scan_worker = None
        self._known_devices: list = []
        self._udp_sock: Optional[socket.socket] = None
        self._udp_seq = 0
        self._vehicle_id = 0
        self._config_data: dict = {}

        self._last_vehicle_world: Optional[Tuple[float, float]] = None
        self._last_vehicle_yaw: Optional[float] = None
        self._calibrated = False
        self._fps_ema = 0.0
        self._fps_last_t = 0.0
        self._frame_size: Tuple[int, int] = (0, 0)
        self._undistort_profile_id: str = "default"
        self._undistort_hint: str = ""

        self._udp_timer = QTimer(self)
        self._udp_timer.timeout.connect(self._emit_udp_pose)

        if _ARUCO_AVAILABLE:
            self._reload_aruco_config()

        self._build_ui()
        if _ARUCO_AVAILABLE and self._video_service is None:
            QTimer.singleShot(800, self._try_initial_scan)

    # ─────────────────── 配置 ───────────────────

    def release_camera_exclusive(self):
        """释放摄像头供标定向导独占使用（Windows 需短暂等待）"""
        if self._scan_worker is not None and self._scan_worker.isRunning():
            self._scan_worker.wait(3000)
        if self._video_service is not None:
            self._video_service.stop_capture()
        time.sleep(0.45)

    def _reload_aruco_config(self):
        try:
            with open(_ARUCO_CONFIG, "r", encoding="utf-8") as f:
                self._config_data = yaml.safe_load(f) or {}
            cfg = load_config_from_yaml(_ARUCO_CONFIG)
            set_config_instance(cfg)
            self._detector = ArUcoDetector()
            self._transformer = CoordinateTransformer()
            self._vehicle_id = int(cfg.VEHICLE_ID)
            self._apply_undistort_for_current_camera()
        except Exception as e:
            logger.error("ArUco config load failed: %s", e)

    def _current_camera_info(self) -> Tuple[Optional[str], Optional[str], int]:
        dev = self.cb_camera.currentData() if hasattr(self, "cb_camera") else None
        if isinstance(dev, dict):
            uid = str(dev.get("index", dev.get("uid", "")))
            name = dev.get("name", "")
            idx = int(dev.get("index", 0))
            return uid, name, idx
        return None, None, 0

    def _apply_undistort_for_current_camera(self):
        if self._undistort is None:
            return
        ud = migrate_undistort_section(self._config_data.get("undistort"))
        self._config_data["undistort"] = ud
        uid, name, _ = self._current_camera_info()
        pid, prof, hint = resolve_profile(ud, _PROJECT_ROOT, uid, name)
        self._undistort_profile_id = pid
        self._undistort_hint = hint
        flat = load_profile_into_undistort_dict(
            prof, _PROJECT_ROOT, bool(ud.get("enabled", False))
        )
        self._undistort.load_from_dict(flat, _PROJECT_ROOT)

    def set_camera_broadcaster(self, broadcaster, api_host: str = "127.0.0.1",
                               api_port: int = 8000, get_api_bases=None):
        if self._video_service is not None:
            try:
                self._video_service.frame_ready.disconnect(self._on_frame)
                self._video_service.status_changed.disconnect(self._on_capture_status)
            except Exception:
                pass
        self._video_service = broadcaster
        if broadcaster is not None:
            broadcaster.frame_ready.connect(self._on_frame)
            broadcaster.status_changed.connect(self._on_capture_status)

    # ─────────────────── UI ───────────────────

    def _build_ui(self):
        root = QHBoxLayout(self)
        root.setContentsMargins(6, 6, 6, 6)
        splitter = QSplitter(Qt.Horizontal)
        root.addWidget(splitter)

        preview_box = QGroupBox("摄像头预览")
        pv_layout = QVBoxLayout(preview_box)
        self.lbl_preview = QLabel("未开始采集")
        self.lbl_preview.setAlignment(Qt.AlignCenter)
        self.lbl_preview.setMinimumSize(640, 480)
        self.lbl_preview.setStyleSheet("background:#1a1a1a; color:#888;")
        pv_layout.addWidget(self.lbl_preview, stretch=1)
        self.lbl_stream_info = QLabel("")
        self.lbl_stream_info.setAlignment(Qt.AlignCenter)
        self.lbl_stream_info.setStyleSheet("color:#AAA; font-size:12px;")
        pv_layout.addWidget(self.lbl_stream_info)
        splitter.addWidget(preview_box)

        ctrl = QWidget()
        ctrl_layout = QVBoxLayout(ctrl)
        ctrl_layout.setContentsMargins(0, 0, 0, 0)

        if not _ARUCO_AVAILABLE:
            hint = "请安装依赖: pip install opencv-python PyYAML"
            if _ARUCO_IMPORT_ERROR:
                hint = f"{_ARUCO_IMPORT_ERROR}\n\n{hint}"
            err = QLabel(f"ArUco 定位模块未就绪：\n{hint}")
            err.setWordWrap(True)
            err.setStyleSheet("color:#CC4444;")
            ctrl_layout.addWidget(err)
            ctrl_layout.addStretch(1)
            splitter.addWidget(ctrl)
            splitter.setStretchFactor(0, 3)
            splitter.setStretchFactor(1, 1)
            return

        # ── 视频源 ──
        cam_grp = QGroupBox("视频源")
        cam_grid = QGridLayout(cam_grp)

        cam_grid.addWidget(QLabel("摄像头:"), 0, 0)
        cam_pick = QHBoxLayout()
        self.cb_camera = QComboBox()
        self.cb_camera.setMinimumWidth(160)
        cam_pick.addWidget(self.cb_camera, stretch=1)
        self.btn_scan = QPushButton("扫描")
        self.btn_scan.setFixedWidth(52)
        self.btn_scan.clicked.connect(self._start_camera_scan)
        cam_pick.addWidget(self.btn_scan)
        cam_pick_w = QWidget()
        cam_pick_w.setLayout(cam_pick)
        cam_grid.addWidget(cam_pick_w, 0, 1)

        self.scan_progress = QProgressBar()
        self.scan_progress.setRange(0, 100)
        self.scan_progress.setValue(0)
        self.scan_progress.setTextVisible(True)
        self.scan_progress.setFormat("就绪")
        self.scan_progress.setFixedHeight(16)
        cam_grid.addWidget(self.scan_progress, 1, 0, 1, 2)

        cam_grid.addWidget(QLabel("分辨率:"), 2, 0)
        self.cb_resolution = QComboBox()
        self.cb_resolution.setToolTip("驱动原生：不强制设置宽高，由驱动决定（推荐）")
        self._populate_resolutions()
        cam_grid.addWidget(self.cb_resolution, 2, 1)

        cam_grid.addWidget(QLabel("目标 FPS:"), 3, 0)
        self.cb_fps = QComboBox()
        for f in ("15", "24", "30", "60"):
            self.cb_fps.addItem(f)
        self.cb_fps.setCurrentText(
            str(self._config_data.get("camera", {}).get("fps_hint", 30))
        )
        cam_grid.addWidget(self.cb_fps, 3, 1)

        flip_row = QHBoxLayout()
        self.chk_flip_h = QCheckBox("水平翻转")
        self.chk_flip_v = QCheckBox("垂直翻转")
        flip_row.addWidget(self.chk_flip_h)
        flip_row.addWidget(self.chk_flip_v)
        cam_grid.addLayout(flip_row, 4, 0, 1, 2)

        ud_row = QHBoxLayout()
        self.chk_undistort = QCheckBox("镜头去畸变")
        self.chk_undistort.setToolTip("在「ArUco 配置 → 镜头去畸变」中管理标定与绑定")
        self.chk_undistort.toggled.connect(self._on_undistort_toggled)
        ud_row.addWidget(self.chk_undistort)
        self.lbl_undistort = QLabel("")
        self.lbl_undistort.setStyleSheet("color:#888; font-size:11px;")
        ud_row.addWidget(self.lbl_undistort, stretch=1)
        cam_grid.addLayout(ud_row, 5, 0, 1, 2)
        ud_cfg = self._config_data.get("undistort", {}) or {}
        self.chk_undistort.setChecked(bool(ud_cfg.get("enabled", False)))
        if self._undistort is not None:
            self._undistort.set_enabled(self.chk_undistort.isChecked())
        self._refresh_undistort_label()

        cap_row = QHBoxLayout()
        self.btn_capture = QPushButton("开始采集")
        self.btn_capture.clicked.connect(self._toggle_capture)
        cap_row.addWidget(self.btn_capture)
        self.btn_settings = QPushButton("ArUco 配置…")
        self.btn_settings.setToolTip("检测、场地、镜头去畸变与标定向导")
        self.btn_settings.clicked.connect(self._open_settings)
        cap_row.addWidget(self.btn_settings)
        cam_grid.addLayout(cap_row, 6, 0, 1, 2)

        self.lbl_capture_status = QLabel("未采集")
        self.lbl_capture_status.setStyleSheet("color:#888;")
        cam_grid.addWidget(self.lbl_capture_status, 7, 0, 1, 2)
        ctrl_layout.addWidget(cam_grp)

        # ── 定位状态 ──
        pose_grp = QGroupBox("定位状态")
        pose_layout = QVBoxLayout(pose_grp)
        self.lbl_calib = QLabel("标定: 未标定")
        self.lbl_markers = QLabel("标记: —")
        self.lbl_pose = QLabel("位姿: —")
        self.lbl_video_stats = QLabel("视频: —")
        for lb in (self.lbl_calib, self.lbl_markers, self.lbl_pose, self.lbl_video_stats):
            lb.setWordWrap(True)
            pose_layout.addWidget(lb)
        ctrl_layout.addWidget(pose_grp)

        # ── UDP ──
        udp_grp = QGroupBox("UDP 位姿广播")
        udp_grid = QGridLayout(udp_grp)
        self.chk_udp = QCheckBox("启用 UDP 发送")
        self.chk_udp.toggled.connect(self._on_udp_toggled)
        udp_grid.addWidget(self.chk_udp, 0, 0, 1, 2)

        udp_grid.addWidget(QLabel("目标1:"), 1, 0)
        self.edit_host1 = QLineEdit("192.168.0.181")
        udp_grid.addWidget(self.edit_host1, 1, 1)
        udp_grid.addWidget(QLabel("端口:"), 2, 0)
        self.spin_port1 = QSpinBox()
        self.spin_port1.setRange(1, 65535)
        self.spin_port1.setValue(9005)
        udp_grid.addWidget(self.spin_port1, 2, 1)

        udp_grid.addWidget(QLabel("目标2:"), 3, 0)
        self.edit_host2 = QLineEdit("")
        udp_grid.addWidget(self.edit_host2, 3, 1)
        udp_grid.addWidget(QLabel("端口:"), 4, 0)
        self.spin_port2 = QSpinBox()
        self.spin_port2.setRange(0, 65535)
        self.spin_port2.setValue(9010)
        udp_grid.addWidget(self.spin_port2, 4, 1)

        udp_grid.addWidget(QLabel("频率 (Hz):"), 5, 0)
        self.spin_udp_hz = QDoubleSpinBox()
        self.spin_udp_hz.setRange(1.0, 60.0)
        self.spin_udp_hz.setValue(20.0)
        udp_grid.addWidget(self.spin_udp_hz, 5, 1)

        self.chk_send_yaw = QCheckBox("发送航向角 (yaw)")
        self.chk_send_yaw.setChecked(True)
        udp_grid.addWidget(self.chk_send_yaw, 6, 0, 1, 2)
        ctrl_layout.addWidget(udp_grp)

        ctrl_layout.addStretch(1)
        splitter.addWidget(ctrl)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 1)

    def _populate_resolutions(self):
        self.cb_resolution.clear()
        self.cb_resolution.addItem("驱动原生 (推荐)", None)
        for label, size in (
            ("1920×1080", (1920, 1080)),
            ("1280×720", (1280, 720)),
            ("640×480", (640, 480)),
        ):
            self.cb_resolution.addItem(label, size)

    def _refresh_undistort_label(self):
        if self._undistort is None:
            return
        ud = migrate_undistort_section(self._config_data.get("undistort"))
        profiles = ud.get("profiles") or {}
        prof = profiles.get(self._undistort_profile_id, {})
        name = prof.get("name") or self._undistort_profile_id
        calib = "已标定" if self._undistort.calib_loaded else "无标定"
        on_off = "开" if self._undistort.enabled else "关"
        self.lbl_undistort.setText(
            f"{self._undistort_hint} | 【{name}】{calib} | {on_off}"
        )

    def _on_undistort_toggled(self, checked: bool):
        if self._undistort is not None:
            self._undistort.set_enabled(checked)
            ud = migrate_undistort_section(self._config_data.get("undistort"))
            ud["enabled"] = checked
            self._config_data["undistort"] = ud
            self._refresh_undistort_label()

    def _on_config_changed(self):
        self._reload_aruco_config()
        ud_cfg = self._config_data.get("undistort", {}) or {}
        self.chk_undistort.blockSignals(True)
        self.chk_undistort.setChecked(bool(ud_cfg.get("enabled", False)))
        self.chk_undistort.blockSignals(False)
        self._apply_undistort_for_current_camera()
        self._refresh_undistort_label()

    def _open_settings(self):
        from .aruco_settings_dialog import ArucoSettingsDialog
        self.release_camera_exclusive()
        self._sync_capture_ui(capturing=False)
        self.lbl_capture_status.setText("未采集")
        self.lbl_capture_status.setStyleSheet("color:#888;")
        uid, name, cam_idx = self._current_camera_info()
        dlg = ArucoSettingsDialog(
            _ARUCO_CONFIG, self,
            camera_index=cam_idx,
            camera_uid=uid,
            camera_name=name,
            on_calibration_saved=self._on_config_changed,
        )
        if dlg.exec_() == ArucoSettingsDialog.Accepted:
            self._config_data = dlg.get_data()
            self._on_config_changed()

    # ─────────────────── 摄像头扫描 ───────────────────

    def _try_initial_scan(self):
        if self._video_service is not None and self.cb_camera.count() == 0:
            self._start_camera_scan()

    def _start_camera_scan(self):
        if not _ARUCO_AVAILABLE:
            return
        if self._video_service is None:
            QMessageBox.warning(self, "提示", "视频服务未就绪，请稍候再试")
            return
        if self._scan_worker is not None and self._scan_worker.isRunning():
            return
        self.btn_scan.setEnabled(False)
        self.scan_progress.setValue(0)
        self.scan_progress.setFormat("扫描中…")
        self._scan_worker = CameraScanWorker(self._video_service, self)
        self._scan_worker.scan_progress.connect(self._on_scan_progress)
        self._scan_worker.scan_finished.connect(self._on_scan_finished)
        self._scan_worker.scan_failed.connect(self._on_scan_failed)
        self._scan_worker.finished.connect(lambda: self.btn_scan.setEnabled(True))
        self._scan_worker.start()

    def _on_scan_progress(self, current: int, total: int, message: str):
        pct = int(current / total * 100) if total else 0
        self.scan_progress.setValue(pct)
        self.scan_progress.setFormat(f"{message} ({current}/{total})")

    def _on_scan_finished(self, devices: list):
        if self._video_service is not None:
            try:
                self._video_service.restore_after_scan()
            except Exception:
                pass
        self._known_devices = devices
        self.cb_camera.clear()
        if not devices:
            self.cb_camera.addItem("未检测到摄像头", None)
        else:
            for dev in devices:
                self.cb_camera.addItem(f"#{dev['index']}  {dev['name']}", dev)
            try:
                self.cb_camera.currentIndexChanged.disconnect(self._on_camera_changed)
            except Exception:
                pass
            self.cb_camera.currentIndexChanged.connect(self._on_camera_changed)
            self._on_camera_changed()
        self.scan_progress.setValue(100)
        self.scan_progress.setFormat(f"完成 — {len(devices)} 个")

    def _on_camera_changed(self, _index: int = -1):
        self._apply_undistort_for_current_camera()
        self._refresh_undistort_label()

    def _on_scan_failed(self, msg: str):
        if self._video_service is not None:
            try:
                self._video_service.restore_after_scan()
            except Exception:
                pass
        self.scan_progress.setFormat("扫描失败")

    # ─────────────────── 采集 ───────────────────

    def _get_resolution(self) -> Tuple[Optional[int], Optional[int]]:
        res = self.cb_resolution.currentData()
        if res:
            return int(res[0]), int(res[1])
        return None, None

    def _apply_capture_options(self):
        if self._video_service is None:
            return
        try:
            fps = int(self.cb_fps.currentText())
        except ValueError:
            fps = 30
        self._video_service.configure(
            fps=fps,
            flip_h=self.chk_flip_h.isChecked(),
            flip_v=self.chk_flip_v.isChecked(),
        )

    def _toggle_capture(self):
        if self._video_service is not None and self._video_service.is_capturing:
            self._stop_capture()
        else:
            self._start_capture()

    def _start_capture(self):
        if not _ARUCO_AVAILABLE or self._video_service is None:
            QMessageBox.warning(self, "提示", "视频服务未就绪")
            return
        dev = self.cb_camera.currentData()
        if not isinstance(dev, dict):
            QMessageBox.warning(self, "提示", "请先扫描并选择摄像头")
            return

        self._apply_capture_options()
        w, h = self._get_resolution()
        ok = self._video_service.start_local(
            device_index=dev["index"], width=w, height=h,
        )
        if not ok:
            QMessageBox.warning(
                self, "错误",
                self._video_service.get_status().get("last_error", "无法打开摄像头")
            )
            return

        self._fps_ema = 0.0
        self._fps_last_t = time.perf_counter()
        self._sync_capture_ui(capturing=True)
        st = self._video_service.get_status()
        self.lbl_capture_status.setText(
            f"采集中 — 目标 {self.cb_fps.currentText()} FPS"
        )
        self.lbl_capture_status.setStyleSheet("color:#44CC44;")

    def _stop_capture(self):
        if self._video_service is not None:
            self._video_service.stop_capture()
        self._sync_capture_ui(capturing=False)
        self.lbl_preview.setText("已停止")
        self.lbl_preview.setPixmap(QPixmap())
        self.lbl_stream_info.setText("")
        self.lbl_capture_status.setText("未采集")
        self.lbl_capture_status.setStyleSheet("color:#888;")
        self.lbl_video_stats.setText("视频: —")

    def _sync_capture_ui(self, capturing: bool):
        self.btn_capture.setText("停止采集" if capturing else "开始采集")
        enabled = not capturing
        self.cb_camera.setEnabled(enabled)
        self.btn_scan.setEnabled(enabled)
        self.cb_resolution.setEnabled(enabled)
        self.cb_fps.setEnabled(enabled)

    def _on_capture_status(self, status: str):
        if "错误" in status or "失败" in status:
            self.lbl_capture_status.setText(status)
            self.lbl_capture_status.setStyleSheet("color:#CC4444;")
            self._sync_capture_ui(capturing=False)

    # ─────────────────── 帧处理 ───────────────────

    def _on_frame(self, frame: np.ndarray):
        if self._detector is None or self._transformer is None:
            return

        now = time.perf_counter()
        if self._fps_last_t > 0:
            dt = now - self._fps_last_t
            if dt > 0:
                inst = 1.0 / dt
                self._fps_ema = inst if self._fps_ema <= 0 else (0.9 * self._fps_ema + 0.1 * inst)
        self._fps_last_t = now

        if self._undistort is not None:
            frame = self._undistort.apply(frame)

        h, w = frame.shape[:2]
        self._frame_size = (w, h)
        display = self._process_frame(frame)
        self._show_frame(display)

        svc_fps = 0.0
        if self._video_service is not None:
            svc_fps = float(self._video_service.get_status().get("measured_fps", 0))
        fps_show = svc_fps if svc_fps > 0 else self._fps_ema
        ud = "开" if (self._undistort and self._undistort.enabled) else "关"
        self.lbl_stream_info.setText(
            f"{w}×{h}  @  {fps_show:.1f} FPS  |  去畸变: {ud}"
        )
        self.lbl_video_stats.setText(
            f"视频: {w}×{h}，实测 {fps_show:.1f} FPS，去畸变 {ud}"
        )

    def _process_frame(self, image: np.ndarray) -> np.ndarray:
        corners, ids, vis = self._detector.detect_markers(image)
        required = self._detector.get_required_markers(corners, ids)

        detected_n = len(ids) if ids is not None else 0
        self.lbl_markers.setText(f"标记: 检测到 {detected_n} 个")

        if required is not None:
            ok = self._transformer.calibrate(required)
            self._calibrated = ok
            self.lbl_calib.setText("标定: 成功" if ok else "标定: 失败")
            if not ok:
                self._transformer.reset_calibration()
        else:
            self._calibrated = False
            self._transformer.reset_calibration()
            self.lbl_calib.setText("标定: 未标定 (标记不足)")

        self._last_vehicle_world = None
        self._last_vehicle_yaw = None

        if ids is not None and corners is not None:
            flat = ids.flatten()
            matches = np.where(flat == self._vehicle_id)[0]
            if matches.size > 0 and self._calibrated:
                i = int(matches[0])
                pts = np.array(corners[i][0], dtype=np.float32)
                cx, cy = float(np.mean(pts[:, 0])), float(np.mean(pts[:, 1]))
                world = self._transformer.pixel_to_world(cx, cy, z=0.0)
                if world is not None:
                    c1, c2 = pts[1], pts[2]
                    p1 = self._transformer.pixel_to_world(float(c1[0]), float(c1[1]), z=0.0)
                    p2 = self._transformer.pixel_to_world(float(c2[0]), float(c2[1]), z=0.0)
                    if p1 and p2:
                        yaw = math.degrees(math.atan2(p2[1] - p1[1], p2[0] - p1[0]))
                        self._last_vehicle_world = world
                        self._last_vehicle_yaw = yaw
                        self.lbl_pose.setText(
                            f"位姿: X={world[0]:.1f}mm  Y={world[1]:.1f}mm  "
                            f"Yaw={yaw:.1f}°"
                        )
                        cv2.circle(vis, (int(cx), int(cy)), 6, (0, 255, 0), -1)
        if self._last_vehicle_world is None:
            self.lbl_pose.setText("位姿: 未检测到车辆标记")

        return vis

    def _show_frame(self, frame: np.ndarray):
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        h, w, ch = rgb.shape
        qt_img = QImage(rgb.data, w, h, ch * w, QImage.Format_RGB888).copy()
        scaled = QPixmap.fromImage(qt_img).scaled(
            self.lbl_preview.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation
        )
        self.lbl_preview.setPixmap(scaled)

    # ─────────────────── UDP ───────────────────

    def _ensure_udp_socket(self) -> socket.socket:
        if self._udp_sock is None:
            self._udp_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        return self._udp_sock

    def _on_udp_toggled(self, enabled: bool):
        if enabled:
            hz = max(float(self.spin_udp_hz.value()), 1.0)
            self._udp_timer.start(int(1000 / hz))
        else:
            self._udp_timer.stop()

    def _emit_udp_pose(self):
        if not self.chk_udp.isChecked():
            return
        targets = parse_targets(
            self.edit_host1.text(), int(self.spin_port1.value()),
            self.edit_host2.text(), int(self.spin_port2.value()),
        )
        if not targets or not self._calibrated:
            return
        holdover = self._last_vehicle_world is None
        if self._last_vehicle_world:
            wx, wy = self._last_vehicle_world
            yaw = float(self._last_vehicle_yaw or 0.0)
        else:
            wx, wy, yaw = 0.0, 0.0, 0.0
        if not self.chk_send_yaw.isChecked():
            yaw = 0.0
        pos = (wx / 1000.0, wy / 1000.0, 0.0)
        euler = (0.0, 0.0, yaw)
        self._udp_seq += 1
        payload = build_payload(self._udp_seq, pos, euler, holdover=holdover)
        try:
            send_to_targets(self._ensure_udp_socket(), payload, targets)
        except OSError as e:
            logger.warning("UDP send error: %s", e)

    # ─────────────────── 生命周期 ───────────────────

    def cleanup(self):
        self._udp_timer.stop()
        self._stop_capture()
        if self._scan_worker is not None and self._scan_worker.isRunning():
            self._scan_worker.wait(2000)
        if self._udp_sock is not None:
            try:
                self._udp_sock.close()
            except Exception:
                pass
            self._udp_sock = None

    def reset_state(self):
        self._stop_capture()
        self.chk_udp.setChecked(False)
