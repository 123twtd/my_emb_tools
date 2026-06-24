"""
Configuration module for ArUco coordinate system.
Loads YAML with fallback paths; supports rebuild from dict and serialization.
"""
from pathlib import Path
from typing import Any, Dict, Optional, Union

import cv2
import numpy as np
import yaml

# Built-in defaults (used when restoring defaults in UI). Mirrors a typical config.yaml.
DEFAULT_CONFIG_DATA: Dict[str, Any] = {
    "aruco": {
        "dict_type": "DICT_4X4_50",
        "marker_size": 0.05,
    },
    "aruco_params": {
        "minMarkerPerimeterRate": 0.02,
        "adaptiveThreshWinSizeMin": 3,
        "adaptiveThreshWinSizeMax": 23,
        "adaptiveThreshWinSizeStep": 10,
        "cornerRefinementMethod": "NONE",
    },
    "world_coordinates": {
        2: [0.0, 0.0],
        1: [100.0, 0.0],
        4: [100.0, 100.0],
        3: [0.0, 100.0],
    },
    "vehicle_id": 0,
    "car_id": 0,
    "min_marker_count": 4,
    "ui": {"trace_window_ms": 500},
}


class Config:
    """Runtime configuration (also constructible from an in-memory dict)."""

    def __init__(
        self,
        config_file: str = "config.yaml",
        *,
        _raw_data: Optional[Dict[str, Any]] = None,
        _source_path: Optional[Path] = None,
    ):
        if _raw_data is not None:
            data = _raw_data
            self._source_path = _source_path
        else:
            path = self._resolve_config_path(config_file)
            self._source_path = path
            with open(path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)
        self._apply_parsed_data(data)

    def _apply_parsed_data(self, config_data: Dict[str, Any]) -> None:
        if not config_data:
            config_data = {}
        aruco_config = config_data.get("aruco", {}) or {}
        self.DICT_TYPE_NAME = str(aruco_config.get("dict_type", "DICT_4X4_50"))
        self.ARUCO_DICT = getattr(cv2.aruco, self.DICT_TYPE_NAME)
        self.MARKER_SIZE = float(aruco_config.get("marker_size", 0.05))
        self.ARUCO_PARAMS = dict(config_data.get("aruco_params", {}) or {})

        world_coords = config_data.get("world_coordinates", {}) or {}
        self.WORLD_COORDINATES: Dict[int, np.ndarray] = {}
        for marker_id, coords in world_coords.items():
            self.WORLD_COORDINATES[int(marker_id)] = np.array(coords, dtype=np.float32)

        self.MIN_MARKER_COUNT = int(config_data.get("min_marker_count", 4))
        ui_config = config_data.get("ui", {}) or {}
        self.TRACE_WINDOW_MS = int(ui_config.get("trace_window_ms", 500))
        self.VEHICLE_ID = int(config_data.get("vehicle_id", config_data.get("car_id", 0)))

    @staticmethod
    def _resolve_config_path(config_file: str) -> Path:
        cwd_candidate = Path.cwd() / config_file
        package_candidate = Path(__file__).resolve().parent / config_file

        for candidate in (cwd_candidate, package_candidate):
            if candidate.exists():
                return candidate

        tried = [str(cwd_candidate), str(package_candidate)]
        raise FileNotFoundError(
            "Config file not found. Tried paths: " + ", ".join(tried)
        )


def config_to_dict(cfg: Config) -> Dict[str, Any]:
    """Serialize config to a nested dict suitable for YAML."""
    wc: Dict[int, Any] = {}
    for k, v in cfg.WORLD_COORDINATES.items():
        wc[int(k)] = [float(v[0]), float(v[1])]
    return {
        "aruco": {
            "dict_type": cfg.DICT_TYPE_NAME,
            "marker_size": cfg.MARKER_SIZE,
        },
        "aruco_params": dict(cfg.ARUCO_PARAMS),
        "world_coordinates": wc,
        "vehicle_id": cfg.VEHICLE_ID,
        "car_id": cfg.VEHICLE_ID,
        "min_marker_count": cfg.MIN_MARKER_COUNT,
        "ui": {"trace_window_ms": cfg.TRACE_WINDOW_MS},
    }


def save_config_dict_to_yaml(path: Union[str, Path], data: Dict[str, Any]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        yaml.safe_dump(
            data,
            f,
            allow_unicode=True,
            sort_keys=False,
            default_flow_style=False,
        )


def load_config_from_yaml(path: Union[str, Path]) -> Config:
    path = Path(path)
    with open(path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f)
    return Config(_raw_data=raw, _source_path=path)


def load_config_from_dict(data: Dict[str, Any], source_path: Optional[Path] = None) -> Config:
    return Config(_raw_data=dict(data), _source_path=source_path)


# Global singleton (mutable reference replaced by set_config_instance).
_config_instance: Optional[Config] = None


def get_config() -> Config:
    global _config_instance
    if _config_instance is None:
        _config_instance = Config()
    return _config_instance


def set_config_instance(cfg: Config) -> None:
    global _config_instance
    _config_instance = cfg


def reset_config_singleton() -> None:
    global _config_instance
    _config_instance = None


def load_config():
    """Backward compatibility."""
    return get_config()


def __getattr__(name: str):
    cfg = get_config()
    if hasattr(cfg, name):
        return getattr(cfg, name)
    raise AttributeError(f"module '{__name__}' has no attribute '{name}'")
