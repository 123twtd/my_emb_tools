# -*- coding: utf-8 -*-
"""Multi-threaded video capture with frame-drop for real-time performance.

Supports three source types:
  - Camera index (int) or video file path (str) -> cv2.VideoCapture
  - WiFi API URL (str starting with http/rtsp) -> cv2.VideoCapture with network stream
  - Serial port (dict with 'port' and 'baud' keys) -> serial JPEG frame reader
"""
from __future__ import annotations

import queue
import time
from typing import Optional, Union

import cv2
import numpy as np
from PyQt5.QtCore import QThread, pyqtSignal


class VideoCaptureThread(QThread):
    """Background thread that continuously captures frames from a VideoCapture.

    Uses a small frame queue (maxsize=2) so that slow consumers automatically
    drop old frames — only the latest frame is kept.
    """

    # Emits the latest BGR frame (numpy ndarray)
    frame_ready = pyqtSignal(np.ndarray)
    # Emits error message string
    error_occurred = pyqtSignal(str)
    # Emits when capture starts/stops
    status_changed = pyqtSignal(str)

    def __init__(
        self,
        source: Union[int, str, dict],
        fps_hint: float = 30.0,
        buffer_size: int = 2,
        parent=None,
    ):
        """
        Args:
            source: Camera index (int), file/URL string (str), or
                    serial config dict {'port': str, 'baud': int}.
            fps_hint: Target frame rate hint.
            buffer_size: Frame queue max size.
            parent: Parent QObject.
        """
        super().__init__(parent)
        self.source = source
        self.fps_hint = float(fps_hint)
        self._queue: queue.Queue[np.ndarray] = queue.Queue(maxsize=buffer_size)
        self._running = False
        self._cap: Optional[cv2.VideoCapture] = None
        self._serial = None
        self._actual_fps = 0.0

    def actual_fps(self) -> float:
        return self._actual_fps

    @staticmethod
    def _is_serial_source(source) -> bool:
        return isinstance(source, dict) and "port" in source

    @staticmethod
    def _is_url_source(source) -> bool:
        return isinstance(source, str) and (
            source.startswith("http://")
            or source.startswith("https://")
            or source.startswith("rtsp://")
            or source.startswith("rtp://")
        )

    def _open_capture(self) -> bool:
        """Open the VideoCapture and apply best-effort settings."""
        self._cap = cv2.VideoCapture(self.source)
        if not self._cap.isOpened():
            self.error_occurred.emit(f"Failed to open capture source: {self.source}")
            return False

        # Reduce internal buffering to minimize latency
        try:
            self._cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        except Exception:
            pass

        # Try to set frame rate if it's a camera index
        if isinstance(self.source, int):
            try:
                self._cap.set(cv2.CAP_PROP_FPS, self.fps_hint)
            except Exception:
                pass

        # Read one frame to confirm
        ret, _ = self._cap.read()
        if not ret:
            self.error_occurred.emit(f"Capture opened but cannot read frames: {self.source}")
            self._cap.release()
            self._cap = None
            return False

        return True

    def _open_serial(self) -> bool:
        """Open a serial port for JPEG frame streaming."""
        try:
            import serial
        except ImportError:
            self.error_occurred.emit(
                "pyserial not installed. Install with: pip install pyserial"
            )
            return False

        port = self.source["port"]
        baud = int(self.source.get("baud", 115200))
        try:
            self._serial = serial.Serial(port=port, baudrate=baud, timeout=0.1)
        except Exception as e:
            self.error_occurred.emit(f"Failed to open serial port {port}: {e}")
            return False
        return True

    def _read_serial_frame(self) -> Optional[np.ndarray]:
        """Read one JPEG frame from serial stream.

        Protocol: find JPEG SOI (0xFFD8) and EOI (0xFFD9) markers,
        extract the bytes between them, and decode.
        """
        if self._serial is None:
            return None

        buf = bytearray()
        # Find SOI marker
        while self._running:
            b = self._serial.read(1)
            if not b:
                continue
            buf.append(b[0])
            if len(buf) >= 2 and buf[-2] == 0xFF and buf[-1] == 0xD8:
                break

        # Read until EOI marker
        while self._running:
            b = self._serial.read(1)
            if not b:
                continue
            buf.append(b[0])
            if len(buf) >= 2 and buf[-2] == 0xFF and buf[-1] == 0xD9:
                break

        if not buf:
            return None

        frame_arr = np.frombuffer(bytes(buf), dtype=np.uint8)
        frame = cv2.imdecode(frame_arr, cv2.IMREAD_COLOR)
        return frame

    def _apply_banding_mitigation(self) -> None:
        """Best-effort reduction of horizontal banding under mains-frequency lights."""
        if self._cap is None or not self._cap.isOpened():
            return
        try:
            self._cap.set(cv2.CAP_PROP_AUTO_EXPOSURE, 0.25)
        except Exception:
            pass

    def run(self) -> None:
        """Main thread loop: read frames and push to queue."""
        is_serial = self._is_serial_source(self.source)

        if is_serial:
            if not self._open_serial():
                return
        else:
            if not self._open_capture():
                return
            self._apply_banding_mitigation()

        self._running = True
        self.status_changed.emit("started")

        frame_interval = 1.0 / max(self.fps_hint, 1.0)
        frame_count = 0
        fps_t0 = time.perf_counter()

        while self._running:
            if is_serial:
                frame = self._read_serial_frame()
                ret = frame is not None
            else:
                if self._cap is None:
                    break
                ret, frame = self._cap.read()

            if not ret:
                if is_serial:
                    # Serial read error — brief pause and retry
                    time.sleep(0.01)
                    continue
                # End of stream (video file) or read error
                if isinstance(self.source, str):
                    self.status_changed.emit("finished")
                else:
                    self.error_occurred.emit("Capture read error")
                break

            now = time.perf_counter()
            frame_count += 1

            # Calculate actual FPS every second
            if now - fps_t0 >= 1.0:
                self._actual_fps = frame_count / (now - fps_t0)
                frame_count = 0
                fps_t0 = now

            # Push to queue — drop old frame if queue is full (keeps latest)
            try:
                self._queue.put_nowait(frame)
            except queue.Full:
                try:
                    self._queue.get_nowait()
                    self._queue.put_nowait(frame)
                except queue.Empty:
                    pass

            # Emit the frame to main thread (non-blocking signal)
            self.frame_ready.emit(frame)

            # Throttle to avoid burning CPU if capture is faster than needed
            elapsed = time.perf_counter() - now
            if elapsed < frame_interval:
                time.sleep(frame_interval - elapsed)

        self._running = False
        if self._serial is not None:
            try:
                self._serial.close()
            except Exception:
                pass
            self._serial = None
        if self._cap is not None:
            self._cap.release()
            self._cap = None
        self.status_changed.emit("stopped")

    def stop(self) -> None:
        """Request thread stop and wait for it to finish."""
        self._running = False
        # Drain queue to unblock any pending get
        while not self._queue.empty():
            try:
                self._queue.get_nowait()
            except queue.Empty:
                break
        self.wait(2000)  # Wait up to 2 seconds

    def get_latest_frame(self) -> Optional[np.ndarray]:
        """Non-blocking peek at the latest frame in queue."""
        latest: Optional[np.ndarray] = None
        while not self._queue.empty():
            try:
                latest = self._queue.get_nowait()
            except queue.Empty:
                break
        return latest
