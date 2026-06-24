"""工具函数模块 - HEX/文本编解码转换"""

import re


def bytes_to_hex(data: bytes) -> str:
    """字节流转 HEX 字符串，如 b'\\x01\\x02' -> '01 02 '"""
    return " ".join(f"{b:02X}" for b in data) + (" " if data else "")


def bytes_to_text(data: bytes, encoding: str, buffer: bytearray) -> str:
    """
    字节流转文本，支持 GBK 和 UTF-8 编码。
    使用 buffer 缓存不完整的多字节字符，避免截断乱码。
    """
    buffer.extend(data)

    if encoding == "GBK":
        decoded, remaining = _decode_gbk(buffer)
    elif encoding == "UTF-8":
        decoded, remaining = _decode_utf8(buffer)
    else:
        decoded = buffer.decode(encoding, errors="replace")
        remaining = bytearray()

    buffer.clear()
    buffer.extend(remaining)
    return decoded


def _decode_gbk(buffer: bytearray) -> tuple:
    """GBK 解码：ASCII(< 0x80) 为单字节，其余为双字节"""
    result = []
    i = 0
    while i < len(buffer):
        if buffer[i] < 0x80:
            result.append(buffer[i:i + 1])
            i += 1
        else:
            if i + 1 < len(buffer):
                result.append(buffer[i:i + 2])
                i += 2
            else:
                break
    decoded = b"".join(result).decode("GBK", errors="replace")
    return decoded, buffer[i:]


def _decode_utf8(buffer: bytearray) -> tuple:
    """UTF-8 解码：根据首字节判断字符长度 (1/2/3/4 字节)"""
    result = []
    i = 0
    while i < len(buffer):
        b = buffer[i]
        if b < 0x80:
            char_len = 1
        elif b < 0xE0:
            char_len = 2
        elif b < 0xF0:
            char_len = 3
        elif b < 0xF8:
            char_len = 4
        else:
            # 0xF8~0xFF 为无效 UTF-8 起始字节，跳过避免产生乱码
            i += 1
            continue

        if i + char_len <= len(buffer):
            result.append(buffer[i:i + char_len])
            i += char_len
        else:
            break

    decoded = b"".join(result).decode("UTF-8", errors="replace")
    return decoded, buffer[i:]


def text_to_bytes(text: str, encoding: str) -> bytes:
    """文本转字节流"""
    return text.encode(encoding, errors="replace")


def hex_to_bytes(hex_str: str) -> bytes:
    """
    HEX 字符串转字节流，自动过滤非十六进制字符，两两配对。
    如 '01 0A FF' -> b'\\x01\\x0a\\xff'
    """
    cleaned = re.sub(r"[^0-9A-Fa-f]", "", hex_str)
    if len(cleaned) % 2 != 0:
        cleaned = cleaned[:-1]
    return bytes.fromhex(cleaned) if cleaned else b""


def parse_escape_sequences(s: str) -> bytes:
    """
    将用户输入的含转义序列的字符串解析为原始字节。
    支持: \\n \\r \\t \\\\ \\xNN
    其余字符按 UTF-8 编码。
    如 '#\\n' -> b'#\\n'(即 0x23 0x0A)
    """
    result = bytearray()
    i = 0
    while i < len(s):
        if s[i] == '\\' and i + 1 < len(s):
            c = s[i + 1]
            if c == 'n':
                result.append(0x0A)
                i += 2
            elif c == 'r':
                result.append(0x0D)
                i += 2
            elif c == 't':
                result.append(0x09)
                i += 2
            elif c == '\\':
                result.append(0x5C)
                i += 2
            elif c == 'x' and i + 3 < len(s):
                hex_val = s[i + 2:i + 4]
                if all(ch in '0123456789ABCDEFabcdef' for ch in hex_val):
                    result.append(int(hex_val, 16))
                    i += 4
                else:
                    result.extend(s[i].encode('utf-8'))
                    i += 1
            else:
                result.extend(s[i].encode('utf-8'))
                i += 1
        else:
            result.extend(s[i].encode('utf-8'))
            i += 1
    return bytes(result)
