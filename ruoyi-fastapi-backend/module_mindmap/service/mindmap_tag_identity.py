"""脑图标签稳定身份工具。"""

import hashlib
import re
from typing import Any


def build_custom_tag_key(value: Any) -> str:
    """按名称生成与大小写无关、可重复计算的自定义标签键。"""
    name = str(value or '').strip()[:200]
    digest = hashlib.sha1(name.casefold().encode('utf-8')).hexdigest()[:20]
    normalized = re.sub(r'[^a-zA-Z0-9_-]+', '_', name).strip('_').lower()[:40]
    return f'custom_{normalized}_{digest}'[:100]
