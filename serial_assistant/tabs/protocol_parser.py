"""可配置文本协议解析器 - 用于示波器模式的数据帧解析"""


class FrameParser:
    """
    解析自定义文本协议帧。
    帧格式: header + value1 + delimiter + value2 + ... + footer
    示例: b'#123.5,456.7,789.0\\n' → [[123.5, 456.7, 789.0]]

    支持四种模式:
    - 包头 + 包尾 (默认): header + payload + footer
    - 仅包头: header + payload，下一个 header 作为当前帧结束标志
    - 仅包尾: payload + footer
    - 都没有: 无法确定帧边界，数据持续缓冲
    """

    def __init__(self, header: bytes = b"#",
                 footer: bytes = b"\n",
                 delimiter: bytes = b",",
                 max_channels: int = 8):
        self._header = header
        self._footer = footer
        self._delimiter = delimiter
        self._max_channels = max_channels
        self._buffer = bytearray()

    @property
    def header(self) -> bytes:
        return self._header

    @header.setter
    def header(self, value: bytes):
        self._header = value

    @property
    def footer(self) -> bytes:
        return self._footer

    @footer.setter
    def footer(self, value: bytes):
        self._footer = value

    @property
    def delimiter(self) -> bytes:
        return self._delimiter

    @delimiter.setter
    def delimiter(self, value: bytes):
        self._delimiter = value

    def reset(self):
        """清空内部缓冲区"""
        self._buffer.clear()

    def feed(self, data: bytes) -> list[list[float]]:
        """
        喂入新数据，返回解析出的完整帧列表。
        每帧是一个 float 列表，对应各通道值。
        """
        self._buffer.extend(data)
        results = []

        has_header = bool(self._header)
        has_footer = bool(self._footer)

        while True:
            if has_header and has_footer:
                # ── 模式 1: 包头 + 包尾 ──
                header_pos = self._find_subsequence(self._buffer, self._header)
                if header_pos == -1:
                    if len(self._header) > 1 and len(self._buffer) > 0:
                        keep = min(len(self._header) - 1, len(self._buffer))
                        self._buffer = bytearray(self._buffer[-keep:])
                    else:
                        self._buffer.clear()
                    break

                payload_start = header_pos + len(self._header)
                footer_pos = self._find_subsequence(self._buffer, self._footer, payload_start)
                if footer_pos == -1:
                    self._buffer = bytearray(self._buffer[header_pos:])
                    break

                payload = bytes(self._buffer[payload_start:footer_pos])
                self._buffer = bytearray(self._buffer[footer_pos + len(self._footer):])

            elif has_header and not has_footer:
                # ── 模式 2: 仅包头 ──
                # 需要找到两个包头：第一个标记帧开始，第二个标记帧结束
                first_pos = self._find_subsequence(self._buffer, self._header)
                if first_pos == -1:
                    if len(self._header) > 1 and len(self._buffer) > 0:
                        keep = min(len(self._header) - 1, len(self._buffer))
                        self._buffer = bytearray(self._buffer[-keep:])
                    else:
                        self._buffer.clear()
                    break

                payload_start = first_pos + len(self._header)
                second_pos = self._find_subsequence(self._buffer, self._header, payload_start)
                if second_pos == -1:
                    # 等待下一个包头到来
                    self._buffer = bytearray(self._buffer[first_pos:])
                    break

                payload = bytes(self._buffer[payload_start:second_pos])
                self._buffer = bytearray(self._buffer[second_pos:])

            elif not has_header and has_footer:
                # ── 模式 3: 仅包尾 ──
                footer_pos = self._find_subsequence(self._buffer, self._footer)
                if footer_pos == -1:
                    # 保留末尾可能不完整的包尾起始字节
                    if len(self._footer) > 1 and len(self._buffer) > 0:
                        keep = min(len(self._footer) - 1, len(self._buffer))
                        self._buffer = bytearray(self._buffer[-keep:])
                    # 否则保留全部数据等待包尾
                    break

                payload = bytes(self._buffer[:footer_pos])
                self._buffer = bytearray(self._buffer[footer_pos + len(self._footer):])

            else:
                # ── 模式 4: 都没有 ──
                # 无法确定帧边界，持续缓冲
                break

            # 解析帧内容
            values = self._parse_payload(payload)
            if values is not None:
                results.append(values)

        # 安全限制：防止无包尾时缓冲区无限增长
        if len(self._buffer) > 1_000_000:
            self._buffer = bytearray(self._buffer[-10000:])

        return results

    def _parse_payload(self, payload: bytes) -> list[float] | None:
        """解析帧内容，返回通道值列表；解析失败返回 None"""
        if not payload:
            return None

        parts = payload.split(self._delimiter) if self._delimiter else [payload]
        if len(parts) > self._max_channels:
            return None

        values = []
        for part in parts:
            part = part.strip()
            if not part:
                continue
            try:
                values.append(float(part))
            except ValueError:
                return None  # 任一通道解析失败则丢弃整帧

        return values if values else None

    @staticmethod
    def _find_subsequence(data: bytearray, sub: bytes, start: int = 0) -> int:
        """在 bytearray 中查找子序列，返回起始位置，未找到返回 -1"""
        if not sub:
            return start
        for i in range(start, len(data) - len(sub) + 1):
            if data[i:i + len(sub)] == sub:
                return i
        return -1
