"""镜头去畸变 - 从 NPZ 或 YAML 加载标定系数"""

from __future__ import annotations

import os
from typing import Any, Dict, Optional, Tuple

import numpy as np

from aruco_loc.camera_calib import (
    infer_calib_image_size,
    load_npz,
    scale_camera_matrix,
)

CV2_AVAILABLE = False
try:
    import cv2
    CV2_AVAILABLE = True
except ImportError:
    cv2 = None  # type: ignore

# alpha=0：裁掉无效边缘，避免 alpha=1 时大面积黑色空洞
_UNDISTORT_ALPHA = 0.0


def _as_matrix3(raw) -> Optional[np.ndarray]:
    if raw is None:
        return None
    try:
        m = np.array(raw, dtype=np.float64)
        if m.shape == (3, 3):
            return m
    except Exception:
        pass
    return None


def _as_dist(raw) -> Optional[np.ndarray]:
    if raw is None:
        return None
    try:
        d = np.array(raw, dtype=np.float64).reshape(-1)
        if d.size >= 4:
            return d
    except Exception:
        pass
    return None


class LensUndistort:
    """按 camera_matrix / dist_coeffs 对帧做 undistort"""

    def __init__(self):
        self.enabled = False
        self._camera_matrix: Optional[np.ndarray] = None
        self._dist_coeffs: Optional[np.ndarray] = None
        self._calib_size: Tuple[int, int] = (0, 0)
        self._npz_path: Optional[str] = None
        self._map1 = None
        self._map2 = None
        self._map_size: Optional[Tuple[int, int]] = None
        self._calib_loaded = False

    @property
    def calib_loaded(self) -> bool:
        return self._calib_loaded

    @property
    def npz_path(self) -> Optional[str]:
        return self._npz_path

    def load_from_dict(
        self,
        data: Optional[Dict[str, Any]],
        project_root: Optional[str] = None,
    ) -> None:
        data = data or {}
        self.enabled = bool(data.get("enabled", False))
        self._npz_path = None
        self._camera_matrix = None
        self._dist_coeffs = None
        self._calib_size = (0, 0)
        self._calib_loaded = False

        stored_w = int(data.get("calib_width") or 0)
        stored_h = int(data.get("calib_height") or 0)

        npz_rel = data.get("npz_path")
        if npz_rel and project_root:
            npz_abs = npz_rel if os.path.isabs(npz_rel) else os.path.join(project_root, npz_rel)
            loaded = load_npz(npz_abs)
            if loaded is not None:
                mtx, dist, nw, nh = loaded
                self._camera_matrix = mtx
                self._dist_coeffs = dist
                self._calib_size = infer_calib_image_size(
                    mtx, nw or stored_w, nh or stored_h
                )
                self._npz_path = npz_abs
                self._calib_loaded = True
                self._invalidate_maps()
                return

        self._camera_matrix = _as_matrix3(data.get("camera_matrix"))
        self._dist_coeffs = _as_dist(data.get("dist_coeffs"))
        if self._camera_matrix is not None:
            self._calib_size = infer_calib_image_size(
                self._camera_matrix, stored_w, stored_h
            )
        self._calib_loaded = (
            self._camera_matrix is not None and self._dist_coeffs is not None
        )
        self._invalidate_maps()

    def set_enabled(self, enabled: bool) -> None:
        self.enabled = bool(enabled)

    def status_text(self) -> str:
        if not self._calib_loaded:
            return "未配置标定系数"
        src = "NPZ" if self._npz_path else "YAML"
        if self.enabled:
            return f"已开启 ({src})"
        return f"已关闭（{src} 已加载）"

    def _invalidate_maps(self) -> None:
        self._map1 = None
        self._map2 = None
        self._map_size = None

    def _matrix_for_frame(self, width: int, height: int) -> np.ndarray:
        assert self._camera_matrix is not None
        cw, ch = self._calib_size
        if cw > 0 and ch > 0 and (cw != width or ch != height):
            return scale_camera_matrix(
                self._camera_matrix, (cw, ch), (width, height)
            )
        return self._camera_matrix

    def _ensure_maps(self, width: int, height: int) -> bool:
        if not CV2_AVAILABLE or not self._calib_loaded:
            return False
        size = (int(width), int(height))
        if self._map_size == size and self._map1 is not None:
            return True
        try:
            mtx = self._matrix_for_frame(width, height)
            dist = self._dist_coeffs
            new_mtx, _roi = cv2.getOptimalNewCameraMatrix(
                mtx, dist, size, _UNDISTORT_ALPHA, size
            )
            self._map1, self._map2 = cv2.initUndistortRectifyMap(
                mtx,
                dist,
                None,
                new_mtx,
                size,
                cv2.CV_16SC2,
            )
            self._map_size = size
            return True
        except Exception:
            self._invalidate_maps()
            return False

    def apply(self, frame):
        if not self.enabled or not self._calib_loaded or frame is None:
            return frame
        if not CV2_AVAILABLE:
            return frame
        h, w = frame.shape[:2]
        if not self._ensure_maps(w, h):
            return frame
        return cv2.remap(
            frame, self._map1, self._map2, cv2.INTER_LINEAR,
            borderMode=cv2.BORDER_CONSTANT,
        )
