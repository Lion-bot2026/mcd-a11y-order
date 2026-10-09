# -*- coding: utf-8 -*-
"""麦当劳 MCP 响应解析。

麦当劳 MCP 的返回格式不统一，实测至少有四种形态，不能无脑 json.loads：
  1. 纯 JSON                       —— query-my-account
  2. 说明文字 + JSON                —— query-nearby-stores / calculate-price
  3. Markdown                       —— available-coupons / query-my-coupons / campaign-calendar
  4. TOON 紧凑表                    —— list-nutrition-foods

本模块只做「取数据」这一件事，并且对缺失值一律返回 None，绝不当 0。
"""
from __future__ import annotations

import csv
import io
import json
import re
import unicodedata
from typing import Any

__all__ = ["extract_json", "parse_toon", "normalize_name", "coerce_scalar"]

# data 字段内含裸换行，strict=True 会直接抛异常 —— 必须用 strict=False
_DECODER = json.JSONDecoder(strict=False)

# 表头定位必须用 search而非 match：官方返回常带说明文字前缀（如
# 「## Original Response」）或 UTF-8 BOM，match 会因 ^ 锚定失败而
# 静默返回 0 条 —— 那会让 plan 悄悄变成「匹配到 0 项」，与本项目
# 「绝不静默返回空」的原则直接冲突。re.M 让 ^ 也能匹配行首。
_TOON_HEADER = re.compile(r"\[(\d+)\]\{([^}]*)\}\s*:", re.M)
_NULL_TOKENS = {"null", "none", "", "-", "na", "n/a", "nan", "\\n"}


def extract_json(text: str) -> Any:
    """从「说明文字 + JSON + 尾部指令」的混合文本里取出顶层 JSON 对象。

    三级降级：定位 {"success" → raw_decode(strict=False) → 扫描最长可解析片段。
    失败返回 None，由调用方抛出可见错误，绝不静默返回空。
    """
    if not isinstance(text, str):
        return None
    s = text.strip()
    if not s:
        return None

    # 官方返回常在业务 JSON 之前塞一段 "Original Response" 说明文字
    marker = s.find("Original Response")
    start = s.find('{"success"', marker if marker >= 0 else 0)
    if start < 0:
        start = s.find("{")
    if start < 0:
        return None

    try:
        obj, _ = _DECODER.raw_decode(s[start:])
        return obj
    except (json.JSONDecodeError, ValueError):
        pass

    # 兜底：扫描所有 { 起点，取能解析最长的那一段
    best: Any = None
    span = -1
    for m in re.finditer(r"\{", s):
        try:
            obj, end = _DECODER.raw_decode(s[m.start():])
        except (json.JSONDecodeError, ValueError):
            continue
        if end > span:
            best, span = obj, end
    return best


def coerce_scalar(v: Any) -> Any:
    """把字符串转成数字；无法转换或表示缺失时返回 None（绝不当 0）。"""
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return v
    s = str(v).strip()
    if s.lower() in _NULL_TOKENS:
        return None
    # 去掉千分位与常见单位后缀
    s = s.replace(",", "").replace("%", "")
    try:
        f = float(s)
    except ValueError:
        return s
    return int(f) if f.is_integer() else f


def parse_toon(data: str) -> list[dict]:
    """解析 TOON 紧凑表。

    形如::

        [160]{productName,nutritionDescription,energyKj,energyKcal,protein,fat,carbohydrate,sodium,calcium}:
          猪柳麦满分,null,1288,308,16,16,24,781,213

    字段名从 header 动态读取 —— 官方调整字段顺序时不会静默错位。
    表头定位用 search，允许说明文字前缀与 BOM 存在。
    """
    if not isinstance(data, str):
        return []
    # BOM 与首尾空白都不影响表头识别
    m = _TOON_HEADER.search(data.lstrip("﻿ \t\r\n"))
    if not m:
        return []
    fields = [f.strip() for f in m.group(2).split(",")]
    rows: list[dict] = []
    for line in data[m.end():].splitlines():
        line = line.strip()
        if not line:
            continue
        # 用 csv 而非 split(",") —— 正确处理引号包裹的含逗号餐品名
        try:
            cols = next(csv.reader(io.StringIO(line)))
        except (csv.Error, StopIteration):
            continue
        if len(cols) < 2:
            continue
        rows.append({f: coerce_scalar(cols[i]) if i < len(cols) else None
                     for i, f in enumerate(fields)})
    return rows


_PUNCT = re.compile(r"[\s·・\-—_（）()【】\[\]“”\"'’‘,，。.、/\\|]+")


def normalize_name(s: str) -> str:
    """餐品名归一化：全角转半角、去标点空白、转小写。用于跨表匹配。"""
    if not s:
        return ""
    s = unicodedata.normalize("NFKC", str(s))
    return _PUNCT.sub("", s).lower()
