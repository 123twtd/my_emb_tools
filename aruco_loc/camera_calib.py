"""棋盘格相机标定 - 参考 cameracalib/classboard.py"""

from __future__ import annotations

import os
from typing import List, Optional, Tuple

import numpy as np

CV2_AVAILABLE = False
try:
    import cv2
    CV2_AVAILABLE = True
except ImportError:
    cv2 = None  # type: ignore

DEFAULT_BOARD_COLS = 9
DEFAULT_BOARD_ROWS = 6
DEFAULT_SQUARE_MM = 25.0
MIN_VALID_FRAMES = 5
TARGET_CAPTURE_FRAMES = 15


def default_npz_path(project_root: str) -> str:
    return os.path.join(project_root, "config", "camera_calibration.npz")


def default_undistort_dict() -> dict:
    return {
        "enabled": False,
        "npz_path": "config/camera_calibration.npz",
        "camera_matrix": [
            [800.0, 0.0, 320.0],
            [0.0, 800.0, 240.0],
            [0.0, 0.0, 1.0],
        ],
        "dist_coeffs": [0.0, 0.0, 0.0, 0.0, 0.0],
    }


def delete_npz_file(npz_path: str) -> bool:
    if npz_path and os.path.isfile(npz_path):
        try:
            os.remove(npz_path)
            return True
        except OSError:
            return False
    return False


def load_npz(
    npz_path: str,
) -> Optional[Tuple[np.ndarray, np.ndarray, int, int]]:
    """返回 (mtx, dist, image_width, image_height)；旧 NPZ 无尺寸时宽高为 0"""
    if not npz_path or not os.path.isfile(npz_path):
        return None
    try:
        data = np.load(npz_path)
        mtx = np.array(data["mtx"], dtype=np.float64)
        dist = np.array(data["dist"], dtype=np.float64).reshape(-1)
        w = int(data["image_width"]) if "image_width" in data else 0
        h = int(data["image_height"]) if "image_height" in data else 0
        return mtx, dist, w, h
    except Exception:
        return None


def save_npz(
    npz_path: str,
    mtx: np.ndarray,
    dist: np.ndarray,
    image_size: Optional[Tuple[int, int]] = None,
    rvecs=None,
    tvecs=None,
) -> None:
    os.makedirs(os.path.dirname(npz_path) or ".", exist_ok=True)
    kwargs = {"mtx": mtx, "dist": dist}
    if image_size is not None:
        kwargs["image_width"] = int(image_size[0])
        kwargs["image_height"] = int(image_size[1])
    if rvecs is not None:
        kwargs["rvecs"] = rvecs
    if tvecs is not None:
        kwargs["tvecs"] = tvecs
    np.savez(npz_path, **kwargs)


def infer_calib_image_size(
    mtx: np.ndarray,
    stored_width: int = 0,
    stored_height: int = 0,
) -> Tuple[int, int]:
    if stored_width > 0 and stored_height > 0:
        return int(stored_width), int(stored_height)
    cx = float(mtx[0, 2])
    cy = float(mtx[1, 2])
    return max(int(round(cx * 2)), 1), max(int(round(cy * 2)), 1)


def scale_camera_matrix(
    mtx: np.ndarray,
    from_size: Tuple[int, int],
    to_size: Tuple[int, int],
) -> np.ndarray:
    fw, fh = int(from_size[0]), int(from_size[1])
    tw, th = int(to_size[0]), int(to_size[1])
    if fw == tw and fh == th:
        return np.array(mtx, dtype=np.float64, copy=True)
    sx = tw / fw
    sy = th / fh
    out = np.array(mtx, dtype=np.float64, copy=True)
    out[0, 0] *= sx
    out[1, 1] *= sy
    out[0, 2] *= sx
    out[1, 2] *= sy
    return out


def matrix_to_yaml_list(mtx: np.ndarray) -> list:
    m = np.array(mtx, dtype=float)
    return [[float(m[i, j]) for j in range(3)] for i in range(3)]


def dist_to_yaml_list(dist: np.ndarray) -> list:
    d = np.array(dist, dtype=float).reshape(-1)
    out = [float(x) for x in d[:5]]
    while len(out) < 5:
        out.append(0.0)
    return out


def build_object_points(cols: int, rows: int, square_mm: float) -> np.ndarray:
    """棋盘格内角点世界坐标 (Z=0)，单位 mm"""
    objp = np.zeros((cols * rows, 3), np.float32)
    objp[:, :2] = np.mgrid[0:cols, 0:rows].T.reshape(-1, 2)
    objp *= float(square_mm)
    return objp


def find_chessboard(
    gray: np.ndarray,
    board_size: Tuple[int, int],
    *,
    fast: bool = False,
):
    """检测棋盘格内角点。fast=True 时用于实时预览，略降精度换速度。"""
    if not CV2_AVAILABLE:
        return False, None
    cols, rows = int(board_size[0]), int(board_size[1])
    size = (cols, rows)

    if not fast and hasattr(cv2, "findChessboardCornersSB"):
        try:
            ret, corners = cv2.findChessboardCornersSB(gray, size)
            if ret and corners is not None:
                return True, corners
        except Exception:
            pass

    flags = cv2.CALIB_CB_ADAPTIVE_THRESH + cv2.CALIB_CB_NORMALIZE_IMAGE
    if fast:
        flags |= cv2.CALIB_CB_FAST_CHECK
    ret, corners = cv2.findChessboardCorners(gray, size, flags)
    if not ret or corners is None:
        return False, None
    criteria = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 30, 0.001)
    corners = cv2.cornerSubPix(gray, corners, (11, 11), (-1, -1), criteria)
    return True, corners


def calibrate_from_corners(
    objpoints: List[np.ndarray],
    imgpoints: List[np.ndarray],
    image_size: Tuple[int, int],
) -> Tuple[float, np.ndarray, np.ndarray]:
    if not CV2_AVAILABLE:
        raise RuntimeError("opencv-python 未安装")
    if len(objpoints) < MIN_VALID_FRAMES:
        raise RuntimeError(f"有效帧不足，至少需要 {MIN_VALID_FRAMES} 张检测到棋盘格的图像")
    rms, mtx, dist, _rvecs, _tvecs = cv2.calibrateCamera(
        objpoints, imgpoints, image_size, None, None
    )
    return float(rms), mtx, dist
