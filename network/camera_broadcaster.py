"""视频流服务 - 多源采集（本机摄像头 / HTTP MJPEG）、API 广播

摄像头枚举/打开方式参考 aruco_app：cv2.VideoCapture(index)，不强制 DSHOW 后端。
（Windows 上 CAP_DSHOW 按索引打开会触发 can't be used to capture by index）
"""

import logging
import platform
import subprocess
import threading
import time
from typing import List, Dict, Optional, Iterator, Tuple, Callable

from PyQt5.QtCore import QObject, pyqtSignal

logger = logging.getLogger(__name__)

CV2_AVAILABLE = False
REQUESTS_AVAILABLE = False
try:
    import cv2
    import numpy as np
    CV2_AVAILABLE = True
    try:
        cv2.setLogLevel(3)
    except Exception:
        pass
    try:
        cv2.utils.logging.setLogLevel(cv2.utils.logging.LOG_LEVEL_SILENT)
    except Exception:
        pass
except ImportError:
    np = None  # type: ignore

try:
    import requests
    REQUESTS_AVAILABLE = True
except ImportError:
    pass


def _silence_opencv_logging() -> None:
    if not CV2_AVAILABLE:
        return
    try:
        cv2.setLogLevel(3)
    except Exception:
        pass
    try:
        cv2.utils.logging.setLogLevel(cv2.utils.logging.LOG_LEVEL_SILENT)
    except Exception:
        pass

COMMON_RESOLUTIONS: Tuple[Tuple[int, int], ...] = (
    (320, 240), (640, 480), (800, 600), (1024, 768),
    (1280, 720), (1280, 960), (1920, 1080), (2560, 1440), (3840, 2160),
)

_AUDIO_NAME_PATTERN = (
    "microphone", "麦克风", "mic array", "audio", "声音", "耳机"
)


def _windows_camera_names() -> List[str]:
    if platform.system() != "Windows":
        return []
    try:
        ps = (
            "Get-CimInstance Win32_PnPEntity | "
            "Where-Object { $_.PNPClass -eq 'Camera' -and $_.Status -eq 'OK' } | "
            "Select-Object -ExpandProperty Name"
        )
        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps],
            capture_output=True, text=True, timeout=8,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        if result.returncode != 0:
            return []
        names = []
        for line in result.stdout.splitlines():
            name = line.strip()
            if not name:
                continue
            lower = name.lower()
            if any(k in lower for k in _AUDIO_NAME_PATTERN):
                continue
            names.append(name)
        return names
    except Exception as e:
        logger.debug(f"Failed to query Windows camera names: {e}")
        return []


def _open_capture(index: int):
    """与 aruco_app 一致：默认后端 + 索引，不指定 DSHOW"""
    if not CV2_AVAILABLE:
        return None
    cap = cv2.VideoCapture(index)
    if not cap.isOpened():
        cap.release()
        return None
    return cap


def _is_valid_video_frame(frame) -> bool:
    if frame is None or not CV2_AVAILABLE:
        return False
    if frame.ndim != 3 or frame.shape[2] < 3:
        return False
    h, w = frame.shape[:2]
    return w >= 80 and h >= 60


def _read_test_frame(cap, attempts: int = 3) -> Optional[Tuple[bool, object]]:
    for _ in range(attempts):
        ret, frame = cap.read()
        if ret and _is_valid_video_frame(frame):
            return ret, frame
        time.sleep(0.05)
    return None


def _flush_frames(cap, count: int = 6):
    """分辨率切换后丢弃缓冲帧"""
    if not CV2_AVAILABLE or cap is None:
        return
    for _ in range(count):
        cap.grab()
        time.sleep(0.03)

  
def _read_stable_frame(cap, attempts: int = 8) -> Optional[object]:
    frame = None
    for _ in range(attempts):
        ret, f = cap.read()
        if ret and _is_valid_video_frame(f):
            frame = f
        time.sleep(0.04)
    return frame


def _apply_fourcc_mjpg(cap) -> bool:
    if not CV2_AVAILABLE:
        return False
    try:
        cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
        return True
    except Exception:
        return False


def _try_set_resolution(cap, width: int, height: int) -> Optional[Tuple[int, int]]:
    """USB 1080p 通常需 MJPEG + 预热读帧"""
    if not CV2_AVAILABLE:
        return None
    w, h = int(width), int(height)
    for use_mjpg in (True, False):
        if use_mjpg:
            _apply_fourcc_mjpg(cap)
        for tw, th in ((w, h), (h, w)):
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, tw)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, th)
            _flush_frames(cap, 8)
            frame = _read_stable_frame(cap, attempts=6)
            if frame is None:
                continue
            fw, fh = int(frame.shape[1]), int(frame.shape[0])
            if abs(fw - w) <= 32 and abs(fh - h) <= 32:
                return fw, fh
    return None


def _apply_aruco_capture_settings(cap, fps: float = 30.0):
    """与 aruco_app 一致：仅缓冲、曝光、帧率，不改分辨率"""
    if not CV2_AVAILABLE or cap is None:
        return
    try:
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
    except Exception:
        pass
    try:
        cap.set(cv2.CAP_PROP_AUTO_EXPOSURE, 0.25)
    except Exception:
        pass
    try:
        cap.set(cv2.CAP_PROP_FPS, fps)
    except Exception:
        pass


def _native_frame_size(cap) -> Optional[Tuple[int, int]]:
    """读一帧获取驱动实际输出的分辨率（aruco 不 set 宽高，靠读帧得到真实尺寸）"""
    frame = _read_stable_frame(cap, attempts=8)
    if frame is not None:
        return int(frame.shape[1]), int(frame.shape[0])
    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
    h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
    return (w, h) if w > 0 and h > 0 else None


def _probe_index_opens(index: int, timeout: float = 1.2) -> bool:
    """带超时的 index 探测，避免 Windows 上 VideoCapture 长时间卡住"""
    if not CV2_AVAILABLE:
        return False
    _silence_opencv_logging()
    result = {"ok": False}

    def _try():
        cap = _open_capture(index)
        try:
            if cap is None:
                result["ok"] = False
                return
            ret, frame = cap.read()
            result["ok"] = bool(ret and _is_valid_video_frame(frame))
        finally:
            if cap is not None:
                cap.release()

    t = threading.Thread(target=_try, daemon=True)
    t.start()
    t.join(timeout)
    return result["ok"]


class VideoStreamBroadcaster(QObject):
    """统一视频流采集与 API 广播"""

    frame_ready = pyqtSignal(object)
    status_changed = pyqtSignal(str)
    capture_changed = pyqtSignal(bool)
    api_broadcast_changed = pyqtSignal(bool)

    SOURCE_LOCAL = "local"
    SOURCE_HTTP = "http"

    def __init__(self, fps: int = 15, jpeg_quality: int = 85,
                 max_device_scan: int = 10, parent=None):
        super().__init__(parent)
        self._fps = max(1, min(fps, 60))
        self._jpeg_quality = max(10, min(jpeg_quality, 100))
        self._max_device_scan = max(1, min(max_device_scan, 20))

        self._source_type: Optional[str] = None
        self._device_index: Optional[int] = None
        self._http_url: Optional[str] = None
        self._width: Optional[int] = None
        self._height: Optional[int] = None

        self._cap = None
        self._capturing = False
        self._api_broadcast = False
        self._thread: Optional[threading.Thread] = None
        self._enum_lock = threading.Lock()
        self._lock = threading.Lock()
        self._latest_jpeg: Optional[bytes] = None
        self._latest_frame_bgr = None
        self._frame_width = 0
        self._frame_height = 0
        self._frame_count = 0
        self._measured_fps = 0.0
        self._last_error = ""
        self._device_cache: List[Dict] = []
        self._pending_scan_restore: Optional[dict] = None
        self._flip_h = False
        self._flip_v = False

    @staticmethod
    def is_available() -> bool:
        return CV2_AVAILABLE

    @staticmethod
    def http_available() -> bool:
        return CV2_AVAILABLE and REQUESTS_AVAILABLE

    # ── 设备枚举（与 aruco_app._probe_camera_indices 同思路）──

    @staticmethod
    def probe_camera_indices(max_index: int = 10) -> List[int]:
        """快速探测可用摄像头索引"""
        if not CV2_AVAILABLE:
            return []
        _silence_opencv_logging()
        out: List[int] = []
        misses = 0
        for i in range(max_index):
            if _probe_index_opens(i, timeout=1.0):
                out.append(i)
                misses = 0
            else:
                misses += 1
                if i > 0 and misses >= 2:
                    break
        return out

    def enumerate_devices(
        self,
        refresh: bool = True,
        progress_callback: Optional[Callable[[int, int, str], None]] = None,
    ) -> List[Dict]:
        if not CV2_AVAILABLE:
            return []

        with self._enum_lock:
            pause_capture = (
                self._capturing
                and self._source_type == self.SOURCE_LOCAL
                and self._cap is not None
            )
            saved = None
            if pause_capture:
                saved = self._save_local_state()
                self._release_local_capture()

            try:
                devices = self._scan_devices(progress_callback)
                self._device_cache = devices
                self._pending_scan_restore = saved if pause_capture else None
                return list(devices)
            finally:
                pass

    def restore_after_scan(self):
        """扫描完成后恢复先前捕获状态"""
        saved = self._pending_scan_restore
        self._pending_scan_restore = None
        if saved and saved.get("device_index") is not None:
            self._restore_local_state(saved)

    def _scan_devices(
        self,
        progress_callback: Optional[Callable[[int, int, str], None]] = None,
    ) -> List[Dict]:
        """与 aruco_app._probe_camera_indices 相同：只测 index 能否打开"""
        devices: List[Dict] = []
        total = self._max_device_scan
        misses = 0

        if progress_callback:
            progress_callback(0, total, "正在获取设备名称...")

        pnp_names = _windows_camera_names()

        for index in range(total):
            if progress_callback:
                progress_callback(index + 1, total, f"探测摄像头 #{index}...")

            if not _probe_index_opens(index, timeout=1.2):
                misses += 1
                if index > 0 and misses >= 2:
                    break
                continue
            misses = 0

            name_idx = len(devices)
            name = pnp_names[name_idx] if name_idx < len(pnp_names) else f"摄像头 #{index}"
            devices.append({
                "index": index,
                "device_uid": str(index),
                "name": name,
            })

        return devices

    def probe_device_resolutions(self, device_index: int, backend: int = None) -> List[Dict]:
        """可选：读取当前驱动原生分辨率（不做逐项探测）"""
        if not CV2_AVAILABLE:
            return []
        cap = cv2.VideoCapture(device_index)
        if not cap.isOpened():
            return []
        try:
            _apply_aruco_capture_settings(cap, self._fps)
            size = _native_frame_size(cap)
            if size:
                w, h = size
                return [{"width": w, "height": h, "label": f"{w}x{h} (驱动原生)"}]
            return []
        finally:
            cap.release()

    def _configure_capture(self, cap, width: Optional[int], height: Optional[int]) -> Optional[Tuple[int, int]]:
        """默认走 aruco 原生模式；仅当用户指定宽高时才尝试设置"""
        if not CV2_AVAILABLE:
            return None
        _apply_aruco_capture_settings(cap, self._fps)
        if width and height:
            return _try_set_resolution(cap, int(width), int(height))
        return _native_frame_size(cap)

    @property
    def is_capturing(self) -> bool:
        return self._capturing

    @property
    def is_broadcasting(self) -> bool:
        return self._api_broadcast and self._capturing

    @property
    def api_broadcast_enabled(self) -> bool:
        return self._api_broadcast

    @property
    def source_type(self) -> Optional[str]:
        return self._source_type

    def get_status(self) -> dict:
        with self._lock:
            has_frame = self._latest_jpeg is not None
            w, h = self._frame_width, self._frame_height
        return {
            "capturing": self._capturing,
            "api_broadcast": self._api_broadcast,
            "source_type": self._source_type,
            "device_index": self._device_index,
            "http_url": self._http_url,
            "width": w or self._width,
            "height": h or self._height,
            "configured_width": self._width,
            "configured_height": self._height,
            "fps": self._fps,
            "measured_fps": round(self._measured_fps, 1),
            "jpeg_quality": self._jpeg_quality,
            "frame_count": self._frame_count,
            "has_frame": has_frame,
            "last_error": self._last_error,
            "opencv_available": CV2_AVAILABLE,
            "http_available": self.http_available(),
        }

    def configure(self, fps: Optional[int] = None, jpeg_quality: Optional[int] = None,
                  width: Optional[int] = None, height: Optional[int] = None,
                  flip_h: Optional[bool] = None, flip_v: Optional[bool] = None):
        if fps is not None:
            self._fps = max(1, min(int(fps), 60))
        if jpeg_quality is not None:
            self._jpeg_quality = max(10, min(int(jpeg_quality), 100))
        if width is not None:
            self._width = int(width) if width > 0 else None
        if height is not None:
            self._height = int(height) if height > 0 else None
        if flip_h is not None:
            self._flip_h = bool(flip_h)
        if flip_v is not None:
            self._flip_v = bool(flip_v)

    def _apply_flip(self, frame):
        if not CV2_AVAILABLE or frame is None:
            return frame
        if self._flip_h and self._flip_v:
            return cv2.flip(frame, -1)
        if self._flip_h:
            return cv2.flip(frame, 1)
        if self._flip_v:
            return cv2.flip(frame, 0)
        return frame

    def start_local(
        self,
        device_index: int = 0,
        backend: Optional[int] = None,
        width: Optional[int] = None,
        height: Optional[int] = None,
        device_uid: Optional[str] = None,
    ) -> bool:
        if not CV2_AVAILABLE:
            self._fail("opencv-python 未安装")
            return False

        self.stop_capture()

        cap = cv2.VideoCapture(device_index)
        if not cap.isOpened():
            self._fail(f"无法打开摄像头 #{device_index}")
            return False

        req_w = width if width is not None else self._width
        req_h = height if height is not None else self._height
        # 未指定分辨率 → aruco 原生模式，不 set 宽高
        if not req_w or not req_h:
            req_w, req_h = None, None

        actual = self._configure_capture(cap, req_w, req_h)
        if actual is None and _read_test_frame(cap) is None:
            cap.release()
            self._fail(f"摄像头 #{device_index} 无法读取画面")
            return False

        self._cap = cap
        self._source_type = self.SOURCE_LOCAL
        self._device_index = device_index
        self._http_url = None
        if actual:
            self._width, self._height = actual
        else:
            self._width = self._height = None

        label = f"摄像头 #{device_index}"
        if self._width and self._height:
            label += f" {self._width}x{self._height}"
        return self._start_capture_thread(label)

    def start_http(self, url: str) -> bool:
        if not self.http_available():
            self._fail("需要 opencv-python 和 requests")
            return False
        url = url.strip()
        if not url:
            self._fail("URL 不能为空")
            return False

        self.stop_capture()
        self._source_type = self.SOURCE_HTTP
        self._http_url = url
        self._device_index = None
        self._cap = None
        return self._start_capture_thread("HTTP 流")

    def _start_capture_thread(self, label: str) -> bool:
        self._capturing = True
        self._frame_count = 0
        self._measured_fps = 0.0
        self._last_error = ""
        with self._lock:
            self._latest_jpeg = None
            self._latest_frame_bgr = None
            self._frame_width = 0
            self._frame_height = 0

        self._thread = threading.Thread(target=self._capture_loop, daemon=True)
        self._thread.start()
        self.capture_changed.emit(True)
        self.status_changed.emit(f"捕获中: {label}")
        logger.info(f"Video capture started: {label}")
        return True

    def stop_capture(self):
        self._capturing = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=3)
        self._thread = None
        self._release_local_capture()

        self._source_type = None
        self._http_url = None
        self._device_index = None
        with self._lock:
            self._latest_jpeg = None
            self._latest_frame_bgr = None

        if self._api_broadcast:
            self._api_broadcast = False
            self.api_broadcast_changed.emit(False)

        self.capture_changed.emit(False)
        self.status_changed.emit("已停止")

    def set_api_broadcast(self, enabled: bool) -> bool:
        if enabled and not self._capturing:
            self._last_error = "请先开始视频捕获"
            return False
        self._api_broadcast = enabled
        self.api_broadcast_changed.emit(enabled)
        self.status_changed.emit("API 广播已开启" if enabled else "API 广播已关闭")
        return True

    def start(self, device_index: int = 0) -> bool:
        ok = self.start_local(device_index)
        if ok:
            self.set_api_broadcast(True)
        return ok

    def stop(self):
        self.set_api_broadcast(False)
        self.stop_capture()

    def get_snapshot(self) -> Optional[bytes]:
        if not self._api_broadcast:
            return None
        with self._lock:
            if self._latest_jpeg is None:
                return None
            return bytes(self._latest_jpeg)

    def iter_mjpeg(self) -> Iterator[bytes]:
        boundary = b"--frame"
        interval = 1.0 / max(self._fps, 1)
        while self._api_broadcast and self._capturing:
            jpeg = None
            with self._lock:
                if self._latest_jpeg:
                    jpeg = bytes(self._latest_jpeg)
            if jpeg:
                yield (
                    boundary + b"\r\n"
                    b"Content-Type: image/jpeg\r\n\r\n"
                    + jpeg + b"\r\n"
                )
            time.sleep(interval)

    def _fail(self, msg: str):
        self._last_error = msg
        self.status_changed.emit(msg)

    def _save_local_state(self) -> dict:
        return {
            "device_index": self._device_index,
            "width": self._width,
            "height": self._height,
            "api_broadcast": self._api_broadcast,
        }

    def _restore_local_state(self, saved: dict):
        if saved.get("device_index") is None:
            return
        self.start_local(
            saved["device_index"],
            width=saved.get("width"),
            height=saved.get("height"),
        )
        if saved.get("api_broadcast"):
            self.set_api_broadcast(True)

    def _release_local_capture(self):
        if self._cap is not None:
            try:
                self._cap.release()
            except Exception:
                pass
            self._cap = None

    def _capture_loop(self):
        if self._source_type == self.SOURCE_LOCAL:
            self._loop_local()
        elif self._source_type == self.SOURCE_HTTP:
            self._loop_http()

    def _loop_local(self):
        # 帧率：优先用驱动报告值（同 aruco start_camera）
        fps = self._fps
        if self._cap is not None:
            try:
                drv = float(self._cap.get(cv2.CAP_PROP_FPS))
                if drv > 0:
                    fps = min(drv, 60.0)
            except Exception:
                pass
        interval = 1.0 / max(fps, 1)
        encode_params = [cv2.IMWRITE_JPEG_QUALITY, self._jpeg_quality]
        fps_timer = time.monotonic()
        fps_frames = 0

        while self._capturing and self._cap is not None:
            loop_start = time.monotonic()
            try:
                ret, frame = self._cap.read()
            except Exception as e:
                self._last_error = str(e)[:80]
                time.sleep(0.1)
                continue

            if not ret or not _is_valid_video_frame(frame):
                time.sleep(0.05)
                continue

            self._publish_frame(frame, encode_params)
            fps_frames += 1
            elapsed_total = time.monotonic() - fps_timer
            if elapsed_total >= 1.0:
                self._measured_fps = fps_frames / elapsed_total
                fps_frames = 0
                fps_timer = time.monotonic()

            sleep_time = interval - (time.monotonic() - loop_start)
            if sleep_time > 0:
                time.sleep(sleep_time)

        self._release_local_capture()

    def _loop_http(self):
        encode_params = [cv2.IMWRITE_JPEG_QUALITY, self._jpeg_quality]
        fps_timer = time.monotonic()
        fps_frames = 0

        try:
            session = requests.Session()
            response = session.get(self._http_url, stream=True, timeout=10)
            if response.status_code != 200:
                self._fail(f"HTTP {response.status_code}")
                self._capturing = False
                self.capture_changed.emit(False)
                return

            buffer = b""
            for chunk in response.iter_content(chunk_size=4096):
                if not self._capturing:
                    break
                buffer += chunk
                start = buffer.find(b"\xff\xd8")
                end = buffer.find(b"\xff\xd9", start + 2) if start != -1 else -1
                if start != -1 and end != -1 and end > start:
                    jpg_data = buffer[start:end + 2]
                    buffer = buffer[end + 2:]
                    frame = cv2.imdecode(
                        np.frombuffer(jpg_data, dtype=np.uint8), cv2.IMREAD_COLOR
                    )
                    if frame is not None:
                        self._publish_frame(frame, encode_params)
                        fps_frames += 1
                        elapsed_total = time.monotonic() - fps_timer
                        if elapsed_total >= 1.0:
                            self._measured_fps = fps_frames / elapsed_total
                            fps_frames = 0
                            fps_timer = time.monotonic()
        except Exception as e:
            self._fail(f"HTTP 错误: {str(e)[:40]}")
        finally:
            if self._capturing:
                self._capturing = False
                self.capture_changed.emit(False)

    def _publish_frame(self, frame, encode_params):
        frame = self._apply_flip(frame)
        ok, jpeg = cv2.imencode(".jpg", frame, encode_params)
        if not ok:
            return
        h, w = frame.shape[:2]
        jpeg_bytes = jpeg.tobytes()
        with self._lock:
            self._latest_frame_bgr = frame
            self._latest_jpeg = jpeg_bytes
            self._frame_width = w
            self._frame_height = h
            self._frame_count += 1
        self.frame_ready.emit(frame)


CameraBroadcaster = VideoStreamBroadcaster
