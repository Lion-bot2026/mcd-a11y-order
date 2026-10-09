# -*- coding: utf-8 -*-
"""三种输出模式。

screen-reader 模式是本项目的核心差异化：面向 NVDA / VoiceOver 等读屏软件的
纯文本输出层，遵守六条硬规则。
"""
from __future__ import annotations

from typing import Any

CN_DIGITS = "零一二三四五六七八九"
CN_UNITS = ["", "十", "百", "千"]

DISCLAIMER = "本输出仅供参考，不构成医疗、营养或其他专业建议。"

MODES = ("screen-reader", "large-print", "plain")


def int_to_cn(n: int) -> str:
    """整数转中文读法。19 -> 十九 / 105 -> 一百零五 / 10000 -> 一万"""
    n = int(n)
    if n == 0:
        return "零"
    if n < 0:
        return "负" + int_to_cn(-n)
    if n >= 10000:
        w, r = divmod(n, 10000)
        s = int_to_cn(w) + "万"
        if r:
            if r < 1000:
                s += "零"
            s += int_to_cn(r)
        return s

    digits = str(n)
    length = len(digits)
    parts: list[str] = []
    zero_pending = False
    for i, ch in enumerate(digits):
        d = int(ch)
        unit = CN_UNITS[length - 1 - i]
        if d == 0:
            zero_pending = True
            continue
        if zero_pending and parts:
            parts.append("零")
        zero_pending = False
        parts.append(CN_DIGITS[d] + unit)
    s = "".join(parts)
    if s.startswith("一十"):  # 19 -> 十九，而非 一十九
        s = s[1:]
    return s


def money_to_cn(cents: int) -> str:
    """分转中文货币读法。1988 -> 十九元八角八分 / 1905 -> 十九元零五分

    读屏软件会把「19.88元」读成「十九点八八元」，不符合中文货币习惯。
    """
    cents = int(cents)
    yuan, rest = divmod(cents, 100)
    jiao, fen = divmod(rest, 10)
    parts: list[str] = []
    if yuan:
        parts.append(int_to_cn(yuan) + "元")
    if jiao:
        parts.append(CN_DIGITS[jiao] + "角")
    elif fen and yuan:
        parts.append("零")
    if fen:
        parts.append(CN_DIGITS[fen] + "分")
    return "".join(parts) if parts else "零元"


def money(mode: str, cents: int | None) -> str:
    if cents is None:
        return "价格未获取" if mode == "screen-reader" else "—"
    if mode == "screen-reader":
        return money_to_cn(cents)
    return f"{cents / 100:.2f} 元"


def unit(mode: str, value: Any, unit_cn: str, unit_sym: str, digits: int = 0) -> str:
    """按模式渲染带单位的数值。缺失值两种模式都必须说清楚，不能显示 0。"""
    if value is None:
        return "未获取" if mode == "screen-reader" else "未获取"
    if isinstance(value, float):
        value = round(value, digits) if digits else int(round(value))
    if mode == "screen-reader":
        return f"{value} {unit_cn}"
    return f"{value}{unit_sym}"


class Out:
    """按模式渲染的分块输出器。"""

    def __init__(self, mode: str = "plain") -> None:
        if mode not in MODES:
            raise ValueError(f"未知输出模式：{mode}，可选 {MODES}")
        self.mode = mode
        self.lines: list[str] = []

    # ---------- 基础 ----------
    def _add(self, s: str) -> None:
        self.lines.append(s)

    def blank(self) -> None:
        self._add("")

    def title(self, text: str) -> None:
        if self.mode == "screen-reader":
            self._add(text)
        elif self.mode == "large-print":
            self._add("")
            self._add(text)
        else:
            self._add(f"## {text}")

    def step(self, text: str) -> None:
        """步骤标题 —— screen-reader 下显式播报，让听者知道进度。"""
        self._add(text)

    def item(self, index: int, text: str, total: int | None = None) -> None:
        # 读屏模式下「第 一 项」会被逐字读出，必须连写为「第一项」
        if self.mode == "screen-reader":
            self._add(f"  第{int_to_cn(index)}项，{text}")
        else:
            self._add(f"{index}. {text}")

    def note(self, text: str) -> None:
        self._add(f"  {text}" if self.mode != "plain" else text)

    def boundary(self, text: str) -> None:
        """数据边界声明 —— 三种模式下都必须显著出现，不可省略。"""
        if self.mode == "screen-reader":
            self._add(f"  请注意。{text}")
        else:
            self._add(f"> {text}")

    def warn(self, text: str) -> None:
        if self.mode == "screen-reader":
            self._add(f"  重要提示。{text}")
        else:
            self._add(f"**{text}**")

    def text(self) -> str:
        body = "\n".join(self.lines).rstrip()
        return f"{body}\n\n{DISCLAIMER}\n"


def render_disclaimer(mode: str) -> str:
    return DISCLAIMER
