"""去畸变参数配置集（命名、摄像头绑定、NPZ）"""

from __future__ import annotations

import copy
import os
import re
from typing import Any, Dict, List, Optional, Tuple

from aruco_loc.camera_calib import (
    default_npz_path,
    delete_npz_file,
    load_npz,
    matrix_to_yaml_list,
    dist_to_yaml_list,
)

DEFAULT_PROFILE_ID = "default"
PLACEHOLDER_MATRIX = [
    [800.0, 0.0, 320.0],
    [0.0, 800.0, 240.0],
    [0.0, 0.0, 1.0],
]
PLACEHOLDER_DIST = [0.0, 0.0, 0.0, 0.0, 0.0]


def _slug(name: str) -> str:
    s = re.sub(r"[^\w\u4e00-\u9fff-]+", "_", (name or "").strip())
    return s.strip("_") or "profile"


def default_profile_entry() -> Dict[str, Any]:
    return {
        "name": "默认（无标定）",
        "npz_path": None,
        "camera_matrix": copy.deepcopy(PLACEHOLDER_MATRIX),
        "dist_coeffs": copy.deepcopy(PLACEHOLDER_DIST),
        "bind_camera_uid": None,
        "bind_camera_name": None,
        "rms": None,
        "board_cols": 9,
        "board_rows": 6,
        "square_mm": 25.0,
    }


def default_undistort_section() -> Dict[str, Any]:
    return {
        "enabled": False,
        "use_mode": "auto",
        "manual_profile_id": DEFAULT_PROFILE_ID,
        "profiles": {
            DEFAULT_PROFILE_ID: default_profile_entry(),
        },
    }


def migrate_undistort_section(ud: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """将旧版 flat undistort 配置迁移为 profiles 结构"""
    if not ud:
        return default_undistort_section()
    if "profiles" in ud and isinstance(ud.get("profiles"), dict):
        out = default_undistort_section()
        out.update({k: v for k, v in ud.items() if k != "profiles"})
        out["profiles"] = copy.deepcopy(ud["profiles"])
        if DEFAULT_PROFILE_ID not in out["profiles"]:
            out["profiles"][DEFAULT_PROFILE_ID] = default_profile_entry()
        return out

    prof = default_profile_entry()
    if ud.get("npz_path"):
        prof["npz_path"] = ud["npz_path"]
    if ud.get("camera_matrix"):
        prof["camera_matrix"] = ud["camera_matrix"]
    if ud.get("dist_coeffs"):
        prof["dist_coeffs"] = ud["dist_coeffs"]
    return {
        "enabled": bool(ud.get("enabled", False)),
        "use_mode": ud.get("use_mode", "auto"),
        "manual_profile_id": ud.get("manual_profile_id", DEFAULT_PROFILE_ID),
        "profiles": {DEFAULT_PROFILE_ID: prof},
    }


def list_profiles(ud: Dict[str, Any]) -> List[Tuple[str, Dict[str, Any]]]:
    ud = migrate_undistort_section(ud)
    profiles = ud.get("profiles") or {}
    items = list(profiles.items())
    items.sort(key=lambda x: (0 if x[0] == DEFAULT_PROFILE_ID else 1, x[0]))
    return items


def profile_npz_abs(project_root: str, npz_rel: Optional[str]) -> Optional[str]:
    if not npz_rel:
        return None
    return npz_rel if os.path.isabs(npz_rel) else os.path.join(project_root, npz_rel)


def profile_has_calib(project_root: str, prof: Dict[str, Any]) -> bool:
    npz = profile_npz_abs(project_root, prof.get("npz_path"))
    if npz and os.path.isfile(npz):
        return load_npz(npz) is not None
    mat = prof.get("camera_matrix")
    dist = prof.get("dist_coeffs")
    if not mat or not dist:
        return False
    if prof.get("id") == DEFAULT_PROFILE_ID or prof.get("name", "").startswith("默认"):
        return npz is not None and os.path.isfile(npz)
    return True


def resolve_profile(
    ud: Dict[str, Any],
    project_root: str,
    device_uid: Optional[str] = None,
    device_name: Optional[str] = None,
) -> Tuple[str, Dict[str, Any], str]:
    """
    解析当前应使用的 profile。
    返回 (profile_id, profile_dict, status_hint)
    """
    ud = migrate_undistort_section(ud)
    profiles: Dict[str, Dict] = ud.get("profiles") or {}

    use_mode = ud.get("use_mode", "auto")
    if use_mode == "manual":
        pid = ud.get("manual_profile_id") or DEFAULT_PROFILE_ID
        prof = profiles.get(pid) or profiles.get(DEFAULT_PROFILE_ID) or default_profile_entry()
        label = prof.get("name") or pid
        return pid, prof, f"手动: {label}"

    uid = str(device_uid) if device_uid is not None else None
    name = (device_name or "").strip()

    for pid, prof in profiles.items():
        if pid == DEFAULT_PROFILE_ID:
            continue
        bind_uid = prof.get("bind_camera_uid")
        bind_name = (prof.get("bind_camera_name") or "").strip()
        if bind_uid is not None and uid is not None and str(bind_uid) == uid:
            label = prof.get("name") or pid
            return pid, prof, f"已绑定摄像头 → {label}"
        if bind_name and name and bind_name == name:
            label = prof.get("name") or pid
            return pid, prof, f"已绑定摄像头 → {label}"

    prof = profiles.get(DEFAULT_PROFILE_ID) or default_profile_entry()
    return DEFAULT_PROFILE_ID, prof, "默认参数（未绑定匹配）"


def profile_status_line(
    profile_id: str,
    prof: Dict[str, Any],
    project_root: str,
    hint: str,
) -> str:
    name = prof.get("name") or profile_id
    has = profile_has_calib(project_root, prof)
    bind = prof.get("bind_camera_name") or prof.get("bind_camera_uid")
    bind_txt = f"绑定: {bind}" if bind else "未绑定摄像头"
    calib_txt = "已标定" if has else "无有效 NPZ"
    rms = prof.get("rms")
    rms_txt = f" RMS={rms:.3f}px" if isinstance(rms, (int, float)) else ""
    return f"{hint} | 【{name}】{calib_txt}{rms_txt} | {bind_txt}"


def load_profile_into_undistort_dict(
    prof: Dict[str, Any],
    project_root: str,
    enabled: bool,
) -> Dict[str, Any]:
    """供 LensUndistort.load_from_dict 使用的扁平结构"""
    npz_rel = prof.get("npz_path")
    out = {
        "enabled": enabled,
        "npz_path": npz_rel,
        "camera_matrix": prof.get("camera_matrix") or PLACEHOLDER_MATRIX,
        "dist_coeffs": prof.get("dist_coeffs") or PLACEHOLDER_DIST,
    }
    npz_abs = profile_npz_abs(project_root, prof.get("npz_path"))
    if npz_abs and os.path.isfile(npz_abs):
        loaded = load_npz(npz_abs)
        if loaded:
            mtx, dist, nw, nh = loaded
            out["camera_matrix"] = matrix_to_yaml_list(mtx)
            out["dist_coeffs"] = dist_to_yaml_list(dist)
            if nw > 0 and nh > 0:
                out["calib_width"] = nw
                out["calib_height"] = nh
    cw = prof.get("calib_width")
    ch = prof.get("calib_height")
    if cw and ch:
        out["calib_width"] = int(cw)
        out["calib_height"] = int(ch)
    return out


def npz_path_for_profile(project_root: str, profile_id: str) -> str:
    folder = os.path.join(project_root, "config", "calib")
    os.makedirs(folder, exist_ok=True)
    return os.path.join(folder, f"{profile_id}.npz")


def save_profile_calibration(
    ud: Dict[str, Any],
    project_root: str,
    profile_id: str,
    profile_name: str,
    mtx,
    dist,
    rms: float,
    bind_camera_uid: Optional[str],
    bind_camera_name: Optional[str],
    board_cols: int,
    board_rows: int,
    square_mm: float,
    image_size: Optional[Tuple[int, int]] = None,
) -> Dict[str, Any]:
    from aruco_loc.camera_calib import save_npz

    ud = migrate_undistort_section(ud)
    profiles = ud.setdefault("profiles", {})
    npz_abs = npz_path_for_profile(project_root, profile_id)
    save_npz(npz_abs, mtx, dist, image_size=image_size)
    npz_rel = os.path.relpath(npz_abs, project_root).replace("\\", "/")

    entry = {
        "name": profile_name,
        "npz_path": npz_rel,
        "camera_matrix": matrix_to_yaml_list(mtx),
        "dist_coeffs": dist_to_yaml_list(dist),
        "bind_camera_uid": str(bind_camera_uid) if bind_camera_uid is not None else None,
        "bind_camera_name": bind_camera_name or None,
        "rms": float(rms),
        "board_cols": int(board_cols),
        "board_rows": int(board_rows),
        "square_mm": float(square_mm),
    }
    if image_size is not None:
        entry["calib_width"] = int(image_size[0])
        entry["calib_height"] = int(image_size[1])
    profiles[profile_id] = entry
    ud["manual_profile_id"] = profile_id
    return ud


def delete_profile(ud: Dict[str, Any], project_root: str, profile_id: str) -> Dict[str, Any]:
    if profile_id == DEFAULT_PROFILE_ID:
        raise ValueError("不能删除默认配置")
    ud = migrate_undistort_section(ud)
    profiles = ud.get("profiles") or {}
    prof = profiles.pop(profile_id, None)
    if prof:
        npz_abs = profile_npz_abs(project_root, prof.get("npz_path"))
        if npz_abs:
            delete_npz_file(npz_abs)
    if ud.get("manual_profile_id") == profile_id:
        ud["manual_profile_id"] = DEFAULT_PROFILE_ID
    ud["profiles"] = profiles
    return ud


def restore_defaults(ud: Dict[str, Any], project_root: str) -> Dict[str, Any]:
    ud = migrate_undistort_section(ud)
    for pid, prof in list((ud.get("profiles") or {}).items()):
        if pid == DEFAULT_PROFILE_ID:
            continue
        npz_abs = profile_npz_abs(project_root, prof.get("npz_path"))
        if npz_abs:
            delete_npz_file(npz_abs)
    legacy = default_npz_path(project_root)
    delete_npz_file(legacy)
    return default_undistort_section()
