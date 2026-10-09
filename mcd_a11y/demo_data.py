# -*- coding: utf-8 -*-
"""离线演示数据。

【来源透明】
  * 营养数据：156 条，来自官方 MCP 工具 list-nutrition-foods 的真实返回
    （经社区公开快照转存，字段与本工具返回完全一致）。
  * 特制样本：1 条真实抓包（酸黄瓜），字段值与 query-meal-detail 返回一致。
  * 门店与菜单：为演示构造，标注为合成样例，**不含真实门店名、地址或个人信息**。

运行 --demo 时会在输出顶部声明这些边界，不让合成数据冒充真实返回。
"""
from __future__ import annotations

import json
import os
from typing import Any

from .menu import ModifierOption, StoreInfo
from .nutrition import MenuItem, NutritionItem, from_toon_rows

_SNAPSHOT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                         "data", "nutrition_snapshot.json")

DEMO_BANNER = (
    "离线演示模式。营养数据为官方 MCP 真实返回的快照，"
    "门店与菜单为合成样例，不代表当前真实供应与价格。"
)


def load_nutrition() -> list[NutritionItem]:
    """加载 156 条真实营养快照。"""
    if not os.path.exists(_SNAPSHOT):
        raise SystemExit(f"缺少离线快照文件：{_SNAPSHOT}")
    with open(_SNAPSHOT, encoding="utf-8") as f:
        data = json.load(f)
    return from_toon_rows(data.get("foods") or [])


def demo_menu(limit: int = 40) -> list[MenuItem]:
    """用真实营养快照里的餐品名构造演示菜单（code 为演示用编号）。"""
    items = load_nutrition()
    out: list[MenuItem] = []
    for i, n in enumerate(items[:limit]):
        out.append(MenuItem(
            code=f"DEMO{i:04d}",
            name=n.product_name,
            current_price_yuan=None,   # 演示不编造价格
            store_code="DEMO-STORE",
        ))
    return out


def demo_stores() -> list[StoreInfo]:
    """合成门店样例。刻意使用占位名称，避免混淆为真实门店。"""
    return [
        StoreInfo(store_code="DEMO-0001", store_name="演示门店 A（合成样例）",
                  address="合成地址，非真实门店", distance=380,
                  business_status="1", business_start="07:00", business_end="22:00"),
        StoreInfo(store_code="DEMO-0002", store_name="演示门店 B（合成样例）",
                  address="合成地址，非真实门店", distance=620,
                  business_status="1", business_start="06:30", business_end="23:00"),
        StoreInfo(store_code="DEMO-0003", store_name="演示门店 C（合成样例）",
                  address="合成地址，非真实门店", distance=890,
                  business_status="0", business_start="09:00", business_end="21:00"),
    ]


def demo_modifications() -> list[ModifierOption]:
    """真实抓包的特制选项（深圳某门店 query-meal-detail 返回，字段值未改动）。"""
    return [
        ModifierOption(group_key="0", code="100202", name="酸黄瓜", price=0,
                       max_quantity=1, min_quantity=0, selected_quantity=1,
                       selected_key="0-1", unselected_key="0-0"),
        ModifierOption(group_key="1", code="100301", name="甜酸酱", price=0,
                       max_quantity=1, min_quantity=0, selected_quantity=1,
                       selected_key="1-1", unselected_key="1-0"),
    ]


def snapshot_meta() -> dict:
    if not os.path.exists(_SNAPSHOT):
        return {}
    with open(_SNAPSHOT, encoding="utf-8") as f:
        return json.load(f).get("_meta") or {}
