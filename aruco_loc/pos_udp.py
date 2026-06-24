# -*- coding: utf-8 -*-
"""UDP payload builder and sender (compatible with pos_sender_test_linear.py)."""
import json
import socket
import time
from typing import Iterable, List, Tuple

PayloadPos = Tuple[float, float, float]
# Euler tuple is (roll_deg, pitch_deg, yaw_deg); matches typical robotics JSON usage.
PayloadEuler = Tuple[float, float, float]
Target = Tuple[str, int]


def build_payload(
    seq: int,
    pos: PayloadPos,
    euler: PayloadEuler,
    holdover: bool = False,
) -> bytes:
    # 构建机器人位姿数据字典
    data = {
        "type": "robot_position",
        "pos": [round(pos[0], 2), round(pos[1], 2), round(pos[2], 2)],  # 位置坐标保留2位小数
        "euler": [round(euler[0], 2), round(euler[1], 2), round(euler[2], 2)],  # 欧拉角保留2位小数
        "seq": seq,  # 序列号
        "timestamp": time.time(),  # 当前时间戳
        "holdover": holdover,  # 保持状态标志
    }
    # 序列化为JSON并编码为UTF-8字节流
    return json.dumps(data, sort_keys=True).encode("utf-8")


def parse_targets(
    host1: str,
    port1: int,
    host2: str,
    port2: int,
) -> List[Target]:
    out: List[Target] = []
    h1 = (host1 or "").strip()
    h2 = (host2 or "").strip()
    if h1:
        out.append((h1, int(port1)))
    if h2:
        out.append((h2, int(port2)))
    return out


def send_to_targets(sock: socket.socket, payload: bytes, targets: Iterable[Target]) -> None:
    for host, port in targets:
        sock.sendto(payload, (host, int(port)))
