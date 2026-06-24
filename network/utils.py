"""网络服务通用工具 - 端口可用性检查等"""

import socket
import logging
from typing import List, Set

logger = logging.getLogger(__name__)


def get_local_lan_ip() -> str:
    """获取本机局域网 IP（用于展示给其他设备访问的地址）"""
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.connect(("8.8.8.8", 80))
        ip = sock.getsockname()[0]
        sock.close()
        return ip
    except Exception:
        return "127.0.0.1"


def local_ipv4_addresses() -> Set[str]:
    """本机可用于绑定的 IPv4 地址集合"""
    addrs = {"127.0.0.1", "0.0.0.0"}
    try:
        hostname = socket.gethostname()
        for info in socket.getaddrinfo(hostname, None, socket.AF_INET):
            addrs.add(info[4][0])
    except Exception:
        pass
    lan = get_local_lan_ip()
    if lan:
        addrs.add(lan)
    return addrs


def format_service_bind_label(host: str, port: int) -> str:
    """服务面板显示的监听地址（host:port）"""
    host = (host or "127.0.0.1").strip()
    port = int(port)
    if host in ("0.0.0.0", "", "::"):
        return f"0.0.0.0:{port}"
    return f"{host}:{port}"


def api_access_bases(bind_host: str, port: int) -> List[str]:
    """根据 API 监听配置，生成可供客户端访问的 URL 前缀列表"""
    lan = get_local_lan_ip()
    port = int(port)
    host = (bind_host or "127.0.0.1").strip()

    if host in ("0.0.0.0", "::", ""):
        bases = []
        if lan and lan != "127.0.0.1":
            bases.append(f"http://{lan}:{port}")
        bases.append(f"http://127.0.0.1:{port}")
        return bases

    if host == "127.0.0.1":
        bases = [f"http://127.0.0.1:{port}"]
        if lan and lan != "127.0.0.1":
            bases.append(f"http://{lan}:{port}  ← 局域网需将监听改为 0.0.0.0")
        return bases

    return [f"http://{host}:{port}"]


def _raise_bind_error(host: str, port: int, err: OSError) -> None:
    """将底层 bind 错误转为更易理解的提示并抛出"""
    winerr = getattr(err, "winerror", None)
    errno = getattr(err, "errno", None)
    msg = str(err)

    if host not in ("0.0.0.0", "127.0.0.1", "::") and host not in local_ipv4_addresses():
        raise OSError(
            f"监听地址 {host} 不在本机网卡上，请改为 0.0.0.0 或本机 IP（当前可用: "
            f"{', '.join(sorted(local_ipv4_addresses() - {'0.0.0.0'}))}"
        ) from err

    if winerr == 10013 or errno in (13, 10048):
        raise OSError(
            f"端口 {port} 无法绑定：可能已被占用、被系统保留，或当前地址无权限监听。"
            f"建议将监听地址改为 0.0.0.0 并更换端口（如 18000）。"
        ) from err

    if winerr == 10049 or errno == 99:
        raise OSError(
            f"监听地址 {host} 无法使用，请改为 0.0.0.0 或 127.0.0.1"
        ) from err

    raise OSError(f"无法绑定 {host}:{port} — {msg}") from err


def check_port_available(host: str, port: int) -> None:
    """
    同步检查端口是否可用（未被占用）。

    Raises:
        OSError: 端口不可用或地址无效时抛出
    """
    host = (host or "127.0.0.1").strip()
    if host in ("", "::"):
        host = "0.0.0.0"

    if host not in ("0.0.0.0", "127.0.0.1") and host not in local_ipv4_addresses():
        _raise_bind_error(host, port, OSError("address not available"))

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        sock.bind((host, port))
    except OSError as e:
        _raise_bind_error(host, port, e)
    finally:
        sock.close()
