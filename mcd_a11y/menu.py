# -*- coding: utf-8 -*-
"""门店、菜单与「特制」（modification）解析。

【重要数据边界】
`query-meal-detail` 的 modification.items[].values[] 实测只有 8 个字段：
    code / price / name / maxQuantity / minQuantity /
    selectedQuantity / selectedKey / unselectedKey
**没有任何营养字段。**

因此本项目对特制只输出三件事：
    1. 选项清单        —— 真实数据
    2. 对价格的影响    —— 真实数据
    3. 对钠的方向性提示 —— 规则库推断，显著标注「非量化」
绝不编造「去掉酱料可减少 xxx 毫克钠」这样的数字。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .nutrition import MenuItem
from .parser import coerce_scalar

__all__ = ["StoreInfo", "ModifierOption", "parse_stores", "parse_meals",
           "parse_modifications", "sodium_hint", "SODIUM_HINT_RULES",
           "SODIUM_HINT_DISCLAIMER"]

SODIUM_HINT_DISCLAIMER = (
    "以上钠提示为方向性推断。麦当劳 MCP 的 modification 接口不返回分项营养数据，"
    "本项目不做钠的量化计算。"
)

# 规则库：关键词 → 方向性提示。只说「通常是主要来源」，不给毫克数。
SODIUM_HINT_RULES: tuple[tuple[tuple[str, ...], str], ...] = (
    (("酱", "沙司", "调味", "蘸"), "酱料通常是钠的主要来源"),
    (("酸黄瓜", "酸瓜", "腌", "泡菜", "橄榄"), "腌渍类配料通常含钠较高"),
    (("芝士", "奶酪", "吉士"), "奶酪类配料通常含钠较高"),
    (("培根", "烟肉", "火腿", "香肠", "肉松"), "加工肉制品通常含钠较高"),
    (("盐", "咸"), "该项名称直接提示含盐"),
    (("糖", " syrup", "枫糖"), "糖浆类配料通常含糖较高"),
)


@dataclass
class StoreInfo:
    store_code: str
    store_name: str
    address: str | None = None
    distance: float | None = None          # 单位：米（官方字段，实测为米）
    business_status: str | bool | None = None
    business_start: str | None = None
    business_end: str | None = None
    be_code: str | None = None
    lat: float | None = None
    lng: float | None = None

    @property
    def is_open(self) -> bool | None:
        """无法判断时返回 None —— 不打烊不等于营业中。

        注意：官方 query-nearby-stores 实测返回的是布尔值（True/False），
        早期版本用 str() 强转导致 False 变成字符串 "False"，无法被识别为「已打烊」。
        这里必须先判断布尔，再回落字符串。
        """
        v = self.business_status
        if v is None or v == "":
            return None
        if isinstance(v, bool):
            return v
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            return bool(v)
        s = str(v).strip()
        low = s.lower()
        if low in ("true", "1", "yes", "y", "open", "营业中", "营业"):
            return True
        if low in ("false", "0", "no", "n", "closed", "打烊", "休息", "已打烊", "未营业"):
            return False
        if "营业" in s and "未" not in s:
            return True
        if "打烊" in s or "休息" in s or "closed" in low:
            return False
        return None


@dataclass
class ModifierOption:
    group_key: str          # 由 selectedKey 前缀推导，同组互斥
    code: str
    name: str
    price: float | None     # 价格影响，真实数据
    max_quantity: int | None = None
    min_quantity: int | None = None
    selected_quantity: int | None = None
    selected_key: str | None = None
    unselected_key: str | None = None

    @property
    def is_default_selected(self) -> bool:
        return bool(self.selected_quantity)

    @property
    def price_text(self) -> str:
        if self.price is None:
            return "价格影响未知"
        if self.price == 0:
            return "不影响价格"
        return f"{'加' if self.price > 0 else '减'} {abs(self.price):g} 元"


def parse_stores(data: Any) -> list[StoreInfo]:
    """解析 query-nearby-stores / delivery-query-stores 的门店列表。"""
    if isinstance(data, dict):
        data = data.get("data") or data.get("list") or []
    if not isinstance(data, list):
        return []
    out: list[StoreInfo] = []
    for s in data:
        if not isinstance(s, dict):
            continue
        out.append(StoreInfo(
            store_code=str(s.get("storeCode") or s.get("code") or "").strip(),
            store_name=str(s.get("storeName") or s.get("name") or "").strip(),
            address=s.get("address"),
            distance=coerce_scalar(s.get("distance")),
            # 保留原始类型（实测为布尔），交由 StoreInfo.is_open 统一判定
            business_status=s.get("businessStatus"),
            business_start=(None if s.get("businessStartTime") is None
                            else str(s.get("businessStartTime"))),
            business_end=(None if s.get("businessEndTime") is None
                          else str(s.get("businessEndTime"))),
            be_code=(None if s.get("beCode") is None else str(s.get("beCode"))),
            lat=coerce_scalar(s.get("latitude")),
            lng=coerce_scalar(s.get("longitude")),
        ))
    return [s for s in out if s.store_code]


def rank_stores(stores: list[StoreInfo], open_first: bool = True) -> list[StoreInfo]:
    """可达性排序：营业中优先，其次距离升序。

    open_first=False 时纯按距离升序 —— 打烊的门店不再被强推到末尾
    （否则「关闭优先」会变成「打烊门店排最后」，与只按距离的预期相反）。

    确定性排序：无法判断营业状态或距离的排在后面，而不是靠猜测插到前面。
    """
    def key(s: StoreInfo):
        st = s.is_open
        if open_first:
            open_rank = 0 if st is True else (2 if st is False else 1)
        else:
            open_rank = 0
        dist = s.distance if isinstance(s.distance, (int, float)) else float("inf")
        return (open_rank, dist)
    return sorted(stores, key=key)


def parse_meals(data: Any, store_code: str | None = None) -> list[MenuItem]:
    """解析 query-meals。分类名是中文且不稳定的，因此不做任何分类名硬匹配。"""
    if not isinstance(data, dict):
        return []
    meals_map = data.get("meals") or {}
    items: list[MenuItem] = []
    seen: set[str] = set()

    if isinstance(meals_map, dict):
        for code, m in meals_map.items():
            if not isinstance(m, dict) or code in seen:
                continue
            seen.add(code)
            items.append(MenuItem(
                code=str(code),
                name=str(m.get("name") or "").strip(),
                current_price_yuan=coerce_scalar(m.get("currentPrice")),
                original_price_yuan=coerce_scalar(m.get("originalPrice")),
                store_code=store_code,
            ))

    # 分类下的餐品（可能与 meals 映射重复，按 code 去重）
    for cat in (data.get("categories") or []):
        if not isinstance(cat, dict):
            continue
        cat_name = cat.get("name")
        for m in (cat.get("meals") or []):
            if not isinstance(m, dict):
                continue
            code = str(m.get("code") or "").strip()
            if not code or code in seen:
                continue
            seen.add(code)
            items.append(MenuItem(
                code=code,
                name=str(m.get("name") or "").strip(),
                category=(None if cat_name is None else str(cat_name)),
                current_price_yuan=coerce_scalar(m.get("currentPrice")),
                original_price_yuan=coerce_scalar(m.get("originalPrice")),
                store_code=store_code,
            ))
    return [i for i in items if i.name]


def parse_modifications(detail: Any) -> list[ModifierOption]:
    """解析 query-meal-detail 的 modification 结构。

    真实抓包示例::

        {"code":"100202","price":0,"name":"酸黄瓜","maxQuantity":1,"minQuantity":0,
         "selectedQuantity":1,"selectedKey":"0-1","unselectedKey":"0-0"}
    """
    if not isinstance(detail, dict):
        return []
    if "data" in detail and isinstance(detail["data"], dict):
        detail = detail["data"]
    mod = detail.get("modification")
    if not isinstance(mod, dict):
        return []

    out: list[ModifierOption] = []
    for group_idx, group in enumerate(mod.get("items") or []):
        if not isinstance(group, dict):
            continue
        group_name = group.get("name")
        for v in (group.get("values") or []):
            if not isinstance(v, dict):
                continue
            sel = str(v.get("selectedKey") or "")
            # selectedKey 形如 "0-1"，前缀即组号
            gkey = sel.split("-")[0] if "-" in sel else str(group_idx)
            out.append(ModifierOption(
                group_key=gkey,
                code=str(v.get("code") or "").strip(),
                name=str(v.get("name") or group_name or "").strip(),
                price=coerce_scalar(v.get("price")),
                max_quantity=coerce_scalar(v.get("maxQuantity")),
                min_quantity=coerce_scalar(v.get("minQuantity")),
                selected_quantity=coerce_scalar(v.get("selectedQuantity")),
                selected_key=v.get("selectedKey"),
                unselected_key=v.get("unselectedKey"),
            ))
    return [o for o in out if o.name]


# 甜品饮品识别：纯按钠排序会把可乐（钠 0 毫克）与甜品顶到最前面，
# 对「这一餐吃什么」毫无帮助。按名称关键词识别后归入「甜品与饮品」分区，
# 不计入主餐建议。
#
# 这是启发式规则，不是官方分类 —— 官方 query-meals 的分类名是中文且不稳定的，
# 无法稳定映射到「主食 / 小食 / 饮品」。识别不出的一律按餐食处理。
LIGHT_FOOD_KEYWORDS = (
    # 饮品
    "可乐", "雪碧", "芬达", "美年达", "汽水", "苏打",
    "红茶", "绿茶", "奶茶", "茶", "柠檬", "酸梅",
    "咖啡", "拿铁", "美式", "卡布", "浓缩", "可可",
    "牛奶", "豆浆", "果汁", "橙汁", "苹果汁", "椰",
    "饮用水", "矿泉水", "气泡水", "美汁源", "橙橙", "柠柠", "纯悦", "怡泉",
    # 甜品
    "新地", "麦旋风", "旋酷", "圆筒", "甜筒", "冰淇淋", "冰激凌",
    "圣代", "朱古力", "巧克力", "慕斯", "布丁", "蛋糕", "派",
)


def is_light_food(name: str) -> bool:
    """按名称关键词判断是否甜品/饮品。识别不出的一律按餐食处理（宁可错分为餐食）。"""
    n = str(name or "")
    return any(k in n for k in LIGHT_FOOD_KEYWORDS)


def sodium_hint(name: str) -> str | None:
    """方向性钠提示。命中规则库则返回提示文案，否则返回 None（不强行解释）。"""
    n = str(name or "")
    for kws, hint in SODIUM_HINT_RULES:
        if any(k in n for k in kws):
            return hint
    return None
