"""串口通信核心模块 - 封装 pyserial 操作，使用 Qt 信号槽与 UI 通信"""

import threading

from PyQt5.QtCore import QThread
import serial
import serial.tools.list_ports
from serial_assistant.channel.base_channel import DataChannel


class SerialWorker(DataChannel):
    """串口工作线程，在后台线程中处理串口收发，避免阻塞 UI

    线程安全策略：
    - _write_lock: 仅保护 write 操作，防止多线程并发写
    - read_loop: 独占读取，无需锁（只有 reader 线程访问 read 相关 API）
    - is_open: 依赖 Python GIL 的原子性，不加锁
    - close: 先设 _running=False 通知 reader 退出，再安全关闭 serial
    """

    def __init__(self):
        super().__init__()
        self._serial: serial.Serial | None = None
        self._running = False
        self._write_lock = threading.Lock()

    def is_open(self) -> bool:
        return self._serial is not None and self._serial.is_open

    def open_channel(self, port: str, baudrate: int, data_bits: int,
                     stop_bits: float, parity: str) -> bool:
        """打开串口，返回是否成功"""
        try:
            stop_bits_map = {1.0: serial.STOPBITS_ONE,
                             1.5: serial.STOPBITS_ONE_POINT_FIVE,
                             2.0: serial.STOPBITS_TWO}
            parity_map = {"无": serial.PARITY_NONE,
                          "奇": serial.PARITY_ODD,
                          "偶": serial.PARITY_EVEN}

            self._serial = serial.Serial(
                port=port,
                baudrate=baudrate,
                bytesize=data_bits,
                stopbits=stop_bits_map.get(stop_bits, serial.STOPBITS_ONE),
                parity=parity_map.get(parity, serial.PARITY_NONE),
                timeout=0.05,
            )
            self._running = True
            return True
        except serial.SerialException as e:
            self.error_occurred.emit(f"串口打开失败: {e}")
            return False

    def close_channel(self):
        """关闭串口（先停止读取循环，再关闭端口）"""
        self._running = False
        if self._serial and self._serial.is_open:
            try:
                self._serial.cancel_read()
            except Exception:
                pass
            try:
                self._serial.close()
            except Exception:
                pass
        self._serial = None

    def send_data(self, data: bytes) -> bool:
        """发送数据（线程安全，可从任意线程调用）"""
        with self._write_lock:
            if self._serial and self._serial.is_open:
                try:
                    self._serial.write(data)
                except serial.SerialException as e:
                    self.error_occurred.emit(f"发送失败: {e}")
                    self.closed_unexpected.emit()
                    return False
            return True
        return False

    def read_loop(self):
        """后台读取循环，由 QThread 调用

        无需加锁：只有本线程读取 serial，write 操作由 _write_lock 保护互不干扰。
        pyserial 的 Serial 对象在 timeout 模式下 read/write 可安全并发。
        """
        while self._running:
            try:
                if self._serial is None or not self._serial.is_open:
                    break
                waiting = self._serial.in_waiting
                if waiting > 0:
                    data = self._serial.read(waiting)
                    if data:
                        self.data_received.emit(data)
                else:
                    QThread.msleep(5)
            except serial.SerialException:
                self.closed_unexpected.emit()
                break
            except Exception:
                break


def get_available_ports() -> list[str]:
    """获取当前可用的串口列表"""
    ports = serial.tools.list_ports.comports()
    return [p.device for p in sorted(ports, key=lambda p: p.device)]
