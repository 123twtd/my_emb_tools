"""图传 Tab (Beta) - 图片转像素字节流通过 UART 发送 + ESP32-CAM 视频流接收"""

import logging

import numpy as np
from PIL import Image
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QGroupBox, QLabel, QLineEdit, QPushButton, QComboBox,
    QCheckBox, QProgressBar, QSpinBox, QFileDialog, QMessageBox, QTabWidget
)
from PyQt5.QtCore import Qt, QThread, pyqtSignal
from PyQt5.QtGui import QPixmap, QImage

from .base_tab import SerialTab
from .camera_scan_worker import CameraScanWorker
from ..utils import hex_to_bytes

logger = logging.getLogger(__name__)

# 视频流依赖检测
VIDEO_AVAILABLE = False
try:
    import cv2
    import requests
    VIDEO_AVAILABLE = True
except ImportError:
    pass


class ImageSendWorker(QThread):
    """后台图片发送线程"""

    progress_updated = pyqtSignal(int, int, int)  # percent, sent_bytes, total_bytes
    send_finished = pyqtSignal(bool, str)  # success, message

    def __init__(self, serial_worker, pixel_data: bytes, frame_header: bytes,
                 frame_footer: bytes, chunk_size: int, interval_ms: int):
        super().__init__()
        self._serial_worker = serial_worker
        self._pixel_data = pixel_data
        self._frame_header = frame_header
        self._frame_footer = frame_footer
        self._chunk_size = chunk_size
        self._interval_ms = interval_ms
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    def run(self):
        total = len(self._pixel_data)
        sent = 0
        try:
            while sent < total and not self._cancelled:
                chunk = self._pixel_data[sent:sent + self._chunk_size]
                frame = self._frame_header + chunk + self._frame_footer
                self._serial_worker.send(frame)
                sent += len(chunk)
                self.progress_updated.emit(int(sent / total * 100), sent, total)
                if self._interval_ms > 0:
                    self.msleep(self._interval_ms)

            if self._cancelled:
                self.send_finished.emit(False, "已取消")
            else:
                self.send_finished.emit(True, "发送完成")
        except Exception as e:
            self.send_finished.emit(False, f"发送失败: {e}")


class ImageTab(SerialTab):
    """图传模式 Tab"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._image_path = ""
        self._original_image = None
        self._pixel_data = b""
        self._send_worker = None
        self._video_service = None
        self._api_host = "127.0.0.1"
        self._api_port = 8000
        self._get_api_bases = None
        self._scan_worker = None
        self._known_devices: list = []
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        
        self.sub_tabs = QTabWidget()
        layout.addWidget(self.sub_tabs)

        # ── 1. 图片发送子标签 ──
        send_tab = QWidget()
        send_layout = QVBoxLayout(send_tab)
        send_layout.setContentsMargins(4, 4, 4, 4)
        send_layout.setSpacing(6)

        # 图片预览区
        preview_group = QGroupBox("图片预览")
        preview_layout = QVBoxLayout(preview_group)
        preview_layout.setContentsMargins(4, 14, 4, 4)

        self.lbl_preview = QLabel("请选择图片文件")
        self.lbl_preview.setAlignment(Qt.AlignCenter)
        self.lbl_preview.setMinimumHeight(200)
        self.lbl_preview.setStyleSheet("background-color: #2E2E2E; color: #AAAAAA;")
        preview_layout.addWidget(self.lbl_preview)

        self.lbl_info = QLabel("")
        self.lbl_info.setAlignment(Qt.AlignCenter)
        preview_layout.addWidget(self.lbl_info)

        send_layout.addWidget(preview_group, stretch=1)

        # 图片控制区
        ctrl_group = QGroupBox("图片设置")
        ctrl_layout = QGridLayout(ctrl_group)
        ctrl_layout.setContentsMargins(6, 14, 6, 6)
        ctrl_layout.setHorizontalSpacing(8)
        ctrl_layout.setVerticalSpacing(4)

        ctrl_layout.addWidget(QLabel("图片:"), 0, 0)
        self.lbl_filepath = QLabel("未选择")
        self.lbl_filepath.setStyleSheet("color: #888888;")
        ctrl_layout.addWidget(self.lbl_filepath, 0, 1, 1, 2)
        btn_select = QPushButton("选择图片")
        btn_select.clicked.connect(self._on_select_image)
        ctrl_layout.addWidget(btn_select, 0, 3)

        ctrl_layout.addWidget(QLabel("格式:"), 1, 0)
        self.cb_format = QComboBox()
        self.cb_format.addItems(["RGB565", "RGB888", "Grayscale"])
        self.cb_format.currentTextChanged.connect(self._on_settings_changed)
        ctrl_layout.addWidget(self.cb_format, 1, 1)

        ctrl_layout.addWidget(QLabel("坐标原点:"), 1, 2)
        self.cb_origin = QComboBox()
        self.cb_origin.addItems(["左上", "右上", "左下", "右下"])
        self.cb_origin.currentTextChanged.connect(self._on_settings_changed)
        ctrl_layout.addWidget(self.cb_origin, 1, 3)

        ctrl_layout.addWidget(QLabel("变换:"), 2, 0)
        self.cb_hflip = QCheckBox("水平翻转")
        self.cb_hflip.stateChanged.connect(lambda _: self._on_settings_changed())
        ctrl_layout.addWidget(self.cb_hflip, 2, 1)
        self.cb_vflip = QCheckBox("垂直翻转")
        self.cb_vflip.stateChanged.connect(lambda _: self._on_settings_changed())
        ctrl_layout.addWidget(self.cb_vflip, 2, 2)

        self.cb_rotation = QComboBox()
        self.cb_rotation.addItems(["0°", "90°", "180°", "270°"])
        self.cb_rotation.currentTextChanged.connect(self._on_settings_changed)
        ctrl_layout.addWidget(self.cb_rotation, 2, 3)

        send_layout.addWidget(ctrl_group)

        # 帧配置区
        frame_group = QGroupBox("帧配置")
        frame_layout = QGridLayout(frame_group)
        frame_layout.setContentsMargins(6, 14, 6, 6)
        frame_layout.setHorizontalSpacing(8)
        frame_layout.setVerticalSpacing(4)

        frame_layout.addWidget(QLabel("帧头(HEX):"), 0, 0)
        self.ed_frame_header = QLineEdit("AA BB")
        frame_layout.addWidget(self.ed_frame_header, 0, 1)

        frame_layout.addWidget(QLabel("帧尾(HEX):"), 0, 2)
        self.ed_frame_footer = QLineEdit("FF FE")
        frame_layout.addWidget(self.ed_frame_footer, 0, 3)

        frame_layout.addWidget(QLabel("帧大小(B):"), 1, 0)
        self.ed_chunk_size = QLineEdit("1024")
        self.ed_chunk_size.setFixedWidth(80)
        frame_layout.addWidget(self.ed_chunk_size, 1, 1)

        frame_layout.addWidget(QLabel("帧间隔(ms):"), 1, 2)
        self.ed_interval = QLineEdit("10")
        self.ed_interval.setFixedWidth(80)
        frame_layout.addWidget(self.ed_interval, 1, 3)

        send_layout.addWidget(frame_group)

        # 发送控制区
        send_ctrl_group = QGroupBox("发送控制")
        send_ctrl_layout = QVBoxLayout(send_ctrl_group)
        send_ctrl_layout.setContentsMargins(6, 14, 6, 6)

        self.btn_send_image = QPushButton("发送图片")
        self.btn_send_image.setEnabled(False)
        self.btn_send_image.clicked.connect(self._on_send_clicked)
        send_ctrl_layout.addWidget(self.btn_send_image)

        self.progress_bar = QProgressBar()
        self.progress_bar.setValue(0)
        send_ctrl_layout.addWidget(self.progress_bar)

        self.lbl_progress = QLabel("就绪")
        self.lbl_progress.setAlignment(Qt.AlignCenter)
        send_ctrl_layout.addWidget(self.lbl_progress)

        send_layout.addWidget(send_ctrl_group)
        
        self.sub_tabs.addTab(send_tab, "图片发送")

        # ── 2. 视频流（统一捕获 + API 广播）──
        stream_tab = QWidget()
        stream_layout = QVBoxLayout(stream_tab)
        stream_layout.setContentsMargins(4, 4, 4, 4)
        stream_layout.setSpacing(6)

        self.lbl_stream_preview = QLabel("选择视频源并开始捕获")
        self.lbl_stream_preview.setAlignment(Qt.AlignCenter)
        self.lbl_stream_preview.setMinimumHeight(220)
        self.lbl_stream_preview.setStyleSheet("background-color: #2E2E2E; color: #AAAAAA;")
        stream_layout.addWidget(self.lbl_stream_preview, stretch=1)

        self.lbl_stream_info = QLabel("")
        self.lbl_stream_info.setAlignment(Qt.AlignCenter)
        stream_layout.addWidget(self.lbl_stream_info)

        source_group = QGroupBox("视频源")
        source_layout = QGridLayout(source_group)
        source_layout.setContentsMargins(6, 14, 6, 6)
        source_layout.setHorizontalSpacing(8)
        source_layout.setVerticalSpacing(4)

        source_layout.addWidget(QLabel("来源:"), 0, 0)
        self.cb_source = QComboBox()
        self.cb_source.addItems(["本机摄像头", "HTTP MJPEG"])
        self.cb_source.currentIndexChanged.connect(self._on_source_changed)
        source_layout.addWidget(self.cb_source, 0, 1, 1, 3)

        # 本机摄像头配置
        self._local_cfg = QWidget()
        local_cfg_layout = QGridLayout(self._local_cfg)
        local_cfg_layout.setContentsMargins(0, 0, 0, 0)
        local_cfg_layout.setHorizontalSpacing(8)
        local_cfg_layout.setVerticalSpacing(4)

        local_cfg_layout.addWidget(QLabel("设备:"), 0, 0)
        self.cb_camera = QComboBox()
        self.cb_camera.setMinimumWidth(180)
        self.cb_camera.currentIndexChanged.connect(self._on_camera_selected)
        local_cfg_layout.addWidget(self.cb_camera, 0, 1, 1, 2)

        self.btn_scan_cam = QPushButton("扫描")
        self.btn_scan_cam.setFixedWidth(60)
        self.btn_scan_cam.setToolTip("重新扫描本机摄像头（支持热插拔）")
        self.btn_scan_cam.clicked.connect(self._start_camera_scan)
        local_cfg_layout.addWidget(self.btn_scan_cam, 0, 3)

        self.scan_progress = QProgressBar()
        self.scan_progress.setRange(0, 100)
        self.scan_progress.setValue(0)
        self.scan_progress.setTextVisible(True)
        self.scan_progress.setFormat("就绪")
        self.scan_progress.setFixedHeight(18)
        local_cfg_layout.addWidget(self.scan_progress, 1, 0, 1, 4)

        local_cfg_layout.addWidget(QLabel("分辨率:"), 2, 0)
        self.cb_resolution = QComboBox()
        self.cb_resolution.setMinimumWidth(140)
        self.cb_resolution.setToolTip("驱动原生：与 aruco 相同，不强制设置宽高，由驱动决定")
        local_cfg_layout.addWidget(self.cb_resolution, 2, 1)

        local_cfg_layout.addWidget(QLabel("帧率:"), 2, 2)
        self.cb_fps = QComboBox()
        self.cb_fps.addItems(["5", "10", "15", "24", "30", "60"])
        self.cb_fps.setCurrentText("15")
        local_cfg_layout.addWidget(self.cb_fps, 2, 3)

        local_cfg_layout.addWidget(QLabel("JPEG质量:"), 3, 0)
        self.cb_quality = QComboBox()
        self.cb_quality.addItems(["60", "75", "85", "95"])
        self.cb_quality.setCurrentText("85")
        local_cfg_layout.addWidget(self.cb_quality, 3, 1)

        self.cb_custom_res = QCheckBox("强制分辨率")
        self.cb_custom_res.setToolTip("勾选后使用右侧自定义宽高（如 1920×1080）")
        local_cfg_layout.addWidget(self.cb_custom_res, 3, 2)

        custom_res_row = QHBoxLayout()
        custom_res_row.setContentsMargins(0, 0, 0, 0)
        custom_res_row.addWidget(QLabel("宽"))
        self.spin_res_w = QSpinBox()
        self.spin_res_w.setRange(160, 3840)
        self.spin_res_w.setValue(1920)
        self.spin_res_w.setFixedWidth(72)
        custom_res_row.addWidget(self.spin_res_w)
        custom_res_row.addWidget(QLabel("高"))
        self.spin_res_h = QSpinBox()
        self.spin_res_h.setRange(120, 2160)
        self.spin_res_h.setValue(1080)
        self.spin_res_h.setFixedWidth(72)
        custom_res_row.addWidget(self.spin_res_h)
        custom_res_wrap = QWidget()
        custom_res_wrap.setLayout(custom_res_row)
        local_cfg_layout.addWidget(custom_res_wrap, 3, 3)

        source_layout.addWidget(self._local_cfg, 1, 0, 1, 4)

        # HTTP 配置
        self._http_cfg = QWidget()
        http_cfg_layout = QHBoxLayout(self._http_cfg)
        http_cfg_layout.setContentsMargins(0, 0, 0, 0)
        http_cfg_layout.addWidget(QLabel("URL:"))
        self.ed_stream_url = QLineEdit("http://192.168.1.100:81/stream")
        self.ed_stream_url.setPlaceholderText("http://host:port/stream")
        http_cfg_layout.addWidget(self.ed_stream_url, stretch=1)
        self._http_cfg.setVisible(False)
        source_layout.addWidget(self._http_cfg, 2, 0, 1, 4)

        stream_layout.addWidget(source_group)

        ctrl_group = QGroupBox("捕获与广播")
        ctrl_layout = QGridLayout(ctrl_group)
        ctrl_layout.setContentsMargins(6, 14, 6, 6)
        ctrl_layout.setHorizontalSpacing(8)

        self.btn_capture = QPushButton("开始捕获")
        self.btn_capture.clicked.connect(self._on_toggle_capture)
        ctrl_layout.addWidget(self.btn_capture, 0, 0)

        self.cb_api_broadcast = QCheckBox("API 广播（默认关闭）")
        self.cb_api_broadcast.setToolTip("开启后外部程序可通过 API 拉取视频流/快照")
        self.cb_api_broadcast.stateChanged.connect(self._on_api_broadcast_changed)
        ctrl_layout.addWidget(self.cb_api_broadcast, 0, 1, 1, 2)

        self.cb_stream_hflip = QCheckBox("水平翻转")
        self.cb_stream_hflip.setToolTip("对捕获帧做左右镜像（预览与 API 广播同步）")
        self.cb_stream_hflip.stateChanged.connect(self._on_stream_flip_changed)
        ctrl_layout.addWidget(self.cb_stream_hflip, 1, 0)

        self.cb_stream_vflip = QCheckBox("垂直翻转")
        self.cb_stream_vflip.setToolTip("对捕获帧做上下翻转（预览与 API 广播同步）")
        self.cb_stream_vflip.stateChanged.connect(self._on_stream_flip_changed)
        ctrl_layout.addWidget(self.cb_stream_vflip, 1, 1)

        self.lbl_stream_status = QLabel("未捕获")
        self.lbl_stream_status.setStyleSheet("color: #888888;")
        ctrl_layout.addWidget(self.lbl_stream_status, 2, 0, 1, 3)

        if not VIDEO_AVAILABLE:
            source_group.setEnabled(False)
            ctrl_group.setEnabled(False)
            source_group.setToolTip("需要安装 opencv-python 和 requests")
            self.lbl_stream_status.setText("依赖缺失")
            self.lbl_stream_status.setStyleSheet("color: #CC6600;")

        stream_layout.addWidget(ctrl_group)

        api_group = QGroupBox("API 端点（需启动 API 服务并勾选 API 广播）")
        api_layout = QVBoxLayout(api_group)
        api_layout.setContentsMargins(6, 14, 6, 6)
        self.lbl_api_endpoints = QLabel("捕获并开启 API 广播后显示")
        self.lbl_api_endpoints.setWordWrap(True)
        self.lbl_api_endpoints.setStyleSheet("color: #888888; font-size: 11px;")
        api_layout.addWidget(self.lbl_api_endpoints)
        stream_layout.addWidget(api_group)

        self.sub_tabs.addTab(stream_tab, "视频流")

    # ──────────────────── 图片处理 ────────────────────

    def _on_select_image(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "选择图片", "",
            "Image Files (*.png *.jpg *.jpeg *.bmp *.gif);;All Files (*)"
        )
        if path:
            self._image_path = path
            self.lbl_filepath.setText(path.split("/")[-1])
            try:
                self._original_image = Image.open(path).convert("RGB")
                self._process_and_preview()
                self.btn_send_image.setEnabled(True)
            except Exception as e:
                QMessageBox.warning(self, "错误", f"无法加载图片: {e}")

    def _on_settings_changed(self):
        if self._original_image is not None:
            self._process_and_preview()

    def _process_and_preview(self):
        """处理图片并更新预览"""
        img = self._original_image.copy()

        # 坐标原点变换
        origin = self.cb_origin.currentText()
        if origin == "右上":
            img = img.transpose(Image.FLIP_LEFT_RIGHT)
        elif origin == "左下":
            img = img.transpose(Image.FLIP_TOP_BOTTOM)
        elif origin == "右下":
            img = img.transpose(Image.FLIP_LEFT_RIGHT).transpose(Image.FLIP_TOP_BOTTOM)

        # 旋转
        rotation = int(self.cb_rotation.currentText().replace("°", ""))
        if rotation:
            img = img.rotate(rotation, expand=True)

        # 翻转
        if self.cb_hflip.isChecked():
            img = img.transpose(Image.FLIP_LEFT_RIGHT)
        if self.cb_vflip.isChecked():
            img = img.transpose(Image.FLIP_TOP_BOTTOM)

        # 生成预览
        preview = img.copy()
        preview.thumbnail((300, 200))
        qt_img = QImage(
            preview.tobytes(), preview.width, preview.height,
            preview.width * 3, QImage.Format_RGB888
        ).copy()  # 复制以避免内存被回收
        self.lbl_preview.setPixmap(QPixmap.fromImage(qt_img))

        # 生成像素数据
        fmt = self.cb_format.currentText()
        if fmt == "RGB565":
            arr = np.array(img, dtype=np.uint16)
            r = (arr[:, :, 0].astype(np.uint16) >> 3) << 11
            g = (arr[:, :, 1].astype(np.uint16) >> 2) << 5
            b = arr[:, :, 2].astype(np.uint16) >> 3
            pixel_data = (r | g | b).astype(np.uint16).tobytes()
            bpp = 2
        elif fmt == "RGB888":
            pixel_data = np.array(img, dtype=np.uint8).tobytes()
            bpp = 3
        else:  # Grayscale
            gray = img.convert("L")
            pixel_data = np.array(gray, dtype=np.uint8).tobytes()
            bpp = 1

        self._pixel_data = pixel_data

        w, h = img.size
        self.lbl_info.setText(
            f"分辨率: {w}x{h}  格式: {fmt}  大小: {len(pixel_data)} B  ({bpp} B/px)"
        )

    # ──────────────────── 发送 ────────────────────

    def _on_send_clicked(self):
        if not self._pixel_data:
            QMessageBox.warning(self, "提示", "请先选择图片")
            return

        if self._serial_worker is None or not self._serial_worker.is_open:
            QMessageBox.warning(self, "提示", "请先打开串口")
            return

        if self._send_worker is not None and self._send_worker.isRunning():
            # 取消发送
            self._send_worker.cancel()
            return

        # 解析帧头帧尾
        try:
            frame_header = hex_to_bytes(self.ed_frame_header.text())
            frame_footer = hex_to_bytes(self.ed_frame_footer.text())
        except Exception:
            QMessageBox.warning(self, "错误", "帧头/帧尾 HEX 格式无效")
            return

        try:
            chunk_size = int(self.ed_chunk_size.text())
            interval_ms = int(self.ed_interval.text())
        except ValueError:
            QMessageBox.warning(self, "错误", "帧大小/间隔必须为数字")
            return

        if chunk_size <= 0:
            QMessageBox.warning(self, "错误", "帧大小必须大于 0")
            return

        self.btn_send_image.setText("取消发送")
        self.progress_bar.setValue(0)
        self.lbl_progress.setText("发送中...")

        self._send_worker = ImageSendWorker(
            self._serial_worker, self._pixel_data,
            frame_header, frame_footer, chunk_size, interval_ms
        )
        self._send_worker.progress_updated.connect(self._on_progress)
        self._send_worker.send_finished.connect(self._on_send_finished)
        self._send_worker.start()

    def _on_progress(self, percent: int, sent: int, total: int):
        self.progress_bar.setValue(percent)
        self.lbl_progress.setText(f"已发送: {sent} / {total} B ({percent}%)")

    def _on_send_finished(self, success: bool, message: str):
        self.btn_send_image.setText("发送图片")
        self.lbl_progress.setText(message)
        if not success:
            QMessageBox.warning(self, "提示", message)

    def set_camera_broadcaster(self, broadcaster, api_host: str = "127.0.0.1",
                               api_port: int = 8000, get_api_bases=None):
        """由 MainWindow 注入统一视频流服务"""
        if self._video_service is not None:
            try:
                self._video_service.frame_ready.disconnect(self._on_stream_frame)
                self._video_service.status_changed.disconnect(self._on_stream_status)
                self._video_service.capture_changed.disconnect(self._on_capture_changed)
                self._video_service.api_broadcast_changed.disconnect(self._on_api_broadcast_changed_remote)
            except Exception:
                pass

        self._video_service = broadcaster
        self._api_host = api_host
        self._api_port = api_port
        self._get_api_bases = get_api_bases

        if broadcaster is not None:
            broadcaster.frame_ready.connect(self._on_stream_frame)
            broadcaster.status_changed.connect(self._on_stream_status)
            broadcaster.capture_changed.connect(self._on_capture_changed)
            broadcaster.api_broadcast_changed.connect(self._on_api_broadcast_changed_remote)
            self._start_camera_scan()
            self._sync_stream_ui()

    def _api_base_urls(self) -> list:
        if self._get_api_bases:
            try:
                return self._get_api_bases()
            except Exception:
                pass
        return [f"http://{self._api_host}:{self._api_port}"]

    # ─────────────────── 生命周期 ────────────────────

    def on_data_received(self, data: bytes):
        pass  # 图传模式暂不处理接收数据

    def on_port_toggled(self, is_open: bool):
        self.btn_send_image.setEnabled(is_open and self._pixel_data)

    def reset_state(self):
        if self._send_worker is not None and self._send_worker.isRunning():
            self._send_worker.cancel()

    def cleanup(self):
        """释放资源"""
        if self._send_worker is not None and self._send_worker.isRunning():
            self._send_worker.cancel()
        if self._scan_worker is not None and self._scan_worker.isRunning():
            self._scan_worker.wait(2000)
        if self._video_service is not None and self._video_service.is_capturing:
            self._video_service.stop_capture()
            self._sync_stream_ui()

    # ─────────────────── 视频流（统一）────────────────────

    def _on_source_changed(self, index: int):
        is_local = index == 0
        self._local_cfg.setVisible(is_local)
        self._http_cfg.setVisible(not is_local)

    def _start_camera_scan(self):
        if not VIDEO_AVAILABLE:
            QMessageBox.warning(self, "提示", "需要安装 opencv-python")
            return
        if self._video_service is None:
            QMessageBox.warning(
                self, "提示",
                "视频服务未就绪，请稍候再试\n（需等待网络服务初始化完成）"
            )
            return
        if self._scan_worker is not None and self._scan_worker.isRunning():
            return

        self.btn_scan_cam.setEnabled(False)
        self.btn_scan_cam.setText("扫描中")
        self.scan_progress.setValue(0)
        self.scan_progress.setFormat("准备扫描...")
        self.lbl_stream_status.setText("正在扫描摄像头...")
        self.lbl_stream_status.setStyleSheet("color: #CCAA00;")

        self._scan_worker = CameraScanWorker(self._video_service, self)
        self._scan_worker.scan_progress.connect(self._on_scan_progress)
        self._scan_worker.scan_finished.connect(self._on_scan_finished)
        self._scan_worker.scan_failed.connect(self._on_scan_failed)
        def _scan_done():
            self.btn_scan_cam.setEnabled(True)
            self.btn_scan_cam.setText("扫描")
        self._scan_worker.finished.connect(_scan_done)
        self._scan_worker.start()

    def _on_scan_progress(self, current: int, total: int, message: str):
        pct = int(current / total * 100) if total else 0
        self.scan_progress.setValue(pct)
        self.scan_progress.setFormat(f"{message}  ({current}/{total})")
        self.lbl_stream_status.setText(message)

    def _on_scan_finished(self, devices: list):
        if self._video_service is not None:
            try:
                self._video_service.restore_after_scan()
            except Exception:
                pass
        self._known_devices = devices
        prev_data = self.cb_camera.currentData() if self.cb_camera.count() > 0 else None
        self.cb_camera.blockSignals(True)
        self.cb_camera.clear()
        if not devices:
            self.cb_camera.addItem("未检测到摄像头（请插入后点扫描）", None)
            self.cb_resolution.clear()
        else:
            for dev in devices:
                label = f"#{dev['index']}  {dev['name']}"
                self.cb_camera.addItem(label, dev)
            if isinstance(prev_data, dict):
                for i in range(self.cb_camera.count()):
                    d = self.cb_camera.itemData(i)
                    if (isinstance(d, dict)
                            and d.get("device_uid") == prev_data.get("device_uid")):
                        self.cb_camera.setCurrentIndex(i)
                        break
            self._populate_resolutions()
        self.cb_camera.blockSignals(False)
        count = len(devices)
        self.scan_progress.setValue(100)
        self.scan_progress.setFormat(f"完成 — 发现 {count} 个摄像头")
        self.lbl_stream_status.setText(f"扫描完成: 发现 {count} 个摄像头")
        self.lbl_stream_status.setStyleSheet("color: #44CC44;" if count else "color: #CC6600;")

    def _on_scan_failed(self, msg: str):
        if self._video_service is not None:
            try:
                self._video_service.restore_after_scan()
            except Exception:
                pass
        self.scan_progress.setFormat("扫描失败")
        self.lbl_stream_status.setText(f"扫描失败: {msg[:40]}")
        self.lbl_stream_status.setStyleSheet("color: #CC4444;")

    def _on_camera_selected(self, _index: int):
        self._populate_resolutions()

    def _populate_resolutions(self):
        """与 aruco 一致：默认驱动原生；可选手动指定常用分辨率"""
        self.cb_resolution.clear()
        self.cb_resolution.addItem("驱动原生 (推荐)", None)
        for label, size in (
            ("1920×1080", (1920, 1080)),
            ("1280×720", (1280, 720)),
            ("640×480", (640, 480)),
        ):
            self.cb_resolution.addItem(label, size)
        self.cb_resolution.setCurrentIndex(0)

    def _get_capture_resolution(self) -> tuple:
        if self.cb_custom_res.isChecked():
            return self.spin_res_w.value(), self.spin_res_h.value()
        res = self.cb_resolution.currentData()
        if res:
            return res[0], res[1]
        return None, None  # 驱动原生，不 set 宽高

    def _on_toggle_capture(self):
        if not VIDEO_AVAILABLE or self._video_service is None:
            QMessageBox.warning(self, "提示", "视频服务未就绪")
            return

        if self._video_service.is_capturing:
            self._video_service.stop_capture()
            self._sync_stream_ui()
            return

        try:
            fps = int(self.cb_fps.currentText())
            quality = int(self.cb_quality.currentText())
        except ValueError:
            fps, quality = 15, 85
        self._video_service.configure(fps=fps, jpeg_quality=quality,
                                      flip_h=self.cb_stream_hflip.isChecked(),
                                      flip_v=self.cb_stream_vflip.isChecked())

        if self.cb_source.currentIndex() == 0:
            dev = self.cb_camera.currentData()
            if not isinstance(dev, dict):
                QMessageBox.warning(self, "提示", "请先扫描并选择摄像头")
                return
            res = self._get_capture_resolution()
            width, height = res
            ok = self._video_service.start_local(
                device_index=dev["index"],
                width=width,
                height=height,
            )
        else:
            url = self.ed_stream_url.text().strip()
            if not url:
                QMessageBox.warning(self, "提示", "请输入 HTTP 流地址")
                return
            ok = self._video_service.start_http(url)

        if not ok:
            QMessageBox.warning(
                self, "错误",
                self._video_service.get_status().get("last_error", "无法开始捕获")
            )
            return

        self._sync_stream_ui()

    def _on_stream_flip_changed(self, _state: int = 0):
        if self._video_service is None:
            return
        self._video_service.configure(
            flip_h=self.cb_stream_hflip.isChecked(),
            flip_v=self.cb_stream_vflip.isChecked(),
        )

    def _on_api_broadcast_changed(self, state: int):
        if self._video_service is None:
            return
        enabled = state == Qt.Checked
        if enabled and not self._video_service.is_capturing:
            self.cb_api_broadcast.blockSignals(True)
            self.cb_api_broadcast.setChecked(False)
            self.cb_api_broadcast.blockSignals(False)
            QMessageBox.warning(self, "提示", "请先开始视频捕获")
            return
        self._video_service.set_api_broadcast(enabled)
        self._sync_stream_ui()

    def _on_api_broadcast_changed_remote(self, _enabled: bool):
        self.cb_api_broadcast.blockSignals(True)
        self.cb_api_broadcast.setChecked(self._video_service.api_broadcast_enabled)
        self.cb_api_broadcast.blockSignals(False)
        self._sync_stream_ui()

    def _on_capture_changed(self, capturing: bool):
        self._sync_stream_ui()
        if not capturing:
            self.lbl_stream_preview.setText("选择视频源并开始捕获")
            self.lbl_stream_info.setText("")

    def _sync_stream_ui(self):
        svc = self._video_service
        capturing = svc is not None and svc.is_capturing
        api_on = svc is not None and svc.api_broadcast_enabled

        self.btn_capture.setText("停止捕获" if capturing else "开始捕获")
        enabled = not capturing
        self.cb_source.setEnabled(enabled)
        self._local_cfg.setEnabled(enabled and self.cb_source.currentIndex() == 0)
        self._http_cfg.setEnabled(enabled and self.cb_source.currentIndex() == 1)
        self.btn_scan_cam.setEnabled(enabled)
        self.cb_camera.setEnabled(enabled)
        self.cb_resolution.setEnabled(enabled)
        self.cb_fps.setEnabled(enabled)
        self.cb_quality.setEnabled(enabled)
        self.cb_custom_res.setEnabled(enabled)
        self.spin_res_w.setEnabled(enabled)
        self.spin_res_h.setEnabled(enabled)
        self.ed_stream_url.setEnabled(enabled)

        self.cb_api_broadcast.blockSignals(True)
        self.cb_api_broadcast.setChecked(api_on)
        self.cb_api_broadcast.setEnabled(capturing)
        self.cb_api_broadcast.blockSignals(False)

        base = self._api_base_urls()[0]
        if api_on:
            st = svc.get_status() if svc else {}
            src = "本机摄像头" if st.get("source_type") == "local" else "HTTP"
            lines = [f"来源: {src}"]
            for b in self._api_base_urls():
                lines.append(f"GET {b}/api/camera/stream    — MJPEG 流（局域网可访问）")
                lines.append(f"GET {b}/api/camera/snapshot  — 单帧")
            lines.append(f"GET {base}/api/camera/status    — 状态")
            self.lbl_api_endpoints.setText("\n".join(lines))
            self.lbl_api_endpoints.setStyleSheet("color: #98C379; font-size: 11px;")
        else:
            hint = "、".join(self._api_base_urls())
            self.lbl_api_endpoints.setText(
                f"勾选「API 广播」后可通过以下地址拉流：\n{hint}\n"
                f"（局域网访问请在 设置→网络服务 将 API 监听改为 0.0.0.0）"
            )
            self.lbl_api_endpoints.setStyleSheet("color: #888888; font-size: 11px;")

    def _on_stream_status(self, status: str):
        self.lbl_stream_status.setText(status)
        if "错误" in status or "无法" in status or "失败" in status:
            self.lbl_stream_status.setStyleSheet("color: #CC4444;")
            self._sync_stream_ui()
        elif "广播" in status and "开启" in status:
            self.lbl_stream_status.setStyleSheet("color: #44CC44;")
        elif "捕获" in status:
            self.lbl_stream_status.setStyleSheet("color: #44CC44;")
        else:
            self.lbl_stream_status.setStyleSheet("color: #888888;")

    def _on_stream_frame(self, frame):
        if not VIDEO_AVAILABLE or self._video_service is None:
            return
        if not self._video_service.is_capturing:
            return

        st = self._video_service.get_status()
        rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        h, w, ch = rgb_frame.shape
        qt_img = QImage(rgb_frame.data, w, h, ch * w, QImage.Format_RGB888).copy()
        self.lbl_stream_preview.setPixmap(QPixmap.fromImage(qt_img).scaled(
            self.lbl_stream_preview.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation
        ))

        dev = self.cb_camera.currentData()
        if st.get("source_type") == "local" and isinstance(dev, dict):
            src_label = f"#{dev.get('index', '?')} {dev.get('name', '本机')[:24]}"
        else:
            src_label = "HTTP"
        fps = st.get("measured_fps", 0)
        api_tag = " | API广播中" if st.get("api_broadcast") else ""
        if fps > 0:
            self.lbl_stream_info.setText(
                f"[{src_label}] {w}x{h} @ {fps:.1f} FPS{api_tag}"
            )
        else:
            self.lbl_stream_info.setText(f"[{src_label}] {w}x{h}{api_tag}")
