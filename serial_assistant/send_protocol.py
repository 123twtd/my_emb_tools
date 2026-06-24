"""发送模板与转义解析"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from .utils import hex_to_bytes, parse_escape_sequences, text_to_bytes


def extract_template_fields(template: str) -> List[str]:
    """从模板中提取 {field} 占位符名称"""
    return list(dict.fromkeys(re.findall(r"\{(\w+)\}", template)))


def render_template(
    template: str,
    mode: str,
    fields: Optional[Dict[str, Any]] = None,
    encoding: str = "UTF-8",
    use_escape: bool = False,
) -> bytes:
    """将协议模板渲染为字节流。mode: text | hex"""
    text = template
    for key, val in (fields or {}).items():
        text = text.replace("{" + key + "}", str(val))
    if mode == "hex":
        if use_escape:
            return parse_escape_sequences(text)
        return hex_to_bytes(text)
    if use_escape:
        return parse_escape_sequences(text)
    return text_to_bytes(text, encoding)
