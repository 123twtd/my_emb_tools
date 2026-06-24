"""镜头标定向导 - 棋盘格采集 → calibrateCamera → 保存 NPZ 配置集"""

from __future__ import annotations

import os
import threading
import time
from typing import List, Optional, Tuple

import yaml
from PyQt5.QtCore import Qt, QThread, QTimer, pyqtSignal
from PyQt5.QtGui import QImage, QPixmap
from PyQt5.QtWidgets import (
    QWizard, QWizardPage, QVBoxLayout, QHBoxLayout, QLabel, QSpinBox,
    QDoubleSpinBox, QPushButton, QMessageBox, QProgressBar, QGridLayout,
    QLineEdit, QCheckBox, QFormLayout, QApplication,
)

from app_paths import app_root, config_path

_PROJECT_ROOT = app_root()
_ARUCO_CONFIG = config_path("aruco_config.yaml")

try:
    import cv2
    import numpy as np
    from aruco_loc.camera_calib import (
        DEFAULT_BOARD_COLS, DEFAULT_BOARD_ROWS, DEFAULT_SQUARE_MM,
        MIN_VALID_FRAMES, TARGET_CAPTURE_FRAMES,
        build_object_points, find_chessboard, calibrate_from_corners,
    )
    from aruco_loc.undistort_profiles import (
        migrate_undistort_section, save_profile_calibration, restore_defaults,
        _slug,
    )
    try:
        cv2.setLogLevel(3)
        cv2.utils.logging.setLogLevel(cv2.utils.logging.LOG_LEVEL_SILENT)
    except Exception:
        pass
    _CALIB_AVAILABLE = True
except Exception:
    _CALIB_AVAILABLE = False


class _CalibPreviewThread(QThread):
    """实时预览 + 轻量棋盘格检测（不阻塞 UI）"""

    frame_ready = pyqtSignal(object, bool)
    preview_failed = pyqtSignal(str)

    def __init__(self, camera_index: int, board_cols: int, board_rows: int,
                 parent=None):
        super().__init__(parent)
        self._index = camera_index
        self._board = (int(board_cols), int(board_rows))
        self._running = False
        self._lock = threading.Lock()
        self._latest_bgr: Optional[np.ndarray] = None

    def set_board(self, cols: int, rows: int):
        self._board = (int(cols), int(rows))

    def get_latest_frame(self) -> Optional[np.ndarray]:
        with self._lock:
            return None if self._latest_bgr is None else self._latest_bgr.copy()

    def stop(self):
        self._running = False

    def _open_camera(self):
        time.sleep(0.35)
        cap = cv2.VideoCapture(self._index)
        if not cap.isOpened():
            return None
        try:
            cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        except Exception:
            pass
        ret, frame = cap.read()
        if not ret or frame is None:
            cap.release()
            return None
        return cap

    def run(self):
        cap = self._open_camera()
        if cap is None:
            self.preview_failed.emit(
                f"无法打开摄像头 #{self._index}。\n"
                "请先在主界面停止采集，或关闭占用摄像头的其他程序后重试。"
            )
            return
        self._running = True
        while self._running:
            ret, frame = cap.read()
            if not ret or frame is None:
                time.sleep(0.02)
                continue
            with self._lock:
                self._latest_bgr = frame
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            ok, corners = find_chessboard(gray, self._board, fast=True)
            vis = frame.copy()
            if ok and corners is not None:
                cv2.drawChessboardCorners(vis, self._board, corners, ok)
            self.frame_ready.emit(vis, bool(ok))
            time.sleep(0.05)
        cap.release()


def _show_bgr_label(label: QLabel, frame):
    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    h, w, ch = rgb.shape
    img = QImage(rgb.data, w, h, ch * w, QImage.Format_RGB888).copy()
    label.setPixmap(QPixmap.fromImage(img).scaled(
        label.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation
    ))


class IntroPage(QWizardPage):
    def __init__(self):
        super().__init__()
        self.setTitle("镜头去畸变标定")
        self.setSubTitle("使用棋盘格自动计算相机内参与畸变系数，保存为命名配置。")
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(
            "流程：填写标定板参数 → 手动拍照采集（实时预览识别角点）→ "
            "点「完成并标定」→ 命名并保存。\n\n"
            "「恢复默认」将清除所有自定义标定配置及 NPZ 文件。"
        ))


class BoardPage(QWizardPage):
    def __init__(self):
        super().__init__()
        self.setTitle("标定板参数")
        self.setSubTitle("与实物棋盘格一致：内角点列数 × 行数，方格边长 (mm)。")
        grid = QGridLayout(self)
        grid.addWidget(QLabel("内角点列数:"), 0, 0)
        self.spin_cols = QSpinBox()
        self.spin_cols.setRange(3, 20)
        self.spin_cols.setValue(DEFAULT_BOARD_COLS)
        grid.addWidget(self.spin_cols, 0, 1)
        grid.addWidget(QLabel("内角点行数:"), 1, 0)
        self.spin_rows = QSpinBox()
        self.spin_rows.setRange(3, 20)
        self.spin_rows.setValue(DEFAULT_BOARD_ROWS)
        grid.addWidget(self.spin_rows, 1, 1)
        grid.addWidget(QLabel("方格边长 (mm):"), 2, 0)
        self.spin_square = QDoubleSpinBox()
        self.spin_square.setRange(1.0, 500.0)
        self.spin_square.setDecimals(2)
        self.spin_square.setValue(DEFAULT_SQUARE_MM)
        grid.addWidget(self.spin_square, 2, 1)
        hint = QLabel(
            "注意：内角点 = 格子交点数量（比格子数少 1）。\n"
            "填写完成后点「下一步」进入手动拍照采集。"
        )
        hint.setStyleSheet("color:#888; font-size:11px;")
        grid.addWidget(hint, 3, 0, 1, 2)

    def isComplete(self) -> bool:
        return True

    def validatePage(self) -> bool:
        wiz: CameraCalibWizard = self.wizard()  # type: ignore
        wiz.board_cols = int(self.spin_cols.value())
        wiz.board_rows = int(self.spin_rows.value())
        wiz.square_mm = float(self.spin_square.value())
        return True


class CapturePage(QWizardPage):
    def __init__(self, camera_index: int):
        super().__init__()
        self._camera_index = camera_index
        self._preview_thread: Optional[_CalibPreviewThread] = None
        self._objpoints: List = []
        self._imgpoints: List = []
        self._image_size: Optional[Tuple[int, int]] = None
        self._corners_visible = False
        self._rms = 0.0
        self._mtx = None
        self._dist = None
        self._objp = None

        self.setTitle("手动采集标定图")
        self.setSubTitle("预览中识别到棋盘格后点「拍照收录」，多角度拍满后点「完成并标定」。")

        layout = QVBoxLayout(self)
        self.lbl_board_params = QLabel("")
        self.lbl_board_params.setStyleSheet("color:#AAA; font-size:12px;")
        layout.addWidget(self.lbl_board_params)

        self.lbl_detect = QLabel("检测: 等待画面…")
        self.lbl_detect.setStyleSheet("color:#888; font-size:13px;")
        layout.addWidget(self.lbl_detect)

        self.lbl_hint = QLabel(
            "将标定板放入视野，绿色角点覆盖正确时点「拍照收录」。"
            f"至少 {MIN_VALID_FRAMES} 张、建议 {TARGET_CAPTURE_FRAMES} 张不同角度。"
        )
        self.lbl_hint.setWordWrap(True)
        self.lbl_hint.setStyleSheet("color:#CCAA00; font-size:12px;")
        layout.addWidget(self.lbl_hint)

        self.lbl_preview = QLabel("正在打开摄像头…")
        self.lbl_preview.setAlignment(Qt.AlignCenter)
        self.lbl_preview.setMinimumHeight(280)
        self.lbl_preview.setStyleSheet("background:#1a1a1a; color:#666;")
        layout.addWidget(self.lbl_preview)

        self.lbl_count = QLabel(f"已收录: 0 / {TARGET_CAPTURE_FRAMES}（最少 {MIN_VALID_FRAMES}）")
        self.lbl_count.setStyleSheet("font-size:14px;")
        layout.addWidget(self.lbl_count)

        self.progress = QProgressBar()
        self.progress.setRange(0, TARGET_CAPTURE_FRAMES)
        self.progress.setValue(0)
        layout.addWidget(self.progress)

        btn_row = QHBoxLayout()
        self.btn_shot = QPushButton("拍照收录")
        self.btn_shot.setToolTip("当前帧识别到棋盘格时收录一张")
        self.btn_shot.clicked.connect(self._on_shot)
        btn_row.addWidget(self.btn_shot)
        self.btn_undo = QPushButton("删除上一张")
        self.btn_undo.clicked.connect(self._on_undo)
        btn_row.addWidget(self.btn_undo)
        self.btn_calibrate = QPushButton("完成并标定")
        self.btn_calibrate.setToolTip(f"至少收录 {MIN_VALID_FRAMES} 张后批量计算畸变系数")
        self.btn_calibrate.clicked.connect(self._on_calibrate)
        btn_row.addWidget(self.btn_calibrate)
        layout.addLayout(btn_row)

        self.lbl_result = QLabel("")
        self.lbl_result.setWordWrap(True)
        layout.addWidget(self.lbl_result)

    def isComplete(self) -> bool:
        return self._mtx is not None

    def _sync_board_params(self):
        wiz: CameraCalibWizard = self.wizard()  # type: ignore
        if wiz is None:
            return
        board = wiz.page(1)
        if board is not None and hasattr(board, "spin_cols"):
            wiz.board_cols = int(board.spin_cols.value())
            wiz.board_rows = int(board.spin_rows.value())
            wiz.square_mm = float(board.spin_square.value())
        self._objp = build_object_points(
            wiz.board_cols, wiz.board_rows, wiz.square_mm
        )
        if self._preview_thread is not None:
            self._preview_thread.set_board(wiz.board_cols, wiz.board_rows)

    def initializePage(self):
        self._sync_board_params()
        wiz = self.wizard()
        if wiz:
            wiz.setButtonText(QWizard.NextButton, "下一步")
            wiz.button(QWizard.NextButton).setEnabled(self._mtx is not None)
            self.lbl_board_params.setText(
                f"标定板: {wiz.board_cols}×{wiz.board_rows}  方格 {wiz.square_mm} mm"
            )
        self.lbl_preview.setText("正在打开摄像头…")
        self.lbl_preview.setPixmap(QPixmap())
        QTimer.singleShot(450, self._start_preview)

    def cleanupPage(self):
        self.shutdown()

    def shutdown(self):
        self._stop_preview()

    def validatePage(self) -> bool:
        if self._mtx is None:
            QMessageBox.information(
                self, "尚未标定",
                f"请先拍照收录至少 {MIN_VALID_FRAMES} 张有效图，再点「完成并标定」。"
            )
            return False
        return True

    def _on_preview_failed(self, msg: str):
        self.lbl_preview.setPixmap(QPixmap())
        self.lbl_preview.setText(msg)
        self.lbl_preview.setStyleSheet("background:#1a1a1a; color:#CC6666;")

    def _on_frame(self, frame, found: bool):
        self._corners_visible = found
        _show_bgr_label(self.lbl_preview, frame)
        if found:
            self.lbl_detect.setText("检测: ✓ 已识别棋盘格（可拍照）")
            self.lbl_detect.setStyleSheet("color:#44CC44; font-size:13px;")
        else:
            self.lbl_detect.setText("检测: ✗ 未识别到棋盘格")
            self.lbl_detect.setStyleSheet("color:#CC8844; font-size:13px;")

    def _start_preview(self):
        self._stop_preview()
        wiz: CameraCalibWizard = self.wizard()  # type: ignore
        self.lbl_preview.setStyleSheet("background:#1a1a1a; color:#666;")
        self._preview_thread = _CalibPreviewThread(
            self._camera_index, wiz.board_cols, wiz.board_rows, self,
        )
        self._preview_thread.frame_ready.connect(self._on_frame)
        self._preview_thread.preview_failed.connect(self._on_preview_failed)
        self._preview_thread.start()

    def _stop_preview(self):
        thread = self._preview_thread
        self._preview_thread = None
        if thread is None:
            return
        try:
            thread.frame_ready.disconnect(self._on_frame)
        except Exception:
            pass
        try:
            thread.preview_failed.disconnect(self._on_preview_failed)
        except Exception:
            pass
        thread.stop()
        if not thread.wait(5000):
            thread.terminate()
            thread.wait(1000)

    def _update_count_ui(self):
        n = len(self._objpoints)
        self.lbl_count.setText(
            f"已收录: {n} / {TARGET_CAPTURE_FRAMES}（最少 {MIN_VALID_FRAMES}）"
        )
        self.progress.setValue(min(n, TARGET_CAPTURE_FRAMES))
        wiz = self.wizard()
        if wiz:
            wiz.button(QWizard.NextButton).setEnabled(self._mtx is not None)

    def _on_shot(self):
        self._sync_board_params()
        wiz: CameraCalibWizard = self.wizard()  # type: ignore
        if self._preview_thread is None:
            return
        frame = self._preview_thread.get_latest_frame()
        if frame is None:
            QMessageBox.information(self, "无画面", "摄像头尚未就绪")
            return
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        board = (wiz.board_cols, wiz.board_rows)
        ok, corners = find_chessboard(gray, board, fast=False)
        if not ok or corners is None:
            QMessageBox.information(
                self, "未检测到棋盘格",
                "当前画面未识别到完整棋盘格。\n"
                "请调整：光照、对焦、标定板是否平整、参数列×行是否正确。"
            )
            return
        h, w = frame.shape[:2]
        self._image_size = (w, h)
        self._objpoints.append(self._objp.copy())
        self._imgpoints.append(corners)
        self._mtx = None
        self._dist = None
        self.lbl_result.setText("")
        self._update_count_ui()
        self.lbl_hint.setText(
            f"已收录第 {len(self._objpoints)} 张。请变换角度后继续拍照，"
            f"或点「完成并标定」。"
        )

    def _on_undo(self):
        if not self._objpoints:
            return
        self._objpoints.pop()
        self._imgpoints.pop()
        self._mtx = None
        self._dist = None
        self.lbl_result.setText("")
        self._update_count_ui()
        wiz = self.wizard()
        if wiz:
            wiz.button(QWizard.NextButton).setEnabled(False)

    def _on_calibrate(self):
        self._sync_board_params()
        n = len(self._objpoints)
        if n < MIN_VALID_FRAMES:
            QMessageBox.warning(
                self, "张数不足",
                f"当前仅 {n} 张，至少需要 {MIN_VALID_FRAMES} 张。\n"
                "请继续拍照收录不同角度的标定板图像。"
            )
            return
        if self._image_size is None:
            QMessageBox.warning(self, "错误", "无有效图像尺寸")
            return
        self.btn_calibrate.setEnabled(False)
        self.btn_shot.setEnabled(False)
        self.lbl_hint.setText("正在计算标定参数…")
        try:
            rms, mtx, dist = calibrate_from_corners(
                self._objpoints, self._imgpoints, self._image_size,
            )
            self._rms = rms
            self._mtx = mtx
            self._dist = dist
            self.lbl_result.setText(
                f"标定成功 — RMS: {rms:.4f} px | "
                f"fx={mtx[0,0]:.1f} fy={mtx[1,1]:.1f} "
                f"cx={mtx[0,2]:.1f} cy={mtx[1,2]:.1f} | "
                f"使用 {n} 张图"
            )
            self.lbl_result.setStyleSheet("color:#44CC44;")
            self.lbl_hint.setText("标定完成，可点右下角「下一步」继续保存。")
            wiz = self.wizard()
            if wiz:
                wiz.button(QWizard.NextButton).setEnabled(True)
            QMessageBox.information(
                self, "标定成功",
                f"已用 {n} 张图完成标定，RMS = {rms:.4f} px。\n请点「下一步」命名并保存。"
            )
        except Exception as e:
            self.lbl_result.setText(str(e))
            self.lbl_result.setStyleSheet("color:#CC4444;")
            self.lbl_hint.setText("标定失败，可删除质量差的图后重试。")
            QMessageBox.warning(self, "标定失败", str(e))
        finally:
            self.btn_calibrate.setEnabled(True)
            self.btn_shot.setEnabled(True)

    def get_calibration(self):
        return self._mtx, self._dist, self._rms


class FinishPage(QWizardPage):
    def __init__(self, camera_uid: Optional[str], camera_name: Optional[str]):
        super().__init__()
        self._camera_uid = camera_uid
        self._camera_name = camera_name or ""
        self.setTitle("命名并保存")
        self.setSubTitle("为本次标定命名，可选绑定到当前摄像头。")

        layout = QVBoxLayout(self)
        form = QFormLayout()
        default_name = camera_name or f"摄像头{camera_uid or ''}"
        self.edit_name = QLineEdit(default_name.strip() or "我的标定")
        self.edit_name.textChanged.connect(self._update_summary)
        form.addRow("配置名称:", self.edit_name)
        self.lbl_camera = QLabel(
            f"当前摄像头: #{camera_uid} {camera_name}" if camera_uid is not None
            else "未指定摄像头"
        )
        form.addRow("", self.lbl_camera)
        self.chk_bind = QCheckBox("绑定到当前摄像头（切换到此摄像头时自动加载）")
        self.chk_bind.setChecked(camera_uid is not None)
        self.chk_bind.toggled.connect(lambda _: self._update_summary())
        form.addRow("", self.chk_bind)
        layout.addLayout(form)
        self.lbl_summary = QLabel("")
        self.lbl_summary.setWordWrap(True)
        layout.addWidget(self.lbl_summary)

    def initializePage(self):
        self._update_summary()

    def _update_summary(self, _text: str = ""):
        wiz: CameraCalibWizard = self.wizard()  # type: ignore
        if wiz is None:
            return
        cap_page: CapturePage = wiz.page(2)  # type: ignore
        mtx, dist, rms = cap_page.get_calibration()
        if mtx is None:
            self.lbl_summary.setText("无标定结果")
            return
        pid = _slug(self.edit_name.text())
        bind_txt = (
            f"绑定: #{self._camera_uid} {self._camera_name}"
            if self.chk_bind.isChecked() and self._camera_uid is not None
            else "不绑定摄像头"
        )
        self.lbl_summary.setText(
            f"将保存为配置 ID: {pid}\n"
            f"RMS: {rms:.4f} px | {bind_txt}\n"
            f"dist: {[round(float(x), 6) for x in dist.reshape(-1)[:5]]}"
        )


class CameraCalibWizard(QWizard):
    calibration_saved = pyqtSignal()

    def __init__(
        self,
        camera_index: int = 0,
        camera_uid: Optional[str] = None,
        camera_name: Optional[str] = None,
        parent=None,
    ):
        super().__init__(parent)
        if not _CALIB_AVAILABLE:
            raise RuntimeError("标定模块不可用，请安装 opencv-python")
        self._camera_index = camera_index
        self._camera_uid = camera_uid
        self._camera_name = camera_name
        self.board_cols = DEFAULT_BOARD_COLS
        self.board_rows = DEFAULT_BOARD_ROWS
        self.square_mm = DEFAULT_SQUARE_MM

        self.setWindowTitle("镜头去畸变标定向导")
        self.setMinimumSize(560, 680)
        self.setWizardStyle(QWizard.ModernStyle)

        self.addPage(IntroPage())
        self.addPage(BoardPage())
        self.addPage(CapturePage(camera_index))
        self.addPage(FinishPage(camera_uid, camera_name))

        self.setButtonText(QWizard.CancelButton, "取消")
        self.setButtonText(QWizard.NextButton, "下一步")
        self.setButtonText(QWizard.BackButton, "上一步")
        self.setButtonText(QWizard.FinishButton, "保存并完成")

        self.button(QWizard.CustomButton1).setText("恢复默认")
        self.setOption(QWizard.HaveCustomButton1, True)
        self.customButtonClicked.connect(self._on_restore_defaults)

    def _shutdown_capture(self):
        cap_page: CapturePage = self.page(2)  # type: ignore
        if cap_page is not None:
            cap_page.shutdown()
        QApplication.processEvents()

    def closeEvent(self, event):
        self._shutdown_capture()
        super().closeEvent(event)

    def reject(self):
        self._shutdown_capture()
        super().reject()

    def _on_restore_defaults(self):
        reply = QMessageBox.question(
            self, "恢复默认",
            "将删除所有自定义标定 NPZ 并重置为出厂默认配置，是否继续？",
            QMessageBox.Yes | QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return
        try:
            with open(_ARUCO_CONFIG, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
            data["undistort"] = restore_defaults(data.get("undistort"), _PROJECT_ROOT)
            with open(_ARUCO_CONFIG, "w", encoding="utf-8") as f:
                yaml.safe_dump(data, f, allow_unicode=True, sort_keys=False)
            QMessageBox.information(self, "已恢复", "已恢复默认配置并删除标定 NPZ 文件。")
            self.calibration_saved.emit()
        except Exception as e:
            QMessageBox.warning(self, "失败", str(e))

    def accept(self):
        self._shutdown_capture()
        cap_page: CapturePage = self.page(2)  # type: ignore
        finish_page: FinishPage = self.page(3)  # type: ignore
        mtx, dist, rms = cap_page.get_calibration()
        if mtx is None:
            QMessageBox.warning(self, "无法保存", "尚无有效标定结果")
            return
        name = finish_page.edit_name.text().strip() or "我的标定"
        pid = _slug(name)
        bind = finish_page.chk_bind.isChecked()
        saved_name = name
        try:
            with open(_ARUCO_CONFIG, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
            ud = migrate_undistort_section(data.get("undistort"))
            ud = save_profile_calibration(
                ud, _PROJECT_ROOT, pid, name, mtx, dist, rms,
                self._camera_uid if bind else None,
                self._camera_name if bind else None,
                self.board_cols, self.board_rows, self.square_mm,
                image_size=cap_page._image_size,
            )
            data["undistort"] = ud
            with open(_ARUCO_CONFIG, "w", encoding="utf-8") as f:
                yaml.safe_dump(data, f, allow_unicode=True, sort_keys=False)
        except Exception as e:
            QMessageBox.warning(self, "保存失败", str(e))
            return
        self.calibration_saved.emit()
        super().accept()
        QMessageBox.information(self.parent() or self, "保存成功", f"配置「{saved_name}」已保存。")
