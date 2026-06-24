"""接收侧可配置帧解析 — 支持包头/包尾/分隔符/定长/命名字段"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

from .utils import parse_escape_sequences


@dataclass
class ParsedFrame:
    """一帧解析结果"""
    fields: Dict[str, str]
    raw_payload: bytes
    timestamp: datetime = field(default_factory=datetime.now)

    def display_line(self) -> str:
        parts = [f"{k}={v}" for k, v in self.fields.items()]
        return "  ".join(parts) if parts else self.raw_payload.decode("utf-8", errors="replace")


def _to_bytes(text: str, use_escape: bool = True) -> bytes:
    if not text:
        return b""
    return parse_escape_sequences(text) if use_escape else text.encode("utf-8", errors="replace")


@dataclass
class ParserConfig:
    """解析器配置"""
    id: str
    name: str
    enabled: bool = True
    header: str = ""
    footer: str = ""
    delimiter: str = ","
    encoding: str = "utf-8"
    frame_length: int = 0
    split_mode: str = "delimiter"
    field_names: List[str] = field(default_factory=list)
    field_widths: List[int] = field(default_factory=list)
    history_max: int = 50

    @classmethod
    def from_dict(cls, d: dict) -> ParserConfig:
        return cls(
            id=str(d.get("id", "")),
            name=str(d.get("name", "未命名")),
            enabled=bool(d.get("enabled", True)),
            header=str(d.get("header", "")),
            footer=str(d.get("footer", "")),
            delimiter=str(d.get("delimiter", ",")),
            encoding=str(d.get("encoding", "utf-8")),
            frame_length=int(d.get("frame_length", 0) or 0),
            split_mode=str(d.get("split_mode", "delimiter")),
            field_names=list(d.get("field_names") or []),
            field_widths=[int(x) for x in (d.get("field_widths") or [])],
            history_max=int(d.get("history_max", 50) or 50),
        )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "enabled": self.enabled,
            "header": self.header,
            "footer": self.footer,
            "delimiter": self.delimiter,
            "encoding": self.encoding,
            "frame_length": self.frame_length,
            "split_mode": self.split_mode,
            "field_names": self.field_names,
            "field_widths": self.field_widths,
            "history_max": self.history_max,
        }


class RxFrameParser:
    """单路接收解析器"""

    def __init__(self, config: ParserConfig):
        self.config = config
        self._buffer = bytearray()
        self._header = _to_bytes(config.header)
        self._footer = _to_bytes(config.footer)
        self._delimiter = _to_bytes(config.delimiter)

    def update_config(self, config: ParserConfig):
        self.config = config
        self._header = _to_bytes(config.header)
        self._footer = _to_bytes(config.footer)
        self._delimiter = _to_bytes(config.delimiter)

    def reset(self):
        self._buffer.clear()

    def feed(self, data: bytes) -> List[ParsedFrame]:
        self._buffer.extend(data)
        results: List[ParsedFrame] = []
        while True:
            payload = self._extract_payload()
            if payload is None:
                break
            frame = self._parse_payload(payload)
            if frame:
                results.append(frame)
        if len(self._buffer) > 1_000_000:
            self._buffer = bytearray(self._buffer[-10000:])
        return results

    def _extract_payload(self) -> Optional[bytes]:
        cfg = self.config
        buf = self._buffer
        has_h = bool(self._header)
        has_f = bool(self._footer)
        fixed_len = cfg.frame_length

        if fixed_len > 0 and has_h:
            pos = self._find(self._header)
            if pos == -1:
                self._trim_partial(self._header)
                return None
            start = pos + len(self._header)
            if len(buf) < start + fixed_len:
                self._buffer = bytearray(buf[pos:])
                return None
            payload = bytes(buf[start:start + fixed_len])
            del buf[:start + fixed_len]
            return payload

        if fixed_len > 0 and not has_h:
            if len(buf) < fixed_len:
                return None
            payload = bytes(buf[:fixed_len])
            del buf[:fixed_len]
            return payload

        if has_h and has_f:
            pos = self._find(self._header)
            if pos == -1:
                self._trim_partial(self._header)
                return None
            start = pos + len(self._header)
            fpos = self._find(self._footer, start)
            if fpos == -1:
                self._buffer = bytearray(buf[pos:])
                return None
            payload = bytes(buf[start:fpos])
            del buf[:fpos + len(self._footer)]
            return payload

        if has_h and not has_f:
            first = self._find(self._header)
            if first == -1:
                self._trim_partial(self._header)
                return None
            start = first + len(self._header)
            second = self._find(self._header, start)
            if second == -1:
                self._buffer = bytearray(buf[first:])
                return None
            payload = bytes(buf[start:second])
            del buf[second:]
            return payload

        if not has_h and has_f:
            fpos = self._find(self._footer)
            if fpos == -1:
                self._trim_partial(self._footer)
                return None
            payload = bytes(buf[:fpos])
            del buf[:fpos + len(self._footer)]
            return payload

        if self._delimiter:
            dpos = self._find(self._delimiter)
            if dpos == -1:
                return None
            payload = bytes(buf[:dpos])
            del buf[:dpos + len(self._delimiter)]
            return payload

        return None

    def _parse_payload(self, payload: bytes) -> Optional[ParsedFrame]:
        if not payload:
            return None
        cfg = self.config
        enc = cfg.encoding or "utf-8"
        names = cfg.field_names

        if cfg.split_mode == "fixed_width" and cfg.field_widths:
            fields: Dict[str, str] = {}
            offset = 0
            for i, width in enumerate(cfg.field_widths):
                if offset + width > len(payload):
                    break
                chunk = payload[offset:offset + width]
                offset += width
                key = names[i] if i < len(names) else f"f{i}"
                fields[key] = chunk.decode(enc, errors="replace").strip()
            if not fields:
                return None
            return ParsedFrame(fields=fields, raw_payload=payload)

        if self._delimiter and cfg.split_mode == "delimiter":
            parts = payload.split(self._delimiter)
        else:
            parts = [payload]

        fields = {}
        idx = 0
        for part in parts:
            text = part.decode(enc, errors="replace").strip()
            if not text:
                continue
            key = names[idx] if idx < len(names) else f"f{idx}"
            fields[key] = text
            idx += 1

        if not fields and payload:
            fields["data"] = payload.decode(enc, errors="replace")

        return ParsedFrame(fields=fields, raw_payload=payload) if fields else None

    def _find(self, sub: bytes, start: int = 0) -> int:
        if not sub:
            return start
        data = self._buffer
        for i in range(start, len(data) - len(sub) + 1):
            if data[i:i + len(sub)] == sub:
                return i
        return -1

    def _trim_partial(self, marker: bytes):
        if len(marker) <= 1:
            return
        keep = min(len(marker) - 1, len(self._buffer))
        if keep:
            self._buffer = bytearray(self._buffer[-keep:])
        else:
            self._buffer.clear()
